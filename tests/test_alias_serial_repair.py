"""Offline tests only. The repair CLI and a MariaDB connection are never started."""
import copy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock, patch

from scripts import repair_alias_serials_20261030 as repair


class AliasSerialRepairTests(unittest.TestCase):
    def setUp(self):
        self.audit = json.loads((Path(__file__).resolve().parents[1] /
                                 'reports/audit_aliases_2026-10-30.json').read_text(encoding='utf-8'))
        self.plan = repair.build_plan(self.audit)
        self.before = {table: [] for table in repair.TABLES}
        self.before['lista_formowania_sn'] = [copy.deepcopy(row) for row in self.audit['evidence']['aliases']
                                             if row['produkt_id'] in repair.SAFE_FORMS]
        self.before['lista_formowania_v2'] = [copy.deepcopy(row) for row in self.audit['evidence']['forms']
                                             if row['id'] in repair.SAFE_FORMS]
        self.before['lista_formowania_formy_v2'] = [copy.deepcopy(row) for row in self.audit['evidence']['patterns']
                                                   if row['produkt_id'] in repair.SAFE_FORMS]
        for ref in self.plan['references']:
            fk, pk, prefix = repair.REFERENCES[ref['table']]
            row = {pk: ref['record_id'], fk: ref['form_id'], 'sn': ref['old_sn'],
                   'czas': '2026-10-30T10:00:00', 'operator': 'preserve'}
            if prefix:
                row['prefix'] = ref['prefix']
            if ref.get('stage') is not None:
                row['production_stage'] = ref['stage']
            self.before[ref['table']].append(row)
        self.originals = {table: [] for table in repair.TABLES}
        self.originals['lista_formowania_v2'] = [{'id': form} for form in self.plan['original_forms']]
        for p in self.plan['proposals']:
            peer = p['serial_peers'][0]
            self.originals['lista_formowania_sn'].append(dict(
                id=peer['id'],produkt_id=peer['form'],prefix=p['prefix'],sn=p['old_sn'],
                alias=None,canceled=peer['canceled']))

    def test_scope_excludes_every_ambiguous_case_and_keeps_proposals_fixed(self):
        self.assertEqual(len(self.plan['proposals']),12)
        self.assertEqual(len(self.plan['skipped']),15)
        self.assertFalse({39376,39561,39574,39575,39774,39775,34857,39553} & set(self.plan['forms']))
        self.assertEqual(len(self.plan['model_changes']),28)
        repair.validate_snapshot(self.audit,self.plan,self.before,self.originals)

    def test_new_records_or_changed_aliases_abort_preflight(self):
        changed = copy.deepcopy(self.before)
        changed['lista_formowania_sn'][0]['alias'] = 'changed'
        with self.assertRaises(repair.RepairError):
            repair.validate_snapshot(self.audit,self.plan,changed,self.originals)
        changed = copy.deepcopy(self.before)
        changed['grinding'].append(dict(id=999999,item_id=34128,prefix='SK',sn=6974))
        with self.assertRaises(repair.RepairError):
            repair.validate_snapshot(self.audit,self.plan,changed,self.originals)

    def test_missing_original_aborts_preflight(self):
        self.originals['lista_formowania_v2'].pop()
        with self.assertRaises(repair.RepairError):
            repair.validate_snapshot(self.audit,self.plan,self.before,self.originals)

    def test_generated_cache_can_change_primary_keys_but_not_casting_identity(self):
        for row in self.before['casting_report_tmp']:
            row['record_id'] += 100000
        repair.validate_snapshot(self.audit,self.plan,self.before,self.originals)
        changes = repair.operations(self.plan,self.before)
        self.assertTrue(all(c['row_id'] > 100000 for c in changes if c['table']=='casting_report_tmp'))
        self.before['casting_report_tmp'][0]['sn'] += 1
        with self.assertRaises(repair.RepairError):
            repair.validate_snapshot(self.audit,self.plan,self.before,self.originals)

    def database(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        for table, rows in self.before.items():
            fields = sorted({key for row in rows for key in row}) or ['id']
            db.execute(f'CREATE TABLE `{table}` (' + ','.join(f'`{field}`' for field in fields) + ')')
            for row in rows:
                keys = list(row)
                db.execute(f'INSERT INTO `{table}` (' + ','.join(f'`{k}`' for k in keys)
                           + ') VALUES (' + ','.join('?' for _ in keys) + ')', list(row.values()))
        db.commit()
        return db

    @staticmethod
    def read_database(db):
        return {table: [dict(row) for row in db.execute(f'SELECT * FROM `{table}` ORDER BY `{pk}`')]
                for table, (_, pk) in repair.TABLES.items()}

    def test_offline_sql_changes_only_planned_serial_fields(self):
        db = self.database()
        before = self.read_database(db)
        changes = repair.operations(self.plan,before)
        self.assertEqual(len(changes),62)  # 12 serials + 28 model cells + 22 linked records.
        self.assertFalse({'shipments_history','produkty','lista_formowania_v2'} & {c['table'] for c in changes})
        class Cursor:
            def execute(self,sql,params):
                self.rowcount = db.execute(sql.replace('%s','?'),params).rowcount
        repair.apply_operations(Cursor(),changes)
        after = self.read_database(db)
        repair.verify_after(before,after,changes)
        self.assertEqual([r['alias'] for r in before['lista_formowania_sn']],
                         [r['alias'] for r in after['lista_formowania_sn']])
        self.assertEqual([r for r in before['lista_formowania_historia_v2'] if r['sn'] is None],
                         [r for r in after['lista_formowania_historia_v2'] if r['sn'] is None])

    def test_offline_sql_failure_rolls_back_the_whole_transaction(self):
        db = self.database()
        before = self.read_database(db)
        class FailingCursor:
            calls = 0
            def execute(self,sql,params):
                self.calls += 1
                if self.calls == 3:
                    raise RuntimeError('simulated write failure')
                self.rowcount = db.execute(sql.replace('%s','?'),params).rowcount
        db.execute('BEGIN')
        with self.assertRaises(RuntimeError):
            try:
                repair.apply_operations(FailingCursor(),repair.operations(self.plan,before))
            except RuntimeError:
                db.rollback()
                raise
        self.assertEqual(self.read_database(db),before)

    def test_postcheck_rejects_alias_or_timestamp_changes(self):
        changes = repair.operations(self.plan,self.before)
        after = copy.deepcopy(self.before)
        for c in changes:
            row = next(r for r in after[c['table']] if r[c['pk']]==c['row_id'])
            row[c['column']] = c['new']
        repair.verify_after(self.before,after,changes)
        after['grinding'][0]['czas'] = 'changed'
        with self.assertRaises(repair.RepairError):
            repair.verify_after(self.before,after,changes)

    def connection(self):
        plan = self.plan
        audit = self.audit
        class Cursor:
            rowcount = 1
            def __init__(self): self.sqls=[]; self.rows=[]
            def execute(self,sql,params=None):
                self.sqls.append(sql)
                if 'DATABASE() AS db' in sql: self.rows=[{'db':'tower'}]
                elif 'FROM forming_serial_locks' in sql: self.rows=[{'prefix':p} for p in plan['prefixes']]
                elif 'SELECT * FROM produkty' in sql:
                    self.rows=[r for r in audit['evidence']['product_counters'] if r['produkt_id'] in plan['product_ids']]
                elif 'SELECT id, produkt_id, prefix, sn' in sql:
                    keys={(p['prefix'],p['old_sn']) for p in plan['proposals']}
                    self.rows=[dict(id=r['id'],produkt_id=r['form_id'],prefix=r['prefix'],sn=r['sn'])
                               for r in audit['evidence']['serial_peers'] if (r['prefix'],r['sn']) in keys]
                else: self.rows=[]
            def fetchone(self): return self.rows[0]
            def fetchall(self): return copy.deepcopy(self.rows)
            def close(self): pass
        cursor=Cursor()
        connection=Mock()
        connection.cursor.return_value=cursor
        return connection,cursor

    def test_readonly_check_never_calls_update_backup_or_commit(self):
        connection,cursor=self.connection()
        with patch.object(repair,'check_schema',return_value={}), \
             patch.object(repair,'numbering_maxima',return_value=self.audit['numbering_bases']), \
             patch.object(repair,'snapshot',side_effect=[self.before,self.originals]), \
             patch.object(repair,'write_backup') as backup, \
             patch.object(repair,'apply_operations') as apply:
            result=repair.run(connection,self.audit,apply=False)
        self.assertFalse(result['applied'])
        self.assertTrue(all(sql.startswith('SELECT') for sql in cursor.sqls))
        backup.assert_not_called()
        apply.assert_not_called()
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()

    def test_changed_original_after_updates_forces_rollback_without_commit(self):
        connection,_=self.connection()
        changes=repair.operations(self.plan,self.before)
        after=copy.deepcopy(self.before)
        for c in changes:
            row=next(r for r in after[c['table']] if r[c['pk']]==c['row_id'])
            row[c['column']]=c['new']
        damaged=copy.deepcopy(self.originals)
        damaged['lista_formowania_historia_v2'].append({'id':999999,'sn':123})
        with patch.dict('os.environ',{'MES_REPAIR_MAINTENANCE':'1'}), \
             patch.object(repair,'check_schema',return_value={}), \
             patch.object(repair,'numbering_maxima',return_value=self.audit['numbering_bases']), \
             patch.object(repair,'snapshot',side_effect=[self.before,self.originals,after,damaged]), \
             patch.object(repair,'write_backup',return_value=Path('offline-before-image.json')), \
             patch.object(repair,'apply_operations'):
            with self.assertRaisesRegex(repair.RepairError,'original casting'):
                repair.run(connection,self.audit,apply=True)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()


if __name__ == '__main__': unittest.main()
