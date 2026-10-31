"""Deletion handler tests use only a recording connection, never a live database."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class Connection:
    def __init__(self, alias='AE-1040', stage='formed', advanced=False, fail=False):
        self.form = dict(id=39041, alias=alias, item_status=stage)
        self.advanced = advanced
        self.fail = fail
        self.calls = []

    def start_transaction(self, **kwargs):
        self.calls.append(('begin', ()))

    def cursor(self, **kwargs):
        return self

    def execute(self, sql, params):
        self.sql = ' '.join(sql.split())
        self.calls.append((self.sql, params))
        if self.fail and self.sql.startswith('DELETE'):
            raise RuntimeError('test failure')

    def fetchone(self):
        if 'SELECT id, alias' in self.sql:
            return self.form
        return {'id': 1} if self.advanced else None

    def commit(self):
        self.calls.append(('commit', ()))

    def rollback(self):
        self.calls.append(('rollback', ()))

    def close(self):
        pass


class RemoveOutlineTest(unittest.TestCase):
    def run_handler(self, connection):
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'remove_outline_form')
        node.decorator_list = []
        messages = []
        scope = dict(connect=lambda **kw: connection,
                     app=SimpleNamespace(config=dict(MYSQL_HOST='test', MYSQL_PORT=3306,
                         MYSQL_USER='test', MYSQL_PASSWORD='test', MYSQL_DATABASE='test'),
                         logger=SimpleNamespace(exception=lambda *_: None)),
                     session={'user': 'office'}, flash=messages.append,
                     redirect=lambda target: target, url_for=lambda name: '/' + name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        self.assertEqual(scope['remove_outline_form'](39041), '/forming')
        return messages

    def test_only_selected_repeat_is_canceled_and_history_is_preserved(self):
        connection = Connection()
        self.run_handler(connection)
        writes = [(sql, params) for sql, params in connection.calls
                  if sql.startswith(('UPDATE', 'INSERT', 'DELETE'))]
        self.assertEqual(len(writes), 4)
        self.assertTrue(all(params[0] == 39041 for _, params in writes))
        self.assertFalse(any('produkty' in sql for sql, _ in writes))
        self.assertEqual([sql for sql, _ in writes if sql.startswith('DELETE')],
                         ['DELETE FROM lista_formowania_v2 WHERE id = %s'])
        self.assertTrue(any('INSERT INTO lista_formowania_historia_v2' in sql
                            and params == (39041, 'office') for sql, params in writes))
        self.assertIn(('commit', ()), connection.calls)

    def test_original_or_advanced_form_is_not_modified(self):
        cases = [Connection(alias=None), Connection(alias='-'), Connection(stage='casted'),
                 Connection(advanced=True), Connection()]
        cases[-1].form = None
        for connection in cases:
            with self.subTest(form=connection.form, advanced=connection.advanced):
                self.run_handler(connection)
                self.assertFalse(any(sql.startswith(('UPDATE', 'INSERT', 'DELETE'))
                                     for sql, _ in connection.calls))
                self.assertIn(('rollback', ()), connection.calls)

    def test_error_rolls_back_without_commit(self):
        connection = Connection(fail=True)
        self.run_handler(connection)
        self.assertIn(('rollback', ()), connection.calls)
        self.assertNotIn(('commit', ()), connection.calls)


if __name__ == '__main__':
    unittest.main()
