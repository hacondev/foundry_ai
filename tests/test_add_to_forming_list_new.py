"""Check transaction boundaries without importing Flask or connecting to a database."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


source = ast.parse(Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8"))
functions = []
for name in ("zablokuj_prefix_new", "nadaj_nr_seryjny_new", "zapisz_formy_new",
             "add_to_forming_list_new", "add_to_forming_list_from_production_orders_new",
             "add_to_forming_list_from_outline_new", "add_to_forming_list_again_new"):
    node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    functions.append(node)


class Connection:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.lastrowid = 100

    def cursor(self, **kwargs):
        return self

    def start_transaction(self, **kwargs):
        self.calls.append(("begin", kwargs))

    def execute(self, sql, params):
        self.sql = " ".join(sql.split())
        self.calls.append((self.sql, params))
        if self.sql.startswith("INSERT INTO lista_formowania_v2"):
            self.lastrowid += 1
        if self.fail and self.sql.startswith("INSERT INTO lista_formowania_historia"):
            raise RuntimeError("write failed")

    def executemany(self, sql, rows):
        self.calls.append(("serials", rows))

    def fetchall(self):
        if "SELECT DISTINCT f.id, f.item_status" in self.sql:
            return [dict(id=99, item_status="formed")]
        if "WHERE alias =" in self.sql or "sn BETWEEN" in self.sql:
            return []
        if "FROM produkty" in self.sql:
            product = dict(produkt_id=7, prefix="AB", sztuk=2, nazwa="Product",
                           dni_do_wybicia=1, czas_studzenia=2)
            for i in range(1, 5):
                product[f"id_model{i}"] = 1 if i == 1 else None
                product[f"skrzynia{i}"] = None
            if "produkt_id IN" in self.sql:
                return [dict(product, produkt_id=product_id)
                        for product_id in self.calls[-1][1]]
            return [product]
        if "FROM tag_modele" in self.sql:
            return [dict(id=1, nazwa="Model")]
        return [dict(prefix="AB")]

    def fetchone(self):
        assigned = [row[0] for sql, rows in self.calls if sql == "serials" for row in rows]
        return dict(ostatni=max([140] + assigned))

    def commit(self):
        self.calls.append(("commit", None))

    def rollback(self):
        self.calls.append(("rollback", None))

    def close(self):
        self.calls.append(("close", None))


class TransactionTests(unittest.TestCase):
    def run_view(self, connection, form=None, view="add_to_forming_list_new"):
        messages = []
        namespace = dict(
            connect=lambda **kwargs: connection,
            app=SimpleNamespace(config=dict(MYSQL_HOST="test", MYSQL_PORT=3306,
                MYSQL_USER="test", MYSQL_PASSWORD="test", MYSQL_DATABASE="test"),
                logger=SimpleNamespace(exception=lambda *args: None)),
            g=SimpleNamespace(user=True), session={"user": "operator"},
            request=SimpleNamespace(form=form if form is not None else
                                    {"quantity": "2", "nazwa": "Product"}),
            flash=messages.append, url_for=lambda name: name,
            redirect=lambda target: target,
        )
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<views>", "exec"), namespace)
        namespace[view]()
        return messages

    def test_batch_commits_once_and_assigns_distinct_ranges(self):
        connection = Connection()
        self.run_view(connection)
        serials = [rows for sql, rows in connection.calls if sql == "serials"]
        self.assertEqual(serials, [[(141, None, 101), (142, None, 101)],
                                  [(143, None, 102), (144, None, 102)]])
        operations = [sql for sql, _ in connection.calls]
        self.assertEqual(operations.count("commit"), 1)
        self.assertNotIn("rollback", operations)
        lock = next(i for i, sql in enumerate(operations) if "FROM forming_serial_locks" in sql)
        maximum = next(i for i, sql in enumerate(operations) if "MAX(sn)" in sql)
        self.assertLess(lock, maximum)
        self.assertIn("FOR UPDATE", operations[lock])

    def test_write_failure_rolls_back_without_commit(self):
        connection = Connection(fail=True)
        self.run_view(connection)
        operations = [sql for sql, _ in connection.calls]
        self.assertEqual(operations.count("rollback"), 1)
        self.assertNotIn("commit", operations)
        self.assertEqual(operations[-1], "close")

    def test_production_order_rounds_up_and_keeps_order_id(self):
        connection = Connection()
        self.run_view(connection, dict(quantity_po="3", unique_id="PO-1",
            item_index="OTHER", index_odlew="7"),
            "add_to_forming_list_from_production_orders_new")
        serials = [row for sql, rows in connection.calls if sql == "serials" for row in rows]
        self.assertEqual(serials, [(141, "PO-1", 101), (142, "PO-1", 101),
                                   (143, "PO-1", 102), (144, "PO-1", 102)])
        self.assertEqual(sum(sql == "commit" for sql, _ in connection.calls), 1)

    def test_all_special_pairs_share_one_transaction(self):
        for item_index, ids in {"705651": (64, 67), "705638": (64, 65),
                                "705639": (66, 68), "705637": (64, 67)}.items():
            with self.subTest(item_index=item_index):
                connection = Connection()
                self.run_view(connection, dict(quantity_po="1", unique_id="PO-2",
                    item_index=item_index), "add_to_forming_list_from_production_orders_new")
                selection = next(params for sql, params in connection.calls
                                 if "produkt_id IN" in sql)
                self.assertEqual(selection, ids)
                serials = [row for sql, rows in connection.calls if sql == "serials" for row in rows]
                self.assertEqual([row[0] for row in serials], [141, 142, 143, 144])
                self.assertTrue(all(row[1] == "PO-2" for row in serials))
                self.assertEqual(sum(sql == "commit" for sql, _ in connection.calls), 1)

    def test_second_product_failure_rolls_back_whole_order(self):
        class SecondProductFailure(Connection):
            def execute(self, sql, params):
                super().execute(sql, params)
                if self.sql.startswith("UPDATE produkty") and params[1] == 67:
                    raise RuntimeError("second product failed")

        connection = SecondProductFailure()
        self.run_view(connection, dict(quantity_po="1", unique_id="PO-3",
            item_index="705651"), "add_to_forming_list_from_production_orders_new")
        self.assertEqual(sum(sql == "serials" for sql, _ in connection.calls), 2)
        self.assertEqual(sum(sql == "rollback" for sql, _ in connection.calls), 1)
        self.assertFalse(any(sql == "commit" for sql, _ in connection.calls))

    def test_invalid_order_does_not_start_transaction(self):
        connection = Connection()
        self.run_view(connection, dict(quantity_po="0", unique_id="PO-4"),
                      "add_to_forming_list_from_production_orders_new")
        self.assertEqual(connection.calls, [])

    def test_outline_keeps_manual_numbers_alias_and_formed_status(self):
        connection = Connection()
        self.run_view(connection, dict(product="Product", sn="AB-00120"),
                      "add_to_forming_list_from_outline_new")
        serials = [row for sql, rows in connection.calls if sql == "serials" for row in rows]
        self.assertEqual(serials, [(120, None, 101), (121, None, 101)])
        form = next(params for sql, params in connection.calls
                    if sql.startswith("INSERT INTO lista_formowania_v2"))
        self.assertIn("formed", form)
        self.assertEqual(form[-1], "AB-120")
        history = next(params for sql, params in connection.calls
                       if sql.startswith("INSERT INTO lista_formowania_historia"))
        self.assertEqual(history, (101, "formed", "operator"))
        operations = [sql for sql, _ in connection.calls]
        lock = next(i for i, sql in enumerate(operations) if "FROM forming_serial_locks" in sql)
        insert = next(i for i, sql in enumerate(operations)
                      if sql.startswith("INSERT INTO lista_formowania_v2"))
        self.assertLess(lock, insert)
        self.assertEqual(operations.count("commit"), 1)

    def test_outline_rejects_duplicate_alias(self):
        for conflict in ("WHERE alias =",):
            with self.subTest(conflict=conflict):
                class ConflictConnection(Connection):
                    def fetchall(self):
                        if conflict in self.sql:
                            return [dict(id=99)]
                        return super().fetchall()
                connection = ConflictConnection()
                self.run_view(connection, dict(product="Product", sn="AB-120"),
                              "add_to_forming_list_from_outline_new")
                operations = [sql for sql, _ in connection.calls]
                self.assertIn("rollback", operations)
                self.assertNotIn("commit", operations)
                self.assertFalse(any(sql.startswith("INSERT INTO lista_formowania_v2")
                                     for sql in operations))

    def test_outline_accepts_serial_already_present_in_mes(self):
        class ExistingSerialConnection(Connection):
            def fetchall(self):
                if "sn BETWEEN" in self.sql:
                    return [dict(sn=120)]
                return super().fetchall()

        connection = ExistingSerialConnection()
        self.run_view(connection, dict(product="Product", sn="AB-120"),
                      "add_to_forming_list_from_outline_new")
        operations = [sql for sql, _ in connection.calls]
        self.assertIn("commit", operations)
        self.assertNotIn("rollback", operations)
        serials = [row for sql, rows in connection.calls if sql == "serials" for row in rows]
        self.assertEqual(serials, [(120, None, 101), (121, None, 101)])

    def test_outline_wrong_prefix_rolls_back(self):
        connection = Connection()
        self.run_view(connection, dict(product="Product", sn="OTHER-120"),
                      "add_to_forming_list_from_outline_new")
        self.assertTrue(any(sql == "rollback" for sql, _ in connection.calls))
        self.assertFalse(any(sql == "commit" for sql, _ in connection.calls))

    def test_outline_blocks_source_in_new_by_entered_serial_before_any_form_insert(self):
        class NewSource(Connection):
            def fetchall(self):
                if "SELECT DISTINCT f.id, f.item_status" in self.sql:
                    return [dict(id=99, item_status="new")]
                return super().fetchall()

        connection = NewSource()
        messages = self.run_view(connection, dict(product="Product", sn="AB-121"),
                                 "add_to_forming_list_from_outline_new")
        lookup = next((sql, params) for sql, params in connection.calls
                      if "SELECT DISTINCT f.id, f.item_status" in sql)
        self.assertEqual(lookup[1], ("AB", 121, 7))
        self.assertIn("FOR UPDATE", lookup[0])
        self.assertIn("s.sn = %s", lookup[0])
        self.assertIn("status new", messages[0])
        self.assertIn(("rollback", None), connection.calls)
        self.assertNotIn(("commit", None), connection.calls)
        self.assertFalse(any(sql.startswith(("INSERT INTO lista_formowania", "UPDATE produkty"))
                             or sql == "serials" for sql, _ in connection.calls))

    def test_outline_accepts_source_after_new_and_blocks_any_matching_new_form(self):
        for statuses, allowed in [(["formed"], True), (["assembled"], True),
                                  (["qa_ok"], True), (["shimpment"], True),
                                  (["formed", "new"], False)]:
            with self.subTest(statuses=statuses):
                class Source(Connection):
                    def fetchall(self):
                        if "SELECT DISTINCT f.id, f.item_status" in self.sql:
                            return [dict(id=90+i, item_status=status) for i, status in enumerate(statuses)]
                        return super().fetchall()
                connection = Source()
                self.run_view(connection, dict(product="Product", sn="AB-120"),
                              "add_to_forming_list_from_outline_new")
                self.assertEqual(("commit", None) in connection.calls, allowed)
                self.assertEqual(("rollback", None) in connection.calls, not allowed)

    def test_outline_second_piece_is_blocked_in_new_then_allowed_in_formed(self):
        # Two physical pieces in the source form; the entered serial is the second.
        source = dict(id=99, item_status="new", prefix="AB", serials=(120, 121))

        class SecondPieceSource(Connection):
            def fetchall(self):
                if "SELECT DISTINCT f.id, f.item_status" in self.sql:
                    prefix, sn, product_id = self.calls[-1][1]
                    if prefix == source["prefix"] and sn in source["serials"] and product_id == 7:
                        return [dict(id=source["id"], item_status=source["item_status"])]
                    return []
                return super().fetchall()

        blocked = SecondPieceSource()
        messages = self.run_view(blocked, dict(product="Product", sn="AB-121"),
                                 "add_to_forming_list_from_outline_new")
        self.assertIn("status new", messages[0])
        self.assertIn(("rollback", None), blocked.calls)
        self.assertNotIn(("commit", None), blocked.calls)
        self.assertFalse(any(sql.startswith("INSERT INTO lista_formowania") or sql == "serials"
                             for sql, _ in blocked.calls))

        # Simulate progressing the source form, without connecting to a database.
        source["item_status"] = "formed"
        allowed = SecondPieceSource()
        self.run_view(allowed, dict(product="Product", sn="AB-121"),
                      "add_to_forming_list_from_outline_new")
        self.assertIn(("commit", None), allowed.calls)
        self.assertNotIn(("rollback", None), allowed.calls)
        form = next(params for sql, params in allowed.calls
                    if sql.startswith("INSERT INTO lista_formowania_v2"))
        self.assertEqual(form[-1], "AB-121")
        self.assertEqual([params for sql, params in allowed.calls
                          if sql == "serials"], [[(121, None, 101), (122, None, 101)]])
        self.assertEqual([params for sql, params in allowed.calls
                          if sql.startswith("INSERT INTO lista_formowania_historia_v2")],
                         [(101, "formed", "operator")])
        self.assertEqual(source, dict(id=99, item_status="formed", prefix="AB", serials=(120, 121)))

    def test_outline_duplicate_writes_only_new_form_and_its_history(self):
        connection = Connection()
        self.run_view(connection, dict(product="Product", sn="AB-120"),
                      "add_to_forming_list_from_outline_new")
        calls = connection.calls
        form = next(params for sql, params in calls
                    if sql.startswith("INSERT INTO lista_formowania_v2"))
        self.assertEqual(form[-1], "AB-120")
        models = [params for sql, params in calls
                  if sql.startswith("INSERT INTO lista_formowania_formy_v2")]
        self.assertTrue(models)
        self.assertTrue(all(params[1] == 101 and params[-1] == "AB-120" for params in models))
        self.assertTrue(all(params[6:8] == (120, 121) for params in models))
        histories = [params for sql, params in calls
                     if sql.startswith("INSERT INTO lista_formowania_historia_v2")]
        self.assertEqual(histories, [(101, "formed", "operator")])
        self.assertEqual([rows for sql, rows in calls if sql == "serials"],
                         [[(120, None, 101), (121, None, 101)]])
        # No existing casting, serial or history row is updated or deleted.
        mutations = [sql for sql, _ in calls if sql.startswith(("UPDATE ", "DELETE "))]
        self.assertEqual(len(mutations), 1)
        self.assertTrue(mutations[0].startswith("UPDATE produkty SET counter = GREATEST"))
        counters = [params for sql, params in calls if sql.startswith("UPDATE produkty")]
        self.assertEqual(counters, [(121, 7)])

    def test_outline_write_failure_rolls_back(self):
        connection = Connection(fail=True)
        self.run_view(connection, dict(product="Product", sn="AB-120"),
                      "add_to_forming_list_from_outline_new")
        self.assertTrue(any(sql == "rollback" for sql, _ in connection.calls))
        self.assertFalse(any(sql == "commit" for sql, _ in connection.calls))

    def test_outline_invalid_serial_does_not_start_transaction(self):
        for serial in ("", "AB", "AB-0", "AB-text"):
            connection = Connection()
            self.run_view(connection, dict(product="Product", sn=serial),
                          "add_to_forming_list_from_outline_new")
            self.assertEqual(connection.calls, [])

    def test_repeated_forms_keep_empty_serials_and_do_not_change_counter(self):
        connection = Connection()
        self.run_view(connection, dict(quantity="2", nazwa="Product", komentarz="Repeat"),
                      "add_to_forming_list_again_new")
        operations = [sql for sql, _ in connection.calls]
        forms = [params for sql, params in connection.calls
                 if sql.startswith("INSERT INTO lista_formowania_v2")]
        self.assertEqual(len(forms), 2)
        self.assertTrue(all(params[-2] == "1" for params in forms))
        self.assertTrue(all("Repeat" in params for params in forms))
        models = [params for sql, params in connection.calls
                  if sql.startswith("INSERT INTO lista_formowania_formy_v2")]
        self.assertTrue(all(params[6:14] == (None,) * 8 for params in models))
        self.assertEqual(sum("SET status = 'repeated'" in sql for sql in operations), 2)
        self.assertEqual(sum("INSERT INTO lista_formowania_historia" in sql
                             for sql in operations), 2)
        lock = next(i for i, sql in enumerate(operations) if "FROM forming_serial_locks" in sql)
        write = next(i for i, sql in enumerate(operations)
                     if sql.startswith("INSERT INTO lista_formowania_v2"))
        self.assertLess(lock, write)
        self.assertNotIn("serials", operations)
        self.assertFalse(any("MAX(sn)" in sql or sql.startswith("UPDATE produkty")
                             for sql in operations))
        self.assertEqual(operations.count("commit"), 1)

    def test_repeated_form_write_failure_rolls_back(self):
        connection = Connection(fail=True)
        self.run_view(connection, dict(quantity="2", nazwa="Product"),
                      "add_to_forming_list_again_new")
        operations = [sql for sql, _ in connection.calls]
        self.assertEqual(operations.count("rollback"), 1)
        self.assertNotIn("commit", operations)

    def test_repeated_invalid_quantity_does_not_start_transaction(self):
        connection = Connection()
        self.run_view(connection, dict(quantity="0", nazwa="Product"),
                      "add_to_forming_list_again_new")
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
