"""Only UPDATE fragments run on SQLite. The MariaDB procedure is never executed."""
from pathlib import Path
import re
import sqlite3
import unittest


SQL_PATH = Path(__file__).resolve().parents[1]/'migrations/alias_serials/ME_1425_70072/repair.sql'


class MeSerialSqlTests(unittest.TestCase):
    def setUp(self):
        self.sql=SQL_PATH.read_text(encoding='utf-8')
        self.updates=re.findall(r'^\s*UPDATE\s+[^;]+;',self.sql,re.MULTILINE)
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE lista_formowania_sn(id INTEGER,produkt_id INTEGER,prefix TEXT,sn INTEGER,alias TEXT,updated_at TEXT);
            INSERT INTO lista_formowania_sn VALUES (70072,39376,'ME',1425,'ME-1425','old');
            CREATE TABLE lista_formowania_formy_v2(id INTEGER,produkt_id INTEGER,prefix TEXT,model1_sn INTEGER,alias TEXT,czas_ostatniej_modyfiakcji TEXT);
            INSERT INTO lista_formowania_formy_v2 VALUES
                (86994,39376,'ME',1425,'ME-1425','old'),(86995,39376,'ME',1425,'ME-1425','old'),
                (86880,39325,'ME',1425,NULL,'old'),(86881,39325,'ME',1425,NULL,'old');
            CREATE TABLE lista_formowania_historia_v2(id INTEGER,produkt_id INTEGER,prefix TEXT,sn INTEGER,czas TEXT);
            INSERT INTO lista_formowania_historia_v2 VALUES
                (364583,39376,'ME',1425,'old'),(366189,39376,'ME',1425,'old'),(366530,39376,'ME',1425,'old'),
                (364007,39376,NULL,NULL,'old'),(364002,39375,NULL,NULL,'old'),(900000,39325,'ME',1425,'old');
            CREATE TABLE grinding(id INTEGER,item_id INTEGER,prefix TEXT,sn INTEGER,alias TEXT,czas TEXT);
            INSERT INTO grinding VALUES (14436,39376,'ME',1425,'ME-1425','old');
            CREATE TABLE mecalac_fr_inspection(id INTEGER,ids INTEGER,prefix TEXT,sn INTEGER,czas TEXT);
            INSERT INTO mecalac_fr_inspection VALUES (512,39376,'ME',1425,'old');
            CREATE TABLE defects(id INTEGER,form_id INTEGER,sn INTEGER,czas TEXT);
            INSERT INTO defects VALUES (8314,39376,1425,'old');
            CREATE TABLE shipments_items(id INTEGER,form_id INTEGER,sn TEXT,czas TEXT);
            INSERT INTO shipments_items VALUES (2281,39376,'ME-1425','old');
            CREATE TABLE shipments_history(id INTEGER,sn TEXT);
            INSERT INTO shipments_history VALUES (3257,'ME-1425');
            CREATE TABLE casting_report_tmp(record_id INTEGER,id INTEGER,prefix TEXT,sn INTEGER,alias TEXT,updated_at TEXT);
            INSERT INTO casting_report_tmp VALUES (662,39376,'ME',1425,'ME-1425','old');
            CREATE TABLE produkty(produkt_id INTEGER,prefix TEXT,counter INTEGER);
            INSERT INTO produkty VALUES (62,'ME',1432);
        ''')
        self.tables=[r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    def snapshot(self):
        return {table:self.db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in self.tables}

    def test_nine_updates_preserve_aliases_dates_and_other_forms(self):
        before=self.snapshot()
        counts=[self.db.execute(sql).rowcount for sql in self.updates]
        self.assertEqual(counts,[1,2,3,1,1,1,1,1,1])
        after=self.snapshot()
        for table in self.tables:
            columns=[r[1] for r in self.db.execute(f'PRAGMA table_info({table})')]
            for old,new in zip(before[table],after[table]):
                for col,old_value,new_value in zip(columns,old,new):
                    if old_value!=new_value:
                        self.assertIn(col,('sn','model1_sn','counter'))
                        self.assertEqual(new_value,'ME-1433' if isinstance(old_value,str) else 1433)
        self.assertEqual(after['lista_formowania_formy_v2'][2:],before['lista_formowania_formy_v2'][2:])
        self.assertEqual(after['lista_formowania_historia_v2'][3:],before['lista_formowania_historia_v2'][3:])
        self.assertEqual(after['shipments_history'],before['shipments_history'])

    def test_partial_failure_rolls_back(self):
        before=self.snapshot()
        self.db.execute('BEGIN')
        with self.assertRaises(sqlite3.OperationalError):
            try:
                for statement in self.updates[:3]: self.db.execute(statement)
                self.db.execute('SELECT nonexistent_column')
            except sqlite3.OperationalError:
                self.db.rollback()
                raise
        self.assertEqual(self.snapshot(),before)

    def test_batch_has_automatic_commit_and_rollback_handler(self):
        self.assertEqual(len(self.updates),9)
        self.assertEqual(len(re.findall(r'IF ROW_COUNT\(\)<>',self.sql)),9)
        self.assertIn('DECLARE EXIT HANDLER FOR SQLEXCEPTION',self.sql)
        self.assertIn('ROLLBACK;\n        RESIGNAL;',self.sql)
        self.assertRegex(self.sql,r'\n    COMMIT;')
        self.assertRegex(self.sql,r'\nCALL tower\.repair_me_1425_70072\(\);')
        self.assertIn('SELECT counter INTO v_counter',self.sql)
        self.assertNotIn('-- COMMIT;',self.sql)
        self.assertLess(self.sql.index('\nROLLBACK;'),self.sql.index('DROP PROCEDURE'))


if __name__=='__main__': unittest.main()
