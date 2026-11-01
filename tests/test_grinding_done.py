"""Database paging and global search in the completed grinding list."""
import ast
import datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from flask import abort
from werkzeug.exceptions import BadRequest
from jinja2 import Environment


class GrindingDoneTests(unittest.TestCase):
    endpoint = 'grinding_done'
    modes = ('0', '1', '2')
    excluded_mode = '3'

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('CONCAT', -1, lambda *args: ''.join(map(str, args)))
        self.db.executescript("""
            CREATE TABLE grinding (id INTEGER PRIMARY KEY, item_id INTEGER, prefix TEXT,
                sn INTEGER, nazwa_produktu TEXT, mode TEXT, operator TEXT, trail INTEGER);
            CREATE TABLE lista_formowania_v2 (id INTEGER PRIMARY KEY, trail TEXT);
            INSERT INTO lista_formowania_v2 VALUES (1, '1');
        """)
        self.db.executemany("INSERT INTO grinding VALUES (?,1,'AB',?,'Product', '0','Operator',0)",
                            [(i, i) for i in range(1, 206)])
        self.db.execute("INSERT INTO grinding VALUES (999,1,'CD',999,'Rework','3','Operator',0)")
        self.db.execute('UPDATE grinding SET mode=? WHERE id <> 999', (self.modes[0],))
        self.db.execute('UPDATE grinding SET mode=? WHERE id=999', (self.excluded_mode,))
        self.args = {}
        self.queries = []
        def query_db(sql, params=None):
            self.queries.append(sql)
            return [dict(r) for r in self.db.execute(sql.replace('%s', '?'), params or ())]
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == self.endpoint)
        route.decorator_list = []
        scope = dict(g=SimpleNamespace(user=True), request=SimpleNamespace(args=self.args),
                     abort=abort, datetime=datetime, query_db=query_db,
                     render_template=lambda name, **kwargs: kwargs,
                     url_for=lambda endpoint, **kwargs: (endpoint, kwargs), redirect=lambda url: url)
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'main.py', 'exec'), scope)
        self.route = scope[self.endpoint]

    def test_pages_and_current_trial_flag(self):
        serials = []
        for page, size in [(1, 100), (2, 100), (3, 5)]:
            self.args['page'] = str(page)
            result = self.route()
            self.assertEqual(len(result['items']), size)
            self.assertEqual(result['total'], 205)
            self.assertEqual(result['pages'], 3)
            self.assertTrue(all(r['trail'] == 1 for r in result['items']))
            serials.extend(r['sn'] for r in result['items'])
        self.assertEqual(serials, list(range(205, 0, -1)))

    def test_search_and_redirect_keep_filter(self):
        self.args['q'] = 'ab-1'
        self.assertEqual(self.route()['total'], 111)
        self.args.update(q='pRoDuCt', page='2')
        self.assertEqual(len(self.route()['items']), 100)
        self.args.update(page='4')
        self.assertEqual(self.route(), (self.endpoint, {'q': 'pRoDuCt'}))
        self.args.update(q="' OR 1=1 --", page='1')
        self.assertEqual(self.route()['total'], 0)
        self.args['q'] = '%'
        self.assertEqual(self.route()['total'], 0)

    def test_invalid_pages(self):
        for page in ['0', '-1', 'abc', '21474837']:
            self.args['page'] = page
            with self.assertRaises(BadRequest):
                self.route()
        self.assertEqual(self.queries, [])

    def test_template(self):
        template = Path('templates', self.endpoint + '.html').read_text(encoding='utf-8')
        Environment().parse(template)
        self.assertIn('paging: false', template)
        self.assertIn('lengthChange: false', template)
        self.assertIn('btn btn-dark">Szukaj', template)
        self.assertIn(f"url_for('{self.endpoint}', page=page+1, q=search)", template)

    def test_includes_each_supported_mode(self):
        for mode in self.modes:
            self.db.execute('UPDATE grinding SET mode=? WHERE id <> 999', (mode,))
            self.assertEqual(self.route()['total'], 205)


class GrindingReworkTests(GrindingDoneTests):
    endpoint = 'grinding_rework'
    modes = ('3', '4')
    excluded_mode = '0'
