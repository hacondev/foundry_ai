import ast
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit
from flask import Flask, request, redirect, url_for
from werkzeug.exceptions import HTTPException


class RedirectTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='redirect_to_previous')
        scope = dict(app=self.app,request=request,redirect=redirect,url_for=url_for,
                     urlsplit=urlsplit,unquote=unquote,HTTPException=HTTPException)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<redirect>','exec'),scope)
        self.previous = scope['redirect_to_previous']
        self.app.add_url_rule('/quality',endpoint='quality',view_func=lambda:'quality')
        self.app.add_url_rule('/claims',endpoint='claims',view_func=lambda:'claims')
        self.app.add_url_rule('/action',endpoint='action',view_func=lambda:self.previous('quality'),methods=['GET','POST'])
        self.app.add_url_rule('/action/<id>',endpoint='action_id',view_func=lambda id:self.previous('quality'))
        self.app.add_url_rule('/post-only',endpoint='post_only',view_func=lambda:'',methods=['POST'])
        self.client = self.app.test_client()

    def test_bad_referrers_end_at_fallback_after_one_redirect(self):
        for referrer in (None,'http://localhost/action','http://localhost/action?sn=bad',
                         'http://localhost/action/','http://localhost/%61ction',
                         'http://localhost/post-only','http://localhost/missing',
                         'https://example.com/claims','http://[invalid', 'javascript:alert(1)'):
            for method in ('GET','POST'):
                with self.subTest(referrer=referrer,method=method):
                    headers = {'Referer':referrer} if referrer else {}
                    response=self.client.open('/action',method=method,headers=headers,follow_redirects=True)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.request.path,'/quality')
                    self.assertEqual(len(response.history),1)

    def test_valid_page_referrer_keeps_search_parameters(self):
        response=self.client.get('/action',headers={'Referer':'http://localhost/claims?search=AB-123'},follow_redirects=True)
        self.assertEqual(response.request.path,'/claims')
        self.assertEqual(response.request.args['search'],'AB-123')
        self.assertEqual(len(response.history),1)

    def test_same_action_with_different_id_is_not_reentered(self):
        response=self.client.get('/action/1',headers={'Referer':'http://localhost/action/2'},follow_redirects=True)
        self.assertEqual(response.request.path,'/quality')
        self.assertEqual(len(response.history),1)

    def test_no_direct_referrer_redirects_remain(self):
        tree=ast.parse(Path('main.py').read_text(encoding='utf-8'))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
               and n.func.id=='redirect' and n.args and isinstance(n.args[0],ast.Attribute)
               and isinstance(n.args[0].value,ast.Name) and n.args[0].value.id=='request'
               and n.args[0].attr=='referrer']
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
