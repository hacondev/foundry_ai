"""Test allocation without importing the app or connecting to production."""
import ast
from pathlib import Path
import types
import unittest

source = ast.parse(Path(__file__).resolve().parents[1].joinpath('main.py').read_text(encoding='utf-8'))
node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'nadaj_nr_seryjny')


class Connection:
    def __init__(self, pieces=2, fail=False):
        self.calls = []
        self.pieces = pieces
        self.fail = fail
        self.rolled_back = False
        self.closed = False

    def cursor(self, **kwargs):
        return self

    def commit(self):
        self.calls.append(('commit', ()))

    def start_transaction(self):
        self.calls.append(('begin', ()))

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if self.fail and sql.startswith('UPDATE'):
            raise RuntimeError('write failed')

    def fetchall(self):
        if 'FROM produkty' in self.calls[-1][0]:
            return [dict(produkt_id=7, sztuk=self.pieces, prefix='AB', counter=120),
                    dict(produkt_id=8, sztuk=2, prefix='AB', counter=130)]
        return [dict(id=51), dict(id=52)]

    def fetchone(self):
        return {'maximum': 140 if 'lista_formowania_sn' in self.calls[-1][0] else 125}


class AllocationTests(unittest.TestCase):
    def allocate(self, connection):
        namespace = {'mysql': types.SimpleNamespace(connection=connection)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<allocator>', 'exec'), namespace)
        namespace['nadaj_nr_seryjny'](7, 999)

    def test_prefix_lock_target_scope_and_existing_serials(self):
        conn = Connection()
        self.allocate(conn)
        lock = next(sql for sql, _ in conn.calls if 'FROM produkty' in sql)
        self.assertIn('FOR UPDATE', lock)
        selection = next((sql, params) for sql, params in conn.calls if 'SELECT id FROM' in sql)
        self.assertIn('prod_id = %s AND produkt_id = %s', selection[0])
        self.assertEqual(selection[1], (7, 999))
        updates = [params for sql, params in conn.calls if sql.startswith('UPDATE lista_formowania_formy')]
        self.assertEqual(updates, [(141, 142, 51), (141, 142, 52)])
        self.assertTrue(conn.closed)

    def test_all_eight_serials_are_distinct(self):
        conn = Connection(pieces=8)
        self.allocate(conn)
        update = next(params for sql, params in conn.calls if sql.startswith('UPDATE lista_formowania_formy'))
        self.assertEqual(update[:-1], tuple(range(141, 149)))

    def test_failure_rolls_back(self):
        conn = Connection(fail=True)
        with self.assertRaises(RuntimeError):
            self.allocate(conn)
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)

    def test_invalid_piece_count_rolls_back(self):
        conn = Connection(pieces=0)
        with self.assertRaises(ValueError):
            self.allocate(conn)
        self.assertTrue(conn.rolled_back)


if __name__ == '__main__':
    unittest.main()
