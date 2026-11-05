"""Cancel real fixture rows without importing the application or using a live DB."""
import ast
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest


class Connection:
    def __init__(self, db):
        self.db = db
        self.fail = False
        self.commits = 0
        self.rollbacks = 0

    def start_transaction(self, **kwargs):
        self.db.execute('BEGIN')

    def cursor(self, **kwargs):
        return self

    def execute(self, sql, params):
        if self.fail and sql.startswith('DELETE FROM lista_formowania_v2'):
            raise RuntimeError('simulated failure')
        self.result = self.db.execute(sql.replace('%s', '?').replace('FOR UPDATE', ''), params)

    def fetchone(self):
        row = self.result.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self.result.fetchall()]

    def commit(self):
        self.commits += 1
        self.db.commit()

    def rollback(self):
        self.rollbacks += 1
        self.db.rollback()

    def close(self):
        pass


class OfficeCancellationTests(unittest.TestCase):
    routes = ('remove_from_forming_list_by_office', 'remove_from_forming_list_on_all_stages')

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE produkty(produkt_id INTEGER PRIMARY KEY, prefix TEXT, sztuk INTEGER, counter INTEGER);
            CREATE TABLE lista_formowania_v2(id INTEGER PRIMARY KEY,id_produktu INTEGER,prefix TEXT,item_status TEXT);
            CREATE TABLE lista_formowania_sn(id INTEGER PRIMARY KEY,produkt_id INTEGER,prefix TEXT,sn INTEGER,canceled TEXT DEFAULT '0');
            CREATE TABLE lista_formowania_formy_v2(id INTEGER PRIMARY KEY,produkt_id INTEGER,prod_id INTEGER,
                status TEXT DEFAULT 'active',zaformowano TEXT DEFAULT '0',model1_sn INTEGER,model2_sn INTEGER,
                model3_sn INTEGER,model4_sn INTEGER,model5_sn INTEGER,model6_sn INTEGER,model7_sn INTEGER,model8_sn INTEGER);
            CREATE TABLE lista_formowania_historia_v2(id INTEGER PRIMARY KEY AUTOINCREMENT,produkt_id INTEGER,production_stage TEXT,operator TEXT,sn INTEGER,prefix TEXT);
            INSERT INTO produkty VALUES(7,'AB',2,11),(8,'CD',1,99);
            INSERT INTO lista_formowania_v2 VALUES(100,7,'AB','new'),(200,8,'CD','formed');
            INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn,canceled) VALUES(0,90,'AB',9,'1'),(1,100,'AB',10,'0'),(2,100,'AB',11,'0'),(3,200,'CD',99,'0');
            INSERT INTO lista_formowania_formy_v2(id,produkt_id,prod_id,model1_sn,model2_sn) VALUES
                (0,90,7,9,NULL),(1,100,7,10,11),(2,100,7,10,11),(3,200,8,99,NULL);
            UPDATE lista_formowania_formy_v2 SET status='canceled' WHERE id=0;
            INSERT INTO lista_formowania_historia_v2(produkt_id,production_stage,operator) VALUES
                (100,'new','operator'),(200,'formed','operator');
        ''')
        self.db.execute('ALTER TABLE lista_formowania_sn ADD COLUMN alias TEXT')
        self.db.execute('ALTER TABLE lista_formowania_formy_v2 ADD COLUMN model_id INTEGER DEFAULT 215')
        self.db.execute('ALTER TABLE lista_formowania_formy_v2 ADD COLUMN alias TEXT')
        self.connection = Connection(self.db)
        self.messages = []
        self.locks = []
        def query(sql):
            return [dict(row) for row in self.db.execute(sql)]
        self.scope = dict(connect=lambda **kw:self.connection,
            app=SimpleNamespace(config=dict(MYSQL_HOST='test',MYSQL_PORT=3306,MYSQL_USER='test',MYSQL_PASSWORD='test',MYSQL_DATABASE='test'),logger=SimpleNamespace(exception=lambda *_:None)),
            session={'user':'office'},flash=self.messages.append,redirect=lambda target:target,url_for=lambda name:'/'+name,
            request=SimpleNamespace(form={}),zablokuj_prefix_new=lambda cur,prefix:self.locks.append(prefix),
            query_db=query,query_db_first=lambda sql:query(sql)[0],query_update=lambda sql:self.db.execute(sql))
        names = set(self.routes) | {'remove_outline_form','cancel_form_by_office','nadaj_nr_seryjny_new','nadaj_nr_seryjny','increse_counter','sn_validation_forms'}
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        for node in nodes:node.decorator_list=[]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<office>','exec'),self.scope)

    def rows(self,table):
        return [tuple(r) for r in self.db.execute('SELECT * FROM '+table+' ORDER BY rowid')]

    def snapshot(self):
        return {t:self.rows(t) for t in ('produkty','lista_formowania_v2','lista_formowania_sn','lista_formowania_formy_v2','lista_formowania_historia_v2')}

    def restore(self, snapshot):
        for table,rows in snapshot.items():
            self.db.execute('DELETE FROM '+table)
            if rows:self.db.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in rows[0])+')',rows)
        self.db.commit()

    def cancel(self, route='remove_from_forming_list_by_office', form_id=100, serial=' ab-11 '):
        self.db.commit()
        if route=='remove_from_forming_list_on_all_stages':
            self.scope['request'].form={'ns_form_aps':serial}
            return self.scope[route]()
        return self.scope[route](form_id)

    def next_numbers(self):
        return self.scope['nadaj_nr_seryjny_new'](self.connection,'AB',2)

    def add_newer_form(self, stage='new'):
        self.db.executescript(f'''
            INSERT INTO lista_formowania_v2 VALUES(101,7,'AB','{stage}');
            INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn,canceled) VALUES(4,101,'AB',12,'0'),(5,101,'AB',13,'0');
            INSERT INTO lista_formowania_formy_v2(id,produkt_id,prod_id,model1_sn,model2_sn) VALUES(4,101,7,12,13);
        ''')

    def test_last_new_releases_all_serials_in_every_route(self):
        original=self.snapshot()
        for route in self.routes:
            with self.subTest(route=route):
                self.cancel(route)
                self.assertEqual(self.next_numbers(),[10,11])
                self.assertFalse(self.db.execute('SELECT 1 FROM lista_formowania_sn WHERE produkt_id=100').fetchall())
                self.assertEqual(self.db.execute("SELECT COUNT(*) FROM lista_formowania_formy_v2 WHERE produkt_id=100 AND status='canceled'").fetchone()[0], 2)
                self.assertEqual(self.rows('lista_formowania_historia_v2')[:2],original['lista_formowania_historia_v2'])
                self.assertEqual(self.rows('lista_formowania_historia_v2')[-1][1:4],(100,'canceled by the offiice','office'))
                self.assertEqual([r[4:] for r in self.rows('lista_formowania_historia_v2') if r[2]=='canceled by the offiice'], [(10,'AB'),(11,'AB')])
                self.assertIn('zwolnione',self.messages[-1])
                self.assertEqual(self.rows('produkty'),original['produkty'])
                self.restore(original)

    def test_older_new_is_permanently_reserved_in_every_route(self):
        original=self.snapshot()
        for route in self.routes:
            with self.subTest(route=route):
                self.add_newer_form()
                self.cancel(route)
                self.assertEqual(self.next_numbers(),[14,15])
                self.assertEqual(self.db.execute("SELECT COUNT(*) FROM lista_formowania_sn WHERE produkt_id=100 AND canceled='1'").fetchone()[0],2)
                # Releasing the newer tail must not make the older canceled numbers reusable.
                self.cancel(route,form_id=101,serial='AB-13')
                self.assertEqual(self.next_numbers(),[12,13])
                self.assertIn('zablokowane',self.messages[-2])
                self.restore(original)

    def test_non_new_always_reserves_in_every_route(self):
        original=self.snapshot()
        for route in self.routes:
            for stage in ('formed','assembled','casted','knockout','buffer','grinding','defective','cooling','outside','ready_for_cooling','canceled'):
                with self.subTest(route=route,stage=stage):
                    self.db.execute('UPDATE lista_formowania_v2 SET item_status=? WHERE id=100',(stage,))
                    self.cancel(route)
                    self.assertEqual(self.next_numbers(),[12,13])
                    self.assertEqual(self.db.execute("SELECT COUNT(*) FROM lista_formowania_formy_v2 WHERE produkt_id=100 AND status='canceled'").fetchone()[0],2)
                    self.assertEqual(self.rows('produkty'),original['produkty'])
                    self.assertEqual(self.rows('lista_formowania_historia_v2')[-1][2],'canceled by the offiice')
                    self.restore(original)

    def test_newer_canceled_protected_form_still_counts_as_last(self):
        self.add_newer_form(stage='casted')
        self.cancel(form_id=101)
        self.cancel()
        self.assertEqual(self.next_numbers(),[14,15])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lista_formowania_sn WHERE produkt_id=100').fetchone()[0],2)

    def test_newer_live_form_without_parts_still_counts_as_last(self):
        self.db.execute("INSERT INTO lista_formowania_v2 VALUES(101,7,'AB','new')")
        self.cancel()
        self.assertEqual(self.next_numbers(),[12,13])
        self.assertIn('zablokowane',self.messages[-1])

    def test_second_casting_serial_removes_whole_form_only(self):
        self.db.execute("INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn,canceled) VALUES(4,999,'AB',11,'1')")
        before=self.snapshot()
        self.cancel('remove_from_forming_list_on_all_stages')
        self.assertEqual(self.rows('lista_formowania_v2'),[(200,8,'CD','formed')])
        self.assertEqual(self.rows('lista_formowania_sn'),[(0,90,'AB',9,'1',None),(3,200,'CD',99,'0',None),(4,999,'AB',11,'1',None)])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM lista_formowania_formy_v2 WHERE produkt_id=100 AND status='canceled'").fetchone()[0], 2)
        self.assertEqual(self.rows('lista_formowania_formy_v2')[0],before['lista_formowania_formy_v2'][0])
        self.assertEqual(self.rows('lista_formowania_formy_v2')[3],before['lista_formowania_formy_v2'][3])

    def test_missing_invalid_and_ambiguous_serial_do_not_change_data(self):
        self.db.execute("INSERT INTO lista_formowania_v2 VALUES(101,7,'AB','new')")
        self.db.execute("INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn,canceled) VALUES(4,101,'AB',11,'0')")
        self.db.commit()
        before=self.snapshot()
        for serial in ('AB-11','AB-999','bad','AB-0',''):
            self.cancel('remove_from_forming_list_on_all_stages',serial=serial)
            self.assertEqual(self.snapshot(),before)

    def test_transaction_rolls_back_all_changes_on_failure(self):
        before=self.snapshot()
        self.connection.fail=True
        self.cancel()
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.connection.rollbacks,1)
        self.assertEqual(self.connection.commits,0)

    def test_canceling_missing_form_does_not_add_history(self):
        self.cancel()
        before=self.snapshot()
        self.cancel()
        self.assertEqual(self.snapshot(),before)

    def test_alias_duplicate_is_blocked_in_all_routes_without_changes(self):
        self.add_newer_form()
        self.db.execute("UPDATE lista_formowania_sn SET sn=11 WHERE id=4")
        # Alias on the first casting must also protect a collision on the second.
        self.db.execute("UPDATE lista_formowania_sn SET alias='AB-10' WHERE id=1")
        self.db.commit()
        before = self.snapshot()
        for route in self.routes:
            with self.subTest(route=route):
                self.messages.clear()
                self.cancel(route)
                self.assertEqual(self.snapshot(), before)
                self.assertIn('Nie można usunąć formy', self.messages[-1])
                self.assertEqual(self.connection.commits, 0)

    def test_original_and_duplicate_are_both_blocked_in_all_routes(self):
        self.add_newer_form()
        self.db.execute("UPDATE lista_formowania_sn SET sn=11,alias='AB-11' WHERE id=4")
        self.db.commit()
        before = self.snapshot()
        for form_id in (100, 101):
            for route in self.routes:
                with self.subTest(form_id=form_id,route=route):
                    self.messages.clear()
                    self.cancel(route,form_id=form_id,serial='AB-11')
                    self.assertEqual(self.snapshot(),before)
                    self.assertEqual(self.connection.commits,0)
                    self.assertIn('Nie można usunąć formy',self.messages[-1])
                    if route != 'remove_from_forming_list_on_all_stages':
                        self.assertIn('Blokada dotyczy obu form',self.messages[-1])

    def test_alias_alone_does_not_block_removal(self):
        self.db.execute("UPDATE lista_formowania_sn SET alias='AB-10' WHERE produkt_id=100")
        self.cancel()
        self.assertFalse(self.db.execute('SELECT 1 FROM lista_formowania_v2 WHERE id=100').fetchall())

    def test_empty_aliases_do_not_block_removal_by_id(self):
        before = self.snapshot()
        for alias in (None, '', '  ', '-', ' - '):
            with self.subTest(alias=alias):
                self.add_newer_form()
                self.db.execute("UPDATE lista_formowania_sn SET sn=11 WHERE id=4")
                self.db.execute('UPDATE lista_formowania_sn SET alias=? WHERE produkt_id=100', (alias,))
                self.cancel()
                self.assertFalse(self.db.execute('SELECT 1 FROM lista_formowania_v2 WHERE id=100').fetchall())
                self.restore(before)

    def test_different_prefix_or_canceled_assignment_is_not_duplicate(self):
        before = self.snapshot()
        for prefix, canceled in [('CD', '0'), ('AB', '1')]:
            with self.subTest(prefix=prefix,canceled=canceled):
                self.add_newer_form()
                self.db.execute('UPDATE lista_formowania_sn SET sn=11,prefix=?,canceled=? WHERE id=4', (prefix,canceled))
                self.db.execute("UPDATE lista_formowania_sn SET alias='AB-10' WHERE produkt_id=100")
                self.cancel()
                self.assertFalse(self.db.execute('SELECT 1 FROM lista_formowania_v2 WHERE id=100').fetchall())
                self.restore(before)

    def test_outline_formed_duplicate_can_be_removed_without_changing_original(self):
        self.add_newer_form(stage='formed')
        self.db.execute("UPDATE lista_formowania_sn SET sn=11,alias='AB-11' WHERE id=4")
        before = self.snapshot()
        self.cancel('remove_outline_form', form_id=101)
        self.assertFalse(self.db.execute('SELECT 1 FROM lista_formowania_v2 WHERE id=101').fetchall())
        for table,column in [('lista_formowania_v2','id'),('lista_formowania_sn','produkt_id'),('lista_formowania_formy_v2','produkt_id')]:
            index=0 if column=='id' else 1
            self.assertEqual([r for r in self.rows(table) if r[index]==100], [r for r in before[table] if r[index]==100])
        self.assertEqual(self.rows('lista_formowania_historia_v2')[-1][1:4],(101,'canceled by the offiice','office'))
        self.assertTrue(all(r[4]=='1' for r in self.rows('lista_formowania_sn') if r[1]==101))

    def test_outline_button_rejects_other_statuses_and_original_without_alias(self):
        before = self.snapshot()
        for alias,status in [(None,'formed'),('', 'formed'),('-', 'formed'),('AB-10','new'),('AB-10','casted'),('AB-10','assembled')]:
            with self.subTest(alias=alias,status=status):
                self.db.execute('UPDATE lista_formowania_sn SET alias=? WHERE produkt_id=100',(alias,))
                self.db.execute('UPDATE lista_formowania_v2 SET item_status=? WHERE id=100',(status,))
                expected=self.snapshot()
                self.cancel('remove_outline_form')
                self.assertEqual(self.snapshot(),expected)
                self.assertIn('tylko formę poza kolejnością',self.messages[-1])
                self.restore(before)

    def test_canceled_parts_do_not_block_released_serials_in_forming_validator(self):
        self.cancel()
        self.assertTrue(self.scope['sn_validation_forms'](215,7,101,[10,11,'NULL','NULL','NULL','NULL','NULL','NULL']))

    def test_canceled_protected_parts_still_block_serials_in_forming_validator(self):
        self.db.execute("UPDATE lista_formowania_v2 SET item_status='formed' WHERE id=100")
        self.cancel()
        self.assertFalse(self.scope['sn_validation_forms'](215,7,101,[10,11,'NULL','NULL','NULL','NULL','NULL','NULL']))

    def test_legacy_allocator_respects_released_and_protected_serials(self):
        original=self.snapshot()
        for status,expected in [('new',(10,11)),('formed',(12,13))]:
            with self.subTest(status=status):
                self.db.execute('UPDATE lista_formowania_v2 SET item_status=? WHERE id=100',(status,))
                self.cancel()
                self.db.execute('INSERT INTO lista_formowania_formy_v2(id,produkt_id,prod_id) VALUES(4,101,7),(5,101,7)')
                self.scope['nadaj_nr_seryjny'](7)
                result=self.db.execute('SELECT model1_sn,model2_sn FROM lista_formowania_formy_v2 WHERE produkt_id=101').fetchall()
                self.assertEqual([tuple(r) for r in result],[expected,expected])
                self.restore(original)

if __name__=='__main__':unittest.main()
