import ast
from pathlib import Path
import unittest
from flask import Flask, request, redirect, url_for


class FoundryOfficeRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.add_url_rule('/foundry_office', endpoint='forming',
                              view_func=lambda: {'method': request.method,
                                                 'value': request.form.get('value')},
                              methods=['GET', 'POST'])
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'legacy_forming')
        scope = dict(app=self.app, request=request, redirect=redirect, url_for=url_for)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        self.client = self.app.test_client()
        forming = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'forming')
        self.assertEqual(forming.decorator_list[0].args[0].value, '/foundry_office')

    def test_old_url_redirects_preserving_filters(self):
        response = self.client.get('/forming?min_date=2026-10-01&include_undated=1')
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.location, '/foundry_office?min_date=2026-10-01&include_undated=1')

    def test_post_redirect_keeps_method_and_body(self):
        response = self.client.post('/forming', data={'value': 'test'}, follow_redirects=True)
        self.assertEqual(response.get_json(), {'method': 'POST', 'value': 'test'})

    def test_internal_links_use_new_address(self):
        for path in Path('templates').glob('*.html'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('href="/forming"', text, str(path))


if __name__ == '__main__':
    unittest.main()
