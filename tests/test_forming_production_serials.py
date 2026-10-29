import ast
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class ProductionSerialTests(unittest.TestCase):
    def test_four_castings_from_two_forms_are_visible_for_one_order(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'get_production_orders_context')
        assignment = next(n for n in function.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'sql' for t in n.targets))
        sql = ''.join(part.value for part in assignment.value.values)
        with sqlite3.connect(':memory:') as db:
            for alias, table in [('tab1', 'open_orders_sap'), ('tab2', 'sap_mes_relation')]:
                fields = sorted(set(re.findall(alias + r'\.(\w+)', sql)) - {'serial_position'})
                db.execute('CREATE TABLE ' + table + '(' + ','.join(f + ' TEXT' for f in fields) + ')')
            db.executescript('''
                CREATE TABLE lista_formowania_sn(id INTEGER, mes_po_id TEXT, prefix TEXT, sn INTEGER, produkt_id INTEGER);
                CREATE TABLE lista_formowania_historia_v2(produkt_id INTEGER, production_stage TEXT, prefix TEXT, sn INTEGER, czas TEXT);
                INSERT INTO open_orders_sap(unique_id,item_index) VALUES ('198-30387-127','P');
                INSERT INTO sap_mes_relation(item_index) VALUES ('P'),('P');
                INSERT INTO lista_formowania_sn VALUES
                    (1,'198-30387-127','SK',7692,10),
                    (2,'198-30387-127','SK',7693,10),
                    (3,'198-30387-127','SK',7694,11),
                    (4,'198-30387-127','SK',7695,11),
                    (5,'OTHER','SK',7696,12);
            ''')
            db.row_factory = sqlite3.Row
            rows = db.execute(sql).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['assigned_sn'] for r in rows}, {7692, 7693, 7694, 7695})

    def test_order_expands_to_one_row_per_assigned_serial(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        forming = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_production_orders_context')
        assignment = next(n for n in forming.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'sql' for t in n.targets))
        sql = ''.join(part.value for part in assignment.value.values)
        with sqlite3.connect(':memory:') as db:
            for alias, table in [('tab1', 'open_orders_sap'), ('tab2', 'sap_mes_relation')]:
                fields = sorted(set(re.findall(alias + r'\.(\w+)', sql)) - {'serial_position'})
                db.execute('CREATE TABLE ' + table + '(' + ','.join(f + ' TEXT' for f in fields) + ')')
            db.executescript('''
                CREATE TABLE lista_formowania_sn(id INTEGER, mes_po_id TEXT, prefix TEXT, sn INTEGER, produkt_id INTEGER);
                CREATE TABLE lista_formowania_historia_v2(produkt_id INTEGER, production_stage TEXT, prefix TEXT, sn INTEGER);
                INSERT INTO open_orders_sap(unique_id,item_index,data_prod) VALUES ('A','P','2026-10-21'),('B','P','2026-10-21');
                INSERT INTO sap_mes_relation(item_index) VALUES ('P');
                INSERT INTO lista_formowania_sn VALUES (1,'A','X',101,10),(2,'A','X',102,10),(3,'OTHER','X',103,20);
                INSERT INTO lista_formowania_historia_v2 VALUES (10,'formed','X',101),(10,'formed','X',101),(10,'formed','OTHER',102),(10,'new','X',102),(20,'formed',NULL,NULL);
                INSERT INTO lista_formowania_historia_v2 VALUES (10,'knockout','X',102),(10,'knockout','X',102),(10,'knockout','OTHER',101);
                INSERT INTO lista_formowania_historia_v2 VALUES (10,'grinding','X',101),(10,'grinding-repaired','X',102),(10,'grinding','X',101),(20,'grinding','X',101);
                INSERT INTO lista_formowania_historia_v2 VALUES (10,'qa_ok','X',101),(10,'qa_nok','X',102),(10,'qa_ok','X',101),(20,'qa_ok','X',101);
                INSERT INTO lista_formowania_historia_v2 VALUES (10,'shipment','X',102),(10,'shipment','X',102),(10,'shipment','OTHER',101),(20,'shipment','X',101);
                ALTER TABLE lista_formowania_historia_v2 ADD COLUMN czas TEXT;
                INSERT INTO lista_formowania_historia_v2 VALUES
                    (10,'casted','X',101,'2026-10-20 12:00:00'),
                    (10,'casted','X',101,'2026-10-21 13:00:00'),
                    (10,'casted','OTHER',102,'2026-10-22 14:00:00');
            ''')
            db.row_factory = sqlite3.Row
            rows = db.execute(sql).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual({(r['unique_id'], r['assigned_sn']) for r in rows},
                         {('A', 101), ('A', 102), ('B', None)})
        self.assertEqual({r['assigned_sn']:r['has_formed_history'] for r in rows},
                         {101:1,102:0,None:0})
        self.assertEqual({r['assigned_sn']:r['has_knockout_history'] for r in rows},
                         {101:0,102:1,None:0})
        self.assertEqual({r['assigned_sn']:r['has_grinding_history'] for r in rows},
                         {101:1,102:1,None:0})
        self.assertEqual({r['assigned_sn']:r['has_qa_history'] for r in rows},
                         {101:1,102:1,None:0})
        self.assertEqual({r['assigned_sn']:r['has_shipment_history'] for r in rows},
                         {101:0,102:1,None:0})
        self.assertEqual({r['assigned_sn']:r['data_zalania'] for r in rows},
                         {101:'2026-10-21 13:00:00',102:None,None:None})

    def test_table_columns_serials_and_unique_modals(self):
        source = (ROOT / 'templates/forming.html').read_text(encoding='utf-8')
        Environment().parse(source)
        start = source.index('{% macro production_value')
        end = source.index('</table>', start)
        items = [defaultdict(lambda: None, unique_id='A', assigned_prefix='X', assigned_sn=n)
                 for n in (101, 102, None)]
        html = Environment().from_string(source[start:end] + '</table>').render(
            production_orders=items,
            url_for=lambda endpoint, **params: '/quality?sn=' + params['sn'])
        class Parser(HTMLParser):
            def __init__(self): super().__init__(); self.rows=[]; self.ids=[]
            def handle_starttag(self, tag, attrs):
                if tag=='tr': self.rows.append(0)
                if tag in ('th','td'): self.rows[-1]+=1
                self.ids.extend(value for key,value in attrs if key=='id')
        parser=Parser(); parser.feed(html)
        self.assertEqual(parser.rows,[25,25,25,25,25])
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        self.assertIn('X-101',html)
        self.assertIn('X-102',html)


if __name__ == '__main__': unittest.main()
