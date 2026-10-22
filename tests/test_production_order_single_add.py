"""Execute only the route function with mocked dependencies; no database writes."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


class ProductionOrderSingleAddTests(unittest.TestCase):
    def run_route(self, index_sap, quantity='999', pieces=1, logged_in=True):
        source = Path(__file__).resolve().parents[1].joinpath('main.py').read_text(encoding='utf-8')
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'add_to_forming_list_from_production_orders')
        node.decorator_list = []
        self.assertFalse(any(isinstance(n, ast.For) for n in ast.walk(node)))
        calls = []
        product = dict(id_model1=1, id_model2=None, id_model3=None, id_model4=None,
                       prefix='X', sztuk=pieces, czas_studzenia=24, skrzynia1=1,
                       skrzynia2=None, skrzynia3=None, skrzynia4=None,
                       nazwa='Test', dni_do_wybicia=1)
        def query(sql):
            if 'FROM produkty' in sql: return [dict(product)]
            return [{'nazwa':'Model','id':1}]
        def record(name):
            def call(*args): calls.append((name,args))
            return call
        form = dict(item_index=index_sap, unique_id='PO-123', index_odlew='70', nazwa_odlew='Test')
        if quantity is not None: form['quantity_po'] = quantity
        scope = dict(g=SimpleNamespace(user=logged_in), request=SimpleNamespace(form=form),
                     session={'user':'tester'}, query_db=query, flash=record('flash'),
                     redirect=lambda url:url, url_for=lambda endpoint:endpoint,
                     get_produkt_id=lambda stage:{'id':100}, print=lambda *args:None)
        for name in ('add_item_to_forming_list','formy_do_zasypania','nadaj_nr_seryjny',
                     'add_sn_based_on_forms_production_orders','history'):
            scope[name] = record(name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<route>', 'exec'),scope)
        result=scope['add_to_forming_list_from_production_orders']()
        return result,calls

    def test_each_route_adds_one_position_per_component(self):
        cases = [('ordinary',[70]),('705651',[64,67]),('705638',[64,65]),
                 ('705639',[66,68]),('705637',[64,67])]
        for index,expected in cases:
            for quantity in ('999','0','invalid',None):
                with self.subTest(index=index,quantity=quantity):
                    result,calls=self.run_route(index,quantity)
                    added=[int(args[0]) for name,args in calls if name=='add_item_to_forming_list']
                    self.assertEqual(added,expected)
                    self.assertEqual(result,'forming')
                    self.assertEqual(sum(name=='history' for name,args in calls),len(expected))
                    links=[args for name,args in calls if name=='add_sn_based_on_forms_production_orders']
                    self.assertEqual(links,[('100','PO-123')]*len(expected))

    def test_model_capacity_does_not_repeat_form_creation(self):
        _,calls=self.run_route('ordinary',pieces=4)
        self.assertEqual(sum(name=='add_item_to_forming_list' for name,args in calls),1)

    def test_validation_and_login_do_not_add_positions(self):
        for kwargs,expected in [({'pieces':0},'sn_error5'),({'logged_in':False},'login')]:
            result,calls=self.run_route('ordinary',**kwargs)
            self.assertEqual(result,expected)
            self.assertFalse(any(name=='add_item_to_forming_list' for name,args in calls))


if __name__=='__main__': unittest.main()
