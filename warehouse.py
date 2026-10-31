"""Current casting inventory derived from lifecycle history."""

WAREHOUSE_STATUSES = {
    'formed': 'Zaformowane',
    'assembled': 'Skręcone',
    'casted': 'Zalane',
    'cooling': 'W trakcie chłodzenia',
    'knockout': 'Wybite',
    'grinding': 'Oczyszczone',
    'qa_ok': 'Odebrane jakościowo — OK',
    'qa_nok': 'Odebrane jakościowo — NOK',
    'shipment': 'Wysłane',
}

# Select the latest history record before applying any status filter.
# Include every production_stage, so an unlisted latest event cannot expose an older stage.
WAREHOUSE_CTE = """
WITH history_heads AS (
    SELECT produkt_id, sn, prefix, MAX(id) AS event_id
    FROM lista_formowania_historia_v2 GROUP BY produkt_id, sn, prefix
), serials AS (
    SELECT MIN(id) AS serial_id, produkt_id, prefix, sn, MAX(mes_po_id) AS mes_po_id
    FROM lista_formowania_sn
    WHERE COALESCE(canceled, 0) <> 1 AND COALESCE(param1, '0') = '0' AND sn IS NOT NULL
    GROUP BY produkt_id, prefix, sn
), casting_heads AS (
    SELECT s.serial_id, s.produkt_id AS form_id, s.prefix, s.sn, s.mes_po_id,
           MAX(hh.event_id) AS event_id
    FROM serials s
    JOIN history_heads hh ON hh.produkt_id = s.produkt_id
        AND ((hh.sn IS NULL AND (hh.prefix IS NULL OR hh.prefix = s.prefix))
             OR (hh.sn = s.sn AND hh.prefix = s.prefix))
    GROUP BY s.serial_id, s.produkt_id, s.prefix, s.sn, s.mes_po_id
), current_events AS (
    SELECT ch.*, f.nazwa_produktu, f.alias, f.trail, f.repeated, p.customer,
           h.production_stage, h.czas, h.operator,
           CASE
               WHEN h.production_stage IN ('shipment', 'shimpment') THEN 'shipment'
               WHEN h.production_stage IN ('grinding', 'grinding-repaired', 'grinding-repaired-edited',
                                           'grinding-rework-edited', 'grinding-done-edited') THEN 'grinding'
               WHEN h.production_stage IN ('cooling', 'cooling->knockout') THEN 'cooling'
               ELSE h.production_stage
           END AS stage_group
    FROM casting_heads ch
    JOIN lista_formowania_historia_v2 h ON h.id = ch.event_id
    JOIN lista_formowania_v2 f ON f.id = ch.form_id
    LEFT JOIN produkty p ON p.produkt_id = f.id_produktu
    WHERE (%s = '' OR LOWER(CONCAT(COALESCE(f.nazwa_produktu, ''), ' ',
              ch.prefix, '-', ch.sn, ' ', COALESCE(f.alias, ''), ' ',
              COALESCE(ch.mes_po_id, ''), ' ', COALESCE(p.customer, ''))) LIKE %s)
)
"""


def load_warehouse(cursor, status='formed', search='', *, page=1):
    """Return one database page of 100 castings."""
    if status not in WAREHOUSE_STATUSES:
        raise ValueError('Nieprawidłowy etap magazynu.')
    if not isinstance(page, int) or page < 1:
        raise ValueError('Nieprawidłowy numer strony.')
    search = search.strip().lower()[:100]
    sql = WAREHOUSE_CTE + """
        SELECT serial_id, form_id, prefix, sn, mes_po_id, nazwa_produktu, alias,
               trail, repeated, customer, stage_group, production_stage, czas, operator,
               COUNT(*) OVER () AS total_count
        FROM current_events WHERE stage_group = %s
          AND (stage_group NOT IN ('formed', 'casted', 'cooling') OR (czas >= '2026-01-01' AND czas < '2027-01-01'))
        ORDER BY event_id DESC, serial_id DESC LIMIT 100 OFFSET %s
    """
    cursor.execute(sql, (search, '%' + search + '%', status, (page - 1) * 100))
    items = cursor.fetchall()
    total = int(items[0]['total_count']) if items else 0
    return items, total
