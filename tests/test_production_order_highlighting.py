"""Check the actual forming query without importing the app or using production."""
import ast
from pathlib import Path
import re
import sqlite3
import unittest


class ProductionOrderHighlightingTests(unittest.TestCase):
    def test_serials_are_paired_by_id_and_highlighted_individually(self):
        source = Path(__file__).resolve().parents[1].joinpath('main.py').read_text(encoding='utf-8')
        forming = next(n for n in ast.parse(source).body
                       if isinstance(n, ast.FunctionDef) and n.name == 'forming')
        query = next(ast.literal_eval(n.value) for n in forming.body
                     if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'sql' for t in n.targets))
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
            ''')
            db.row_factory = sqlite3.Row
            rows = {row['id']: dict(row) for row in db.execute(query)}
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
