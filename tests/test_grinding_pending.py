"""Exercise the actual grinding route on isolated casting data."""
import ast
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from flask import abort
from werkzeug.exceptions import BadRequest


class GrindingPendingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('CONCAT', -1, lambda *args: ''.join(map(str, args)))
        self.db.executescript('''
            CREATE TABLE lista_formowania_historia_v2 (
                id INTEGER PRIMARY KEY, produkt_id INTEGER, prefix TEXT,
                sn INTEGER, production_stage TEXT);
            CREATE TABLE lista_formowania_v2 (
                id INTEGER PRIMARY KEY, nazwa_produktu TEXT, trail TEXT,
                alias TEXT, id_produktu INTEGER);
            CREATE TABLE produkty (produkt_id INTEGER PRIMARY KEY,
                waga_zeliwa INTEGER, customer TEXT);
            CREATE TABLE lista_formowania_sn (
                produkt_id INTEGER, prefix TEXT, sn INTEGER,
                param1 TEXT DEFAULT '0', canceled TEXT DEFAULT '0');
            INSERT INTO lista_formowania_sn (produkt_id, prefix, sn) VALUES
                (1, 'AB', 100), (1, 'AB', 101), (1, 'CD', 101),
                (1, 'AB', 100), (2, 'AB', 100);
            CREATE TABLE grinding (item_id INTEGER, prefix TEXT, sn INTEGER);
            INSERT INTO produkty VALUES (10, 250, 'Client');
            INSERT INTO lista_formowania_v2 VALUES (1, 'Casting', '1', 'repeat', 10);
            INSERT INTO lista_formowania_v2 VALUES (2, 'Other', '0', NULL, 999);
        ''')
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == 'grinding')
        route.decorator_list = []
        self.queries = []

        def query_db(sql, params=None):
            self.queries.append(sql)
            return [dict(row) for row in self.db.execute(sql.replace('%s', '?'), params or ())]

        self.args = {}
        scope = dict(g=SimpleNamespace(user=True), query_db=query_db,
                     request=SimpleNamespace(args=self.args), abort=abort,
                     redirect=lambda target: ('redirect', target),
                     url_for=lambda endpoint, **kwargs: '/grinding' + ('?q=' + kwargs['q'] if kwargs.get('q') else ''),
                     render_template=lambda name, **kwargs: (name, kwargs))
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'main.py', 'exec'), scope)
        self.route = scope['grinding']

    def test_missing_castings_are_deduplicated_and_matched_by_full_identity(self):
        self.db.executescript('''
            INSERT INTO lista_formowania_historia_v2 VALUES
                (1, 1, NULL, NULL, 'knockout'),
                (2, 1, NULL, NULL, 'knockout'),
                (3, 1, 'AB', 101, 'grinding'),
                (4, 2, 'AB', 100, 'knockout');
            INSERT INTO grinding VALUES (1, 'AB', 101), (999, 'AB', 100);
        ''')
        template, context = self.route()
        self.assertEqual(template, 'grinding.html')
        self.assertEqual(len(self.queries), 1)
        self.assertEqual([(r['id'], r['Prefix'], r['sn']) for r in context['items']],
                         [(2, 'AB', 100), (1, 'AB', 100), (1, 'CD', 101)])
        self.assertEqual(context['items'][1]['waga_zeliwa'], 250)
        self.assertEqual(context['items'][1]['alias'], 'repeat')
        self.assertIsNone(context['items'][0]['customer'])

    def test_all_processed_or_no_history_returns_empty_list(self):
        self.assertEqual(self.route()[1]['items'], [])
        self.db.executescript('''
            INSERT INTO lista_formowania_historia_v2 VALUES (1, 2, NULL, NULL, 'knockout');
            INSERT INTO grinding VALUES (2, 'AB', 100);
        ''')
        self.assertEqual(self.route()[1]['items'], [])

    def test_grinding_alone_is_not_eligible_and_inactive_serials_are_excluded(self):
        self.db.executescript("""
            INSERT INTO lista_formowania_historia_v2 VALUES
                (1, 1, NULL, NULL, 'grinding'),
                (2, 2, NULL, NULL, 'knockout');
            UPDATE lista_formowania_sn SET canceled='1' WHERE produkt_id=2;
        """)
        self.assertEqual(self.route()[1]['items'], [])
        self.db.execute("UPDATE lista_formowania_sn SET canceled='0', param1='1' WHERE produkt_id=2")
        self.assertEqual(self.route()[1]['items'], [])

    def test_serial_specific_knockout_does_not_include_other_castings(self):
        self.db.execute("INSERT INTO lista_formowania_historia_v2 VALUES (1, 1, 'CD', 101, 'knockout')")
        self.assertEqual([(r['Prefix'], r['sn']) for r in self.route()[1]['items']], [('CD', 101)])

    def test_database_pages_have_100_rows_without_overlap(self):
        self.db.execute('DELETE FROM lista_formowania_sn')
        self.db.executemany('INSERT INTO lista_formowania_sn (produkt_id, prefix, sn) VALUES (1, ?, ?)',
                            [('AB', sn) for sn in range(205)])
        self.db.execute("INSERT INTO lista_formowania_historia_v2 VALUES (1, 1, NULL, NULL, 'knockout')")
        pages = []
        for page, size in [(1, 100), (2, 100), (3, 5)]:
            self.args['page'] = str(page)
            context = self.route()[1]
            self.assertEqual(len(context['items']), size)
            self.assertEqual(context['total'], 205)
            self.assertEqual(context['pages'], 3)
            self.assertEqual(context['first'], (page - 1) * 100 + 1)
            self.assertIn(f'LIMIT 100 OFFSET {(page - 1) * 100}', self.queries[-1])
            pages.extend(row['sn'] for row in context['items'])
        self.assertEqual(pages, list(range(205)))
        self.args['page'] = '4'
        self.assertEqual(self.route(), ('redirect', '/grinding'))

    def test_invalid_page_is_rejected_before_query(self):
        for page in ['0', '-1', 'abc', '21474837', '1 OR 1=1']:
            self.args['page'] = page
            with self.assertRaises(BadRequest):
                self.route()
        self.assertEqual(self.queries, [])

    def test_template_keeps_datatable_without_client_paging(self):
        template = Path('templates/grinding.html').read_text(encoding='utf-8')
        self.assertIn("$('#table_id').DataTable", template)
        self.assertIn('paging: false', template)
        self.assertIn('lengthChange: false', template)
        self.assertIn("url_for('grinding', page=page+1, q=search)", template)

    def test_search_finds_serial_outside_first_page_and_paginates_product_matches(self):
        self.db.execute('DELETE FROM lista_formowania_sn')
        self.db.executemany('INSERT INTO lista_formowania_sn (produkt_id, prefix, sn) VALUES (1, ?, ?)',
                            [('AB', sn) for sn in range(205)])
        self.db.execute("INSERT INTO lista_formowania_historia_v2 VALUES (1, 1, NULL, NULL, 'knockout')")
        self.args['q'] = 'ab-204'
        context = self.route()[1]
        self.assertEqual([r['sn'] for r in context['items']], [204])
        self.assertEqual(context['total'], 1)
        self.args.update(q='204')
        self.assertEqual(self.route()[1]['total'], 1)
        self.args.update(q='cAsTiNg', page='2')
        context = self.route()[1]
        self.assertEqual(context['total'], 205)
        self.assertEqual(len(context['items']), 100)
        self.assertEqual(context['items'][0]['sn'], 100)
        self.args['page'] = '4'
        self.assertEqual(self.route(), ('redirect', '/grinding?q=cAsTiNg'))

    def test_search_treats_sql_and_wildcards_as_literal_text(self):
        self.db.execute("INSERT INTO lista_formowania_historia_v2 VALUES (1, 1, NULL, NULL, 'knockout')")
        for search in ["' OR 1=1 --", '%', '_', '!']:
            self.args['q'] = search
            self.assertEqual(self.route()[1]['items'], [])
        self.db.execute("UPDATE lista_formowania_v2 SET nazwa_produktu=? WHERE id=1", ("Part 50%_! O'Brien",))
        for search in ['50%_!', "O'Brien"]:
            self.args['q'] = search
            self.assertEqual(self.route()[1]['total'], 3)


if __name__ == '__main__':
    unittest.main()
