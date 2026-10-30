"""Check the actual forming query without importing the app or using production."""
import ast
from datetime import date
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace
import unittest


class ProductionOrderHighlightingTests(unittest.TestCase):
    def test_deleting_shipment_after_removing_its_castings_clears_highlights(self):
        query, params = self.forming_query()
        with sqlite3.connect(':memory:') as db:
            db.row_factory = sqlite3.Row
            columns = sorted(set(re.findall(r'tab1\.(\w+)', query)) - {'serial_position'})
            db.execute('CREATE TABLE open_orders_sap (' + ', '.join(
                name + (' INTEGER' if name == 'id' else ' TEXT') for name in columns) + ')')
            db.executescript('''
                CREATE TABLE sap_mes_relation(item_index TEXT, index_odlew TEXT, nazwa_odlew TEXT);
                CREATE TABLE lista_formowania_sn(id INTEGER, mes_po_id TEXT, produkt_id INTEGER, prefix TEXT, sn INTEGER, canceled INTEGER);
                CREATE TABLE lista_formowania_historia_v2(id INTEGER PRIMARY KEY AUTOINCREMENT, produkt_id INTEGER, production_stage TEXT, prefix TEXT, sn INTEGER, czas TEXT);
                CREATE TABLE shipments(id INTEGER, mode TEXT, status TEXT);
                CREATE TABLE shipments_items(id INTEGER, ship_id INTEGER, form_id INTEGER, sn TEXT, status TEXT);
                INSERT INTO shipments VALUES (7,'open','active');
                INSERT INTO shipments_items VALUES (1,7,100,'KU-33','active'),(2,7,100,'KU-34','active');
                INSERT INTO open_orders_sap(id, unique_id, data_wysylki)
                    VALUES (1,'A','2026-11-01'),(2,'A','2026-11-01');
                INSERT INTO lista_formowania_sn VALUES
                    (1,'A',100,'KU',33,0),(2,'A',100,'KU',34,0);
                INSERT INTO lista_formowania_historia_v2(produkt_id, production_stage, prefix, sn)
                    VALUES (100,'shimpment','KU',33),(100,'shimpment','KU',34);
            ''')
            def flags():
                return {r['assigned_sn']: r['has_shipment_history']
                        for r in db.execute(query, params)}

            def history_qa(form_id, sn, prefix, stage, operator):
                db.execute('INSERT INTO lista_formowania_historia_v2 '
                           '(produkt_id, sn, prefix, production_stage) VALUES (?,?,?,?)',
                           (form_id, sn, prefix, stage))

            scope = dict(g=SimpleNamespace(user=True), session={'user_id': 18, 'user': 'test'},
                         request=SimpleNamespace(referrer='/shipment'),
                         query_db=lambda sql: [dict(r) for r in db.execute(sql)],
                         query_update=db.execute, history_qa=history_qa,
                         history_shipment=lambda *args: None,
                         flash=lambda message: None, redirect=lambda url: url)
            source = ast.parse(Path(__file__).resolve().parents[1].joinpath(
                'main.py').read_text(encoding='utf-8'))
            functions = [n for n in source.body if isinstance(n, ast.FunctionDef)
                         and n.name in ('del_item_shipment', 'remove_shipment')]
            for node in functions:
                node.decorator_list = []
            exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), scope)
            self.assertEqual(flags(), {33: 1, 34: 1})
            scope['remove_shipment']('7')
            self.assertEqual(db.execute('SELECT status FROM shipments').fetchone()[0], 'active')
            self.assertEqual(flags(), {33: 1, 34: 1})
            scope['del_item_shipment']('1')
            self.assertEqual(flags(), {33: 0, 34: 1})
            scope['del_item_shipment']('2')
            self.assertEqual(flags(), {33: 0, 34: 0})
            scope['remove_shipment']('7')
            self.assertEqual(db.execute('SELECT status FROM shipments').fetchone()[0], 'inactive')
            self.assertEqual(flags(), {33: 0, 34: 0})

    def test_shipping_highlight_accepts_both_status_spellings_for_matching_casting(self):
        query, params = self.forming_query()
        with sqlite3.connect(':memory:') as db:
            columns = sorted(set(re.findall(r'tab1\.(\w+)', query)) - {'serial_position'})
            db.execute('CREATE TABLE open_orders_sap (' + ', '.join(
                name + (' INTEGER' if name == 'id' else ' TEXT') for name in columns) + ')')
            db.executescript('''
                CREATE TABLE sap_mes_relation(item_index TEXT, index_odlew TEXT, nazwa_odlew TEXT);
                CREATE TABLE lista_formowania_sn(id INTEGER, mes_po_id TEXT, produkt_id INTEGER, prefix TEXT, sn INTEGER, canceled INTEGER);
                CREATE TABLE lista_formowania_historia_v2(produkt_id INTEGER, production_stage TEXT, prefix TEXT, sn INTEGER, czas TEXT);
                INSERT INTO open_orders_sap(id, unique_id, data_wysylki)
                    VALUES (1,'A','2026-11-01'),(2,'A','2026-11-01'),
                           (3,'A','2026-11-01'),(4,'A','2026-11-01'),(5,'A','2026-11-01');
                INSERT INTO lista_formowania_sn VALUES
                    (1,'A',100,'KU',33,0),(2,'A',100,'KU',34,0),
                    (3,'A',100,'KU',35,0),(4,'A',100,'KU',36,0),(5,'A',200,'KU',37,0);
                INSERT INTO lista_formowania_historia_v2 VALUES
                    (100,'shimpment','KU',33,NULL),
                    (100,'shipment','KU',34,NULL),
                    (100,'shimpment','OTHER',35,NULL),
                    (100,'shimpment-removed','KU',36,NULL),
                    (999,'shimpment','KU',37,NULL);
                ALTER TABLE lista_formowania_historia_v2 ADD COLUMN id INTEGER;
                UPDATE lista_formowania_historia_v2 SET id = rowid;
            ''')
            db.row_factory = sqlite3.Row
            rows = {r['assigned_sn']: r['has_shipment_history']
                    for r in db.execute(query, params)}
            self.assertEqual(rows, {33: 1, 34: 1, 35: 0, 36: 0, 37: 0})
            # A newer removal clears only the matching casting, even with equal timestamps.
            db.execute("INSERT INTO lista_formowania_historia_v2 VALUES (100,'shimpment-removed','KU',33,NULL,10)")
            rows = {r['assigned_sn']: r['has_shipment_history']
                    for r in db.execute(query, params)}
            self.assertEqual(rows, {33: 0, 34: 1, 35: 0, 36: 0, 37: 0})
            # Re-adding restores the highlight; unrelated later history has no effect.
            db.executescript('''
                INSERT INTO lista_formowania_historia_v2 VALUES
                    (100,'shimpment','KU',33,NULL,11),
                    (100,'shimpment-removed','OTHER',33,NULL,12),
                    (999,'shimpment-removed','KU',33,NULL,13),
                    (100,'qa_ok','KU',33,NULL,14),
                    (100,'shipment-removed','KU',34,NULL,15);
            ''')
            rows = {r['assigned_sn']: r['has_shipment_history']
                    for r in db.execute(query, params)}
            self.assertEqual(rows, {33: 1, 34: 0, 35: 0, 36: 0, 37: 0})

    @staticmethod
    def forming_query(**options):
        """Execute only query construction, including the current date filters."""
        source = Path(__file__).resolve().parents[1].joinpath('main.py').read_text(encoding='utf-8')
        forming = next(n for n in ast.parse(source).body
                       if isinstance(n, ast.FunctionDef) and n.name == 'get_production_orders_context')
        start = next(index for index, node in enumerate(forming.body)
                     if isinstance(node, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'sql' for t in node.targets))
        end = next(index for index in range(start + 1, len(forming.body))
                   if isinstance(forming.body[index], ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'cursor'
                           for t in forming.body[index].targets))
        scope = dict(show_all_records=True, min_date=None, end_date=None, include_undated=True)
        scope.update(options)
        query_code = ast.Module(body=forming.body[start:end], type_ignores=[])
        exec(compile(query_code, 'main.py', 'exec'), {'__builtins__': {}}, scope)
        return scope['sql'].replace('%s', '?'), scope['date_params']

    def test_serials_are_paired_by_id_and_highlighted_individually(self):
        query, params = self.forming_query()
        with sqlite3.connect(':memory:') as db:
            columns = sorted(set(re.findall(r'tab1\.(\w+)', query)) - {'serial_position'})
            db.execute('CREATE TABLE open_orders_sap (' + ', '.join(
                name + (' INTEGER' if name == 'id' else ' TEXT') for name in columns) + ')')
            db.executescript('''
                CREATE TABLE sap_mes_relation(item_index TEXT, index_odlew TEXT, nazwa_odlew TEXT);
                CREATE TABLE lista_formowania_sn(id INTEGER, mes_po_id TEXT, produkt_id INTEGER, prefix TEXT, sn INTEGER);
                CREATE TABLE lista_formowania_historia_v2(produkt_id INTEGER, production_stage TEXT, prefix TEXT, sn INTEGER);
                INSERT INTO open_orders_sap(id, unique_id) VALUES (30,'A'),(10,'A'),(20,'A'),(40,'B'),(50,'C'),(60,'C');
                INSERT INTO lista_formowania_sn VALUES (200,'A',2,'X',2),(100,'A',1,'X',1),(300,'C',3,'Y',1),(400,'C',3,'Y',2);
                INSERT INTO lista_formowania_historia_v2 VALUES (1,'new',NULL,NULL),(2,'formed',NULL,NULL),(2,'formed',NULL,NULL),(2,'casted',NULL,NULL),(3,'formed','Y',2);
                INSERT INTO lista_formowania_historia_v2 VALUES (2,'knockout',NULL,NULL),(2,'knockout',NULL,NULL),(3,'knockout','Y',1),(3,'knockout','OTHER',2);
                INSERT INTO lista_formowania_historia_v2 VALUES (2,'grinding',NULL,NULL),(2,'grinding',NULL,NULL),(3,'grinding-repaired','Y',2),(3,'grinding','OTHER',1);
                INSERT INTO lista_formowania_historia_v2 VALUES (2,'qa_ok',NULL,NULL),(2,'qa_ok',NULL,NULL),(3,'qa_nok','Y',1),(3,'qa_ok','OTHER',2);
                INSERT INTO lista_formowania_historia_v2 VALUES (2,'shipment',NULL,NULL),(2,'shipment',NULL,NULL),(3,'shipment','Y',2),(3,'shipment','OTHER',1);
            ''')
            db.executescript('''
                ALTER TABLE lista_formowania_historia_v2 ADD COLUMN czas TEXT;
                UPDATE lista_formowania_historia_v2 SET czas = '2026-11-02 10:00:00'
                    WHERE production_stage = 'casted';
                INSERT INTO lista_formowania_historia_v2 VALUES
                    (2,'casted',NULL,NULL,'2026-11-03 11:00:00'),
                    (3,'casted','Y',2,'2026-11-04 12:00:00'),
                    (3,'casted','OTHER',1,'2026-11-05 13:00:00');
                ALTER TABLE lista_formowania_historia_v2 ADD COLUMN id INTEGER;
                UPDATE lista_formowania_historia_v2 SET id = rowid;
            ''')
            db.execute("ALTER TABLE lista_formowania_sn ADD COLUMN canceled INTEGER DEFAULT 0")
            db.row_factory = sqlite3.Row
            rows = {row['production_order_id']: dict(row) for row in db.execute(query, params)}
            db.executescript('''
                UPDATE open_orders_sap SET data_form = '2026-11-10';
                UPDATE open_orders_sap SET data_form = '2026-11-01' WHERE id IN (10, 50);
                UPDATE open_orders_sap SET data_form = NULL WHERE id = 40;
                UPDATE open_orders_sap SET data_form = '2026-11-11' WHERE id = 30;
            ''')
            for include_undated, expected in [(False, {20: 2, 60: 2}),
                                              (True, {20: 2, 40: None, 60: 2})]:
                with self.subTest(include_undated=include_undated):
                    filtered_query, filtered_params = self.forming_query(
                        min_date=date(2026, 11, 10), end_date=date(2026, 11, 11),
                        include_undated=include_undated)
                    filtered = {row['production_order_id']: row['assigned_sn']
                                for row in db.execute(filtered_query, filtered_params)}
                    self.assertEqual(filtered, expected)
            for show_all_records in (False, True):
                with self.subTest(show_all_records=show_all_records):
                    dated_query, dated_params = self.forming_query(
                        show_all_records=show_all_records, include_undated=False)
                    dated_rows = list(db.execute(dated_query, dated_params))
                    self.assertEqual(len(dated_rows), 5)
                    self.assertEqual({row['unique_id'] for row in dated_rows}, {'A', 'C'})
        self.assertEqual(len(rows), 6)
        self.assertEqual([rows[i]['data_zalania'] for i in (10, 20, 30, 40, 50, 60)],
                         [None, '2026-11-03 11:00:00', None, None, None, '2026-11-04 12:00:00'])
        self.assertEqual([rows[i]['assigned_sn'] for i in (10, 20, 30)], [1, 2, None])
        self.assertEqual([rows[i]['has_formed_history'] for i in (10, 20, 30, 40, 50, 60)],
                         [0, 1, 0, 0, 0, 1])
        self.assertEqual([rows[i]['has_knockout_history'] for i in (10, 20, 30, 40, 50, 60)],
                         [0, 1, 0, 0, 1, 0])
        self.assertEqual([rows[i]['has_grinding_history'] for i in (10, 20, 30, 40, 50, 60)],
                         [0, 1, 0, 0, 0, 1])
        self.assertEqual([rows[i]['has_qa_history'] for i in (10, 20, 30, 40, 50, 60)],
                         [0, 1, 0, 0, 1, 0])
        self.assertEqual([rows[i]['has_shipment_history'] for i in (10, 20, 30, 40, 50, 60)],
                         [0, 1, 0, 0, 0, 1])


if __name__ == '__main__':
    unittest.main()
