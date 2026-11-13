import ast
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace
import unittest

from flask import Flask, request, session, redirect, url_for, abort
from jinja2 import Environment
from quality_cost import calculate_quality_cost, REPAIR_RATES, REPAIR_MINUTES, WELDING_MINUTES


class QualityCostTest(unittest.TestCase):
    def test_rates_and_all_allowed_times(self):
        for decision, rate in REPAIR_RATES.items():
            times = WELDING_MINUTES if decision == 'spawanie' else REPAIR_MINUTES
            for minutes in times:
                with self.subTest(decision=decision, minutes=minutes):
                    expected = (Decimal(rate) * minutes).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    self.assertEqual(calculate_quality_cost(decision, str(minutes)), expected)
        self.assertEqual(calculate_quality_cost('spawanie', '620'), Decimal('372.00'))
        for decision, rate in REPAIR_RATES.items():
            self.assertEqual(calculate_quality_cost(decision, '60'), Decimal(rate) * 60)
        self.assertEqual(calculate_quality_cost('szlifowanie', '15'), Decimal('10.50'))
        self.assertEqual(calculate_quality_cost('szpachlowanie', '15'), Decimal('9.45'))
        self.assertEqual(calculate_quality_cost('Naprawa gwintu', '15'), Decimal('19.50'))

    def test_scrap_converts_kg_to_tonnes_and_rounds(self):
        self.assertEqual(calculate_quality_cost('złomować', weight_kg=250), Decimal('1261.25'))
        self.assertEqual(calculate_quality_cost('złomować', weight_kg=1), Decimal('5.05'))

    def test_invalid_weights_and_times(self):
        for weight in (None, 0, -1, 'NaN', 'Infinity', 'bad'):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                calculate_quality_cost('złomować', weight_kg=weight)
        for minutes in (None, '', '16', '180', '-15', '15.0'):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                calculate_quality_cost('szlifowanie', minutes)

    def test_other_repairs_cost_zero(self):
        for decision in ('wkręcenie redukcji', 'śrutowanie'):
            self.assertEqual(calculate_quality_cost(decision, '620'), Decimal('0.00'))

    def test_add_route_saves_server_cost_and_exact_serial(self):
        app = Flask(__name__)
        app.secret_key = 'test'
        app.add_url_rule('/defects_item/<id>', endpoint='defects_item', view_func=lambda id: '')
        writes, histories, messages = [], [], []
        def write(sql, params, **kwargs):
            writes.append((sql, params, kwargs))
            return True, 123
        scope = dict(app=app, g=SimpleNamespace(user=True), request=request, session=session,
                     redirect=redirect, url_for=url_for, abort=abort, flash=messages.append,
                     query_db=lambda sql, params: [{'waga_zeliwa': 250}],
                     query_update_new=write, calculate_quality_cost=calculate_quality_cost,
                     defect_n=lambda: 42, defects_history=lambda *args: histories.append(args),
                     redirect_to_previous=lambda endpoint: redirect('/defects'))
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'add_defect')
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        payload = dict(defect_date='2026-11-13', decyzja='spawanie', czas_naprawy='620',
                       miejsce='odlewnia', rodzaj_braku='niedolew', nazwa_produktu='Product',
                       koszt_zlej_jakowsci='0.01')
        with app.test_request_context(method='POST', data=payload):
            session['user'] = 'operator'
            scope['add_defect']('100_999')
        self.assertEqual(writes[0][1][:2], ('999', '100'))
        self.assertEqual(writes[0][1][-1], Decimal('372.00'))
        self.assertEqual(histories, [(123, 'add_new_defect', 'operator')])
        writes.clear()
        payload['czas_naprawy'] = '123'
        with app.test_request_context(method='POST', data=payload):
            session['user'] = 'operator'
            response = scope['add_defect']('100_999')
        self.assertFalse(writes)
        self.assertEqual(response.location, '/defects_item/100_999')
        self.assertTrue(messages)

    def test_template_parses(self):
        Environment().parse(Path('templates/defects_item.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
