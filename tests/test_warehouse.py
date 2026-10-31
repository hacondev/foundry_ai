"""Warehouse lifecycle queries run on isolated data, without importing the app."""
from pathlib import Path
import ast
import sqlite3
from types import SimpleNamespace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
import unittest

from jinja2 import Environment, FileSystemLoader
from flask import Flask, request as flask_request, g as flask_g, render_template, abort, redirect, url_for
from warehouse import WAREHOUSE_STATUSES, load_warehouse


class Cursor:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params):
        self.rows = self.db.execute(sql.replace('%s', '?'), params)

    def fetchall(self):
        return [dict(row) for row in self.rows]

    def fetchone(self):
        row = self.rows.fetchone()
        return dict(row) if row else None

    def close(self):
        self.rows.close()


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('CONCAT', -1, lambda *args: ''.join(map(str, args)))
        self.db.executescript('''
            CREATE TABLE lista_formowania_historia_v2(
                id INTEGER PRIMARY KEY AUTOINCREMENT, produkt_id INTEGER, prefix TEXT,
                sn INTEGER, production_stage TEXT, czas TEXT, operator TEXT);
            CREATE TABLE lista_formowania_sn(
                id INTEGER PRIMARY KEY, produkt_id INTEGER, prefix TEXT, sn INTEGER,
                mes_po_id TEXT, canceled INTEGER DEFAULT 0, param1 TEXT DEFAULT '0');
            CREATE TABLE lista_formowania_v2(
                id INTEGER PRIMARY KEY, id_produktu INTEGER, nazwa_produktu TEXT,
                alias TEXT, trail TEXT DEFAULT '0', repeated TEXT DEFAULT '0');
            CREATE TABLE produkty(produkt_id INTEGER, customer TEXT);
            INSERT INTO produkty VALUES (123,'Liebherr');
        ''')
        self.cursor = Cursor(self.db)

    def casting(self, form_id, sn=123, alias=None):
        self.db.execute('INSERT INTO lista_formowania_v2(id,id_produktu,nazwa_produktu,alias) '
                        'VALUES (?,123,?,?)', (form_id,'LIEBHERR 14447790',alias))
        self.db.execute('INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn,mes_po_id) '
                        "VALUES (?,?,'LT',?,'ORDER-1')", (form_id,form_id,sn))

    def event(self, form_id, stage, sn=None, prefix=None):
        self.db.execute('INSERT INTO lista_formowania_historia_v2 '
                        '(produkt_id,production_stage,sn,prefix,czas,operator) VALUES (?,?,?,?,?,?)',
                        (form_id,stage,sn,prefix,'2026-10-30 10:00:00','operator'))

    def rows(self, status, **options):
        return load_warehouse(self.cursor,status=status,**options)[0]

    def test_all_requested_status_spellings_map_to_their_stage(self):
        groups = {
            'formed':['formed'], 'assembled':['assembled'], 'casted':['casted'],
            'cooling':['cooling','cooling->knockout'], 'knockout':['knockout'],
            'grinding':['grinding','grinding-repaired','grinding-repaired-edited',
                        'grinding-rework-edited','grinding-done-edited'],
            'qa_ok':['qa_ok'], 'qa_nok':['qa_nok'], 'shipment':['shimpment','shipment'],
        }
        form_id = 0
        for stages in groups.values():
            for stage in stages:
                form_id += 1
                self.casting(form_id)
                self.event(form_id,stage)
        for group, stages in groups.items():
            with self.subTest(group=group):
                rows = self.rows(group)
                self.assertEqual({r['production_stage'] for r in rows},set(stages))
                self.assertEqual(len(rows),len(stages))

    def test_only_current_stage_and_matching_physical_casting_are_shown(self):
        self.casting(1)
        self.casting(2,alias='LT-123')
        self.event(1,'formed')
        self.event(1,'assembled')
        self.event(1,'shimpment',sn=123,prefix='LT')
        self.event(2,'formed')
        self.event(2,'grinding',sn=123,prefix='OTHER')
        self.event(2,'qa_ok',sn=999,prefix='LT')
        self.assertEqual([r['form_id'] for r in self.rows('shipment')],[1])
        self.assertEqual([r['form_id'] for r in self.rows('formed')],[2])
        self.assertEqual(self.rows('assembled'),[])
        self.assertEqual(self.rows('qa_ok'),[])

    def test_qa_change_from_ok_to_nok_moves_only_the_matching_casting_once(self):
        self.casting(1)
        self.casting(2,alias='LT-123')
        self.event(1,'qa_ok',123,'LT')
        self.event(1,'qa_ok',123,'LT')
        self.event(2,'qa_ok',123,'LT')
        self.assertEqual({r['form_id'] for r in self.rows('qa_ok')},{1,2})
        self.assertEqual(self.rows('qa_nok'),[])
        original_history = list(self.db.execute(
            'SELECT * FROM lista_formowania_historia_v2 WHERE produkt_id=2'))
        self.event(1,'qa_nok',123,'LT')
        self.event(1,'qa_nok',123,'LT')
        ok,total_ok = load_warehouse(self.cursor,status='qa_ok')
        nok,total_nok = load_warehouse(self.cursor,status='qa_nok')
        self.assertEqual([r['form_id'] for r in ok],[2])
        self.assertEqual([r['form_id'] for r in nok],[1])
        self.assertEqual((total_ok,total_nok),(1,1))
        self.assertEqual(nok[0]['production_stage'],'qa_nok')
        all_rows = [r for status in WAREHOUSE_STATUSES for r in self.rows(status)]
        self.assertEqual(len(all_rows),2)
        self.assertEqual(len({r['serial_id'] for r in all_rows}),2)
        self.assertEqual(list(self.db.execute(
            'SELECT * FROM lista_formowania_historia_v2 WHERE produkt_id=2')),original_history)
        self.assertEqual(self.rows('qa_nok'),nok)

    def test_form_events_expand_to_castings_and_specific_events_override_individually(self):
        self.casting(1)
        self.db.execute("INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn) VALUES (2,1,'LT',124)")
        self.event(1,'formed')
        self.event(1,'knockout',sn=123,prefix='LT')
        self.assertEqual([r['sn'] for r in self.rows('formed')],[124])
        self.assertEqual([r['sn'] for r in self.rows('knockout')],[123])

    def test_removal_events_do_not_restore_an_older_stage(self):
        self.casting(1)
        self.event(1,'grinding')
        self.event(1,'qa_ok',123,'LT')
        self.event(1,'shimpment',123,'LT')
        self.event(1,'shimpment-removed',123,'LT')
        self.assertEqual(self.rows('shipment'),[])
        self.assertEqual(self.rows('qa_ok'),[])
        self.event(1,'qa_canceled',123,'LT')
        self.assertEqual(self.rows('qa_ok'),[])
        self.assertEqual(self.rows('grinding'),[])
        self.event(1,'qa_ok',123,'LT')
        self.event(1,'shimpment',123,'LT')
        self.assertEqual(len(self.rows('shipment')),1)

    def test_real_shipment_removal_does_not_expose_older_qa_or_duplicate_entries(self):
        self.casting(1)
        self.casting(2,alias='LT-123')  # Same serial, separate physical casting.
        self.db.execute("INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn) VALUES (3,1,'LT',124)")
        self.event(1,'grinding')
        self.event(1,'qa_ok',123,'LT')
        self.event(1,'qa_ok',123,'LT')  # Repeated decisions must not duplicate inventory rows.
        self.event(1,'qa_ok',124,'LT')
        self.event(2,'qa_ok',123,'LT')
        self.event(1,'shimpment',123,'LT')
        self.event(1,'shimpment',123,'LT')
        self.event(1,'shimpment',124,'LT')
        self.event(2,'shimpment',123,'LT')
        self.db.executescript('''
            CREATE TABLE shipments_items(id INTEGER,ship_id INTEGER,form_id INTEGER,sn TEXT,status TEXT);
            INSERT INTO shipments_items VALUES (10,7,1,'LT-123','active'),
                (11,7,1,'LT-124','active'),(12,7,2,'LT-123','active');
        ''')
        other_history = list(self.db.execute('SELECT * FROM lista_formowania_historia_v2 WHERE produkt_id=2'))
        self.assertEqual(len(self.rows('shipment')),3)
        self.assertEqual(self.rows('qa_ok'),[])

        def history_qa(form_id,sn,prefix,stage,operator):
            self.db.execute('INSERT INTO lista_formowania_historia_v2 '
                            '(produkt_id,sn,prefix,production_stage,operator) VALUES (?,?,?,?,?)',
                            (form_id,sn,prefix,stage,operator))

        scope = dict(g=SimpleNamespace(user=True),session={'user_id':18,'user':'packer'},
            request=SimpleNamespace(referrer='/edit_shipment/7'),
            query_db=lambda sql: [dict(r) for r in self.db.execute(sql)],
            query_update=self.db.execute,history_qa=history_qa,
            history_shipment=lambda *args: None,redirect=lambda url: url)
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse(root.joinpath('main.py').read_text(encoding='utf-8'))
        route = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='del_item_shipment')
        route.decorator_list = []
        exec(compile(ast.Module(body=[route],type_ignores=[]),'main.py','exec'),scope)
        scope['del_item_shipment']('10')
        shipped = self.rows('shipment')
        received = self.rows('qa_ok')
        self.assertEqual({(r['form_id'],r['sn']) for r in shipped},{(1,124),(2,123)})
        self.assertEqual(received,[])
        all_rows = [r for status in WAREHOUSE_STATUSES for r in self.rows(status)]
        self.assertEqual(len(all_rows),2)
        self.assertEqual(len({r['serial_id'] for r in all_rows}),2)
        self.assertEqual(list(self.db.execute('SELECT * FROM lista_formowania_historia_v2 WHERE produkt_id=2')),other_history)
        self.assertEqual(self.db.execute('SELECT status FROM shipments_items WHERE id=10').fetchone()[0],'inactive')
        self.assertEqual(self.rows('qa_ok'),received)  # Refreshing does not duplicate entries.

    def test_latest_record_wins_even_when_its_status_is_not_in_dropdown(self):
        self.casting(1)
        self.event(1,'formed')
        self.event(1,'qa_ok',123,'LT')
        self.event(1,'comment-edited',123,'LT')
        self.assertEqual(self.rows('formed'),[])
        self.assertEqual(self.rows('qa_ok'),[])
        self.event(1,'assembled')  # A later form-wide event supersedes older per-casting entries.
        self.assertEqual([r['production_stage'] for r in self.rows('assembled')],['assembled'])

    def test_canceled_removed_and_duplicate_serial_records_do_not_inflate_inventory(self):
        for form_id in (1,2,3):
            self.casting(form_id)
            self.event(form_id,'formed')
        self.db.execute('UPDATE lista_formowania_sn SET canceled=1 WHERE id=1')
        self.db.execute("UPDATE lista_formowania_sn SET param1='1' WHERE id=2")
        self.db.execute("INSERT INTO lista_formowania_sn(id,produkt_id,prefix,sn) VALUES (4,3,'LT',123)")
        self.assertEqual([r['form_id'] for r in self.rows('formed')],[3])
        self.event(3,'canceled by office')
        self.assertEqual(self.rows('formed'),[])

    def test_latest_100_search_and_validation(self):
        for form_id in range(1,106):
            self.casting(form_id,sn=form_id)
            self.event(form_id,'formed')
        items,total = load_warehouse(self.cursor)
        self.assertEqual(total,105)
        self.assertEqual([r['sn'] for r in items],list(range(105,5,-1)))
        second_items,second_total = load_warehouse(self.cursor,page=2)
        self.assertEqual([r['sn'] for r in second_items],[5,4,3,2,1])
        self.assertEqual(second_total,total)
        self.assertFalse({r['serial_id'] for r in items} & {r['serial_id'] for r in second_items})
        with self.assertRaises(ValueError): load_warehouse(self.cursor,page=0)
        self.assertEqual([r['sn'] for r in self.rows('formed',search='LT-104')],[104])
        self.assertEqual(len(self.rows('formed',search='liebherr')),100)
        self.assertEqual(self.rows('formed',search="' OR 1=1 --"),[])
        with self.assertRaises(ValueError): load_warehouse(self.cursor,status='invalid')

    def test_formed_casted_and_cooling_are_limited_to_2026_without_filtering_other_stages(self):
        for form_id, stage, timestamp in [
            (1,'formed','2025-12-31 23:59:59'),
            (2,'formed','2026-01-01 00:00:00'),
            (3,'formed','2026-12-31 23:59:59'),
            (4,'formed','2027-01-01 00:00:00'),
            (5,'assembled','2025-12-31 23:59:59'),
            (6,'casted','2025-12-31 23:59:59'),
            (7,'casted','2026-01-01 00:00:00'),
            (8,'casted','2026-12-31 23:59:59'),
            (9,'casted','2027-01-01 00:00:00'),
            (10,'cooling','2025-12-31 23:59:59'),
            (11,'cooling','2026-01-01 00:00:00'),
            (12,'cooling->knockout','2026-12-31 23:59:59'),
            (13,'cooling->knockout','2027-01-01 00:00:00'),
        ]:
            self.casting(form_id)
            self.event(form_id,stage)
            self.db.execute('UPDATE lista_formowania_historia_v2 SET czas=? WHERE produkt_id=?',
                            (timestamp,form_id))
        self.assertEqual({r['form_id'] for r in self.rows('formed')},{2,3})
        self.assertEqual({r['form_id'] for r in self.rows('casted')},{7,8})
        self.assertEqual({r['form_id'] for r in self.rows('cooling')},{11,12})
        self.assertEqual([r['form_id'] for r in self.rows('assembled')],[5])

    def test_template_renders_status_filter_and_empty_state(self):
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1]/'templates'),
                          autoescape=True)
        template = env.get_template('warehouse.html')
        html = template.render(items=[],total=0,page=1,pages=1,status='formed',search='',
                               statuses=WAREHOUSE_STATUSES,first=1,last=0,session={'user':'tester'},
                               url_for=lambda endpoint,**params: '/'+endpoint)
        self.assertIn('Brak odlewów',html)
        self.assertEqual(html.count('<option '),9)
        self.assertIn('Magazyn',html)
        self.assertIn('paging: false',html)
        self.assertIn('aria-label="Strony magazynu"',html)
        self.assertNotIn('colspan=',html)

    def test_repeat_badge_uses_legacy_alias_without_marking_original(self):
        self.casting(1, sn=1040)
        self.casting(2, sn=1040)
        self.db.execute("UPDATE lista_formowania_v2 SET repeated=1 WHERE id=1")
        self.db.execute("UPDATE lista_formowania_v2 SET alias='AE-1040' WHERE id=2")
        for form in (1, 2):
            self.event(form, 'qa_ok', 1040, 'LT')
        items = self.rows('qa_ok')
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1]/'templates'),
                          autoescape=True)
        html = env.get_template('warehouse.html').render(
            items=items, total=2, page=1, pages=1, status='qa_ok', search='',
            statuses=WAREHOUSE_STATUSES, first=1, last=2, session={'user':'tester'},
            url_for=lambda endpoint, **params: '/'+endpoint)
        self.assertEqual(html.count('<span class="badge badge-danger">Powtórka</span>'), 1)
        self.assertNotIn('AE-1040', html)

    def test_standard_quality_links_and_database_pagination_after_alias_rollback(self):
        for form_id in range(1,106):
            self.casting(form_id,sn=form_id)
            self.event(form_id,'qa_ok',form_id,'LT')
        self.casting(106,sn=106)
        self.event(106,'qa_nok',106,'LT')
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse(root.joinpath('main.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n,ast.FunctionDef)
                     and n.name in ('warehouse','quality')]
        for node in functions:
            node.decorator_list = []
        scope = dict(request=flask_request,g=flask_g,mysql=SimpleNamespace(
            new_cursor=lambda **kw: Cursor(self.db)),load_warehouse=load_warehouse,
            WAREHOUSE_STATUSES=WAREHOUSE_STATUSES,render_template=render_template,
            abort=abort,redirect=redirect,url_for=url_for,
            qa_sn_search=lambda: {'standard_quality_search':flask_request.args.get('sn')})
        exec(compile(ast.Module(body=functions,type_ignores=[]),'main.py','exec'),scope)
        app = Flask(__name__,template_folder=str(root/'templates'))
        app.secret_key = 'warehouse-test'
        app.before_request(lambda: setattr(flask_g,'user',SimpleNamespace(username='tester')))
        app.add_url_rule('/warehouse',view_func=scope['warehouse'])
        app.add_url_rule('/quality',view_func=scope['quality'])
        app.add_url_rule('/production_orders',endpoint='production_orders',view_func=lambda: '')
        app.add_url_rule('/logout',endpoint='logout',view_func=lambda: '')
        app.add_url_rule('/foundry_office',endpoint='forming',view_func=lambda: '')
        client=app.test_client()
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.serials=[]; self.pages=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='a' and attrs.get('title')=='Otwórz historię odlewu w Quality':
                    self.serials.append(attrs['href'])
                if tag=='a' and attrs.get('class')=='page-link': self.pages.append(attrs['href'])
        response=client.get('/warehouse?status=qa_ok&q=liebherr&page=2')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        parser=Links(); parser.feed(html)
        self.assertEqual(len(parser.serials),5)
        self.assertIn('Pozycje 101–105 z 105',html)
        self.assertIn('paging: false',html)
        self.assertNotIn('form_id=',html)
        self.assertNotIn('original_for=',html)
        self.assertEqual(parse_qs(urlsplit(parser.serials[0]).query),{'sn':['LT-5']})
        self.assertEqual(client.get(parser.serials[0]).get_json(),{'standard_quality_search':'LT-5'})
        self.assertEqual(parse_qs(urlsplit(parser.pages[0]).query),
                         {'status':['qa_ok'],'q':['liebherr'],'page':['1']})
        first=Links(); first.feed(client.get(parser.pages[0]).get_data(as_text=True))
        self.assertEqual(len(first.serials),100)
        self.assertFalse(set(first.serials) & set(parser.serials))
        nok=Links(); nok.feed(client.get('/warehouse?status=qa_nok').get_data(as_text=True))
        self.assertEqual(len(nok.serials),1)
        self.assertEqual(client.get('/warehouse?status=invalid').status_code,400)
        self.assertEqual(client.get('/warehouse?page=0').status_code,400)

        # Entry context survives status/search submissions, both page links,
        # and the redirect from an out-of-range page.
        for source, endpoint, label in [('forming', '/foundry_office', 'Powrót do formowania'),
                                         ('', '/quality', 'Quality')]:
            entry = {'source': source} if source else {}
            def assert_home(html):
                self.assertIn(f'href="{endpoint}"><span data-feather="home" aria-hidden="true"></span> Home</a>', html)
            for status in ('qa_ok', 'qa_nok'):
                response = client.get('/warehouse', query_string=dict(entry, status=status, q='liebherr'))
                html = response.get_data(as_text=True)
                self.assertIn(f'href="{endpoint}">{label}</a>', html)
                assert_home(html)
                self.assertEqual('name="source" value="forming"' in html, bool(source))
            first_response = client.get('/warehouse', query_string=dict(entry, status='qa_ok', q='liebherr'))
            assert_home(first_response.get_data(as_text=True))
            first_links = Links(); first_links.feed(first_response.get_data(as_text=True))
            next_link = next(link for link in first_links.pages
                             if parse_qs(urlsplit(link).query).get('page') == ['2'])
            response = client.get(next_link)
            html = response.get_data(as_text=True)
            self.assertIn(f'href="{endpoint}">{label}</a>', html)
            assert_home(html)
            second_links = Links(); second_links.feed(html)
            previous_link = next(link for link in second_links.pages
                                 if parse_qs(urlsplit(link).query).get('page') == ['1'])
            for link in (next_link, previous_link):
                params = parse_qs(urlsplit(link).query)
                expected = dict(status=['qa_ok'], q=['liebherr'], page=params['page'])
                if source:
                    expected['source'] = ['forming']
                self.assertEqual(params, expected)
            self.assertIn(f'href="{endpoint}">{label}</a>',
                          client.get(previous_link).get_data(as_text=True))
            assert_home(client.get(previous_link).get_data(as_text=True))
            response = client.get('/warehouse', query_string=dict(entry, status='qa_ok',
                                  q='liebherr', page=999), follow_redirects=True)
            self.assertEqual(len(response.history), 1)
            self.assertIn(f'href="{endpoint}">{label}</a>', response.get_data(as_text=True))
            assert_home(response.get_data(as_text=True))


if __name__ == '__main__': unittest.main()
