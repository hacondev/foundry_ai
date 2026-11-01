"""Action audit: real handlers, Flask requests, SQLite only; never imports main."""
import ast
import datetime
from html.parser import HTMLParser
from pathlib import Path
import sqlite3
import unittest
from flask import Flask, g, request, session, redirect, url_for, flash, render_template, abort


class Forms(HTMLParser):
    def __init__(self):
        super().__init__(); self.forms = {}; self.current = None; self.ids = []; self.targets = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'): self.ids.append(a['id'])
        if a.get('data-target'): self.targets.append(a['data-target'][1:])
        if tag == 'form':
            self.current = a.get('action'); self.forms[self.current] = {}
        if tag == 'input' and self.current and a.get('name'):
            self.forms[self.current][a['name']] = a.get('value', '')
    def handle_endtag(self, tag):
        if tag == 'form': self.current = None


class GrindingActionAudit(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE grinding (id INTEGER PRIMARY KEY, item_id INTEGER, prefix TEXT, sn INTEGER,
              nazwa_produktu TEXT, trail INTEGER, waga_zeliwa INTEGER, mode TEXT, klient TEXT,
              operator TEXT, alias TEXT, czas TEXT);
            CREATE TABLE lista_formowania_historia_v2 (produkt_id INTEGER, sn INTEGER,
              prefix TEXT, production_stage TEXT, operator TEXT);
        """)
        self.history = []
        def query_db(sql, params=None): return [dict(r) for r in self.db.execute(sql.replace("%s", "?"), params or ())]
        def query_update(sql, params=None): self.db.execute(sql.replace("%s", "?"), params or ())
        names = ['mark_as_grinded','mark_as_grinded_repair','edit_grinding_item_dg','edit_grinding_item_rew']
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names + ['history_qa']]
        for n in nodes: n.decorator_list = []
        scope = dict(g=g, request=request, session=session, redirect=redirect, url_for=url_for,
                     flash=flash, datetime=datetime, query_db=query_db, query_update=query_update, query_update_null_in_sql=query_update,
                     history_qa=lambda *args: self.history.append(args))
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),scope)
        real_history = scope['history_qa']
        def history_qa(*args):
            self.history.append(args)
            return real_history(*args)
        scope['history_qa'] = history_qa
        self.app = Flask(__name__, template_folder=str(Path('templates').resolve()))
        self.app.secret_key = 'isolated-audit'
        self.app.config['TESTING'] = True
        self.app.before_request(lambda: setattr(g,'user',session.get('user')))
        for name in names: self.app.add_url_rule('/'+name+'/<id>',view_func=scope[name],methods=['POST'])
        for name in ['grinding','grinding_done','grinding_rework','login']:
            self.app.add_url_rule('/'+name,endpoint=name,view_func=lambda: '')
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess: sess['user']='WZ'

    def parsed(self, view, extra_items=None, **overrides):
        item = dict(id=10,item_id=1,Prefix='AB',prefix='AB',sn=100,nazwa_produktu='Product',
                    trail='0' if view=='grinding' else 0,alias='-',waga_zeliwa=250,
                    customer='Client',klient='Client',mode='0',operator='WZ',czas=datetime.datetime(2026,11,1,10))
        item.update(overrides)
        with self.app.test_request_context('/'+view):
            session['user']='WZ'
            html=render_template(view+'.html',items=[item] + (extra_items or []),operators=[{'operator':'WZ'}],
                now=datetime.datetime(2026,11,1,10),search='',page=1,pages=1,total=1,first=1,last=1)
        parser=Forms(); parser.feed(html)
        for target in parser.targets: self.assertIn(target,parser.ids)
        return parser

    def seed(self, mode='0'):
        self.db.execute("INSERT INTO grinding VALUES (10,1,'AB',100,'Product',0,250,?,'Client','OLD','-', '2026-10-31 10:00:00')",(mode,))

    def test_oszlifowano_from_rendered_form_and_duplicate(self):
        for mode in ('0', '1', '2'):
            with self.subTest(mode=mode):
                self.db.execute('DELETE FROM grinding')
                self.db.execute('DELETE FROM lista_formowania_historia_v2')
                self.history.clear()
                data=self.parsed('grinding').forms['/mark_as_grinded/10']
                data['grinding_mode']=mode
                response=self.client.post('/mark_as_grinded/10',data=data)
                self.assertEqual(response.status_code,302)
                self.assertTrue(response.location.endswith('/grinding'))
                row=self.db.execute('SELECT item_id,prefix,sn,mode FROM grinding').fetchone()
                self.assertEqual(tuple(row),(10,'AB',100,mode))
                self.assertEqual(self.history[0][3],'grinding')
                history=self.db.execute('SELECT produkt_id,prefix,sn,production_stage FROM lista_formowania_historia_v2').fetchone()
                self.assertEqual(tuple(history),(10,'AB',100,'grinding'))
                self.client.post('/mark_as_grinded/10',data=data)
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM grinding').fetchone()[0],1)
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lista_formowania_historia_v2').fetchone()[0],1)

    def test_rework_modes_from_rendered_form(self):
        self.seed()
        data=self.parsed('grinding_done').forms['/mark_as_grinded_repair/10']
        for mode in ['3','4']:
            data['grinding_mode']=mode
            self.assertEqual(self.client.post('/mark_as_grinded_repair/10',data=data).status_code,302)
        self.assertEqual([r[0] for r in self.db.execute('SELECT mode FROM grinding ORDER BY id')],['0','3','4'])
        self.assertEqual(self.history[-1][3],'grinding-repaired')

    def test_rework_appears_in_rework_and_original_remains_in_done(self):
        self.db.create_function('CONCAT', -1, lambda *args: ''.join(map(str, args)))
        self.db.executescript("""
            CREATE TABLE lista_formowania_v2 (id INTEGER PRIMARY KEY, trail TEXT);
            INSERT INTO lista_formowania_v2 VALUES (1, '0');
        """)
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('grinding_done', 'grinding_rework')]
        for node in nodes:
            node.decorator_list = []
        scope = self.app.view_functions['mark_as_grinded_repair'].__globals__
        contexts = {}
        def render_list(name, **kwargs):
            contexts[name] = kwargs
            for item in kwargs['items']:
                item['czas'] = datetime.datetime.fromisoformat(item['czas']) if item['czas'] else datetime.datetime(2026, 11, 1)
            return render_template(name, **kwargs)
        scope.update(abort=abort, render_template=render_list)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), scope)
        for endpoint in ('grinding_done', 'grinding_rework'):
            self.app.view_functions[endpoint] = scope[endpoint]
        for original_mode in ('0', '1', '2'):
            for rework_mode in ('3', '4'):
                with self.subTest(original_mode=original_mode, rework_mode=rework_mode):
                    self.db.execute('DELETE FROM grinding')
                    self.seed(original_mode)
                    self.assertEqual(self.client.get('/grinding_rework').status_code, 200)
                    self.assertEqual(contexts['grinding_rework.html']['total'], 0)
                    response = self.client.get('/grinding_done')
                    self.assertEqual(response.status_code, 200)
                    parser = Forms(); parser.feed(response.get_data(as_text=True))
                    data = parser.forms['/mark_as_grinded_repair/10']
                    data['grinding_mode'] = rework_mode
                    response = self.client.post('/mark_as_grinded_repair/10', data=data)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.location.endswith('/grinding_done'))
                    for endpoint, mode in [('grinding_done', original_mode), ('grinding_rework', rework_mode)]:
                        response = self.client.get('/' + endpoint + '?q=AB-100')
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('AB-100', response.get_data(as_text=True))
                        context = contexts[endpoint + '.html']
                        self.assertEqual(context['total'], 1)
                        self.assertEqual(context['items'][0]['mode'], mode)
                    records = self.db.execute('SELECT id, mode FROM grinding ORDER BY id').fetchall()
                    self.assertEqual([tuple(r) for r in records], [(10, original_mode), (11, rework_mode)])
                    self.assertEqual(self.history[-1][3], 'grinding-repaired')

    def test_edit_forms_update_operator_and_time(self):
        for view,action,stage in [('grinding_done','edit_grinding_item_dg','grinding-done-edited'),
                                  ('grinding_rework','edit_grinding_item_rew','grinding-rework-edited')]:
            self.db.execute('DELETE FROM grinding'); self.seed()
            data=self.parsed(view).forms['/'+action+'/10']
            data.update(grinding_operator='WZ',new_grinding_datetime='2026-11-01T12:30')
            self.assertEqual(self.client.post('/'+action+'/10',data=data).status_code,302)
            row=self.db.execute('SELECT operator,czas FROM grinding').fetchone()
            self.assertEqual(tuple(row),('WZ','2026-11-01 12:30:00'))
            self.assertEqual(self.history[-1][3],stage)

    def test_edit_changes_only_selected_record(self):
        self.seed()
        self.db.execute("INSERT INTO grinding SELECT 11,item_id,prefix,sn,nazwa_produktu,trail,waga_zeliwa,'3',klient,operator,alias,czas FROM grinding WHERE id=10")
        data=self.parsed('grinding_done').forms['/edit_grinding_item_dg/10']
        data.update(grinding_operator='WZ',new_grinding_datetime='2026-11-01T12:30')
        self.client.post('/edit_grinding_item_dg/10',data=data)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grinding WHERE operator='WZ'").fetchone()[0],1)

    def test_audit_nonprivileged_user_can_post_edit(self):
        self.seed()
        data=self.parsed('grinding_done').forms['/edit_grinding_item_dg/10']
        data.update(grinding_operator='OTHER',new_grinding_datetime='2026-11-01T12:30')
        with self.client.session_transaction() as sess: sess['user']='OTHER'
        self.assertEqual(self.client.post('/edit_grinding_item_dg/10',data=data).status_code,302)
        self.assertEqual(self.db.execute('SELECT operator FROM grinding').fetchone()[0],'OTHER')

    def test_apostrophes_and_sql_text_are_saved_literally(self):
        for view, action, mode in [('grinding', 'mark_as_grinded', '0'),
                                    ('grinding_done', 'mark_as_grinded_repair', '3')]:
            self.db.execute('DELETE FROM grinding')
            data=self.parsed(view,nazwa_produktu="Product O'Brien",alias="A'1").forms['/'+action+'/10']
            data.update(grinding_mode=mode, item_customer="Client'; DROP TABLE grinding; --")
            with self.client.session_transaction() as sess: sess['user']="O'Brien"
            self.assertEqual(self.client.post('/'+action+'/10',data=data).status_code,302)
            row=self.db.execute('SELECT nazwa_produktu,klient,alias,operator FROM grinding').fetchone()
            self.assertEqual(tuple(row),("Product O'Brien", "Client'; DROP TABLE grinding; --", "A'1", "O'Brien"))
            self.assertEqual(self.db.execute('SELECT operator FROM lista_formowania_historia_v2 ORDER BY rowid DESC LIMIT 1').fetchone()[0], "O'Brien")
            if action == 'mark_as_grinded':
                self.client.post('/'+action+'/10',data=data)
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM grinding').fetchone()[0],1)

    def test_pending_modals_are_unique_for_different_prefixes(self):
        parser=self.parsed('grinding',extra_items=[dict(id=10,Prefix='CD',sn=100,
            nazwa_produktu='Other',trail='0',alias='-',waga_zeliwa=250,customer='Client')])
        modals=[target for target in parser.targets if target.startswith('mark_as_grinded_')]
        self.assertEqual(len(modals),2)
        self.assertEqual(len(set(modals)),2)
        for modal in modals: self.assertEqual(parser.ids.count(modal),1)

    def test_both_edit_handlers_leave_other_modes_unchanged(self):
        for action,view in [('edit_grinding_item_dg','grinding_done'),
                            ('edit_grinding_item_rew','grinding_rework')]:
            self.db.execute('DELETE FROM grinding'); self.seed()
            self.db.execute("INSERT INTO grinding SELECT 11,item_id,prefix,sn,nazwa_produktu,trail,waga_zeliwa,'3',klient,operator,alias,czas FROM grinding WHERE id=10")
            data=self.parsed(view).forms['/'+action+'/10']
            data.update(grinding_operator="O'Brien",new_grinding_datetime='2026-11-01T12:30')
            self.client.post('/'+action+'/10',data=data)
            self.assertEqual(self.db.execute('SELECT operator FROM grinding WHERE id=10').fetchone()[0],"O'Brien")
            self.assertEqual(self.db.execute('SELECT operator FROM grinding WHERE id=11').fetchone()[0],'OLD')
