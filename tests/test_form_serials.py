import ast
from pathlib import Path
import unittest
from serials import load_form_serials


def form(product_id, prefix, *numbers):
    return dict(produkt_id=product_id, prefix=prefix,
                **{'model' + str(i) + '_sn': numbers[i-1] if i <= len(numbers) else None
                   for i in range(1, 9)})


class SerialTests(unittest.TestCase):
    def test_batch_preserves_prefix_deduplication_order_and_used_exclusion(self):
        calls = []
        forms = [form(1,'AB',2,10,2,3), form(1,'AB',4), form(2,'CD',2,11), form(3,None,5)]
        used = [dict(produkt_id=1,prefix='AB',sn=2), dict(produkt_id=1,prefix='AB',sn=3),
                dict(produkt_id=2,prefix='OTHER',sn=11)]
        def query(sql):
            calls.append(sql)
            return forms if 'lista_formowania_formy_v2' in sql else used
        result=load_form_serials([1,2,3,4,1],query)
        self.assertEqual(len(calls),2)
        self.assertEqual(result,{1:[['AB','10'],['AB','4']],2:[['CD','11'],['CD','2']],3:[],4:[]})
        self.assertIn('IN (1,2,3,4)',calls[0])

    def test_empty_and_invalid_ids_never_query(self):
        def query(sql): self.fail('Unexpected database call')
        self.assertEqual(load_form_serials([],query),{})
        with self.assertRaises(ValueError): load_form_serials(['1 OR 1=1'],query)

    def test_large_batch_still_two_queries(self):
        calls=[]
        def query(sql): calls.append(sql);return []
        result=load_form_serials(range(1,401),query)
        self.assertEqual(len(result),400)
        self.assertEqual(len(calls),2)

    def test_legacy_entry_point_uses_batch_loader(self):
        source=Path(__file__).resolve().parents[1].joinpath('main.py').read_text(encoding='utf-8')
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='generete_serials')
        calls=[]
        def query(sql):
            calls.append(sql)
            return [form(7,'X',123)] if 'lista_formowania_formy_v2' in sql else []
        scope={'query_db':query}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<serials>','exec'),scope)
        self.assertEqual(scope['generete_serials'](7),[['X','123']])
        self.assertEqual(len(calls),2)


if __name__=='__main__': unittest.main()
