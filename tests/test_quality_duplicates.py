"""Exercise Quality searches without importing production connections."""
import ast
import re
import sqlite3
import unittest
from pathlib import Path

from flask import Flask, request, redirect, url_for
from jinja2 import Environment


class QualityDuplicatesTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE lista_formowania_sn(id,produkt_id,prefix,sn,param1,canceled);
            CREATE TABLE lista_formowania_v2(id,alias,nazwa_produktu,
                dni_do_wybicia,nr_kadzi,filtr,broken,temp_zeliwa,data_zalania,
                komentarz,komentarz_formowanie,komentarz_rdzeniarnia,
                komentarz_zalew,komentarz_wybijanie);
            CREATE TABLE lista_formowania_historia_v2(
                id,produkt_id,production_stage,operator,czas,sn,prefix);
        ''')
        # Insert repeat first: original must still be displayed first.
        for form, alias in [(39041, 'AE-1040'), (38660, None)]:
            self.db.execute('INSERT INTO lista_formowania_v2(id,alias,nazwa_produktu) VALUES(?,?,?)',
                            (form, alias, 'Counterweight'))
            for sn in (1040, 1041):
                self.db.execute('INSERT INTO lista_formowania_sn VALUES(?,?,?,?,?,?)',
                                (form * 10 + sn, form, 'AE', sn, '0', '0'))
            for offset, sn, prefix in [(0, None, None), (1, 1040, 'AE'), (2, 1041, 'AE')]:
                self.db.execute('INSERT INTO lista_formowania_historia_v2 VALUES(?,?,?,?,?,?,?)',
                                (form * 10 + offset, form, 'formed', 'operator', 'date', sn, prefix))
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.messages = []
        scope = dict(app=self.app, request=request, redirect=redirect, url_for=url_for,
                     flash=self.messages.append,
                     query_db=lambda sql: [dict(r) for r in self.db.execute(sql)],
                     render_template=lambda template, **context: (template, context),
                     is_valid_serial_number=lambda serial: bool(re.fullmatch(r'[A-Z]{2}-\d+', serial)),
                     cast_removed_by_the_operator=lambda *_: False,
                     form_was_canceled=lambda *_: False,
                     adv_search_manscan=lambda form: [{'form': form}])
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        names = {'qa_sn_search', 'qa_sn_search_po', 'filter_items_quality'}
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        for node in funcs:
            node.decorator_list = []
        exec(compile(ast.Module(body=funcs, type_ignores=[]), 'main.py', 'exec'), scope)
        self.search = scope['qa_sn_search']
        self.po_search = scope['qa_sn_search_po']
        self.app.add_url_rule('/quality', endpoint='quality', view_func=lambda: '')

    def test_duplicate_search_keeps_form_and_piece_histories_separate(self):
        for serial in ('AE-1040', 'AE-1041'):
            with self.app.test_request_context('/quality?sn=' + serial):
                template, ctx = self.search()
            self.assertEqual(template, 'quality2.html')
            self.assertEqual((ctx['data']['system_id'], ctx['data2']['system_id']), (38660, 39041))
            for key, form in [('items', 38660), ('items2', 39041)]:
                self.assertEqual(len(ctx[key]), 2)
                self.assertEqual({r['produkt_id'] for r in ctx[key]}, {form})
                self.assertEqual({r['sn'] for r in ctx[key]}, {None, int(serial.split('-')[1])})

    def test_single_and_removed_duplicate_display_only_one_form(self):
        self.db.execute("UPDATE lista_formowania_sn SET canceled='1' WHERE produkt_id=39041")
        with self.app.test_request_context('/quality?sn=AE-1040'):
            template, ctx = self.search()
        self.assertEqual(template, 'quality.html')
        self.assertEqual(ctx['data']['system_id'], 38660)
        self.assertNotIn('items2', ctx)

    def test_post_and_production_orders_use_the_same_search(self):
        with self.app.test_request_context('/qa_sn_search', method='POST', data={'sn': 'ae-1040'}):
            self.assertEqual(self.search()[0], 'quality2.html')
        with self.app.test_request_context('/qa_sn_search_po/AE-1040'):
            self.assertEqual(self.po_search('AE-1040')[0], 'quality2.html')

    def test_templates_parse_and_alias_field_is_removed(self):
        for name in ('quality.html', 'quality2.html'):
            source = Path('templates', name).read_text(encoding='utf-8')
            Environment().parse(source)
            self.assertNotIn('<p>Alias:', source)

    def test_single_repeat_badge_depends_on_alias(self):
        from flask import render_template
        self.app.template_folder = str(Path('templates').resolve())
        for endpoint in ('production_orders', 'warehouse'):
            self.app.add_url_rule('/' + endpoint, endpoint=endpoint, view_func=lambda: '')
        self.db.execute('DELETE FROM lista_formowania_sn WHERE produkt_id=39041')
        for alias, expected in [(None, 0), ('', 0), ('-', 0), ('AE-1040', 1)]:
            self.db.execute('UPDATE lista_formowania_v2 SET alias=? WHERE id=38660', (alias,))
            with self.app.test_request_context('/quality?sn=AE-1040'):
                template, context = self.search()
                html = render_template(template, **context)
            self.assertEqual(template, 'quality.html')
            self.assertEqual(html.count('<span class="badge badge-danger">Powtórka</span>'), expected)

    def test_remove_repeat_disappears_from_warehouse_and_quality_preserving_original(self):
        from warehouse import load_warehouse, WAREHOUSE_STATUSES
        # Extend the isolated fixture for the real removal and warehouse queries.
        for column, kind in [('item_status', 'TEXT'), ('id_produktu', 'INTEGER'),
                             ('trail', 'TEXT'), ('repeated', 'TEXT')]:
            self.db.execute(f'ALTER TABLE lista_formowania_v2 ADD COLUMN {column} {kind}')
        self.db.execute("UPDATE lista_formowania_v2 SET item_status='formed', id_produktu=77, trail='0', repeated='0'")
        self.db.execute("UPDATE lista_formowania_historia_v2 SET czas='2026-10-31 10:00:00'")
        self.db.execute('ALTER TABLE lista_formowania_sn ADD COLUMN mes_po_id TEXT')
        self.db.executescript('''
            CREATE TABLE produkty(produkt_id INTEGER, customer TEXT, counter INTEGER);
            INSERT INTO produkty VALUES(77, 'Customer', 1057);
            CREATE TABLE lista_formowania_formy_v2(id INTEGER, produkt_id INTEGER, status TEXT);
            INSERT INTO lista_formowania_formy_v2 VALUES(85363,38660,'active');
            INSERT INTO lista_formowania_formy_v2 VALUES(86252,39041,'active');
        ''')
        self.db.create_function('CONCAT', -1, lambda *args: ''.join(map(str, args)))
        self.db.commit()
        db = self.db

        class LocalConnection:
            def start_transaction(self, **kwargs):
                db.execute('BEGIN')

            def cursor(self, **kwargs):
                return self

            def execute(self, sql, params):
                self.result = db.execute(sql.replace('%s', '?').replace('FOR UPDATE', ''), params)

            def fetchone(self):
                row = self.result.fetchone()
                return dict(row) if row else None

            def fetchall(self):
                return [dict(row) for row in self.result.fetchall()]

            def commit(self):
                db.commit()

            def rollback(self):
                db.rollback()

            def close(self):
                pass

        connection = LocalConnection()

        def original_snapshot():
            return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table} WHERE {column}=38660 ORDER BY id')]
                    for table, column in [('lista_formowania_v2', 'id'), ('lista_formowania_sn', 'produkt_id'),
                                          ('lista_formowania_formy_v2', 'produkt_id'),
                                          ('lista_formowania_historia_v2', 'produkt_id')]}

        before = original_snapshot()
        rows, _ = load_warehouse(connection, status='formed', search='AE-1040')
        self.assertEqual({r['form_id'] for r in rows}, {38660, 39041})
        self.app.config.update(MYSQL_HOST='unused', MYSQL_PORT=3306, MYSQL_USER='unused',
                               MYSQL_PASSWORD='unused', MYSQL_DATABASE='unused')
        scope = self.search.__globals__
        scope.update(connect=lambda **kwargs: connection, session={'user': 'office'})
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'remove_outline_form')
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        self.app.add_url_rule('/forming', endpoint='forming', view_func=lambda: '')
        with self.app.test_request_context('/remove_from_forming_list/39041', method='POST'):
            self.assertEqual(scope['remove_outline_form'](39041).status_code, 302)
        self.assertEqual(original_snapshot(), before)
        self.assertEqual(db.execute('SELECT counter FROM produkty').fetchone()[0], 1057)
        for status in WAREHOUSE_STATUSES:
            rows, _ = load_warehouse(connection, status=status, search='AE-1040')
            self.assertNotIn(39041, {r['form_id'] for r in rows})
        rows, _ = load_warehouse(connection, status='formed', search='AE-1040')
        self.assertEqual({r['form_id'] for r in rows}, {38660})
        for serial in ('AE-1040', 'AE-1041'):
            with self.app.test_request_context('/quality?sn=' + serial):
                template, context = self.search()
            self.assertEqual(template, 'quality.html')
            self.assertEqual(context['data']['system_id'], 38660)
            self.assertNotIn('items2', context)
            self.assertTrue(all(r['produkt_id'] == 38660 for r in context['items']))
        repeat_events = list(db.execute('SELECT production_stage FROM lista_formowania_historia_v2 WHERE produkt_id=39041'))
        self.assertEqual(len(repeat_events), 4)  # Three existing events plus cancellation.
        self.assertIn(('canceled by office',), [tuple(r) for r in repeat_events])


if __name__ == '__main__':
    unittest.main()
