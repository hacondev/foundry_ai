"""Run the view queries against conflicting form and copied trial flags."""
import ast
from pathlib import Path
import sqlite3
import unittest


class TrialViewSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).resolve().parents[1].joinpath(
            'main.py').read_text(encoding='utf-8'))

    def queries(self, function, fragment):
        node = next(n for n in self.tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == function)
        return [n.value for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and fragment in n.value and 'SELECT' in n.value]

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE lista_formowania_v2 (
                id INTEGER, trail TEXT, item_status TEXT, id_produktu INTEGER,
                nazwa_produktu TEXT, data_ostatniej_modyfikacji TEXT,
                data_zalania TEXT, nr_kadzi TEXT, filtr TEXT, broken TEXT,
                temp_zeliwa TEXT, data_dodania TEXT, zmodyfikowane_przez TEXT);
            INSERT INTO lista_formowania_v2(id, trail, item_status, id_produktu)
                VALUES (1,'0','assembled',10),(2,'1','assembled',10),
                       (3,'0','casted',10),(4,'1','casted',10);
            CREATE TABLE produkty (
                produkt_id INTEGER, czas_studzenia INTEGER,
                dni_do_wybicia INTEGER, waga_zeliwa INTEGER);
            INSERT INTO produkty VALUES (10,1,1,100);
            CREATE TABLE lista_formowania_sn(produkt_id INTEGER, trail INTEGER);
            INSERT INTO lista_formowania_sn VALUES (1,1),(2,0),(3,1),(4,0);
            CREATE TABLE grinding(id INTEGER, item_id INTEGER, mode TEXT, trail INTEGER);
            INSERT INTO grinding VALUES (10,1,'0',1),(20,2,'1',0),
                                        (30,3,'3',1),(40,4,'4',0);
            CREATE TABLE mafi_load (
                id INTEGER, id_mafi INTEGER, id_form INTEGER,
                czas TEXT, mafi_status TEXT, trail TEXT);
            INSERT INTO mafi_load VALUES
                (1,100,1,'2026-10-30','ready_to_knockout','1'),
                (2,200,1,'2026-10-29','load','0'),
                (3,200,2,'2026-10-30','load','0'),
                (4,100,2,'2026-10-29','unload','1');
        ''')

    def test_both_casting_tables_use_form_flags(self):
        queries = self.queries('foundry_operator_view2', 'AS trail')
        self.assertEqual(len(queries), 2)
        for query in queries:
            rows = {r['id']: r['trail'] for r in self.db.execute(query)}
            self.assertIn(rows, ({1: '0', 2: '1'}, {3: '0', 4: '1'}))

    def test_grinding_lists_use_current_form_flags(self):
        for view, expected in [('grinding_done', {10: 0, 20: 1}),
                               ('grinding_rework', {30: 0, 40: 1})]:
            with self.subTest(view=view):
                query, = self.queries(view, 'AS current_trail')
                rows = {r['id']: r['current_trail'] for r in self.db.execute(query)}
                self.assertEqual(rows, expected)

    def test_mafi_ignores_stale_flags_and_unloaded_forms(self):
        query, = self.queries('knockout_operator_view', 'AS current_trail')
        rows = {r['id_mafi']: r['current_trail'] for r in self.db.execute(query)}
        self.assertEqual(rows, {100: '0', 200: '1'})
        self.db.execute("UPDATE lista_formowania_v2 SET trail = '0' WHERE id = 2")
        rows = {r['id_mafi']: r['current_trail'] for r in self.db.execute(query)}
        self.assertEqual(rows, {100: '0', 200: '0'})


if __name__ == '__main__':
    unittest.main()
