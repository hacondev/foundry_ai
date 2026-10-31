"""Prepared SQL files are never sent to MariaDB. Exercise only DML on in-memory SQLite."""
from pathlib import Path
import re
import sqlite3
import unittest


DIRECTORY = Path(__file__).resolve().parents[1]/'migrations/alias_serials/AE_1040_69407'


class FirstCounterweightSqlTests(unittest.TestCase):
    def setUp(self):
        self.sql = (DIRECTORY/'03_repair.sql').read_text(encoding='utf-8')
        self.updates = re.findall(r'^\s*UPDATE\s+[^;]+;',self.sql,re.MULTILINE)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE lista_formowania_sn(id INTEGER,produkt_id INTEGER,prefix TEXT,sn INTEGER,alias TEXT,updated_at TEXT);
            INSERT INTO lista_formowania_sn VALUES
                (69407,39041,'AE',1040,'AE-1040','old'),(69408,39041,'AE',1041,'AE-1040','old'),
                (68596,38660,'AE',1040,NULL,'old'),(68597,38660,'AE',1041,NULL,'old');
            CREATE TABLE lista_formowania_formy_v2(id INTEGER,produkt_id INTEGER,prefix TEXT,model1_sn INTEGER,model2_sn INTEGER,alias TEXT,czas_ostatniej_modyfiakcji TEXT);
            INSERT INTO lista_formowania_formy_v2 VALUES
                (86252,39041,'AE',1040,1041,'AE-1040','old'),(86253,39041,'AE',1040,1041,'AE-1040','old'),
                (85363,38660,'AE',1040,1041,NULL,'old'),(85364,38660,'AE',1040,1041,NULL,'old');
            CREATE TABLE lista_formowania_historia_v2(id INTEGER,produkt_id INTEGER,prefix TEXT,sn INTEGER,production_stage TEXT,czas TEXT);
            INSERT INTO lista_formowania_historia_v2 VALUES
                (367509,39041,'AE',1040,'qa_ok','old'),(363046,39041,'AE',1041,'qa_ok','old'),
                (900001,38660,'AE',1040,'shimpment','old'),(900002,39041,NULL,NULL,'formed','old');
            CREATE TABLE mecalac_fr_inspection(id INTEGER,ids INTEGER,prefix TEXT,sn INTEGER,czas TEXT);
            INSERT INTO mecalac_fr_inspection VALUES
                (521,39041,'AE',1040,'old'),(489,39041,'AE',1041,'old'),(500,38660,'AE',1040,'old');
            CREATE TABLE casting_report_tmp(record_id INTEGER,id INTEGER,prefix TEXT,sn INTEGER,alias TEXT,updated_at TEXT);
            INSERT INTO casting_report_tmp VALUES
                (1213,39041,'AE',1040,'AE-1040','old'),(1214,39041,'AE',1041,'AE-1040','old'),
                (1215,38660,'AE',1040,NULL,'old');
            CREATE TABLE produkty(produkt_id INTEGER,prefix TEXT,counter INTEGER);
            INSERT INTO produkty VALUES (77,'AE',1057);
        ''')
        self.tables=['lista_formowania_sn','lista_formowania_formy_v2',
                     'lista_formowania_historia_v2','mecalac_fr_inspection','casting_report_tmp','produkty']

    def snapshot(self):
        return {table:self.db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                for table in self.tables}

    def test_exactly_one_casting_is_renumbered_and_original_and_other_piece_survive(self):
        before=self.snapshot()
        self.assertEqual(len(self.updates),6)
        changed=0
        for statement in self.updates:
            changed+=self.db.execute(statement.replace('counter=v_counter','counter=1057')).rowcount
        self.assertEqual(changed,7)
        after=self.snapshot()
        expected={table:list(rows) for table,rows in before.items()}
        expected['lista_formowania_sn'][0]=(69407,39041,'AE',1058,'AE-1040','old')
        for i,row_id in enumerate((86252,86253)):
            expected['lista_formowania_formy_v2'][i]=(row_id,39041,'AE',1058,1041,'AE-1040','old')
        expected['lista_formowania_historia_v2'][0]=(367509,39041,'AE',1058,'qa_ok','old')
        expected['mecalac_fr_inspection'][0]=(521,39041,'AE',1058,'old')
        expected['casting_report_tmp'][0]=(1213,39041,'AE',1058,'AE-1040','old')
        expected['produkty'][0]=(77,'AE',1058)
        self.assertEqual(after,expected)

    def test_updates_can_be_rolled_back_without_changing_any_record(self):
        before=self.snapshot()
        self.db.execute('BEGIN')
        for statement in self.updates:
            self.db.execute(statement.replace('counter=v_counter','counter=1057'))
        self.db.rollback()
        self.assertEqual(self.snapshot(),before)

    def test_no_automatic_call_and_inspection_files_are_readonly(self):
        active='\n'.join(line for line in self.sql.splitlines() if not line.lstrip().startswith('--'))
        self.assertIsNone(re.search(r'^\s*CALL\b',active,re.MULTILINE|re.IGNORECASE))
        self.assertIn('ROLLBACK;',self.sql)
        self.assertIn('RESIGNAL;',self.sql)
        self.assertIn('IF v_phase=0 THEN',self.sql)
        for name in ('01_check.sql','04_verify.sql'):
            text=(DIRECTORY/name).read_text(encoding='utf-8')
            active='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('--'))
            self.assertIsNone(re.search(r'^\s*(UPDATE|INSERT|DELETE|CREATE|DROP|CALL)\b',
                                        active,re.MULTILINE|re.IGNORECASE))


if __name__=='__main__': unittest.main()
