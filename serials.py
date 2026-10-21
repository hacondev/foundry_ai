"""Read form serials in two queries for any number of forming positions."""


def load_form_serials(product_ids, query):
    ids = sorted({int(value) for value in product_ids})
    if not ids:
        return {}
    # Only normalized integers are interpolated; no user text enters SQL.
    selection = ','.join(map(str, ids))
    forms = query(
        'SELECT produkt_id, model1_sn, model2_sn, model3_sn, model4_sn, '
        'model5_sn, model6_sn, model7_sn, model8_sn, prefix '
        'FROM lista_formowania_formy_v2 WHERE produkt_id IN (' + selection + ') ORDER BY id')
    used = query(
        "SELECT produkt_id, prefix, sn FROM lista_formowania_sn WHERE param1='1' "
        'AND produkt_id IN (' + selection + ')')
    unavailable = {(row['produkt_id'], row['prefix'], str(row['sn'])) for row in used}
    numbers = {key: set() for key in ids}
    prefixes = {}
    for row in forms:
        key = row['produkt_id']
        if row['prefix'] is not None:
            prefixes.setdefault(key, row['prefix'])
        for index in range(1, 9):
            value = row['model' + str(index) + '_sn']
            if isinstance(value, (int, float)):
                numbers[key].add(str(value))
    return {
        key: [[prefixes[key], value] for value in sorted(numbers[key])
              if (key, prefixes[key], value) not in unavailable] if key in prefixes else []
        for key in ids
    }
