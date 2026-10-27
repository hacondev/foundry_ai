from flask import Flask, redirect, url_for, render_template, jsonify, request, g, session, flash, send_from_directory, abort, render_template_string
from flask_mysql_connector import MySQL
import datetime, json, os, hashlib, re
from datetime import timedelta
import pandas as pd
import pyodbc
import requests
from user import users
import platform
from functools import wraps
import ipaddress

#######################################################################################################
####################################### Konfiguracja ##################################################
#######################################################################################################

# app = Flask(__name__)
# app.config['MYSQL_HOST'] = '192.168.1.47'
# app.config['MYSQL_PORT'] = '3307'
# app.config['MYSQL_USER'] = 'plc'
# app.config['MYSQL_PASSWORD'] = 'evJ2!5F6b@f'
# app.config['MYSQL_DATABASE'] = 'tower_test'
# app.secret_key = 'password74320'

app = Flask(__name__)
app.config['MYSQL_HOST'] = '192.168.1.107'
app.config['MYSQL_PORT'] = '3306'
app.config['MYSQL_USER'] = 'plc'
app.config['MYSQL_PASSWORD'] = 'evJ2!5F6b@f'
app.config['MYSQL_DATABASE'] = 'tower'
app.secret_key = 'password74320'

# Upload pliku
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'txt', 'pdf', 'txt'}

mysql = MySQL(app)

#######################################################################################################
########################################### Logowanie  ################################################
#######################################################################################################

def login_required(mode=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Sprawdzenie czy użytkownik jest zalogowany
            if not getattr(g, 'user', None):
                flash('Login required.')
                return redirect(url_for('login'))
            
            # Sprawdzenie wymaganego trybu (mode), jeśli został podany w dekoratorze
            if mode and g.user.mode != mode:
                flash('Access denied. Insufficient permissions for this mode.')
                return redirect(url_for('login'))  # Lub np. abort(403)
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def ip_required(*allowed_networks):
    """
    Dekorator sprawdzający czy żądanie pochodzi z którejkolwiek dozwolonej podsieci.
    Przykład użycia: @ip_required('192.168.1.0/24', '192.168.170.0/24')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Pobranie adresu IP klienta
            client_ip_str = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_ip_str:
                client_ip_str = client_ip_str.split(',')[0].strip()

            try:
                client_ip = ipaddress.ip_address(client_ip_str)
            except ValueError:
                flash('Access denied. Invalid IP format.')
                return abort(403)

            # Sprawdzanie, czy IP pasuje do którejkolwiek z podanych sieci
            access_granted = False
            for net_str in allowed_networks:
                try:
                    network = ipaddress.ip_network(net_str, strict=False)
                    if client_ip in network:
                        access_granted = True
                        break
                except ValueError:
                    # Jeśli w kodzie podano błędny format sieci, pomijamy go
                    continue

            if not access_granted:
                flash(f'Access denied. Your IP ({client_ip_str}) is not authorized.')
                return redirect(url_for('index')) # Lub np. abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator

#######################################################################################################
###################################### Funkcje uniwersalne  ###########################################
#######################################################################################################

def remove_cutomer(list1, list2):
    return [item for item in list2 if item not in list1]


def is_valid_serial_number(value):
    if not isinstance(value, str):
        return False
    pattern = r'^[A-Z]{2}-\d+$'
    return bool(re.match(pattern, value))

def form_was_canceled(prefix, numer):
    sql = f"SELECT * FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn={numer} AND canceled='1'"
    form = query_db(sql)
    result = len(form)
    print(result)
    if result == 1:
        return True
    else:
        return False

def cast_removed_by_the_operator(prefix, numer):
    query = f"SELECT param1 FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn='{numer}'"

    try:
        res = query_db(query)[0]['param1']
    except IndexError: 
        return False

    if res == '1':
        return True
    else:
        return False

    

def split_code(value: str):
    return value.split('-', 1)

def filter_by_sn_and_prefix(data, sn, prefix):
    return [
        item for item in data
        if item.get("sn") == sn and item.get("prefix") == prefix
    ]

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_file_hash(file):
    hash_sha256 = hashlib.sha256()
    for chunk in iter(lambda: file.read(4096), b""):
        hash_sha256.update(chunk)
    file.seek(0)
    return hash_sha256.hexdigest()

def get_mssql_connection():

    if platform.system() == "Windows":
        connection_string = (
            "Driver={SQL Server};"
            "Server=SAPSRV\\MSSQL2019;"
            "Database=Hacon_Praca;"
            "UID=Read_Only_user;"
            "PWD=P@ssword123!;"
        )

    else:
        connection_string = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=192.168.1.108,1433;"
            "DATABASE=Hacon_Praca;"
            "UID=Read_Only_user;"
            "PWD=P@ssword123!;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=20;"
        )

    return pyodbc.connect(connection_string)

def query_db(query):
    cur = mysql.new_cursor(dictionary=True)
    cur.execute(query)
    result = cur.fetchall()
    cur.close()
    return result

# def update_query_in_loop(sql, params):
#     cur = mysql.new_cursor(dictionary=True)
#     cur.execute(query)
#     result = cur.fetchall()
#     cur.close()
#     return result

def query_update_null_in_sql(query, params=None):
    cur = mysql.new_cursor()
    cur.execute(query, params)   # ✅ przekazujemy params
    mysql.connection.commit()
    cur.close()
    return True

def query_db_first(query):
    cur = mysql.new_cursor(dictionary=True)
    cur.execute(query)
    try:
        result = cur.fetchall()[0]
    except:
        result = None
    cur.close()
    return result

def query_update(query):
    cur = mysql.new_cursor()
    cur.execute(query)
    mysql.connection.commit()
    cur.close()
    return True

def query_update_new(query, params=None, return_last_id=False):
    cur = mysql.connection.cursor()

    try:
        cur.execute(query, params)
        mysql.connection.commit()

        if return_last_id:
            last_id = cur.lastrowid
            cur.close()
            return True, last_id

        cur.close()
        return True

    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        print("DB ERROR:", e)
        return False

def check_foundry_ip():
    ip = request.remote_addr
    pattern = r"^192\.168\.35\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)$"
    if re.match(pattern, ip):
        return False

    return True

def query_update_test(query):
    cur = mysql.new_cursor()
    cur.execute(query)
    cur.close()
    return True

def check_format_shipment(text: str) -> bool:
    pattern = r'\d{2,3}-\d{8}$'
    return bool(re.match(pattern, text))

def check_nr_shipment(text: str) -> bool:
    query = "SELECT * FROM `shipments` WHERE nr_wysylki='" + text + "'"
    result = len(query_db(query))
    if result > 0:
        return True
    else:
        return False

@app.before_request
def before_request():
    g.user = None
    if 'user_id' in session:
        user = [x for x in users if x.id == session['user_id']][0]
        g.user = user   

def add_item_to_forming_list(id, id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail):
    query = "INSERT INTO lista_formowania_v2(id_produktu, id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, komentarz_flag, dodane_przez, zmodyfikowane_przez, trail) VALUES (" + str(id) + "," + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "','" + skrzynia4 + "'," + '1' + ",'" + nazwa_produktu + "','" + prefix + "'," + dni_do_wybicia + "," + czas_studzenia + ",'" + item_status + "','" + komentarz + "','0','" + user + "','" + user + "','" + trail + "')"
    query_update(query)
    return True

def add_item_to_forming_list_outline(id, id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail, alias='-'):
    query = "INSERT INTO lista_formowania_v2(id_produktu, id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, komentarz_flag, dodane_przez, zmodyfikowane_przez, trail, alias) VALUES (" + str(id) + "," + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "','" + skrzynia4 + "'," + '1' + ",'" + nazwa_produktu + "','" + prefix + "'," + dni_do_wybicia + "," + czas_studzenia + ",'" + item_status + "','" + komentarz + "','0','" + user + "','" + user + "','" + trail + "','" + alias + "')"
    query_update(query)
    return True

def add_item_to_forming_list_again(id, id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user):
    query = "INSERT INTO lista_formowania_v2(id_produktu, id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, repeated, komentarz, komentarz_flag, dodane_przez, zmodyfikowane_przez) VALUES (" + str(id) + "," + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "'," + skrzynia4 + "," + '1' + ",'" + nazwa_produktu + "','" + prefix + "'," + dni_do_wybicia + "," + czas_studzenia + ",'" + item_status + "', '1','" + komentarz + "','0','" + user + "'," + "'" + user + "'" + ")"
    query_update(query)
    return True

def mark_item_as_assembled(id, komentarz_rdzen, frame1, frame2, user, defect):
    query = "UPDATE lista_formowania_v2 SET item_status='assembled', komentarz_rdzeniarnia='" + komentarz_rdzen + "', flask1='" + str(frame1) +  "', flask2='" + str(frame2) +  "', zmodyfikowane_przez='" + str(user) + "', defekty_rdzeniarnia='" + defect + "', data_zmontowania=current_timestamp(), data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
    query_update(query)
    return True

def sn_validation(nrf, nazwap):
    query = "SELECT * FROM lista_formowania_v2 WHERE alias is NULL AND nazwa_produktu = '" + nazwap + "' AND nr_formowania = '" + nrf + "'"
    res = query_db(query)
    nazwap = nazwap.strip()
    nazwap = nazwap.lower()
    if '56366130221' in nazwap:
        return True    
    elif 'rammschutz' in nazwap:
        return True    
    # elif '56366100212' in nazwap:
    #     return True   
    # elif '56366100214' in nazwap:
    #     return True   
    elif len(res) != 0:
        return False
    else:
        return True
    
def sn_validation_forms(id, prod_id, produkt_id, model_sn_list):

    try:
        id = int(id)
    except ValueError:
        id = 0
    # Poprawka dla STILL 212/214 i 210/211 i ROCLE 643818/644592
    #if id == 35 or id == 36 or id == 43 or id == 44 or id == 24 or id == 25 or id == 80 or id == 81:
        return True
    
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model1_sn = '" + str(model_sn_list[0]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model2_sn = '" + str(model_sn_list[1]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model3_sn = '" + str(model_sn_list[2]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model4_sn = '" + str(model_sn_list[3]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model5_sn = '" + str(model_sn_list[4]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model6_sn = '" + str(model_sn_list[5]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model7_sn = '" + str(model_sn_list[6]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE alias is NULL AND model_id = '" + str(id) + "' AND model8_sn = '" + str(model_sn_list[7]) + "' AND prod_id = '" + str(prod_id) + "' AND produkt_id <> '" + str(produkt_id) + "'"
    res = query_db(query)
    if len(res) != 0:
        return False
    return True

def fields_validation_forms(produkt_id):
    model1_sn_list = []
    model2_sn_list = []
    model3_sn_list = []
    model4_sn_list = []
    model5_sn_list = []
    model6_sn_list = []
    model7_sn_list = []
    model8_sn_list = []
    query = "SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(produkt_id) 
    res = query_db(query)
    for item in res:
        if item == 'model1_sn':
            model1_sn_list.append(item)
        if item == 'model2_sn':
            model2_sn_list.append(item)
        if item == 'model3_sn':
            model3_sn_list.append(item)
        if item == 'model4_sn':
            model4_sn_list.append(item)
        if item == 'model5_sn':
            model5_sn_list.append(item)
        if item == 'model6_sn':
            model6_sn_list.append(item)
        if item == 'model7_sn':
            model7_sn_list.append(item)
        if item == 'model8_sn':
            model8_sn_list.append(item)

    def all_same(items):
        return all(x == items[0] for x in items)
    
    res1 = all_same(model1_sn_list)
    res2 = all_same(model2_sn_list)
    res3 = all_same(model3_sn_list)
    res4 = all_same(model4_sn_list)
    res5 = all_same(model5_sn_list)
    res6 = all_same(model6_sn_list)
    res7 = all_same(model7_sn_list)
    res8 = all_same(model8_sn_list)

    if res1 == True and res2 == True and res3 == True and res4 == True and res5 == True and res6 == True and res7 == True and res8 == True:
        return True
    else:
        return False

def get_produkt_id(status):
    query = "SELECT id FROM lista_formowania_v2 WHERE item_status='" + str(status) + "' ORDER BY id DESC LIMIT 1"
    return query_db_first(query)

def history(produkt_id, production_stage, operator):
    query = "INSERT INTO lista_formowania_historia_v2 (`produkt_id`, `production_stage`, `operator`) VALUES ('" + str(produkt_id) + "','" + production_stage + "','"  + operator + "')"
    query_update(query)
    return True

def history_qa(produkt_id, sn, prefix, production_stage, operator):
    if len(prefix) == 0:
        prefix = 'XX'
    if len(sn) == 0:
        prefix = '0'
    query = "INSERT INTO lista_formowania_historia_v2 (`produkt_id`, `sn`, `prefix`, `production_stage`, `operator`) VALUES ('" + str(produkt_id) + "'," + str(sn) + ",'" + prefix + "','" + production_stage + "','"  + operator + "')"
    query_update(query)
    return True

def check_formed_on(items):
    for item in items:
        if 'formed_on' not in item:
            return False
    return True

def history_forms(produkt_id, production_stage, operator):
    query = "INSERT INTO lista_formowania_formy_historia_v2 (`form_id`, `production_stage`, `operator`) VALUES ('" + str(produkt_id) + "','" + production_stage + "','"  + operator + "')"
    query_update(query)
    return True

def history_shipment(ship_id, sn, activity, operator):
    query = "INSERT INTO `shipments_history` (`ship_id`, `sn`, `activity`, `operator`) VALUES (" + str(ship_id) + ",'" + sn + "','"  + activity + "','"  + operator + "')"
    query_update(query)
    return True

def history_claims(claim_id, operation, user, info=None):
    query = "INSERT INTO `reklamacje_history` (`claim_id`, `operation`, `user`, `info`) VALUES (" + str(claim_id) + ",'" + operation + "','" + user + "','" + (info or '') + "')"
    query_update(query)
    return True

def formy_do_zasypania(produkt_id, prod_id, nazwa_formy_lista, prefix, operator):
    for i in nazwa_formy_lista:
        query = "INSERT INTO `lista_formowania_formy_v2` (`prod_id`, `produkt_id`, `model_id`, `nazwa`, `prefix`, `czas_ostatniej_modyfiakcji`, `operator`) VALUES (" + str(prod_id) + "," + str(produkt_id) + ",'" + str(i['id']) + "','" + str(i['nazwa']) + "','" + str(prefix) + "', current_timestamp(),'" + operator + "')"
        query_update(query)
    return True

def formy_do_zasypania_outline(produkt_id, prod_id, nazwa_formy_lista, prefix, operator, alias):
    for i in nazwa_formy_lista:
        query = "INSERT INTO `lista_formowania_formy_v2` (`prod_id`, `produkt_id`, `model_id`, `nazwa`, `prefix`, `czas_ostatniej_modyfiakcji`, `operator` , `alias`) VALUES (" + str(prod_id) + "," + str(produkt_id) + ",'" + str(i['id']) + "','" + str(i['nazwa']) + "','" + str(prefix) + "', current_timestamp(),'" + operator + "','" + alias + "')"
        query_update(query)
    return True

def formy_do_zasypania_again(produkt_id, prod_id, nazwa_formy_lista, prefix, operator):
    for i in nazwa_formy_lista:
        query = "INSERT INTO `lista_formowania_formy_v2` (`prod_id`, `produkt_id`, `model_id`, `nazwa`, `czas_ostatniej_modyfiakcji`, `operator`, `status`) VALUES (" + str(prod_id) + "," + str(produkt_id) + ",'" + str(i['id']) + "','" + str(i['nazwa']) + "','" + str(prefix) +  "', current_timestamp(),'" + operator + "', 'repeated')"
        query_update(query)
    return True

def forma_zasypana(komentarz_form, sn1, sn2, sn3, sn4, sn5, sn6, sn7, sn8, id, produkt_id, defect, user):
    query = "UPDATE lista_formowania_formy_v2 SET zaformowano='1', komentarz='" + komentarz_form + "', defect='" + defect + "', operator='" + user + "',czas_ostatniej_modyfiakcji=current_timestamp() WHERE id=" + str(id)
    query_update(query)
    query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + sn1 + ", model2_sn=" + sn2 + ", model3_sn=" + sn3 + ", model4_sn=" + sn4 + ", model5_sn=" + sn5 + ", model6_sn=" + sn6 + ", model7_sn=" + sn7 + ", model8_sn=" + sn8 + " WHERE produkt_id=" + str(produkt_id)
    query_update(query)
    return True

def update_semafor():
    query = "UPDATE semafor_linia_automatyczna SET semafor='1', mode='auto', czas=current_timestamp()"
    query_update(query)
    return True

def update_semafor_manual():
    query = "UPDATE semafor_linia_automatyczna SET semafor='1', mode='man', czas=current_timestamp()"
    query_update(query)
    return True

def replace_with_null(arg):
    arg = str(arg)
    if str(arg).strip() == '' or arg == 'None' or arg == None:
        arg = 'NULL'
    return arg

def remove_from_forming_list(id):
    query = "SELECT count(*) as counter FROM lista_formowania_formy_v2 WHERE zaformowano = '0' AND produkt_id=" + str(id)
    #query = "SELECT count(*) as counter FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id)
    res1 = query_db_first(query)
    user = session['user']
    if res1['counter'] == 0:
        query = "UPDATE lista_formowania_v2 SET item_status='formed', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + str(id)
        query_update(query)
        return True
    else:
        return False
    
def replace_none_values(arg):
    for i in arg:
        if i['model1_sn'] == None:
            i['model1_sn'] = '-'
        if i['model2_sn'] == None:
            i['model2_sn'] = '-'
        if i['model3_sn'] == None:
            i['model3_sn'] = '-'
        if i['model4_sn'] == None:
            i['model4_sn'] = '-'
        if i['model5_sn'] == None:
            i['model5_sn'] = '-'
        if i['model6_sn'] == None:
            i['model6_sn'] = '-'
        if i['model7_sn'] == None:
            i['model7_sn'] = '-'
        if i['model8_sn'] == None:
            i['model8_sn'] = '-'
        try:
            if i['flask1'] == None or i['flask1'] == 'NULL':
                i['flask1'] = '-'
        except KeyError:
            continue
        try:
            if i['flask2'] == None or i['flask2'] == 'NULL':
                i['flask2'] = '-'
        except KeyError:
            continue
    return arg

# def delete_frame(form_id, produkt_id):
#     query = "SELECT * FROM lista_formowania_formy_v2 WHERE zaformowano = '0' AND produkt_id=" + str(produkt_id)
#     res = query_db(query)
#     if len(res) == 1:
#         return False
#     else:
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), komentarz='Skrzynia usunięta prze operatora', operator='" + str(session["user"]) + "' WHERE id=" + str(form_id)
#         query_update(query)
#         return True

def delete_frame(form_id):
    query = "DELETE FROM lista_formowania_formy_v2 WHERE zaformowano = '0' AND id=" + str(form_id)
    query_update(query)
    return True
    
def forma_zasypana_auto(produkt_id, form_id):
    query = "SELECT * FROM lista_formowania_v2 where id_produktu" + str(produkt_id)
    n = len(query_db(query))
    query = "SELECT * FROM produkty sztuk where id_produktu" + str(produkt_id)
    k = query_db(query)[0]['sztuk']
    z = n * int(k)

def increse_counter(id, n):
    query = "UPDATE produkty set counter = " + str(n) + " WHERE produkt_id=" + str(id)
    query_update(query)
    return True

def check_pieces_number(id):
    query = "SELECT sztuk FROM produkty WHERE produkt_id=" + str(id)
    pieces_per_pattern = query_db_first(query)['sztuk']
    if pieces_per_pattern == 0:
        return redirect(url_for("sn_error2"))
    else:
        return True
    
def update_counter_based_on_operator_entry(form_id):
    query = "SELECT model1_sn, model2_sn, model3_sn, model4_sn, model5_sn, model6_sn, model7_sn, model8_sn FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(form_id)
    r = query_db(query)
    sn_collection = []
    if r[0]['model1_sn'] != None:
        sn_collection.append(r[0]['model1_sn'])
    if r[0]['model2_sn'] != None:
        sn_collection.append(r[0]['model2_sn'])
    if r[0]['model3_sn'] != None:
        sn_collection.append(r[0]['model3_sn'])
    if r[0]['model4_sn'] != None:
        sn_collection.append(r[0]['model4_sn'])
    if r[0]['model5_sn'] != None:
        sn_collection.append(r[0]['model5_sn'])
    if r[0]['model6_sn'] != None:
        sn_collection.append(r[0]['model6_sn'])
    if r[0]['model7_sn'] != None:
        sn_collection.append(r[0]['model7_sn'])
    if r[0]['model8_sn'] != None:
        sn_collection.append(r[0]['model8_sn'])
    max_sn = max(sn_collection)
    query = "SELECT id_produktu FROM lista_formowania_v2 WHERE id=" + str(form_id)
    r = query_db(query)
    id_produktu = r[0]['id_produktu']
    query = "UPDATE produkty SET counter=" + str(max_sn) + " WHERE produkt_id=" + str(id_produktu)
    query_update(query)
    return True
    
def nadaj_nr_seryjny_2(id):
    query = "SELECT sztuk FROM produkty WHERE produkt_id=" + str(id)
    pieces_per_pattern = query_db_first(query)['sztuk']
    query = "SELECT model1_sn, model2_sn, model3_sn, model4_sn, model5_sn, model6_sn, model7_sn, model8_sn FROM `lista_formowania_formy_v2` WHERE prod_id =" + str(id) + " ORDER BY id DESC"
    sn1_ath = query_db(query)
    tab_serial_numbers = []
    tab_serial_numbers.append(0)
    for i in sn1_ath:
        if i['model1_sn'] != None:
            tab_serial_numbers.append(i['model1_sn'])
        if i['model2_sn'] != None:
            tab_serial_numbers.append(i['model2_sn'])
        if i['model3_sn'] != None:
            tab_serial_numbers.append(i['model3_sn'])
        if i['model4_sn'] != None:
            tab_serial_numbers.append(i['model4_sn'])
        if i['model5_sn'] != None:
            tab_serial_numbers.append(i['model5_sn'])
        if i['model6_sn'] != None:
            tab_serial_numbers.append(i['model6_sn'])
        if i['model7_sn'] != None:
            tab_serial_numbers.append(i['model7_sn'])
        if i['model8_sn'] != None:
            tab_serial_numbers.append(i['model8_sn'])

    sn = max(tab_serial_numbers)
    sn += 1

    query = "SELECT id FROM lista_formowania_formy_v2 where model1_sn is NULL and model2_sn is NULL and model3_sn is NULL and model4_sn is NULL and model5_sn is NULL and model6_sn is NULL and model7_sn is NULL and model8_sn is NULL"
    flasks = query_db(query)
    for item in flasks:
        if pieces_per_pattern == 1:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn)
        elif pieces_per_pattern == 2:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 1)
        elif pieces_per_pattern == 3:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 2)
        elif pieces_per_pattern == 4:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 3)
        elif pieces_per_pattern == 5:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 4)
        elif pieces_per_pattern == 6:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + ", model6_sn=" + str(sn + 5) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 5)
        elif pieces_per_pattern == 7:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + ", model6_sn=" + str(sn + 5) + ", model7_sn=" + str(sn + 6) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 6)
        elif pieces_per_pattern == 8:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + ", model6_sn=" + str(sn + 5) + ", model7_sn=" + str(sn + 6) + " , model8_sn=" + str(sn + 7) + " WHERE zaformowano='0' and id=" + str(item['id'])   
            increse_counter(id, sn + 7)
        query_update(query)

def nadaj_nr_seryjny(id):
    query = "SELECT sztuk FROM produkty WHERE produkt_id=" + str(id)
    pieces_per_pattern = query_db_first(query)['sztuk']
    query = "SELECT model1_sn, model2_sn, model3_sn, model4_sn, model5_sn, model6_sn, model7_sn, model8_sn FROM `lista_formowania_formy_v2` WHERE prod_id =" + str(id) + " ORDER BY id DESC"
    sn1_ath = query_db(query)
    tab_serial_numbers = []
    tab_serial_numbers.append(0)
    for i in sn1_ath:
        if i['model1_sn'] != None:
            tab_serial_numbers.append(i['model1_sn'])
        if i['model2_sn'] != None:
            tab_serial_numbers.append(i['model2_sn'])
        if i['model3_sn'] != None:
            tab_serial_numbers.append(i['model3_sn'])
        if i['model4_sn'] != None:
            tab_serial_numbers.append(i['model4_sn'])
        if i['model5_sn'] != None:
            tab_serial_numbers.append(i['model5_sn'])
        if i['model6_sn'] != None:
            tab_serial_numbers.append(i['model6_sn'])
        if i['model7_sn'] != None:
            tab_serial_numbers.append(i['model7_sn'])
        if i['model8_sn'] != None:
            tab_serial_numbers.append(i['model8_sn'])

    sn = max(tab_serial_numbers)
    sn += 1

    query = "SELECT id FROM lista_formowania_formy_v2 where model1_sn is NULL and model2_sn is NULL and model3_sn is NULL and model4_sn is NULL and model5_sn is NULL and model6_sn is NULL and model7_sn is NULL and model8_sn is NULL"
    flasks = query_db(query)
    for item in flasks:
        if pieces_per_pattern == 1:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn)
        elif pieces_per_pattern == 2:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 1)
        elif pieces_per_pattern == 3:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 2)
        elif pieces_per_pattern == 4:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 3)
        elif pieces_per_pattern == 5:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 4)
        elif pieces_per_pattern == 6:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + ", model6_sn=" + str(sn + 5) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 5)
        elif pieces_per_pattern == 7:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + ", model6_sn=" + str(sn + 5) + ", model7_sn=" + str(sn + 6) + " WHERE zaformowano='0' and id=" + str(item['id'])
            increse_counter(id, sn + 6)
        elif pieces_per_pattern == 8:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(sn) + ", model2_sn=" + str(sn + 1) + ", model3_sn=" + str(sn + 2) + ", model4_sn=" + str(sn + 3) + ", model5_sn=" + str(sn + 4) + ", model6_sn=" + str(sn + 5) + ", model7_sn=" + str(sn + 6) + " , model8_sn=" + str(sn + 7) + " WHERE zaformowano='0' and id=" + str(item['id'])   
            increse_counter(id, sn + 7)
        query_update(query)

def nadaj_nr_seryjny_outline(id, prefix, serial):
    query = "SELECT sztuk FROM produkty WHERE produkt_id=" + str(id)
    pieces_per_pattern = query_db_first(query)['sztuk']
    serial = int(serial)
    query = "SELECT id FROM lista_formowania_formy_v2 where model1_sn is NULL and model2_sn is NULL and model3_sn is NULL and model4_sn is NULL and model5_sn is NULL and model6_sn is NULL and model7_sn is NULL and model8_sn is NULL"
    flasks = query_db(query)
    for item in flasks:
        if pieces_per_pattern == 1:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + " WHERE zaformowano='0' and id=" + str(item['id'])
        elif pieces_per_pattern == 2:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + " WHERE zaformowano='0' and id=" + str(item['id'])
        elif pieces_per_pattern == 3:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + ", model3_sn=" + str(serial + 2) + " WHERE zaformowano='0' and id=" + str(item['id'])
        elif pieces_per_pattern == 4:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + ", model3_sn=" + str(serial + 2) + ", model4_sn=" + str(serial + 3) + " WHERE zaformowano='0' and id=" + str(item['id'])
        elif pieces_per_pattern == 5:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + ", model3_sn=" + str(serial + 2) + ", model4_sn=" + str(serial + 3) + ", model5_sn=" + str(serial + 4) + " WHERE zaformowano='0' and id=" + str(item['id'])         
        elif pieces_per_pattern == 6:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + ", model3_sn=" + str(serial + 2) + ", model4_sn=" + str(serial + 3) + ", model5_sn=" + str(serial + 4) + ", model6_sn=" + str(serial + 5) + " WHERE zaformowano='0' and id=" + str(item['id'])         
        elif pieces_per_pattern == 7:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + ", model3_sn=" + str(serial + 2) + ", model4_sn=" + str(serial + 3) + ", model5_sn=" + str(serial + 4) + ", model6_sn=" + str(serial) + ", model7_sn=" + str(serial + 6) + " WHERE zaformowano='0' and id=" + str(item['id'])       
        elif pieces_per_pattern == 8:
            query = "UPDATE lista_formowania_formy_v2 SET model1_sn=" + str(serial) + ", model2_sn=" + str(serial + 1) + ", model3_sn=" + str(serial + 2) + ", model4_sn=" + str(serial + 3) + ", model5_sn=" + str(serial + 4) + ", model6_sn=" + str(serial) + ", model7_sn=" + str(serial + 6) + " , model8_sn=" + str(serial + 7) + " WHERE zaformowano='0' and id=" + str(item['id'])   
        query_update(query)


def dodanie_nr_skrzyn():
    query = "SELECT counter FROM licznik_skrzyn"
    res = query_db_first(query)
    counter1  = int(res['counter'])
    counter2 = counter1 + 1
    query = "UPDATE licznik_skrzyn SET counter=" + str(counter2) 
    query_update(query)
    falsk_id = datetime.datetime.today().strftime('%m/%d') + '/' + str(counter1)
    return falsk_id

def remove_item_from_forming_list(id):
    query = "SELECT id_produktu FROM lista_formowania_v2 WHERE id=" + str(id)
    id_produktu = query_db_first(query)['id_produktu']
    query = "SELECT sztuk FROM produkty WHERE produkt_id=" + str(id_produktu)
    sztuk = query_db_first(query)['sztuk']
    query = "UPDATE produkty SET counter=counter-" + str(sztuk) + " WHERE produkt_id=" + str(id_produktu)
    query_update(query)
    query = "DELETE FROM lista_formowania_formy_v2 WHERE zaformowano = '0' AND produkt_id=" + str(id)
    query_update(query)
    query = "DELETE FROM lista_formowania_v2 WHERE id=" + str(id)
    query_update(query)
    query = "DELETE FROM lista_formowania_historia_v2 WHERE produkt_id=" + str(id)
    query_update(query) 
    print("Usunieto", id)

    return True

def remove_item_from_forming_list_aps(id):
    query = "DELETE FROM lista_formowania_v2 WHERE id=" + str(id)
    query_update(query)
    print("Usunięto z listy formownia:", id)
    query = "UPDATE lista_formowania_formy_v2 SET status='canceled' WHERE produkt_id=" + str(id)
    query_update(query)
    print("Zmieniona status form na 'canceled' dla id:", id)
    query = "DELETE FROM lista_formowania_historia_v2 WHERE produkt_id=" + str(id)
    query_update(query) 
    print("Usunieto historie formy:", id)
    query = "UPDATE lista_formowania_sn SET canceled='1' WHERE produkt_id=" + str(id)
    query_update(query) 
    print("S/N onzaczony jako canceled dla formy:", id)

    return True

# def remove_item_from_forming_list(id):
#     query = "SELECT id_produktu FROM lista_formowania_v2 WHERE id=" + str(id)
#     id_produktu = query_db_first(query)['id_produktu']
#     query = "SELECT sztuk FROM produkty WHERE produkt_id=" + str(id_produktu)
#     sztuk = query_db_first(query)['sztuk']
#     query = "SELECT id FROM lista_formowania_v2 WHERE item_status in ('new', 'formed') AND id_produktu=" + str(id_produktu) + " ORDER BY id desc LIMIT 1"
#     id_item_to_remove = query_db_first(query)['id']
#     query = "SELECT repeated FROM lista_formowania_v2 WHERE id=" + str(id)
#     repeated = query_db_first(query)['repeated']
#     if repeated == '0':
#         query = "UPDATE produkty SET counter=counter-" + str(sztuk) + " WHERE produkt_id=" + str(id_produktu)
#         query_update(query)
#         query = "DELETE FROM lista_formowania_formy_v2 WHERE zaformowano = '0' AND produkt_id=" + str(id_item_to_remove)
#         query_update(query)
#         query = "DELETE FROM lista_formowania_v2 WHERE id=" + str(id_item_to_remove)
#         query_update(query)
#         query = "DELETE FROM lista_formowania_historia_v2 WHERE produkt_id=" + str(id_item_to_remove)
#         query_update(query) 
#         print('no repeated')   
#         return True
#     else:
#         query = "DELETE FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id_item_to_remove)
#         query_update(query)
#         query = "DELETE FROM lista_formowania_v2 WHERE id=" + str(id_item_to_remove)
#         query_update(query)
#         query = "DELETE FROM lista_formowania_historia_v2 WHERE produkt_id=" + str(id_item_to_remove)
#         query_update(query) 
#         print('repeated')  
#         return True

def oblicz_czas_chlodzenia():
    query = "SELECT id, data_zalania, dni_do_wybicia, czas_studzenia, item_status FROM lista_formowania_v2 WHERE item_status LIKE 'cooling'"
    for i in query_db(query):
        id = i['id']
        data_zalania = i['data_zalania']
        dni_do_wybicia = i['dni_do_wybicia']
        # czas_studzenia = i['czas_studzenia']

        data_chłodzenia = data_zalania + datetime.timedelta(days = int(dni_do_wybicia))
        # data_zalania_datetime = datetime.datetime.strptime(str(data_zalania), "%Y-%m-%d %H:%M:%S")
        data_chłodzenia_datetime = datetime.datetime.strptime(str(data_chłodzenia), "%Y-%m-%d %H:%M:%S")
        data_teraz_datetime = datetime.datetime.now()

        if data_chłodzenia_datetime < data_teraz_datetime:
            query = "UPDATE lista_formowania_v2 SET item_status='knockout', zmodyfikowane_przez='system', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + str(id)
            query_update(query)
            history(id, 'cooling->knockout', 'system')
            print('Zmieniono status z ready_for_cooling -> knockout dla formy id:', id)
        else:
            print('Obliczono czasy chłodzenia dla:', id, '-> satus formy nie zostal zmieniony')

    query = "SELECT tab1.id, tab1.id_form, tab2.data_zalania, tab2.dni_do_wybicia, tab2.czas_studzenia FROM mafi_load tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.id_form = tab2.id WHERE tab1.mafi_status LIKE 'load'"
    for i in query_db(query):
        id = i['id']
        data_zalania = i['data_zalania']
        dni_do_wybicia = i['dni_do_wybicia']
        # czas_studzenia = i['czas_studzenia']

        data_chłodzenia = data_zalania + datetime.timedelta(days = int(dni_do_wybicia))
        # data_zalania_datetime = datetime.datetime.strptime(str(data_zalania), "%Y-%m-%d %H:%M:%S")
        data_chłodzenia_datetime = datetime.datetime.strptime(str(data_chłodzenia), "%Y-%m-%d %H:%M:%S")
        data_teraz_datetime = datetime.datetime.now()

        if data_chłodzenia_datetime < data_teraz_datetime:
            query = "UPDATE mafi_load SET mafi_status='ready_to_knockout', user2='system' WHERE id=" + str(id)
            query_update(query)

    return True

def wyswietl_czasy_studzenia_i_chlodzenia(query):
    for i in query:
        data_teraz_datetime = datetime.datetime.now()
        try:
            data_zalania = i['data_zalania']
            czas_studzenia = i['czas_studzenia']
            # czas_studzenia_minuty = int(czas_studzenia * 60)
            dni_do_wybicia = i['dni_do_wybicia']

            data_studzenia = data_zalania + datetime.timedelta(minutes=czas_studzenia)
            data_chlodzneia = data_zalania + datetime.timedelta(days = int(dni_do_wybicia))

            czas_do_wywiezienia = data_studzenia - data_teraz_datetime
            czas_do_wywiezienia = int(czas_do_wywiezienia.total_seconds() / 60 )
            czas_do_wywiezienia = str(czas_do_wywiezienia).split('.')

            czas_do_konca_chlodzenia = data_chlodzneia - data_teraz_datetime
            czas_do_konca_chlodzenia = int(czas_do_konca_chlodzenia.total_seconds() / 3600 )
            czas_do_konca_chlodzenia = str(czas_do_konca_chlodzenia).split('.')
            
            try:
                czas_do_wywiezienia = czas_do_wywiezienia[0]
                czas_do_konca_chlodzenia = czas_do_konca_chlodzenia[0]
            except IndexError:
                czas_do_wywiezienia = None
                czas_do_konca_chlodzenia = None

            i['data_studzenia'] = str(czas_do_wywiezienia)
            i['czas_do_konca_chlodzenia'] = str(czas_do_konca_chlodzenia)
        except TypeError:
            i['data_zalania'] = None
            i['czas_do_konca_chlodzenia'] = None
    return query
    
def data_for_bot_report(arg):
    query = "SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab2.model1_sn, tab1.data_zalania, tab1.czas_studzenia, tab1.dni_do_wybicia, tab1.data_ostatniej_modyfikacji, (tab3.waga_zeliwa * tab3.sztuk) as waga_netto FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty as tab3 on tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'assembled' ORDER BY tab1.id DESC LIMIT 200"
    query = query_db(query)
    for i in query:
        try:
            data_teraz_datetime = datetime.datetime.now()
            data_zmontowania = i['data_ostatniej_modyfikacji']
            data_od_zmontowania = data_teraz_datetime - data_zmontowania
            data_od_zmontowania = int(data_od_zmontowania.total_seconds() / 60 ) 
            if data_od_zmontowania < 0:
                data_od_zmontowania = 0 
            i['data_od_zmontowania'] = data_od_zmontowania
        except TypeError:
            i['data_od_zmontowania'] = None

    czasy = []
    for i in query:
        czasy.append(i['data_od_zmontowania'])

    formy_zalane = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab2.model1_sn, tab1.data_zalania, tab1.czas_studzenia, tab1.dni_do_wybicia, tab1.data_ostatniej_modyfikacji, tab1.nr_kadzi, tab1.broken, tab1.filtr, tab1.temp_zeliwa, tab1.data_dodania, tab1.zmodyfikowane_przez FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'casted' OR tab1.item_status LIKE 'ready_for_cooling' ORDER BY tab1.id DESC LIMIT 200;")

    a = max(czasy)
    b = len(query)
    c =  len(formy_zalane)
    
    if arg == '1':
        broken = "SELECT DISTINCT tab1.produkt_id as items FROM lista_formowania_historia_v2 tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.broken LIKE 'TAK' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE)"
        filter = "SELECT DISTINCT tab1.produkt_id as items FROM lista_formowania_historia_v2 tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.filtr LIKE 'TAK' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE)"
        formed_mechanical_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE) AND tab3.manual_forming = '0'"
        formed_mechanical_sum_of_mass = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE) AND tab3.manual_forming = '0'"
        formed_manual_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE) AND tab3.manual_forming = '1'"       
        formed_manual_sum_of_mas = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE) AND tab3.manual_forming = '1'"       
        assembled_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.production_stage = 'assembled' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE)"       
        assembled_sum_of_mas = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'assembled' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 840 MINUTE)"    

        broken = query_db(broken)
        broken = len(broken)
        filter = query_db(filter)
        filter = len(filter)
        d = int(broken) + int(filter)

        # Mechanical forming
        mech_1 = query_db(formed_mechanical_n)[0]['x']
        if mech_1 == 'NULL' or mech_1 == None:
            mech_1 = 0
        mech_2 = query_db(formed_mechanical_sum_of_mass)[0]['y'] 
        if mech_2 == 'NULL' or mech_2 == None:
            mech_2 = 0
        mech_2 = mech_2 / 1000
        mech_2 = round(mech_2, 2)
        try:
            mech_3 = int(mech_2) / int(mech_1)
        except ZeroDivisionError:
            mech_3 = 0
        mech_3 = round(mech_3, 2)

        # Manual forming
        man_1 = query_db(formed_manual_n)[0]['x']
        if man_1 == 'NULL' or man_1 == None:
            man_1 = 0
        man_2 = query_db(formed_manual_sum_of_mas)[0]['y'] 
        if man_2 == 'NULL' or man_2 == None:
            man_2 = 0
        man_2 = man_2 / 1000
        man_2 = round(man_2, 2)
        try:
            man_3 = int(man_2) / int(man_1)
        except ZeroDivisionError:
            man_3 = 0
        man_3 = round(man_3, 2)

        # Sum mass mech and manual
        sum_mech_man = float(mech_2) + float(man_2)
        sum_mech_man = round(sum_mech_man, 2) 

        # Assemebled
        assemb_n = query_db(assembled_n)[0]['x']
        if assemb_n == 'NULL' or assemb_n == None:
            assemb_n = 0    
        
        assembled_sum_of_mas = query_db(assembled_sum_of_mas)[0]['y'] 
        if assembled_sum_of_mas == 'NULL' or assembled_sum_of_mas == None:
            assembled_sum_of_mas = 0
        assembled_sum_of_mas = assembled_sum_of_mas / 1000
        assembled_sum_of_mas = round(assembled_sum_of_mas, 2)

        try:
            assembled_avg = int(assembled_sum_of_mas) / int(assemb_n)
        except ZeroDivisionError:
            assembled_avg = 0
        assembled_avg = round(assembled_avg, 2)


    elif arg == '2':
        broken = "SELECT DISTINCT tab1.produkt_id as items FROM lista_formowania_historia_v2 tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.broken LIKE 'TAK' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE)"
        filter = "SELECT DISTINCT tab1.produkt_id as items FROM lista_formowania_historia_v2 tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.filtr LIKE 'TAK' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE)"
        formed_mechanical_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN (SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE) AND tab3.manual_forming = '0'"
        formed_mechanical_sum_of_mass = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN (SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE) AND tab3.manual_forming = '0'"
        formed_manual_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN (SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE) AND tab3.manual_forming = '1'"       
        formed_manual_sum_of_mas = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE) AND tab3.manual_forming = '1'"       
        assembled_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.production_stage = 'assembled' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE)"       
        assembled_sum_of_mas = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'assembled' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE)" 

        broken = query_db(broken)
        broken = len(broken)
        filter = query_db(filter)
        filter = len(filter)
        d = int(broken) + int(filter)

        # Mechanical forming
        mech_1 = query_db(formed_mechanical_n)[0]['x']
        if mech_1 == 'NULL' or mech_1 == None:
            mech_1 = 0
        mech_2 = query_db(formed_mechanical_sum_of_mass)[0]['y'] 
        if mech_2 == 'NULL' or mech_2 == None:
            mech_2 = 0
        mech_2 = mech_2 / 1000
        mech_2 = round(mech_2, 2)
        try:
            mech_3 = int(mech_2) / int(mech_1)
        except ZeroDivisionError:
            mech_3 = 0
        mech_3 = round(mech_3, 2)

        # Manual forming
        man_1 = query_db(formed_manual_n)[0]['x']
        if man_1 == 'NULL' or man_1 == None:
            man_1 = 0
        man_2 = query_db(formed_manual_sum_of_mas)[0]['y'] 
        if man_2 == 'NULL' or man_2 == None:
            man_2 = 0
        man_2 = man_2 / 1000
        man_2 = round(man_2, 2)
        try:
            man_3 = int(man_2) / int(man_1)
        except ZeroDivisionError:
            man_3 = 0
        man_3 = round(man_3, 2)

        # Sum mass mech and manual
        sum_mech_man = float(mech_2) + float(man_2)
        sum_mech_man = round(sum_mech_man, 2) 

        # Assemebled
        assemb_n = query_db(assembled_n)[0]['x']
        if assemb_n == 'NULL' or assemb_n == None:
            assemb_n = 0    
        
        assembled_sum_of_mas = query_db(assembled_sum_of_mas)[0]['y'] 
        if assembled_sum_of_mas == 'NULL' or assembled_sum_of_mas == None:
            assembled_sum_of_mas = 0
        assembled_sum_of_mas = assembled_sum_of_mas / 1000
        assembled_sum_of_mas = round(assembled_sum_of_mas, 2)

        try:
            assembled_avg = int(assembled_sum_of_mas) / int(assemb_n)
        except ZeroDivisionError:
            assembled_avg = 0
        assembled_avg = round(assembled_avg, 2)

    elif arg == '3':
        broken = "SELECT DISTINCT tab1.produkt_id as items FROM lista_formowania_historia_v2 tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.broken LIKE 'TAK' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE)"
        filter = "SELECT DISTINCT tab1.produkt_id as items FROM lista_formowania_historia_v2 tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.filtr LIKE 'TAK' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE)"
        formed_mechanical_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND tab3.manual_forming = '0'"
        formed_mechanical_sum_of_mass = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN (SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND tab3.manual_forming = '0'"
        formed_manual_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN (SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND tab3.manual_forming = '1'"       
        formed_manual_sum_of_mas = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'formed' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND tab3.manual_forming = '1'"       
        assembled_n = "SELECT count(*) x FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.production_stage = 'assembled' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE)"       
        assembled_sum_of_mas = "SELECT sum(tab3.sztuk * tab3.waga_zeliwa) y FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'assembled' AND tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE)" 

        broken = query_db(broken)
        broken = len(broken)
        filter = query_db(filter)
        filter = len(filter)
        d = int(broken) + int(filter)

     # Mechanical forming
        mech_1 = query_db(formed_mechanical_n)[0]['x']
        if mech_1 == 'NULL' or mech_1 == None:
            mech_1 = 0
        mech_2 = query_db(formed_mechanical_sum_of_mass)[0]['y'] 
        if mech_2 == 'NULL' or mech_2 == None:
            mech_2 = 0
        mech_2 = mech_2 / 1000
        mech_2 = round(mech_2, 2)
        try:
            mech_3 = int(mech_2) / int(mech_1)
        except ZeroDivisionError:
            mech_3 = 0
        mech_3 = round(mech_3, 2)

        # Manual forming
        man_1 = query_db(formed_manual_n)[0]['x']
        if man_1 == 'NULL' or man_1 == None:
            man_1 = 0
        man_2 = query_db(formed_manual_sum_of_mas)[0]['y'] 
        if man_2 == 'NULL' or man_2 == None:
            man_2 = 0
        man_2 = man_2 / 1000
        man_2 = round(man_2, 2)
        try:
            man_3 = int(man_2) / int(man_1)
        except ZeroDivisionError:
            man_3 = 0
        man_3 = round(man_3, 2)

        # Sum mass mech and manual
        sum_mech_man = float(mech_2) + float(man_2)
        sum_mech_man = round(sum_mech_man, 2) 

        # Assemebled
        assemb_n = query_db(assembled_n)[0]['x']
        if assemb_n == 'NULL' or assemb_n == None:
            assemb_n = 0    
        
        assembled_sum_of_mas = query_db(assembled_sum_of_mas)[0]['y'] 
        if assembled_sum_of_mas == 'NULL' or assembled_sum_of_mas == None:
            assembled_sum_of_mas = 0
        assembled_sum_of_mas = assembled_sum_of_mas / 1000
        assembled_sum_of_mas = round(assembled_sum_of_mas, 2)

        try:
            assembled_avg = int(assembled_sum_of_mas) / int(assemb_n)
        except ZeroDivisionError:
            assembled_avg = 0
        assembled_avg = round(assembled_avg, 2)

    else:
        d = 0
        mech_1 = 0
        mech_2 = 0
        mech_3 = 0
        man_1  = 0
        man_2  = 0
        man_3  = 0
        sum_mech_man = 0
        assemb_n = 0
        assembled_sum_of_mas = 0
        assembled_avg = 0
    
    #res = [a,b,c,d,0, 0, 0, 0, 0, 0]
    res = [a,b,c,d,mech_1,mech_2,mech_3,man_1,man_2,man_3,sum_mech_man, assemb_n, assembled_sum_of_mas, assembled_avg]
    return res



def wyswitl_czas_od_zmontowania(query):
    for i in query:
        try:
            data_teraz_datetime = datetime.datetime.now()
            data_zmontowania = i['data_ostatniej_modyfikacji']
            data_od_zmontowania = data_teraz_datetime - data_zmontowania
            data_od_zmontowania = int(data_od_zmontowania.total_seconds() / 60 ) 
            # data_od_zmontowania = data_zmontowania - data_teraz_datetime
            # data_od_zmontowania = -1 * int((data_od_zmontowania.total_seconds() / 60) + 2 )
            if data_od_zmontowania < 0:
                data_od_zmontowania = 0 
            i['data_od_zmontowania'] = data_od_zmontowania
        except TypeError:
            i['data_od_zmontowania'] = None


def suma_wagi_netto():
    sql = "SELECT id FROM lista_formowania_v2 WHERE item_status LIKE 'assembled'"
    list_of_items_data = query_db(sql)
    masa = []
    for i in list_of_items_data:
        sql = """
            SELECT
                tab1.produkt_id,
                tab1.param1,
                tab3.waga_zeliwa
            FROM
                `lista_formowania_sn` tab1
            LEFT JOIN lista_formowania_v2 tab2 ON
                tab1.produkt_id = tab2.id 
            LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id
            WHERE
                tab1.param1 = '0' AND tab1.produkt_id =
            """ + str(i['id'])
        
        result = query_db(sql)
        for k in result:
            masa.append(k['waga_zeliwa']) 

    try:
        masa = sum(masa)
        waga = (masa / 1000)
    except TypeError:
        waga = 0
    except ValueError:
        waga = 0

    return waga

def suma_wagi_formy_netto(id):
    masa = []
    sql = """
            SELECT
                tab1.produkt_id,
                tab1.param1,
                tab3.waga_zeliwa
            FROM
                `lista_formowania_sn` tab1
            LEFT JOIN lista_formowania_v2 tab2 ON
                tab1.produkt_id = tab2.id 
            LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id
            WHERE
                tab1.param1 = '0' AND tab1.produkt_id =
            """ + str(id)
        
    result = query_db(sql)
    for k in result:
        masa.append(k['waga_zeliwa']) 

    try:
        waga = sum(masa)
    except TypeError:
        waga = 0
    except ValueError:
        waga = 0

    return waga

def oblicz_numery_seryjne(id):
    sql = "SELECT DISTINCT prefix, sn FROM `lista_formowania_sn` WHERE produkt_id=" + str(id) + " AND param1='0'"
    sn_list = query_db(sql)
    list_of_sn = []
    for i in sn_list:
        try:
            sn = i['prefix'] + '-' + str(i['sn'])
        except IndexError:
            sn = 'XX-000'
        list_of_sn.append(sn)
    
    return list_of_sn

# def suma_wagi_netto():
#     x = query_db("SELECT sum(tab3.waga_zeliwa * tab3.sztuk) as suma_wagi_netto FROM lista_formowania_v2 AS tab1 LEFT JOIN produkty AS tab3 ON tab1.id_produktu = tab3.produkt_id WHERE tab1.item_status LIKE 'assembled'") 
#     print(x)
#     try:
#         x = (x[0]['suma_wagi_netto'] / 1000)
#     except TypeError:
#         x = 0
#     return x

def replace_nulls(arg):
    new_val = {}
    for k,i in arg[0].items():
        if i == None:
            new_val[k] = '-'
        else:
            new_val[k] = i
    return new_val

def filter_decyzja(items):
    wynik = []

    for item in items:
        if item.get('decyzja') not in [None, '', '-']:
            wynik.append(item)

    return wynik

def patterns_on_the_line(arg):
    query ="SELECT position_0, position_1, position_2, position_3, position_4, position_5, position_6, position_7, position_8, position_9, position_10, position_11, position_12, position_13 FROM linia_automatyczna ORDER BY id DESC LIMIT 1"
    res = query_db(query)
    patterns_on_the_line = []
    for i,k in res[0].items():
        patterns_on_the_line.append(k)
   
    patterns_list = []
    for i in patterns_on_the_line:
        query = "SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab3.prefix, tab1.trail, tab1.id_model1 id_model1, tab1.id_model2 id_model2, tab1.id_model3 id_model3, tab1.id_model4 id_model4, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.id_model1=" + str(i) + " AND tab1.item_status LIKE 'new' OR tab1.id_model2=" + str(i) + " AND tab1.item_status LIKE 'new' OR tab1.id_model3=" + str(i) + " AND tab1.item_status LIKE 'new' OR tab1.id_model4=" + str(i) + " AND tab1.item_status LIKE 'new' ORDER BY tab1.id ASC LIMIT 1"
        res = query_db(query)
        patterns_list.append(res)
    
    patterns_list_after_cleanup = []
    for i in patterns_list:
        if len(i) == 0:
            continue
        else:
            patterns_list_after_cleanup.append(i[0])

    sorted_list = []
    for i in patterns_list_after_cleanup:
        if i not in sorted_list:
            if len(i) == 0:
                continue
            sorted_list.append(i)
    
    return sorted_list

def extracting_digits(arg):
    arg = arg.replace('-',' ')
    res = [int(i) for i in arg.split() if i.isdigit()]
    try:
        res = res[0]
    except IndexError:
        res = None
    return res

def adv_search(arg):
    flasks = []

    query = '''
        SELECT
        tab1.id,
        tab2.model1_sn,
        tab2.model2_sn,
        tab2.model3_sn,
        tab2.model4_sn,
        tab2.model5_sn,
        tab2.model6_sn,
        tab2.model7_sn,
        tab2.model8_sn,
        tab3.tag,
        tab3.nazwa
    FROM
        lista_formowania_v2 AS tab1
    LEFT JOIN lista_formowania_formy_v2 AS tab2
    ON
        tab1.id = tab2.produkt_id
    LEFT JOIN tag_modele AS tab3
    ON
        tab2.model_id = tab3.id
    WHERE tab1.id=''' + str(arg)

    res = query_db(query)
    for i in res:
        s1 = i['model1_sn']
        if s1 == None or s1 == 'NULL':
            s1 = 0
        s2 = i['model2_sn']
        if s2 == None or s2 == 'NULL':
            s2 = 0
        s3 = i['model3_sn']
        if s3 == None or s3 == 'NULL':
            s3 = 0
        s4 = i['model4_sn']
        if s4 == None or s4 == 'NULL':
            s4 = 0
        s5 = i['model5_sn']
        if s5 == None or s5 == 'NULL':
            s5 = 0
        s6 = i['model6_sn']
        if s6 == None or s6 == 'NULL':
            s6 = 0
        s7 = i['model7_sn']
        if s7 == None or s7 == 'NULL':
            s7 = 0
        s8 = i['model8_sn']
        if s8 == None or s8 == 'NULL':
            s8 = 0

        if i['tag'] == None:
            tag = '0'
        else:
            tag = i['tag']

        sn = str(s1) + '/' +str(s2) + '/' + str(s3) + '/' + str(s4) + '/' + str(s5) + '/' + str(s6) + '/' + str(s7) + '/' + str(s8)
        query = "SELECT * FROM skrzynie_zaformowane_v2 WHERE nr_formowania LIKE '%" + str(sn) + "%' AND model LIKE '" + tag + "'"
        result = query_db(query)
        try:
            czas = result[0]['czas']
        except IndexError:
            czas = '1999-12-21 17:07:23'
    
        query = "SELECT * FROM widok_skrzyn_zaformowanych WHERE time='" + str(czas) + "'"
        res = query_db(query)

        try:
            flasks.append(res[0])
        except IndexError:
            entry = {
            'flask_name': '-',
            'pattern_name': '-',
            'flask_id1': '-',
            'flask_id2': '-',
            'pattern_id' : '-',
            'time' : '-'
            }
            flasks.append(entry)

    return flasks

def adv_search_manscan(arg):
    query = '''
            SELECT
    tab1.id,
    tab2.model1_sn,
    tab2.model2_sn,
    tab2.model3_sn,
    tab2.model4_sn,
    tab2.model5_sn,
    tab2.model6_sn,
    tab2.model7_sn,
    tab2.model8_sn,
    tab3.tag,
    tab3.nazwa,
    tab4.rfid_tag,
    tab4.czas
    FROM
        lista_formowania_v2 AS tab1
    LEFT JOIN lista_formowania_formy_v2 AS tab2
    ON
        tab1.id = tab2.produkt_id
    LEFT JOIN tag_modele AS tab3
    ON
        tab2.model_id = tab3.id
    LEFT JOIN rfid_gate_mechform AS tab4
    ON
        tab2.id = tab4.form_id
    WHERE
        tab1.id =''' + str(arg)
    
    res = query_db(query)
    for i in res:
        for k,v in i.items():
            if v == None:
                i[k] = '-'

    return res

def expand_models_to_list(data):
    model_keys = [f"model{i}_sn" for i in range(1, 9)]
    result = []

    for key in model_keys:
        sn = data.get(key)

        if sn not in (None, "", "-"):
            item = data.copy()
            item["sn"] = sn

            # usuwamy modelX_sn
            for k in model_keys:
                item.pop(k, None)

            result.append(item)

    return result

def defecs_data(id):

    query = '''
        SELECT DISTINCT
            tab1.*, 
            tab2.*, 
            tab3.manual_forming, tab3.waga_zeliwa, tab3.prefix as pre, 
            tab4.defect defekty_formiernia, tab4.model1_sn, tab4.model2_sn, tab4.model3_sn, tab4.model4_sn, tab4.model5_sn, tab4.model6_sn, tab4.model7_sn, tab4.model8_sn 
        FROM
            `lista_formowania_historia_v2` tab1
        JOIN lista_formowania_v2 tab2 ON
            tab1.produkt_id = tab2.id
        JOIN produkty tab3 ON
            tab2.id_produktu = tab3.produkt_id
        JOIN lista_formowania_formy_v2 tab4 ON tab1.produkt_id = tab4.produkt_id
        WHERE
            tab2.id=
        ''' + str(id)
    
    res = query_db(query)
    item = {}
    for i in res:
        # ID
        item['id'] = i['id']

        # Nazwa
        item['product_name'] = i['nazwa_produktu']

        # Forming line
        if i['manual_forming'] == '0':
            item['forming_line'] = 'mechnical'
        else:
            item['forming_line'] = 'manual'
        
        # Forming
        if i['production_stage'] == 'formed':
            item['formed_on'] = str(i['czas'])
            item['formed_by'] = i['operator']

        # Assambling
        if i['production_stage'] == 'assembled':
            item['assambled_on'] = str(i['czas'])
            item['assambled_by'] = i['operator']
            item['assambled_comment'] = i['komentarz_rdzeniarnia']

        # Casting
        if i['production_stage'] == 'casted':
            item['flooded_on'] = str(i['czas'])
            item['flooded_by'] = i['operator']

        # Knockout
        if i['production_stage'] == 'knockout':
            item['knockout_on'] = str(i['czas'])
            item['knockout_by'] = i['operator']

        # Iron temp
        if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
            item['iron_temp'] = i['temp_zeliwa']

        # Iron temp
        if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
            item['iron_temp'] = i['temp_zeliwa']

        # Ladle number
        if i['nr_kadzi'] != 'NULL' or i['nr_kadzi'] != None:
            item['ladle_no'] = i['nr_kadzi']

        # Refiled
        if i['filtr'] != 'NULL' or i['filtr'] != None:
            if i['filtr'] == 'nie':
                item['refiled'] = 'no'
            else:
                item['refiled'] = 'yes'          

        # Broken
        if i['broken'] != 'NULL' or i['broken'] != None:
            if i['broken'] == 'nie':
                item['broken'] = 'no'
            else:
                item['broken'] = 'yes'     

        # Sand temperature
        if i['sand_temp'] != 'NULL' or i['sand_temp'] != None:
            item['sand_temp'] = i['sand_temp']  
            
        # Masa odlewu
        item['casting_mass'] = i['waga_zeliwa']

        # Prefix
        item['prefix'] = i['prefix']

        # Czas zalewania
        item['czas_zalewania'] = i['czas_zalewania']

        # Scrap before casting
        if i['repeated'] == '0':
            item['scrap_cast'] = 'no'
        else:
            item['scrap_cast'] = 'yes'

        # Komentarz zalew
        if i['komentarz_zalew'] == '':
            item['comment_casting'] = '-'
        else:
            item['comment_casting'] = i['komentarz_zalew']

        # Komentarz wywoz
        if i['komentarz_wywoz'] == '' or i['komentarz_wywoz'] == None:
            item['komentarz_wywoz'] = '-'
        else:
            item['komentarz_wywoz'] = i['komentarz_wywoz']

        # Defekty rdzeniarnia 
        if i['defekty_rdzeniarnia'] == '' or i['defekty_rdzeniarnia'] == None:
            item['defekty_rdzeniarnia'] = '-'
        else:
            item['defekty_rdzeniarnia'] = i['defekty_rdzeniarnia']

        # Time  
        if i['production_stage'] == 'casted':
            time_of_casting = i['czas']
        if i['production_stage'] == 'cooling':
            time_of_cooling = i['czas']

        # Komentarz biuro odlewni
        if i['komentarz'] == '':
            item['comment_biuro'] = '-'
        else:
            item['comment_biuro'] = i['komentarz']

        # Production stage  
        if i['production_stage'] == 'casted':
            time_of_casting = i['czas']
        if i['production_stage'] == 'cooling':
            time_of_cooling = i['czas']

        # Czas studzenia z bazy
        if i['czas_studzenia'] == '' or i['czas_studzenia'] == None:
            item['czas_studzenia'] = '-'
        else:
            item['czas_studzenia'] = i['czas_studzenia']

        # Czas studzenia z bazy
        if i['trail'] == '' or i['trail'] == None:
            item['trail'] = '-'
        else:
            item['trail'] = i['trail']

    # oblicenie czasu 
    try:
        time_of_the_hall = time_of_cooling - time_of_casting
    except UnboundLocalError:
        time_of_the_hall = '-'
    item['time_of_the_hall'] = time_of_the_hall

    # cooling time check
    if time_of_the_hall != '-':
        minuty_na_odlewni = czas_na_minuty(str(time_of_the_hall))
        minuty_chlodzenia = item['czas_studzenia'] * 60
        if minuty_na_odlewni > minuty_chlodzenia:
            item['cooling_time_check'] = 'p'
        else:
            item['cooling_time_check'] = 'n'
    else:
        item['cooling_time_check'] = 'w'

    query = '''
    SELECT DISTINCT
        tab1.model1_sn, tab1.model2_sn, tab1.model3_sn, tab1.model4_sn, tab1.model5_sn, tab1.model6_sn, tab1.model7_sn, tab1.model8_sn, tab1.defect defekty_formiernia, tab2.prefix
    FROM
        `lista_formowania_formy_v2` tab1 LEFT JOIN produkty tab2 ON tab1.prod_id = tab2.produkt_id
    WHERE
        tab1.produkt_id=''' + str(id)
    
    r = query_db(query)

    try:
        defect1 = r[0]['defekty_formiernia']
    except IndexError:
        defect1 = ''
    try:
        defect2 = r[1]['defekty_formiernia']
    except IndexError:
        defect2 = ''
    try:
        defect3 = r[2]['defekty_formiernia']
    except IndexError:
        defect3 = ''
    try:
        defect4 = r[3]['defekty_formiernia']
    except IndexError:
        defect4 = ''
    try:
        defect5 = r[4]['defekty_formiernia']
    except IndexError:
        defect5 = ''
    try:
        defect6 = r[5]['defekty_formiernia']
    except IndexError:
        defect6 = ''
    try:
        defect7 = r[6]['defekty_formiernia']
    except IndexError:
        defect7 = ''
    try:
        defect8 = r[7]['defekty_formiernia']
    except IndexError:
        defect8 = ''

    defects_forming = []
    defects_forming.append(defect1)
    defects_forming.append(defect2)
    defects_forming.append(defect3)
    defects_forming.append(defect4)
    defects_forming.append(defect5)
    defects_forming.append(defect6)
    defects_forming.append(defect7)
    defects_forming.append(defect8)

    defects_forming = [x for x in defects_forming if x]
    defect_forming = ','.join(defects_forming)
    if len(defect_forming) == 0:
        defect_forming = '-'

    item['defect_forming'] = defect_forming

    sns = []
    sns.append(r[0]['model1_sn']) 
    sns.append(r[0]['model2_sn']) 
    sns.append(r[0]['model3_sn']) 
    sns.append(r[0]['model4_sn']) 
    sns.append(r[0]['model5_sn']) 
    sns.append(r[0]['model6_sn']) 
    sns.append(r[0]['model7_sn']) 
    sns.append(r[0]['model8_sn']) 


    sn = r[0]['prefix'] + '-'

    for k in sns:
        if k != None:
            sn = sn + '/' + str(k)

    if sn[0:3] == 'XX-':
        sn = sn[4:]
    else:
        sn = sn[4:]
        #sn = str(sn).replace('-/', '-')

    item['sn'] = sn

    # Check of idexes
    lists_of_sns = []
    for k,z in item.items():
        lists_of_sns.append(k)

    if 'id' not in lists_of_sns:
        item['id'] = '-'
    if 'sn' not in lists_of_sns:
        item['sn'] = '-'
    if 'forming_line' not in lists_of_sns:
        item['forming_line'] = '-'
    if 'formed_on' not in lists_of_sns:
        item['formed_on'] = '-'
    if 'formed_by' not in lists_of_sns:
        item['formed_by'] = '-'
    if 'sand_temp' not in lists_of_sns:
        item['sand_temp'] = '-'
    if 'assambled_on' not in lists_of_sns:
        item['assambled_on'] = '-'
    if 'assambled_by' not in lists_of_sns:
        item['assambled_by'] = '-'
    if 'assambled_comment' not in lists_of_sns:
        item['assambled_comment'] = '-'
    if item['assambled_comment'] == '':
        item['assambled_comment'] = '-'
    if 'flooded_by' not in lists_of_sns:
        item['flooded_by'] = '-'
    if 'flooded_on' not in lists_of_sns:
        item['flooded_on'] = '-'
    if 'iron_temp' not in lists_of_sns:
        item['iron_temp'] = '-'
    if 'ladle_no' not in lists_of_sns:
        item['ladle_no'] = '-'
    if 'refiled' not in lists_of_sns:
        item['refiled'] = '-'
    if 'broken' not in lists_of_sns:
        item['broken'] = '-'
    if 'sand_temp' not in lists_of_sns:
        item['sand_temp'] = '-'
    if 'time_of_the_hall' not in lists_of_sns:
        item['time_of_the_hall'] = '-'
    if 'komentarz_wywoz' not in lists_of_sns:
        item['komentarz_wywoz'] = '-'
    if 'defekty_rdzeniarnia' not in lists_of_sns:
        item['defekty_rdzeniarnia'] = '-'
    if 'knockout_on' not in lists_of_sns:
        item['knockout_on'] = '-'
    if 'knockout_by' not in lists_of_sns:
        item['knockout_by'] = '-'
    if 'czas_zalewania' not in lists_of_sns:
        item['czas_zalewania'] = '-'
    if 'comment_biuro' not in lists_of_sns:
        item['comment_biuro'] = '-'

    return item


def items_data(id):
    item_detailed_info = []
    sql = f"SELECT produkt_id id, sn, prefix FROM lista_formowania_sn WHERE produkt_id={id} AND param1='0'"
    items_serial_numbers = query_db(sql)
  
    for item in items_serial_numbers:
        query = '''
                SELECT DISTINCT
                    tab1.*, 
                    tab2.*, 
                    tab3.manual_forming, tab3.waga_zeliwa, tab3.prefix as pre, 
                    tab4.defect defekty_formiernia
                FROM
                    `lista_formowania_historia_v2` tab1
                JOIN lista_formowania_v2 tab2 ON
                    tab1.produkt_id = tab2.id
                JOIN produkty tab3 ON
                    tab2.id_produktu = tab3.produkt_id
                JOIN lista_formowania_formy_v2 tab4 ON tab1.produkt_id = tab4.produkt_id
                WHERE
                    tab2.id=
                ''' + str(item['id'])
    
        details = query_db(query)
        for i in details:
            # Nazwa
            item['product_name'] = i['nazwa_produktu']

            # Forming line
            if i['manual_forming'] == '0':
                item['forming_line'] = 'mechnical'
            else:
                item['forming_line'] = 'manual'
            
            # Forming
            if i['production_stage'] == 'formed':
                item['formed_on'] = str(i['czas'])
                item['formed_by'] = i['operator']

            # Assambling
            if i['production_stage'] == 'assembled':
                item['assambled_on'] = str(i['czas'])
                item['assambled_by'] = i['operator']
                item['assambled_comment'] = i['komentarz_rdzeniarnia']

            # Casting
            if i['production_stage'] == 'casted':
                item['flooded_on'] = str(i['czas'])
                item['flooded_by'] = i['operator']

            # Knockout
            if i['production_stage'] == 'knockout':
                item['knockout_on'] = str(i['czas'])
                item['knockout_by'] = i['operator']

            # Iron temp
            if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
                item['iron_temp'] = i['temp_zeliwa']

            # Iron temp
            if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
                item['iron_temp'] = i['temp_zeliwa']

            # Ladle number
            if i['nr_kadzi'] != 'NULL' or i['nr_kadzi'] != None:
                item['ladle_no'] = i['nr_kadzi']

            # Refiled
            if i['filtr'] != 'NULL' or i['filtr'] != None:
                if i['filtr'] == 'nie':
                    item['refiled'] = 'no'
                else:
                    item['refiled'] = 'yes'          

            # Broken
            if i['broken'] != 'NULL' or i['broken'] != None:
                if i['broken'] == 'nie':
                    item['broken'] = 'no'
                else:
                    item['broken'] = 'yes'     

            # Sand temperature
            if i['sand_temp'] != 'NULL' or i['sand_temp'] != None:
                item['sand_temp'] = i['sand_temp']  
                
            # Masa odlewu
            item['casting_mass'] = i['waga_zeliwa']

            # Prefix
            item['prefix'] = i['prefix']

            # Czas zalewania
            item['czas_zalewania'] = i['czas_zalewania']

            # Scrap before casting
            if i['repeated'] == '0':
                item['scrap_cast'] = 'no'
                item['scrap'] = 0
            else:
                item['scrap_cast'] = 'yes'
                item['scrap'] = 1

            # Komentarz zalew
            if i['komentarz_zalew'] == '':
                item['comment_casting'] = '-'
            else:
                item['comment_casting'] = i['komentarz_zalew']

            # Komentarz wywoz
            if i['komentarz_wywoz'] == '' or i['komentarz_wywoz'] == None:
                item['komentarz_wywoz'] = '-'
            else:
                item['komentarz_wywoz'] = i['komentarz_wywoz']

            # Defekty rdzeniarnia 
            if i['defekty_rdzeniarnia'] == '' or i['defekty_rdzeniarnia'] == None:
                item['defekty_rdzeniarnia'] = '-'
            else:
                item['defekty_rdzeniarnia'] = i['defekty_rdzeniarnia']

            # Time  
            if i['production_stage'] == 'casted':
                time_of_casting = i['czas']
            if i['production_stage'] == 'cooling':
                time_of_cooling = i['czas']

            # Komentarz biuro odlewni
            if i['komentarz'] == '':
                item['comment_biuro'] = '-'
            else:
                item['comment_biuro'] = i['komentarz']

            # Production stage  
            if i['production_stage'] == 'casted':
                time_of_casting = i['czas']
            if i['production_stage'] == 'cooling':
                time_of_cooling = i['czas']

            # Czas studzenia z bazy
            if i['czas_studzenia'] == '' or i['czas_studzenia'] == None:
                item['czas_studzenia'] = '-'
            else:
                item['czas_studzenia'] = i['czas_studzenia']

            # Czas studzenia z bazy
            if i['trail'] == '' or i['trail'] == None:
                item['trail'] = '-'
            else:
                item['trail'] = i['trail']

            # Alias
            if i['alias'] == '' or i['alias'] == None:
                item['alias'] = '-'
            else:
                item['alias'] = i['alias']

            # Defekty formiernia
            if i['defekty_formiernia'] == '' or i['defekty_formiernia'] == None:
                item['defect_forming'] = '-'
            else:
                item['defect_forming'] = i['defekty_formiernia']

    ######################################################################################################
    ############################# KONIEC PĘTLI POBIERANIA DANYCH Z BAZY ##################################
    ######################################################################################################

        # oblicenie czasu 
        try:
            time_of_the_hall = time_of_cooling - time_of_casting
        except UnboundLocalError:
            time_of_the_hall = '-'
        item['time_of_the_hall'] = time_of_the_hall

        # cooling time check
        if time_of_the_hall != '-':
            minuty_na_odlewni = czas_na_minuty(str(time_of_the_hall))
            minuty_chlodzenia = item['czas_studzenia'] * 60
            if minuty_na_odlewni > minuty_chlodzenia:
                item['cooling_time_check'] = 'p'
            else:
                item['cooling_time_check'] = 'n'
        else:
            item['cooling_time_check'] = 'w'

        # Sprawdzenie kluczy w słowniku item
        missing_keys = [
            'sn', 'forming_line', 'formed_on', 'formed_by', 'sand_temp', 'assambled_on',
            'assambled_by', 'assambled_comment', 'flooded_by', 'flooded_on', 'iron_temp',
            'ladle_no', 'refiled', 'broken', 'time_of_the_hall', 'komentarz_wywoz',
            'defekty_rdzeniarnia', 'knockout_on', 'knockout_by', 'czas_zalewania',
            'comment_biuro', 'alias'
        ]
        for key in missing_keys:
            item.setdefault(key, '-')  

        # items = expand_models_to_list(item)
        item_detailed_info.append(item)

    return item_detailed_info

def items_data_v1(id):    
    query = '''
        SELECT DISTINCT
            tab1.*, 
            tab2.*, 
            tab3.manual_forming, tab3.waga_zeliwa, tab3.prefix as pre, 
            tab4.defect defekty_formiernia, tab4.model1_sn, tab4.model2_sn, tab4.model3_sn, tab4.model4_sn, tab4.model5_sn, tab4.model6_sn, tab4.model7_sn, tab4.model8_sn 
        FROM
            `lista_formowania_historia_v2` tab1
        JOIN lista_formowania_v2 tab2 ON
            tab1.produkt_id = tab2.id
        JOIN produkty tab3 ON
            tab2.id_produktu = tab3.produkt_id
        JOIN lista_formowania_formy_v2 tab4 ON tab1.produkt_id = tab4.produkt_id
        WHERE
            tab2.id=
        ''' + str(id)
    
    defekty_formiernia = []
    
    items = query_db(query)
    item = {}
    for i in items:
        # ID
        item['id'] = i['id']

        # Nazwa
        item['product_name'] = i['nazwa_produktu']

        # Forming line
        if i['manual_forming'] == '0':
            item['forming_line'] = 'mechnical'
        else:
            item['forming_line'] = 'manual'
        
        # Forming
        if i['production_stage'] == 'formed':
            item['formed_on'] = str(i['czas'])
            item['formed_by'] = i['operator']

        # Assambling
        if i['production_stage'] == 'assembled':
            item['assambled_on'] = str(i['czas'])
            item['assambled_by'] = i['operator']
            item['assambled_comment'] = i['komentarz_rdzeniarnia']

        # Casting
        if i['production_stage'] == 'casted':
            item['flooded_on'] = str(i['czas'])
            item['flooded_by'] = i['operator']

        # Knockout
        if i['production_stage'] == 'knockout':
            item['knockout_on'] = str(i['czas'])
            item['knockout_by'] = i['operator']

        # Iron temp
        if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
            item['iron_temp'] = i['temp_zeliwa']

        # Iron temp
        if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
            item['iron_temp'] = i['temp_zeliwa']

        # Ladle number
        if i['nr_kadzi'] != 'NULL' or i['nr_kadzi'] != None:
            item['ladle_no'] = i['nr_kadzi']

        # Refiled
        if i['filtr'] != 'NULL' or i['filtr'] != None:
            if i['filtr'] == 'nie':
                item['refiled'] = 'no'
            else:
                item['refiled'] = 'yes'          

        # Broken
        if i['broken'] != 'NULL' or i['broken'] != None:
            if i['broken'] == 'nie':
                item['broken'] = 'no'
            else:
                item['broken'] = 'yes'     

        # Sand temperature
        if i['sand_temp'] != 'NULL' or i['sand_temp'] != None:
            item['sand_temp'] = i['sand_temp']  
            
        # Masa odlewu
        item['casting_mass'] = i['waga_zeliwa']

        # Prefix
        item['prefix'] = i['prefix']

        # Czas zalewania
        item['czas_zalewania'] = i['czas_zalewania']

        # Scrap before casting
        if i['repeated'] == '0':
            item['scrap_cast'] = 'no'
            item['scrap'] = 0
        else:
            item['scrap_cast'] = 'yes'
            item['scrap'] = 1

        # Komentarz zalew
        if i['komentarz_zalew'] == '':
            item['comment_casting'] = '-'
        else:
            item['comment_casting'] = i['komentarz_zalew']

        # Komentarz wywoz
        if i['komentarz_wywoz'] == '' or i['komentarz_wywoz'] == None:
            item['komentarz_wywoz'] = '-'
        else:
            item['komentarz_wywoz'] = i['komentarz_wywoz']

        # Defekty rdzeniarnia 
        if i['defekty_rdzeniarnia'] == '' or i['defekty_rdzeniarnia'] == None:
            item['defekty_rdzeniarnia'] = '-'
        else:
            item['defekty_rdzeniarnia'] = i['defekty_rdzeniarnia']

        # Time  
        if i['production_stage'] == 'casted':
            time_of_casting = i['czas']
        if i['production_stage'] == 'cooling':
            time_of_cooling = i['czas']

        # Komentarz biuro odlewni
        if i['komentarz'] == '':
            item['comment_biuro'] = '-'
        else:
            item['comment_biuro'] = i['komentarz']

        # Production stage  
        if i['production_stage'] == 'casted':
            time_of_casting = i['czas']
        if i['production_stage'] == 'cooling':
            time_of_cooling = i['czas']

        # Czas studzenia z bazy
        if i['czas_studzenia'] == '' or i['czas_studzenia'] == None:
            item['czas_studzenia'] = '-'
        else:
            item['czas_studzenia'] = i['czas_studzenia']

        # Czas studzenia z bazy
        if i['trail'] == '' or i['trail'] == None:
            item['trail'] = '-'
        else:
            item['trail'] = i['trail']

        # Alias
        if i['alias'] == '' or i['alias'] == None:
            item['alias'] = '-'
        else:
            item['alias'] = i['alias']

        # Defekty formiernia
        if i['defekty_formiernia'] == '' or i['defekty_formiernia'] == None:
            item['defect_forming'] = '-'
        else:
            item['defect_forming'] = i['defekty_formiernia']

        # NUMERY SERYJNE
        if i['model1_sn'] == '' or i['model1_sn'] == None:
            item['model1_sn'] = '-'
        else:
            item['model1_sn'] = i['model1_sn']

        if i['model2_sn'] == '' or i['model2_sn'] == None:
            item['model2_sn'] = '-'
        else:
            item['model2_sn'] = i['model2_sn']

        if i['model3_sn'] == '' or i['model3_sn'] == None:
            item['model3_sn'] = '-'
        else:
            item['model3_sn'] = i['model3_sn']

        if i['model4_sn'] == '' or i['model4_sn'] == None:
            item['model4_sn'] = '-'
        else:
            item['model4_sn'] = i['model4_sn']

        if i['model5_sn'] == '' or i['model5_sn'] == None:
            item['model5_sn'] = '-'
        else:
            item['model5_sn'] = i['model5_sn']

        if i['model6_sn'] == '' or i['model6_sn'] == None:
            item['model6_sn'] = '-'
        else:
            item['model6_sn'] = i['model6_sn']

        if i['model7_sn'] == '' or i['model7_sn'] == None:
            item['model7_sn'] = '-'
        else:
            item['model7_sn'] = i['model7_sn']

        if i['model8_sn'] == '' or i['model8_sn'] == None:
            item['model8_sn'] = '-'
        else:
            item['model8_sn'] = i['model8_sn']

    ######################################################################################################
    ############################# KONIEC PĘTLI POBIERANIA DANYCH Z BAZY ##################################
    ######################################################################################################

    # oblicenie czasu 
    try:
        time_of_the_hall = time_of_cooling - time_of_casting
    except UnboundLocalError:
        time_of_the_hall = '-'
    item['time_of_the_hall'] = time_of_the_hall

    # cooling time check
    if time_of_the_hall != '-':
        minuty_na_odlewni = czas_na_minuty(str(time_of_the_hall))
        minuty_chlodzenia = item['czas_studzenia'] * 60
        if minuty_na_odlewni > minuty_chlodzenia:
            item['cooling_time_check'] = 'p'
        else:
            item['cooling_time_check'] = 'n'
    else:
        item['cooling_time_check'] = 'w'

    # Sprawdzenie kluczy w słowniku item
    missing_keys = [
        'sn', 'forming_line', 'formed_on', 'formed_by', 'sand_temp', 'assambled_on',
        'assambled_by', 'assambled_comment', 'flooded_by', 'flooded_on', 'iron_temp',
        'ladle_no', 'refiled', 'broken', 'time_of_the_hall', 'komentarz_wywoz',
        'defekty_rdzeniarnia', 'knockout_on', 'knockout_by', 'czas_zalewania',
        'comment_biuro', 'alias'
    ]
    for key in missing_keys:
        item.setdefault(key, '-')  

    items = expand_models_to_list(item)
    return items


def items_data_defects_only(item):
    query = '''
        SELECT DISTINCT
            tab1.*, 
            tab2.*, 
            tab3.manual_forming, tab3.waga_zeliwa, tab3.prefix as pre, 
            tab4.defect defekty_formiernia, tab4.model1_sn, tab4.model2_sn, tab4.model3_sn, tab4.model4_sn, tab4.model5_sn, tab4.model6_sn, tab4.model7_sn, tab4.model8_sn 
        FROM
            `lista_formowania_historia_v2` tab1
        JOIN lista_formowania_v2 tab2 ON
            tab1.produkt_id = tab2.id
        JOIN produkty tab3 ON
            tab2.id_produktu = tab3.produkt_id
        JOIN lista_formowania_formy_v2 tab4 ON tab1.produkt_id = tab4.produkt_id
        WHERE
            tab2.id=
        ''' + str(item['form_id'])
        
    items = query_db(query)
    for i in items:
        # ID
        item['id'] = i['id']

        # Nazwa
        item['product_name'] = i['nazwa_produktu']

        # Forming line
        if i['manual_forming'] == '0':
            item['forming_line'] = 'mechnical'
        else:
            item['forming_line'] = 'manual'
        
        # Forming
        if i['production_stage'] == 'formed':
            item['formed_on'] = str(i['czas'])
            item['formed_by'] = i['operator']

        # Assambling
        if i['production_stage'] == 'assembled':
            item['assambled_on'] = str(i['czas'])
            item['assambled_by'] = i['operator']
            if i['komentarz_rdzeniarnia'] == '':
                item['assambled_comment'] = '-'
            else:
                item['assambled_comment'] = i['komentarz_rdzeniarnia']

        # Casting
        if i['production_stage'] == 'casted':
            item['flooded_on'] = str(i['czas'])
            item['flooded_by'] = i['operator']

        # Knockout
        if i['production_stage'] == 'knockout':
            item['knockout_on'] = str(i['czas'])
            item['knockout_by'] = i['operator']

        # Iron temp
        if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
            item['iron_temp'] = i['temp_zeliwa']

        # Iron temp
        if i['temp_zeliwa'] != 'NULL' or i['temp_zeliwa'] != None:
            item['iron_temp'] = i['temp_zeliwa']

        # Ladle number
        if i['nr_kadzi'] != 'NULL' or i['nr_kadzi'] != None:
            item['ladle_no'] = i['nr_kadzi']

        # Refiled
        if i['filtr'] != 'NULL' or i['filtr'] != None:
            if i['filtr'] == 'nie':
                item['refiled'] = 'no'
            else:
                item['refiled'] = 'yes'          

        # Broken
        if i['broken'] != 'NULL' or i['broken'] != None:
            if i['broken'] == 'nie':
                item['broken'] = 'no'
            else:
                item['broken'] = 'yes'     

        # Sand temperature
        if i['sand_temp'] != 'NULL' or i['sand_temp'] != None:
            item['sand_temp'] = i['sand_temp']  
            
        # Masa odlewu
        item['casting_mass'] = i['waga_zeliwa']

        # Prefix
        item['prefix'] = i['prefix']

        # Czas zalewania
        item['czas_zalewania'] = i['czas_zalewania']

        # Scrap before casting
        if i['repeated'] == '0':
            item['scrap_cast'] = 'no'
        else:
            item['scrap_cast'] = 'yes'

        # Komentarz zalew
        if i['komentarz_zalew'] == '':
            item['comment_casting'] = '-'
        else:
            item['comment_casting'] = i['komentarz_zalew']

        # Komentarz wywoz
        if i['komentarz_wywoz'] == '' or i['komentarz_wywoz'] == None:
            item['komentarz_wywoz'] = '-'
        else:
            item['komentarz_wywoz'] = i['komentarz_wywoz']

        # Defekty rdzeniarnia 
        if i['defekty_rdzeniarnia'] == '' or i['defekty_rdzeniarnia'] == None:
            item['defekty_rdzeniarnia'] = '-'
        else:
            item['defekty_rdzeniarnia'] = i['defekty_rdzeniarnia']

        # Time  
        if i['production_stage'] == 'casted':
            time_of_casting = i['czas']
        if i['production_stage'] == 'cooling':
            time_of_cooling = i['czas']

        # Komentarz biuro odlewni
        if i['komentarz'] == '':
            item['comment_biuro'] = '-'
        else:
            item['comment_biuro'] = i['komentarz']

        # Production stage  
        if i['production_stage'] == 'casted':
            time_of_casting = i['czas']
        if i['production_stage'] == 'cooling':
            time_of_cooling = i['czas']

        # Czas studzenia z bazy
        if i['czas_studzenia'] == '' or i['czas_studzenia'] == None:
            item['czas_studzenia'] = '-'
        else:
            item['czas_studzenia'] = i['czas_studzenia']

        # Czas studzenia z bazy
        if i['trail'] == '' or i['trail'] == None:
            item['trail'] = '-'
        else:
            item['trail'] = i['trail']

        # Defekty formiernia
        if i['defekty_formiernia'] == '' or i['defekty_formiernia'] == None:
            item['defect_forming'] = '-'
        else:
            item['defect_forming'] = i['defekty_formiernia']

    ######################################################################################################
    ############################# KONIEC PĘTLI POBIERANIA DANYCH Z BAZY ##################################
    ######################################################################################################

    # oblicenie czasu 
    try:
        time_of_the_hall = time_of_cooling - time_of_casting
    except UnboundLocalError:
        time_of_the_hall = '-'
    item['time_of_the_hall'] = time_of_the_hall

    # cooling time check
    if time_of_the_hall != '-':
        minuty_na_odlewni = czas_na_minuty(str(time_of_the_hall))
        minuty_chlodzenia = item['czas_studzenia'] * 60
        if minuty_na_odlewni > minuty_chlodzenia:
            item['cooling_time_check'] = 'p'
        else:
            item['cooling_time_check'] = 'n'
    else:
        item['cooling_time_check'] = 'w'

    # Sprawdzenie kluczy w słowniku item
    missing_keys = [
        'sn', 'forming_line', 'formed_on', 'formed_by', 'sand_temp', 'assambled_on',
        'assambled_by', 'assambled_comment', 'flooded_by', 'flooded_on', 'iron_temp',
        'ladle_no', 'refiled', 'broken', 'time_of_the_hall', 'komentarz_wywoz',
        'defekty_rdzeniarnia', 'knockout_on', 'knockout_by', 'czas_zalewania',
        'comment_biuro'
    ]
    for key in missing_keys:
        item.setdefault(key, '-')  

    return item

def defects_data_qa_report(id):
    # query = '''
    #     SELECT
    #         tab1.*, tab2.manual_forming, tab2.waga_zeliwa, tab2.prefix, tab2.customer, tab3.defect
    #     FROM
    #         lista_formowania_v2 tab1
    #     JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id
    #     JOIN lista_formowania_formy_v2 tab3 ON tab1.id = tab3.produkt_id
    #     WHERE tab1.id=
    #     ''' + str(id)

    query = '''
        SELECT tab2.*, tab3.manual_forming, tab3.waga_zeliwa, tab3.prefix, tab4.defect, tab3.customer
        FROM
            `lista_formowania_historia_v2` tab1
        JOIN lista_formowania_v2 tab2 ON
            tab1.produkt_id = tab2.id
        JOIN produkty tab3 ON
            tab2.id_produktu = tab3.produkt_id
        JOIN lista_formowania_formy_v2 tab4 ON tab1.produkt_id = tab4.produkt_id
        WHERE
            tab2.id =
        ''' + str(id)
    
    res = query_db(query)
    item = {}
    for i in res:
        # ID
        item['id'] = i['id']

        # Nazwa
        item['product_name'] = i['nazwa_produktu']        

        # Prefix
        item['prefix'] = i['prefix']

        # Refiled
        if i['filtr'] != 'NULL' or i['filtr'] != None:
            if i['filtr'] == 'nie':
                item['refiled'] = 'no'
            else:
                item['refiled'] = 'yes'          

        # Broken
        if i['broken'] != 'NULL' or i['broken'] != None:
            if i['broken'] == 'nie':
                item['broken'] = 'no'
            else:
                item['broken'] = 'yes'     

        # Scrap before casting
        if i['repeated'] == '0':
            item['scrap_cast'] = 'no'
        else:
            item['scrap_cast'] = 'yes'


        # Trail
        item['trail'] =  i['trail']


        # Scram on foundry
        item['scrap'] =  i['repeated']

        # Customer
        item['customer'] =  i['customer']

        # Customer
        item['czas_zalewania'] =  i['czas_zalewania']


    query = '''
    SELECT DISTINCT
        tab1.model1_sn, tab1.model2_sn, tab1.model3_sn, tab1.model4_sn, tab1.model5_sn, tab1.model6_sn, tab1.model7_sn, tab1.model8_sn, tab1.defect defekty_formiernia, tab2.prefix
    FROM
        `lista_formowania_formy_v2` tab1 LEFT JOIN produkty tab2 ON tab1.prod_id = tab2.produkt_id
    WHERE
        tab1.produkt_id=''' + str(id)
    
    r = query_db(query)

    sns = []
    sns.append(r[0]['model1_sn']) 
    sns.append(r[0]['model2_sn']) 
    sns.append(r[0]['model3_sn']) 
    sns.append(r[0]['model4_sn']) 
    sns.append(r[0]['model5_sn']) 
    sns.append(r[0]['model6_sn']) 
    sns.append(r[0]['model7_sn']) 
    sns.append(r[0]['model8_sn']) 

    sn = r[0]['prefix'] + '-'

    for k in sns:
        if k != None:
            sn = sn + '/' + str(k)

    if sn[0:3] == 'XX-':
        sn = sn[4:]
    else:
        sn = sn[4:]

    item['sn'] = sn

    # Check of idexes
    lists_of_sns = []
    for k,z in item.items():
        lists_of_sns.append(k)

    if 'id' not in lists_of_sns:
        item['id'] = '-'
    if 'sn' not in lists_of_sns:
        item['sn'] = '-'
    if 'refiled' not in lists_of_sns:
        item['refiled'] = '-'
    if 'broken' not in lists_of_sns:
        item['broken'] = '-'

    return item

def logowanie_terminal():
        ip_address = request.remote_addr
        ip_address_mask = ip_address.split('.') 
        allowed_ips = ['192.168.1.250', '192.168.1.100', '192.168.1.1']
        if ip_address in allowed_ips:
            return True
        elif ip_address_mask[2] == '35':
            return True
        else:
            return False
        
def update_sand_temp(arg1, arg2):   
    from influxdb_client import InfluxDBClient
    import urllib3

    org = "hacon"
    token = 'kxO2Sq1DSJBPh48IFJtbE61wyUAVju6NiNAT-2Cu8cy1uKv8DGMzWQtx7NXJ8R1yvcP0IHW1TKtxE5jpE8iVhQ=='

    if arg1 == 'auto':
        query = 'from(bucket:"nodered4")\
        |> range(start: -1m)\
        |> filter(fn:(r) => r._measurement == "temp_miesz_auto")\
        |> filter(fn:(r) => r._field == "value")\
        |> yield(name: "mean")'

    else:
        query = 'from(bucket:"nodered")\
        |> range(start: -1m)\
        |> filter(fn:(r) => r._measurement == "temp_silo_mixer_kile")\
        |> filter(fn:(r) => r._field == "value")\
        |> yield(name: "mean")'
         
    client = InfluxDBClient(url="http://192.168.1.107:8086", token=token, org=org)
    query_api = client.query_api()
    try:
        result = client.query_api().query(org=org, query=query)
    except urllib3.exceptions.ConnectTimeoutError:
        result = []
        
    if len(result) == 0:
        result = 'n/a'
    else:
        result = result

    results = []
    for table in result:
        try:
            for record in table.records:
                results.append((record.get_value()))
        except AttributeError:
                results.append(('n/a'))

    try:
        result = str(round(results[-1], 1))
    except TypeError:
        result = 'n/a'

    query = "UPDATE lista_formowania_v2 SET sand_temp='" + result + "' WHERE id=" + str(arg2)
    query_update(query)

    return True

def unique(items):
    unique_list = []
    for x in items:
        if x not in unique_list:
            unique_list.append(x)
    return unique_list

def check_tag_in_db(tag):
    query = "SELECT * FROM `skrzynie` WHERE tag LIKE '%" + str(tag) + "%' or tag2 LIKE '%" + str(tag) + "%'"
    r = query_db(query)
    if tag == 'BRAK_TAGU_NA_SKRZYNI' or tag == 'BRAK_TAGU_W_BAZIE' or tag == 'AWARIA':
        return True
    else:
        if len(r) == 0:
            return False
        else:
            return True

def add_tag_gate_mf(form_id, produkt_id, model_id, rfid_tag):
    query = "INSERT INTO `rfid_gate_mechform` (`form_id`, `produkt_id`, `model_id`, `rfid_tag`) VALUES (" + str(form_id) + "," + str(produkt_id) + "," +  str(model_id) + ",'" +  str(rfid_tag) + "')"
    query_update(query)
    return True

def defect_n(arg=0) -> int:
    query = "SELECT index_present FROM `parameters`"
    index_present = query_db(query)[0]['index_present']
    if index_present == None:
        index_present = 0

    query = "SELECT * FROM `defects`"
    n = len(query_db(query))
    incremented_number =  index_present + 1
    
    if arg == 0:
        query = "UPDATE `parameters` SET index_present=" + str(incremented_number)
        query_update(query)      
    else:
        incremented_number = n

    return incremented_number



def defects_history(defect_id, operation, user):
    n = len(operation)
    if n >= 250:
        n = n[:250]
    query = "INSERT INTO `defects_history`  (defect_id, operation, user) VALUES(" + str(defect_id) + ",'" + operation + "','" + user + "')"
    query_update(query)
    return True


def tag_modele_history(id, ip, action, tag):
    query = "INSERT INTO `tag_modele_historia` (item_id , ip, action, tag) VALUES(" + str(id) + ",'" + ip + "','" + action + "','" + tag + "')"
    query_update(query)
    return True

def akord_history(operator, ip, action, item_id):
    query = "INSERT INTO `akord_historia` (operator , ip, action, item_id) VALUES('" + operator + "','" + ip + "','" + action + "'," + str(item_id) + ")"
    query_update(query)
    return True


def check_id_in_db(db_name):
    query = "SELECT id as x FROM `" + str(db_name) + "` order by id desc LIMIT 1"
    res = query_db(query)
    try:
        res = res[0]['x']
    except IndexError:
        res = None
    return res

def flasks_knockout():
    res = []
    x = query_db("SELECT distinct produkt_id, czas FROM `lista_formowania_historia_v2` WHERE production_stage = 'knockout' ORDER BY id DESC LIMIT 200;")
    for i in x:
        y = query_db('SELECT DISTINCT produkt_id id, prefix, model1_sn,  model2_sn, model3_sn, model4_sn, model5_sn, model6_sn, model7_sn, model8_sn FROM `lista_formowania_formy_v2` WHERE produkt_id =' + str(i['produkt_id']) + ' ORDER BY id desc')
        z = query_db('SELECT nazwa_produktu, data_zalania, trail, alias FROM `lista_formowania_v2` WHERE id =' + str(i['produkt_id']))
        y[0]['czas'] = i['czas']
        y[0]['nazwa_produktu'] = z[0]['nazwa_produktu']
        y[0]['data_zalania'] = z[0]['data_zalania']
        y[0]['trail'] = z[0]['trail']
        y[0]['alias'] = z[0]['alias']
        res.append(y[0])

    return res

def pa_request(msg):
    webhook_url = "https://prod-111.westeurope.logic.azure.com:443/workflows/fabb7b2b2d8d4a9895624c596782be78/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=r3aW2x5bxnDDeoUDKNYPZ5b7Ocyj9qHD0Nf1kqEHEck"
    
    payload = {
        "table_str": msg
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    response = requests.post(url=webhook_url, headers=headers, data=json.dumps(payload))

    if response.status_code in [200, 202]:
        print("Message sent successfully!")
    else:
        print(f"Failed to send message. Status code: {response.status_code}, Response: {response.text}")

    return True

def generate_table_with_grinding_scores(dane, leader):
    html = '<table border="1">\n'
    html += '  <tr><th>Name</th><th>Function</th><th>Sum</th></tr>\n'
    html += f'  <tr><td>{leader}</td><td>Leader</td><td></td></tr>\n'
    for rekord in dane:
        operator = rekord['operator']
        suma = rekord['suma']
        html += f'  <tr><td>{operator}</td><td>Operator</td><td>{suma}</td></tr>\n'
    html += '</table>'
    return html

def czas_na_minuty(czas_str):
    try:
        godziny, minuty, sekundy = map(int, czas_str.split(":"))
    except ValueError:
        godziny, minuty, sekundy = 24, 0, 0
    suma_minut = godziny * 60 + minuty
    return suma_minut

def roznica_w_minutach(data_str):
    data_wejsciowa = datetime.datetime.strptime(str(data_str), "%Y-%m-%d %H:%M:%S")
    teraz = datetime.datetime.now()
    roznica = teraz - data_wejsciowa
    minuty = round(roznica.total_seconds() / 60)
    return minuty

def check_mafi_sn(sn):
    existing_mafi = query_db("SELECT * FROM mafi WHERE SerialNumber=" + str(sn))
    mafi_count = len(existing_mafi)
    if mafi_count > 0:
        return True
    else:
        return False
    
def zamien_przecinki_na_kropki(arg):
    return re.sub(r'(\d+),(\d+)', r'\1.\2', arg)

def forms_qa_ok():
    query1="SELECT distinct tab1.produkt_id, tab3.nazwa, tab2.prefix, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_formy_v2 tab2 ON tab1.produkt_id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.produkt_id > 28000 AND tab1.production_stage = 'knockout' ORDER BY tab1.id DESC LIMIT 100"
    query1 = query_db(query1)
    items_to_display = []
    for i in query1:
        if i['model1_sn'] != None and i['model2_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn'])
            items_to_display.append(item)

        elif i['model1_sn'] != None and i['model2_sn'] != None and i['model3_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model2_sn']) 
            items_to_display.append(item)

        elif i['model1_sn'] != None and i['model2_sn'] != None and i['model3_sn'] != None and i['model4_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model2_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model3_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model4_sn']) 
            items_to_display.append(item)

        elif i['model1_sn'] != None and i['model2_sn'] != None and i['model3_sn'] != None and i['model4_sn'] == None and i['model5_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model2_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model3_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model4_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model5_sn']) 
            items_to_display.append(item)

        elif i['model1_sn'] != None and i['model2_sn'] != None and i['model3_sn'] != None and i['model4_sn'] == None and i['model5_sn'] != None and i['model6_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model2_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model3_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model4_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model5_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model6_sn']) 
            items_to_display.append(item)

        elif i['model1_sn'] != None and i['model2_sn'] != None and i['model3_sn'] != None and i['model4_sn'] == None and i['model5_sn'] != None and i['model6_sn'] != None and i['model7_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model2_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model3_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model4_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model5_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model6_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model7_sn']) 
            items_to_display.append(item)

        elif i['model1_sn'] != None and i['model2_sn'] != None and i['model3_sn'] != None and i['model4_sn'] == None and i['model5_sn'] != None and i['model6_sn'] != None and i['model7_sn'] != None and i['model8_sn'] == None:
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model1_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model2_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model3_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model4_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model5_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model6_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model7_sn']) 
            items_to_display.append(item)
            item = {}
            item['id'] = i['produkt_id']
            item['nazwa'] = i['nazwa']
            item['sn'] = i['prefix'] + '-' + str(i['model8_sn']) 
            items_to_display.append(item)

  
    if len(items_to_display) > 0:
        query_update("TRUNCATE TABLE `forms_qa_ok_temp`")
        for i in items_to_display:
            query = "INSERT INTO `forms_qa_ok_temp` (`form_id`, `nazwa`, `sn`) VALUES (" + str(i['id']) + ",'" + i['nazwa'] + "','" + i['sn'] + "')"
            query_update(query)
        now = datetime.datetime.now()
        data_aktuzalizcji = now.strftime("%Y-%m-%d %H:%M:%S")
        msg = "Lista form gotowych do wysylki zostala zaktualzazowana."
        result = [msg, data_aktuzalizcji]
        return result
    else:
        msg = "Lista form gotowych jest pusta."
        result = [msg, data_aktuzalizcji]
        return result
    
def generete_serials(id):
    data = query_db("SELECT model1_sn, model2_sn, model3_sn, model4_sn, model5_sn, model6_sn, model7_sn, model8_sn, prefix from lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
    result = []
    for item in data:
        for value in item.values():
            if value is not None:
                result.append(value)
    
    marker = next(x for x in result if not isinstance(x, (int, float)))
    numbers = sorted({str(x) for x in result if isinstance(x, (int, float))})
    serials = [[marker, num] for num in numbers]
    for i in serials:
        sql = f"SELECT * FROM `lista_formowania_sn` WHERE produkt_id={id} AND prefix='{i[0]}' AND sn={i[1]} AND param1='1'"
        result = len(query_db(sql))
        if result != 0:
            serials.remove(i)

    return serials

def generete_form_name(id):
    data = query_db("SELECT nazwa_produktu FROM lista_formowania_v2 WHERE id=" + str(id))
    try:
        name = data[0]['nazwa_produktu']
    except IndexError:
        name = '-'
    return name

def filtruj_items(lista_sn, items):
    # zbiór par (sn, prefix) do porównania
    sn_prefix_set = {
        (str(x['sn']), x['prefix'], x['id'])
        for x in lista_sn
    }

    unikalne = [ item for item in items
         if (item.get('sn'), item.get('Prefix') , item.get('id')) not in sn_prefix_set ]
    
    return unikalne

def remove_duplicates_by_id_mafi(data):
    seen = set()
    result = []

    for item in data:
        key = item["id_mafi"]

        if key not in seen:
            seen.add(key)
            result.append(item)

    return result

def add_sn_based_on_forms(id):

    query = """
    SELECT DISTINCT
    t.produkt_id,
    lf.nazwa_produktu,
    lf.alias,
    lf.trail,
    t.prefix,
    t.czas_dodania,
    t.sn

    FROM (
    SELECT produkt_id, prefix, czas_dodania, model1_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model1_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model2_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model2_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model3_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model3_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model4_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model4_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model5_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model5_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model6_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model6_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model7_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model7_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model8_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model8_sn IS NOT NULL

    ) t
    LEFT JOIN lista_formowania_v2 lf
        ON lf.id = t.produkt_id
    WHERE lf.prefix <> 'XX' 
    AND t.produkt_id =
    """ + str(id) 

    rows = query_db(query)

    for row in rows:
        if row["alias"] == None:
            row["alias"] = 'NULL'
        else:
            row["alias"] = "'" + row["alias"] + "'"

        sql = "SELECT * FROM lista_formowania_sn WHERE produkt_id=" + str(row['produkt_id']) + " AND sn=" + str(row['sn'])
        check = query_db(sql)
        if len(check) > 0:
            continue

        sql = "INSERT INTO lista_formowania_sn (produkt_id, nazwa_produktu, alias, trail, prefix, czas_dodania, sn) VALUES (" + str(row['produkt_id']) + ", '" + row["nazwa_produktu"] + "', " + row["alias"] + ", '" + row["trail"] + "', '" + row["prefix"] + "', '" + str(row["czas_dodania"]) + "', " + str(row["sn"]) + ")"
        query_update(sql)

    return True

def add_sn_based_on_forms_production_orders(id, unique_id_po):

    query = """
    SELECT DISTINCT
    t.produkt_id,
    lf.nazwa_produktu,
    lf.alias,
    lf.trail,
    t.prefix,
    t.czas_dodania,
    t.sn

    FROM (
    SELECT produkt_id, prefix, czas_dodania, model1_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model1_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model2_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model2_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model3_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model3_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model4_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model4_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model5_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model5_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model6_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model6_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model7_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model7_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model8_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model8_sn IS NOT NULL

    ) t
    LEFT JOIN lista_formowania_v2 lf
        ON lf.id = t.produkt_id
    WHERE lf.prefix <> 'XX' 
    AND t.produkt_id =
    """ + str(id) 

    rows = query_db(query)

    for row in rows:
        if row["alias"] == None:
            row["alias"] = 'NULL'
        else:
            row["alias"] = "'" + row["alias"] + "'"

        sql = "SELECT * FROM lista_formowania_sn WHERE produkt_id=" + str(row['produkt_id']) + " AND sn=" + str(row['sn'])
        check = query_db(sql)
        if len(check) > 0:
            continue

        sql = "INSERT INTO lista_formowania_sn (produkt_id, nazwa_produktu, alias, trail, prefix, czas_dodania, sn, mes_po_id) VALUES (" + str(row['produkt_id']) + ", '" + row["nazwa_produktu"] + "', " + row["alias"] + ", '" + row["trail"] + "', '" + row["prefix"] + "', '" + str(row["czas_dodania"]) + "', " + str(row["sn"]) + ", '" + str(unique_id_po) + "')"
        query_update(sql)

    return True

def remove_item_from_sn_list(id):
    sql = "DELETE FROM lista_formowania_sn where produkt_id=" + str(id)
    if query_db_first(sql):
        return True
    else:
        return False

def truncate_snl():
    sql = "TRUNCATE TABLE `lista_formowania_sn`"
    query_update(sql)
    print("Tabela `lista_formowania_sn` wyczyszczona!")
    return True


def fetch_snl():
    query = """
    SELECT DISTINCT
    t.produkt_id,
    lf.nazwa_produktu,
    lf.alias,
    lf.trail,
    t.prefix,
    t.czas_dodania,
    t.sn

    FROM (
    SELECT produkt_id, prefix, czas_dodania, model1_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model1_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model2_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model2_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model3_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model3_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model4_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model4_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model5_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model5_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model6_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model6_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model7_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model7_sn IS NOT NULL

    UNION ALL

    SELECT produkt_id, prefix, czas_dodania, model8_sn AS sn
    FROM lista_formowania_formy_v2
    WHERE model8_sn IS NOT NULL

    ) t
    LEFT JOIN lista_formowania_v2 lf
        ON lf.id = t.produkt_id
    -- WHERE lf.prefix <> 'XX' OR lf.prefix = 'XX'
    ORDER BY t.produkt_id ASC;
    """

    items = query_db(query)
    print("Dane do `lista_formowania_sn` pobrane!")
    return items

def update_snl(rows):
    cur = mysql.new_cursor(dictionary=True)
    for row in rows:
        cur.execute("""
            INSERT INTO lista_formowania_sn (
                produkt_id,
                nazwa_produktu,
                alias,
                trail,
                prefix,
                czas_dodania,
                sn
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            row['produkt_id'],
            row['nazwa_produktu'],
            row['alias'],
            row['trail'],
            row['prefix'],
            row['czas_dodania'],
            row['sn']
        ))

    mysql.connection.commit()
    cur.close()
    print("Tabela `lista_formowania_sn` jest aktualna.")
    return True

#######################################################################################################
############################################### EXEC ##################################################
#######################################################################################################

@app.route("/update_sn_list", methods=['POST', 'GET'])
def update_sn_list():
    truncate_snl()
    items = fetch_snl()
    update_snl(items)
    data = {"message 1": "S/N updated!"}
    return jsonify(data)

@app.route("/rfid_tags", methods=['POST', 'GET'])
def rfid_tags():
        idx = 'tagid' 
        return render_template("rfid_tags.html", idx = idx) 

@app.route("/rfid/<id>", methods=['POST', 'GET'])
def rfid(id):
        tag_id = str(request.form['tag_id'])
        if len(tag_id) < 12:
            flash('Wprowadzone RFID tagu jest za krótkie!')
            return redirect(url_for("rfid_tags")) 

        query1 = "SELECT * FROM `tag_modele` WHERE tag='" +  tag_id + "'"
        query2 = "SELECT * FROM `skrzynie` WHERE tag='" +  tag_id + "' or tag2='" + tag_id + "'"

        result1 = query_db(query1)
        result2 = query_db(query2)
        if len(result1) > 1:
            idx = 'tagid' 
            flash('Podany tag modelu został wprowadzony do bazy więcej niż jeden raz.')
            return render_template("tag_details_patterns.html", tag=result1[0])
        if len(result2) > 1:
            idx = 'tagid' 
            flash('Podany tag skrzyni został wprowadzony do bazy więcej niż jeden raz.')
            return render_template("tag_details_frames.html", tag=result2[0]) 

        result1 = query_db_first(query1)
        result2 = query_db_first(query2)

        if result1 == None and result2 == None:
            if tag_id[:4] == '2022':
                tag_id = tag_id.upper()
                return render_template("tag_add_frame.html", tag=tag_id) 
            else:
                return render_template("tag_add_pattern.html", tag=tag_id) 
        else:
            if result2 == None:
                return render_template("tag_details_patterns.html", tag=result1) 
            else:
                return render_template("tag_details_frames.html", tag=result2)
        
@app.route("/edit_frame/<id>", methods=['POST', 'GET'])
def edit_frame(id):
        ip = request.remote_addr
        nazwa = str(request.form['nazwa'])
        opis = str(request.form['opis'])
        rodzaj = str(request.form['rodzaj'])
        uwagi = str(request.form['uwagi'])
        kr = str(request.form['kr'])
        x = str(request.form['x'])
        y = str(request.form['y'])
        z = str(request.form['z'])

        if rodzaj == '':
            rodzaj = str('0')
        if x == '':
            x = str('0')
        if y == '':
            y = str('0')
        if z == '':
            z = str('0')

        panding_changes=str('1')

        uwagi = str(request.form['uwagi'])
        query ="UPDATE skrzynie SET nazwa='" + nazwa + "',opis='" + opis + "',rodzaj='" + rodzaj + "',x='" + x + "',y='" + y + "',z='" + z + "',kr='" + kr + "',uwagi='" + uwagi + "',pending_changes='" + panding_changes +"' WHERE id=" + id + ""
        query_update(query)
        tag_modele_history(id, ip, 'edycja_skrzyni', nazwa)
        flash('Edycja tagu skrzyni zakończona sukcesem')
        return redirect(url_for("rfid_tags")) 

@app.route("/edit_pattern/<id>", methods=['POST', 'GET'])
def edit_pattern(id):
        ip = request.remote_addr
        nazwa = str(request.form['nazwa'])
        wysokosci = str(request.form['wysokosci'])
        if wysokosci == '':
            wysokosci = '0'
        skrzynia1 = str(request.form['skrzynia1'])
        skrzynia2 = str(request.form['skrzynia2'])
        skrzynia3 = str(request.form['skrzynia3'])
        panding_changes=str('1')
        query ="UPDATE tag_modele SET nazwa='" + nazwa + "',wysokosci='" + wysokosci + "',skrzynia1='" + skrzynia1 + "',skrzynia2='" + skrzynia2 + "',skrzynia3='" + skrzynia3 + "',panding_changes='" + panding_changes  + "' WHERE ID=" + id + ""
        query_update(query)
        tag_modele_history(id, ip, 'edycja_modelu', nazwa)
        flash('Edycja tagu modelu zakończona sukcesem')
        return redirect(url_for("rfid_tags")) 

@app.route("/tag_add_frame/<tag>", methods=['POST'])
def tag_add_frame_commit(tag):
        tag = tag.upper()
        query = "SELECT * FROM skrzynie WHERE tag='" + tag + "'"
        result = query_db_first(query)
        try:
            len(result)
            flash('W bazie znajduje się już skrzynia posiadająca takie id tagu')
            return redirect(url_for("rfid_tags")) 
        except TypeError: 
            tag = tag.upper()
            ip = request.remote_addr
            query1 ="INSERT INTO skrzynie(tag) VALUES('" + str(tag) + "')"
            query2 = "SELECT id FROM skrzynie WHERE tag='" + str(tag) + "' ORDER BY id DESC LIMIT 1"
            query_update(query1)
            ref_tag = query_db_first(query2)
            tag_modele_history(ref_tag['id'], ip, 'dodanie_skrzyni', tag)
            flash(f"Dodawanie tagu skrzyni zakończone sukcesem. Tag id: {ref_tag['id']}.")
            return redirect(url_for("rfid_tags")) 

@app.route("/tag_add_pattern/<tag>", methods=['POST'])
def tag_add_pattern(tag):
        tag = str(tag)
        query = "SELECT * FROM tag_modele WHERE tag='" + str(tag) + "'"
        result = query_db_first(query)
        try:
            len(result)
            flash('W bazie znajduje się już model posiadający takie id tagu')
            return redirect(url_for("rfid_tags")) 
        except TypeError: 
            tag = tag.upper()
            ip = request.remote_addr
            query1 ="INSERT INTO tag_modele(tag) VALUES('" + str(tag) + "')"
            query2 = "SELECT id FROM tag_modele WHERE TAG='" + str(tag) + "' ORDER BY id DESC LIMIT 1"
            query_update(query1)
            ref_tag = query_db_first(query2)
            tag_modele_history(ref_tag['id'], ip, 'dodanie_modelu', tag)
            flash(f"Dodawanie tagu modelu zakończone sukcesem. Tag id: {ref_tag['id']}.")
            return redirect(url_for("rfid_tags")) 

@app.route("/tag_frames_search", methods=['GET'])
def tag_frames_search():
    return render_template("tag_frames_search.html") 

@app.route("/tag_frame", methods=['POST', 'GET'])
def tag_frame():
        id = str(request.form['id'])
        query = "SELECT * FROM `skrzynie` WHERE id='" +  id + "'"
        result = query_db_first(query)
        if result == None:
            flash('Podanego id nie ma w bazie skrzyń')
            return redirect("tag_frames_search")
        else:
            return render_template("tag_details_frames.html", tag=result)

def filter_items_quality(items, prefix_arg, sn_arg):
    filtered = []
    
    for item in items:
        prefix = item.get("prefix")
        sn = item.get("sn")
        # zostaw jeśli oba None
        if prefix is None and sn is None:
            filtered.append(item)
            continue
        # zostaw jeśli prefix-sn pasuje
        if prefix == prefix_arg and sn == sn_arg:
            filtered.append(item) 
            continue 
        # w innym przypadku – pomijamy (usuwamy)
    return filtered

# Funkcja do zapisywania danych do tabeli casting_report_tmp w MySQL

def save_castings_to_mysql(data_list):
    try:
        cur = mysql.new_cursor()
        cur.execute("TRUNCATE TABLE casting_report_tmp")

        sql = """
        INSERT INTO casting_report_tmp (
            id,
            sn,
            prefix,
            product_name,
            forming_line,
            iron_temp,
            ladle_no,
            refiled,
            broken,
            sand_temp,
            casting_mass,
            czas_zalewania,
            scrap_cast,
            scrap,
            comment_casting,
            komentarz_wywoz,
            defekty_rdzeniarnia,
            comment_biuro,
            czas_studzenia,
            trail,
            alias,
            defect_forming,
            formed_on,
            formed_by,
            assambled_on,
            assambled_by,
            assambled_comment,
            flooded_on,
            flooded_by,
            time_of_the_hall,
            cooling_time_check,
            knockout_on,
            knockout_by,
            data_defectu,
            decyzja,
            wada
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s
        )
        """

        rows = []

        for item in data_list:
            rows.append((
                item.get("id"),
                item.get("sn"),
                clean_value(item.get("prefix")),
                clean_value(item.get("product_name")),
                clean_value(item.get("forming_line")),
                item.get("iron_temp"),
                clean_value(item.get("ladle_no")),

                yes_no_to_bool(item.get("refiled")),
                yes_no_to_bool(item.get("broken")),

                to_float(item.get("sand_temp")),
                item.get("casting_mass"),
                item.get("czas_zalewania"),

                yes_no_to_bool(item.get("scrap_cast")),
                item.get("scrap"),

                clean_value(item.get("comment_casting")),
                clean_value(item.get("komentarz_wywoz")),
                clean_value(item.get("defekty_rdzeniarnia")),
                clean_value(item.get("comment_biuro")),

                item.get("czas_studzenia"),
                clean_value(item.get("trail")),
                clean_value(item.get("alias")),
                clean_value(item.get("defect_forming")),

                clean_datetime(item.get("formed_on")),
                clean_value(item.get("formed_by")),

                clean_datetime(item.get("assambled_on")),
                clean_value(item.get("assambled_by")),
                clean_value(item.get("assambled_comment")),

                clean_datetime(item.get("flooded_on")),
                clean_value(item.get("flooded_by")),

                timedelta_to_mysql_time(item.get("time_of_the_hall")),

                clean_value(item.get("cooling_time_check")),

                clean_datetime(item.get("knockout_on")),
                clean_value(item.get("knockout_by")),

                clean_datetime(item.get("data_defectu")),

                clean_value(item.get("decyzja")),
                clean_value(item.get("wada"))
            ))

        cur.executemany(sql, rows)
        mysql.connection.commit()
        print(f"Zapisano {cur.rowcount} rekordów do casting_report_tmp.")

        return True

    except Exception as error:
        print(f"Błąd MySQL: {error}")

        if mysql.connection:
            mysql.connection.rollback()

        return False

    except Exception as error:
        print(f"Błąd: {error}")

        if mysql.connection:
            mysql.connection.rollback()

        return False
    

    finally:
        if cur:
            cur.close()

        if mysql.connection and mysql.connection.is_connected():
            mysql.connection.close()

def clean_value(value):
    if value is None:
        return None

    if isinstance(value, str) and value.strip() == "-":
        return None

    return value


def yes_no_to_bool(value):
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip().lower()

        if value == "yes":
            return 1

        if value == "no":
            return 0

        if value == "-":
            return None

    return value


def to_float(value):
    if value is None or value == "-":
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def clean_datetime(value):
    if value is None or value == "-":
        return None

    if isinstance(value, datetime.datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.datetime.strptime(
                value,
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            return None

    return None


def timedelta_to_mysql_time(value):
    if value is None or value == "-":
        return None

    if isinstance(value, datetime.timedelta):
        total_seconds = int(value.total_seconds())

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        return f"{hours:02}:{minutes:02}:{seconds:02}"

    # Jeżeli z jakiegoś powodu przyjdzie już string TIME
    if isinstance(value, str):
        return value

    return None

def save_open_orders_mes_to_mysql(from_date, to_date):
    # -------------------------
    # MSSQL
    # -------------------------
    mssql_conn = get_mssql_connection()
    cur = mssql_conn.cursor()

    cur.execute("""
        EXEC dbo.OpenOrdersMES
            @FromDate = ?,
            @ToDate = ?,
            @LinePerUnit = 1;
    """, from_date, to_date)

    while cur.description is None:
        if not cur.nextset():
            raise RuntimeError("Procedura OpenOrdersMES nie zwróciła danych")

    rows = cur.fetchall()

    columns = [col[0] for col in cur.description]

    # df = pd.DataFrame(
    #     [tuple(row) for row in rows],
    #     columns=columns
    # )

    # -------------------------
    # MySQL
    # -------------------------

    conn = mysql.connection
    mysql_cursor = conn.cursor()

    sql = """
        INSERT INTO open_orders_sap (
            unique_id,
            nr_oferty,
            nr_dok,
            obj_type,
            nr_zam_klienta,
            kod_ph,
            ph,
            item_index,
            grupa_t,
            opis_nazwa,
            obca,
            ilosc,
            waga_jedn,
            waga_calk,
            nr_kat,
            nr_rys,
            nr_bud,
            nr_poz,
            nr_still,
            nr_seq,
            tyg_wysylki,
            tyg_wypr,
            data_dokakt,
            data_dostawy,
            data_wysylki,
            data_prod,
            data_mal,
            data_obr,
            data_szlif,
            data_wybij,
            data_form
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s
        )
    """

    data = [tuple(row) for row in rows]

    try:
        mysql_cursor.execute("DELETE FROM open_orders_sap")

        mysql_cursor.executemany(sql, data)

        conn.commit()

        print(f"Zapisano {len(data)} rekordów do open_orders_sap")

    except Exception as e:
        conn.rollback()
        print(f"Błąd MySQL: {e}")
        raise

    finally:
        mysql_cursor.close()
        cur.close()
        mssql_conn.close()

    return True

def get_shifted_dates(prev, next):
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Klasa timedelta w Pythonie nie obsługuje miesięcy (maksymalna jednostka to tygodnie/dni),
    # dlatego stosuje się przybliżenie w dniach (np. 1 miesiąc = 30 dni, 3 miesiące = 90 dni):
    first_date = today - timedelta(days=prev)
    second_date = today + timedelta(days=next)

    fmt = "%Y-%m-%d %H:%M:%S"
    return first_date.strftime(fmt), second_date.strftime(fmt)


#######################################################################################################
####################################### Obsługa produkcji #############################################
#######################################################################################################

@app.route("/", methods=['POST', 'GET'])
def login():
    try:
        if request.method == 'POST':
            session.pop('user_id', None)
            username = request.form['username']
            password = request.form['password']
            user = [x for x in users if x.username == username][0]
            if user and user.password == password:
                session['user_id'] = user.id
                session['user'] = user.username

                if 'formiernia' in user.username:
                    return redirect(url_for('forming_operator_view'))
                elif 'rdzeniarnia' in user.mode :
                    return redirect(url_for('cores_operator_view'))
                elif 'odlewnia' in user.mode:
                    return redirect(url_for('foundry_operator_view2'))
                elif 'wybijanie' in user.mode:
                    return redirect(url_for('knockout_operator_view'))
                # elif 'magda' in user.username:
                #     return redirect(url_for('forming_list'))
                elif 'forman' in user.mode:
                    return redirect(url_for('forming_operator_m_view'))
                elif 'dash' in user.username:
                    return redirect(url_for('dashboard'))
                elif 'wysylka' in user.mode:
                    return redirect(url_for('shipment'))    
                elif 'kontrola' in user.mode or 'mechaniczny' in user.mode:
                    return redirect(url_for('quality'))
                elif 'mafi' in user.mode:
                    return redirect(url_for('mafi_shipment'))
                elif 'szlifiernia_akordy' in user.mode:
                    return redirect(url_for('grinding_sheefts'))            
                elif 'biuro' in user.mode:
                    return redirect(url_for('forming'))       
                elif 'grinding' in user.mode:
                    return redirect(url_for('grinding'))       
                elif 'kontrszlif' in user.mode:
                    return redirect(url_for('kontrszlif'))    
                else:
                    flash(f'Wrong password or username.')
                    return redirect(url_for('login'))
            else:
                flash(f'Wrong password or username.')
                return redirect(url_for('login'))
        return render_template('login.html')
    except IndexError: 
        flash(f'Wrong password or username.')
        return redirect(url_for('login'))

@app.route('/logout') 
def logout(): 
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/logout_office') 
def logout_office(): 
    session.pop('user_id', None)
    flash(f'xxxx')
    return redirect(url_for('login'))

@app.route("/forming", methods=['POST', 'GET'])
@login_required(mode='biuro')
@ip_required('192.168.1.0/24', '192.168.170.0/24', '192.168.130.0/24')
def forming():
    today = datetime.date.today()
    include_undated = request.args.get('include_undated') == '1'
    show_all_records = request.args.get('show_all_records') == '1'
    try:
        min_value = request.args.get('min_date', (today - timedelta(days=7)).isoformat())
        max_value = request.args.get('max_date', (today + timedelta(days=21)).isoformat())
        min_date = datetime.date.fromisoformat(min_value) if min_value else None
        max_date = datetime.date.fromisoformat(max_value) if max_value else None
        if min_date and max_date and min_date > max_date:
            raise ValueError('Reversed range')
        end_date = max_date + timedelta(days=1) if max_date else None
    except (ValueError, OverflowError):
        abort(400, description='Nieprawidłowy zakres dat formowania.')
    query1="""
        SELECT
            *
        FROM
            lista_formowania_v2 tab1
        LEFT JOIN produkty tab2 ON
            tab1.id_produktu = tab2.produkt_id
        WHERE
            tab1.item_status = 'new'
        ORDER BY
            tab1.id
        DESC
        LIMIT 200
    """
    query2 = query_db("SELECT produkt_id, nazwa, manual_forming FROM produkty WHERE item_status='active' order by nazwa desc")
    nowe = query_db(query1)
    # Fetch order IDs for the displayed forming positions in one query.
    mes_po_ids = {}
    if nowe:
        product_ids = list({item['id'] for item in nowe})
        cursor = mysql.new_cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT DISTINCT produkt_id, TRIM(mes_po_id) AS mes_po_id "
                "FROM lista_formowania_sn WHERE produkt_id IN ("
                + ','.join(['%s'] * len(product_ids)) + ") "
                "AND mes_po_id IS NOT NULL AND TRIM(mes_po_id) <> ''",
                product_ids)
            for row in cursor.fetchall():
                mes_po_ids.setdefault(row['produkt_id'], set()).add(row['mes_po_id'])
        finally:
            cursor.close()
    for i in nowe:
        i['mes_po_ids'] = ', '.join(sorted(mes_po_ids.get(i['id'], [])))
        sn = generete_serials(i['id'])
        result = ['-'.join(item) for item in sn]
        result = " , ".join(result)
        i['sn'] = result
    repeated = query_db("SELECT * FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.item_status = 'formed' AND tab1.alias is not null ORDER BY tab1.id DESC LIMIT 200")
    for i in repeated:
        sn = generete_serials(i['id'])
        result = ['-'.join(item) for item in sn]
        result = " , ".join(result)
        i['sn'] = result

    date_minus, date_plus = get_shifted_dates(7, 30)
    # sql = f"SELECT DISTINCT tab1.unique_id, tab1.nr_oferty, tab1.nr_dok, tab1.obj_type, tab1.nr_zam_klienta, tab1.kod_ph, tab1.ph, tab1.item_index, tab1.grupa_t, tab1.opis_nazwa, tab1.obca, tab1.ilosc, tab1.waga_jedn, tab1.waga_calk, tab1.nr_kat, tab1.nr_rys, tab1.nr_bud, tab1.nr_poz, tab1.nr_still, tab1.nr_seq, tab1.tyg_wysylki, tab1.tyg_wypr, tab1.data_dokakt, tab1.data_dostawy, tab1.data_wysylki, tab1.data_prod, tab1.data_mal, tab1.data_obr, tab1.data_szlif, tab1.data_wybij, tab1.data_form, tab1.updated_at, tab2.index_odlew, tab2.nazwa_odlew FROM open_orders_sap tab1 JOIN sap_mes_relation tab2 ON tab1.item_index = tab2.item_index WHERE data_prod BETWEEN '{date_minus}' AND '{date_plus}' ORDER BY tab1.data_prod DESC"
    # Rank before date filtering so each order row keeps the same serial.
    sql = f"SELECT tab1.id AS production_order_id, tab1.unique_id, tab1.nr_oferty, tab1.nr_dok, tab1.obj_type, tab1.nr_zam_klienta, tab1.kod_ph, tab1.ph, tab1.item_index, tab1.grupa_t, tab1.opis_nazwa, tab1.obca, tab1.ilosc, tab1.waga_jedn, tab1.waga_calk, tab1.nr_kat, tab1.nr_rys, tab1.nr_bud, tab1.nr_poz, tab1.nr_still, tab1.nr_seq, tab1.tyg_wysylki, tab1.tyg_wypr, tab1.data_dokakt, tab1.data_dostawy, tab1.data_wysylki, tab1.data_prod, tab1.data_mal, tab1.data_obr, tab1.data_szlif, tab1.data_wybij, tab1.data_form, tab1.updated_at, tab2.index_odlew, tab2.nazwa_odlew, sn.id AS assigned_serial_id, sn.prefix AS assigned_prefix, sn.sn AS assigned_sn, EXISTS (SELECT 1 FROM lista_formowania_historia_v2 history WHERE history.produkt_id = sn.produkt_id AND history.production_stage = 'formed' AND (history.sn IS NULL OR (history.sn = sn.sn AND history.prefix = sn.prefix))) AS has_formed_history, EXISTS (SELECT 1 FROM lista_formowania_historia_v2 history WHERE history.produkt_id = sn.produkt_id AND history.production_stage = 'knockout' AND (history.sn IS NULL OR (history.sn = sn.sn AND history.prefix = sn.prefix))) AS has_knockout_history, EXISTS (SELECT 1 FROM lista_formowania_historia_v2 history WHERE history.produkt_id = sn.produkt_id AND history.production_stage IN ('grinding', 'grinding-repaired') AND (history.sn IS NULL OR (history.sn = sn.sn AND history.prefix = sn.prefix))) AS has_grinding_history, EXISTS (SELECT 1 FROM lista_formowania_historia_v2 history WHERE history.produkt_id = sn.produkt_id AND history.production_stage IN ('qa_ok', 'qa_nok') AND (history.sn IS NULL OR (history.sn = sn.sn AND history.prefix = sn.prefix))) AS has_qa_history, EXISTS (SELECT 1 FROM lista_formowania_historia_v2 history WHERE history.produkt_id = sn.produkt_id AND history.production_stage = 'shipment' AND (history.sn IS NULL OR (history.sn = sn.sn AND history.prefix = sn.prefix))) AS has_shipment_history, (SELECT MAX(history.czas) FROM lista_formowania_historia_v2 history WHERE history.produkt_id = sn.produkt_id AND history.production_stage = 'casted' AND (history.sn IS NULL OR (history.sn = sn.sn AND history.prefix = sn.prefix))) AS data_zalania FROM (SELECT orders.*, ROW_NUMBER() OVER (PARTITION BY unique_id ORDER BY id) AS serial_position FROM open_orders_sap orders) tab1 LEFT JOIN (SELECT relation.*, ROW_NUMBER() OVER (PARTITION BY item_index ORDER BY index_odlew, nazwa_odlew) AS relation_position FROM sap_mes_relation relation) tab2 ON tab1.item_index = tab2.item_index AND tab2.relation_position = 1 LEFT JOIN (SELECT serials.*, ROW_NUMBER() OVER (PARTITION BY mes_po_id ORDER BY id) AS serial_position FROM lista_formowania_sn serials WHERE serials.sn IS NOT NULL) sn ON sn.mes_po_id = tab1.unique_id AND sn.serial_position = tab1.serial_position ORDER BY tab1.data_prod DESC"
    if not show_all_records:
        sql = sql.replace("SELECT tab1.id AS production_order_id, ", "SELECT DISTINCT ", 1)
    date_conditions, date_params = [], []
    if min_date:
        date_conditions.append('tab1.data_form >= %s')
        date_params.append(min_date.isoformat())
    if end_date:
        date_conditions.append('tab1.data_form < %s')
        date_params.append(end_date.isoformat())
    date_condition = ' AND '.join(date_conditions) if date_conditions else 'tab1.data_form IS NOT NULL'
    if include_undated:
        date_condition = '(tab1.data_form IS NULL OR (' + date_condition + '))'
    sql = sql.replace('ORDER BY tab1.data_prod DESC', 'WHERE ' + date_condition + ' ORDER BY tab1.data_prod DESC')
    cursor = mysql.new_cursor(dictionary=True)
    try:
        cursor.execute(sql, date_params)
        production_orders = cursor.fetchall()
    finally:
        cursor.close()
    #production_orders = query_db("SELECT tab1.*, tab2.*, tab3.prefix, tab3.sn FROM open_orders_sap tab1 JOIN sap_mes_relation tab2 ON tab1.item_index = tab2.item_index RIGHT JOIN lista_formowania_sn tab3 ON tab3.mes_po_id = tab1.unique_id ORDER BY tab1.data_prod DESC;")
    update_time = query_db("SELECT MAX(updated_at) AS updated_at FROM open_orders_sap")
    try:
        update_time=update_time[0]['updated_at']
    except IndexError:
        update_time =  '1970-01-01 00:00:00'
    return render_template("forming.html", items=nowe, products=query2, repeated=repeated, production_orders=production_orders, update_time=update_time,
                           min_forming_date=min_date.isoformat() if min_date else '',
                           max_forming_date=max_date.isoformat() if max_date else '',
                           include_undated=include_undated, show_all_records=show_all_records)

@app.route("/display_po_item_details/<id>", methods=['GET'])
def display_po_item_details(id):
    sql = f"SELECT prefix, sn FROM lista_formowania_sn WHERE mes_po_id ='{id}'"
    result = query_db(sql)
    return jsonify(result)
      

@app.route("/update_production_orders", methods=['GET'])
def update_production_orders():
    save_open_orders_mes_to_mysql('2024-01-01', '2030-01-01')
    return redirect(request.referrer)

@app.route("/shipment", methods=['GET'])
def shipment():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        res = query_db("SELECT * FROM `shipments` WHERE status='active'")
        return render_template("shipment.html", items=res) 
    

@app.route("/edit_shipment/<id>", methods=['POST', 'GET'])
def edit_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        res = query_db('SELECT nr_wysylki x, mode, klient FROM `shipments` WHERE id=' + str(id)) 
        nr_wys = res[0]['x']
        mode = res[0]['mode']
        klient = res[0]['klient']
        #items = query_db("SELECT * FROM `forms_qa_ok_temp`")
        items = query_db("SELECT tab2.nazwa_produktu nazwa, tab1.produkt_id id, CONCAT(tab1.prefix, '-', tab1.sn) sn, tab3.customer, tab2.alias FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.production_stage = 'qa_ok' AND tab3.customer = '" + klient + "'")
        
        for i in items:
            try:
                prefix, sn = (i['sn']).split('-')
            except TypeError:
                prefix = 'XX'
                sn = '00'
            except IndexError:
                prefix = 'XX'
                sn = '00'

            sql = f"SELECT param1 FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn={sn}"
            counter = query_db(sql)[0]['param1']
            if counter != '0':
                items.remove(i)

        ships = query_db("SELECT tab1.*, tab2.alias FROM `shipments_items` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.form_id = tab2.id WHERE status='active' AND ship_id=" + str(id))

    return render_template("edit_shipment.html", items=items, ships=ships, ship_id=id, nr_wys=nr_wys, mode=mode) 

@app.route("/add_shipment", methods=['POST'])
def add_shipment():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        operator = session['user']
        klient = str(request.form['klient'])
        nr_wysylki = str(request.form['nr_wysylki'])
        nr_wysylki = nr_wysylki.replace("'", "")
        numer1 = klient + '-' + nr_wysylki
        if check_nr_shipment(numer1):
            flash(f'Wprowadzony nr wysyłki {numer1} jest już dodany')
            return redirect(request.referrer)            

        if check_format_shipment(nr_wysylki):
            nr_wysylki = klient + '-' + nr_wysylki
            query = "INSERT INTO `shipments` (`status`, `nr_wysylki`, `klient`, `operator`) VALUES ('active', '" + nr_wysylki + "','" + klient + "','" + operator + "')"
            query_update(query)
            operator = session['user']
            ship_id = query_db("SELECT id FROM `shipments` ORDER BY id DESC LIMIT 1")
            ship_id = ship_id[0]['id']
            history_shipment(ship_id, 'NULL', 'Shipment added', operator)

        else:
            flash(f'Numer wysyłki został podany w złym formacie.')
            return redirect(request.referrer)
        
        return redirect(request.referrer)

@app.route("/add_item_shipment/<id>", methods=['GET'])
def add_item_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        item_id, ship_id, item_sn = id.split("_")
        query = "SELECT tab2.nazwa_produktu nazwa, tab1.produkt_id id, tab2.id, CONCAT(tab1.prefix, '-', tab1.sn) sn FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.production_stage = 'qa_ok' AND tab1.produkt_id=" + str(item_id)
        res = query_db(query)[0]
        operator = session['user']
        query = "SELECT * FROM `shipments_items` WHERE status='active' AND sn='" + item_sn + "' AND form_id=" + str(res['id']) 
        check = query_db(query)
        if len(check) == 0:
            query = "INSERT INTO `shipments_items`(`ship_id`, `product`, `form_id`, `sn`, `operator`) VALUES (" + str(ship_id) + ",'" + res['nazwa'] + "'," + str(res['id']) + ",'" + item_sn + "','" + operator + "')"
            query_update(query)
            prefix, sn = item_sn.split("-")
            history_qa(res['id'], sn, prefix, 'shimpment', operator)
            history_shipment(ship_id, item_sn, 'Shipment item added', operator)
            return redirect(request.referrer)
        else:
            flash(f"Przeciwwaga S/N {item_sn} została już dodana do wysyłki!")
            return redirect(request.referrer)


@app.route("/del_item_shipment/<id>", methods=['GET'])
def del_item_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        operator = session['user']
        query = "SELECT * FROM shipments_items WHERE id=" + str(id)
        res = query_db(query)[0]
        form_id = res['form_id']
        prefix, sn = res['sn'].split("-")
        history_qa(form_id, sn, prefix, 'shimpment-removed', operator)
        query = "UPDATE `shipments_items`SET status = 'inactive' WHERE id=" + str(id)
        query_update(query)
        ship_id = query_db("SELECT ship_id FROM `shipments_items` WHERE id=" + str(id))
        ship_id = ship_id[0]['ship_id']
        history_shipment(ship_id, res['sn'], 'Shipment item deleted', operator)
        return redirect(request.referrer)

@app.route("/check_socket/<id>", methods=['GET'])
def check_socket(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        operator = session['user']
        query = "SELECT * FROM shipments_items WHERE id=" + str(id)
        res = query_db(query)[0]
        form_id = res['form_id']
        socket = res['socket']
        prefix, sn = res['sn'].split("-")

        if socket == 0:
            sql = "UPDATE `shipments_items`SET socket = '1' WHERE id=" + str(id)
            query_update(sql)
            history_qa(form_id, sn, prefix, 'socket-check-ok', operator)
            ship_id = query_db("SELECT ship_id FROM `shipments_items` WHERE id=" + str(id))
            ship_id = ship_id[0]['ship_id']
            history_shipment(ship_id, res['sn'], 'socket-check-ok', operator)
            return redirect(request.referrer)
        
        elif socket == 1:
            sql = "UPDATE `shipments_items`SET socket = '0' WHERE id=" + str(id)
            query_update(sql)
            history_qa(form_id, sn, prefix, 'socket-check-nok', operator)
            ship_id = query_db("SELECT ship_id FROM `shipments_items` WHERE id=" + str(id))
            ship_id = ship_id[0]['ship_id']
            history_shipment(ship_id, res['sn'], 'socket-check-nok', operator)
            return redirect(request.referrer)
        
        else:
            flash(f'Nie można zmienić statusu gniazda zaczpu dla przeciwwagi S/N {res["sn"]}.')
            return redirect(request.referrer)

@app.route("/remove_shipment/<id>", methods=['POST'])
def remove_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        query = "SELECT mode FROM `shipments` WHERE id=" + str(id)
        res = query_db(query)[0]['mode']
        query = "SELECT * FROM `shipments_items` WHERE ship_id=" + str(id) + " AND status='active'"
        n = len(query_db(query))
        if res == 'closed':
            flash(f'Nie można usunąć wysyłki posiadjącej status zmaknięta (closed)!')
            return redirect(request.referrer)
        elif n > 0:
            flash(f'Nie można usunąć wysyłki posiadjącej przypisane przeciwwagi. Usuń przeciwwagi z wysyłki!')
            return redirect(request.referrer)
        else:
            query = "UPDATE `shipments` SET status='inactive' WHERE id=" + str(id)
            query_update(query)
            query = "UPDATE `shipments_items` SET status='inactive' WHERE ship_id=" + str(id)
            query_update(query)
            operator = session['user']
            history_shipment(id, 'NULL', 'Shipment deleted', operator)
            return redirect(request.referrer)

@app.route("/close_shipment/<id>", methods=['POST'])
def close_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    elif session['user_id'] not in (18,23,36,37,38,39):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        results = query_db("SELECT * FROM `shipments_items` WHERE ship_id="+ str(id))
        if len(results) == 0:
            flash(f'Nie można zamknąć wysyłki która nie ma przypisanych przciwwag.')
            return redirect(request.referrer)
        query_update("UPDATE shipments SET mode='closed' WHERE id="+ str(id))
        operator = session['user']
        history_shipment(id, 'NULL', 'Shipment closed', operator)
        return redirect(request.referrer)

@app.route("/search_shipment", methods=['POST'])
def search_shimpemt_item():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item = str(request.form['search'])
        item = item.replace("'", "")
        items = query_db("SELECT tab1.* FROM `shipments` tab1 LEFT JOIN `shipments_items` tab2 ON tab1.id = tab2.ship_id WHERE tab2.status='active' AND tab2.sn='" + item + "'")
        return render_template("shipment.html", items=items) 

##############################################################################################
    
@app.route("/mafi", methods=['POST', 'GET'])
@login_required(mode='biuro')
@ip_required('192.168.1.0/24', '192.168.170.0/24', '192.168.130.0/24')
def mafi():
    query= "SELECT * FROM mafi WHERE active='1'"
    query = query_db(query)
    return render_template("mafi.html", items=query) 
    
@app.route("/delete_mafi/<id>", methods=['POST', 'GET'])
def delete_mafi(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query= "UPDATE mafi SET active='0' WHERE id=" + str(id)
        query_update(query)
        return redirect(url_for('mafi'))
    
@app.route("/edit_mafi/<id>", methods=['POST', 'GET'])
def edit_mafi(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sn =  str(request.form['sn']).strip()
        udzwig =  str(request.form['udzwig']).strip()
        mandate =  str(request.form['mandate']).strip()
        if len(mandate) == 0:
            mandate = '1900-01-01'
        cond =  str(request.form['cond']).strip()
        last_inspection =  str(request.form['last_inspection']).strip()
        if len(last_inspection) == 0:
            last_inspection = '1900-01-01'
        inspector =  str(request.form['inspector']).strip()
        next_insp =  str(request.form['next_insp']).strip()
        if len(next_insp) == 0:
            next_insp = '1900-01-01'
        status =  str(request.form['status']).strip()
        rfid =  str(request.form['rfid']).strip()

        query = "UPDATE mafi SET SerialNumber='" + sn + "', CarryingCapacity='" + udzwig + "', ManufacturedOn='" + mandate + "', Cond='" + cond + "', LastInspection='" + last_inspection + "', InspectedBy='" + inspector + "', NextInspection='" + next_insp + "', Status='" + status + "', RFID_1='" + rfid + "' WHERE id=" + str(id)
        query_update(query)

        return redirect(url_for('mafi'))
    
@app.route("/add_mafi", methods=['POST', 'GET'])
def add_mafi():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sn =  str(request.form['sn']).strip()
        check_mafi_sn(sn)
        if check_mafi_sn(sn):
            query= "SELECT * FROM mafi WHERE active='1'"
            query = query_db(query)
            flash(f'Powtórzony numer seryjny mafi !!!')
            return render_template("mafi.html", items=query) 
        else:
            udzwig =  str(request.form['udzwig']).strip()
            if len(udzwig) == 0:
                udzwig = '0'
            mandate =  str(request.form['mandate']).strip()
            if len(mandate) == 0:
                mandate = '1900-01-01'
            cond =  str(request.form['cond']).strip()
            last_inspection =  str(request.form['last_inspection']).strip()
            if len(last_inspection) == 0:
                last_inspection = '1900-01-01'
            inspector =  str(request.form['inspector']).strip()
            next_insp =  str(request.form['next_insp']).strip()
            if len(next_insp) == 0:
                next_insp = '1900-01-01'
            status =  str(request.form['status']).strip()
            rfid =  str(request.form['rfid']).strip()

            query = "INSERT INTO mafi(SerialNumber, CarryingCapacity, ManufacturedOn, Cond, LastInspection, InspectedBy, NextInspection, Status, RFID_1) VALUES('" + sn + "','" + udzwig + "','" + mandate + "','" + cond + "','" + last_inspection + "','" + inspector + "','" + next_insp + "','" + status + "','" + rfid + "')"
            query_update(query)

            return redirect(url_for('mafi'))
    
@app.route("/forming_list", methods=['POST', 'GET'])
def forming_list():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT nazwa FROM produkty")
        query2 = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.id_model1 id_model1, tab1.id_model2 id_model2, tab1.id_model3 id_model3, tab1.id_model4 id_model4, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'new' ORDER BY tab1.id DESC LIMIT 200")
        return render_template("forming_list.html", items = query, formings = query2) 

@app.route("/add_forming_list", methods=['POST', 'GET'])
def add_forming_list():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        try:
            items_to_add_to_forming_list = []
            req = request.args['roles']
            x = req.split("<break>")
            query = query_db("SELECT nazwa FROM produkty")
            return render_template("forming_list.html", items = query) 
        except KeyError: 
            query = query_db("SELECT nazwa FROM produkty")
            return render_template("forming_list.html", items = query) 
        
#######################################################################################

@app.route("/mafi_shipment", methods=['POST', 'GET'])
def mafi_shipment():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query= "SELECT * FROM mafi WHERE active='1'"
        query = query_db(query)
        return render_template("mafi_shipment.html", items=query) 
    
@app.route("/delete_mafi_shipment/<id>", methods=['POST', 'GET'])
def delete_mafi_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query= "UPDATE mafi SET active='0' WHERE id=" + str(id)
        query_update(query)
        return redirect(url_for('mafi_shipment'))

@app.route("/delete_claim/<id>", methods=['POST', 'GET'])
def delete_claim(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query= "UPDATE reklamacje SET status='inactive' WHERE id=" + str(id)
        query_update(query)
        operator = session['user']
        history_claims(id, "deleted claim", operator)
        return redirect(url_for('claims'))
    
@app.route("/edit_mafi_shipment/<id>", methods=['POST', 'GET'])
def edit_mafi_shipment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sn =  str(request.form['sn']).strip()
        udzwig =  str(request.form['udzwig']).strip()
        mandate =  str(request.form['mandate']).strip()
        if len(mandate) == 0:
            mandate = '1900-01-01'
        cond =  str(request.form['cond']).strip()
        last_inspection =  str(request.form['last_inspection']).strip()
        if len(last_inspection) == 0:
            last_inspection = '1900-01-01'
        inspector =  str(request.form['inspector']).strip()
        next_insp =  str(request.form['next_insp']).strip()
        if len(next_insp) == 0:
            next_insp = '1900-01-01'
        status =  str(request.form['status']).strip()
        rfid =  str(request.form['rfid']).strip()

        query = "UPDATE mafi SET SerialNumber='" + sn + "', CarryingCapacity='" + udzwig + "', ManufacturedOn='" + mandate + "', Cond='" + cond + "', LastInspection='" + last_inspection + "', InspectedBy='" + inspector + "', NextInspection='" + next_insp + "', Status='" + status + "', RFID_1='" + rfid + "' WHERE id=" + str(id)
        query_update(query)

        return redirect(url_for('mafi_shipment'))
    
@app.route("/add_mafi_shipment", methods=['POST', 'GET'])
def add_mafi_shipment():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sn =  str(request.form['sn']).strip()
        udzwig =  str(request.form['udzwig']).strip()
        if len(udzwig) == 0:
            udzwig = '0'
        mandate =  str(request.form['mandate']).strip()
        if len(mandate) == 0:
            mandate = '1900-01-01'
        cond =  str(request.form['cond']).strip()
        last_inspection =  str(request.form['last_inspection']).strip()
        if len(last_inspection) == 0:
            last_inspection = '1900-01-01'
        inspector =  str(request.form['inspector']).strip()
        next_insp =  str(request.form['next_insp']).strip()
        if len(next_insp) == 0:
            next_insp = '1900-01-01'
        status =  str(request.form['status']).strip()
        rfid =  str(request.form['rfid']).strip()

        query = "INSERT INTO mafi(SerialNumber, CarryingCapacity, ManufacturedOn, Cond, LastInspection, InspectedBy, NextInspection, Status, RFID_1) VALUES('" + sn + "','" + udzwig + "','" + mandate + "','" + cond + "','" + last_inspection + "','" + inspector + "','" + next_insp + "','" + status + "','" + rfid + "')"
        query_update(query)

        return redirect(url_for('mafi_shipment'))


#######################################################################################
    
@app.route("/form_details_admin_view/<id>", methods=['POST', 'GET'])
def form_details_admin_view(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        query = replace_none_values(query)
        return render_template("form_details_admin_view.html", items=query) 
    
@app.route("/form_details_foundry_operator/<id>", methods=['POST', 'GET'])
def form_details_foundry_operator(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        query = replace_none_values(query)
        return render_template("form_details_foundry_operator.html", items=query) 
    
@app.route("/form_details_kn_operator/<id>", methods=['POST', 'GET'])
def form_details_kn_operator(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        query = replace_none_values(query)
        return render_template("form_details_kn_operator.html", items=query) 
    
@app.route("/form_details_admin_view_buffer/<id>", methods=['POST', 'GET'])
def form_details_admin_view_buffer(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        return render_template("form_details_admin_view_buffer.html", items=query) 

@app.route("/cores", methods=['POST', 'GET'])
def cores():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'formed' LIMIT 200")
        return render_template("cores.html", items=query) 

@app.route("/foundry", methods=['POST', 'GET'])
def foundry():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'assembled' LIMIT 200")
        wyswitl_czas_od_zmontowania(query)
        return render_template("foundry.html", items=query) 
    
@app.route("/foundry_report", methods=['POST', 'GET'])
def foundry_report():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM raporty")
        return render_template("foundry_report.html", items=query) 
    
@app.route("/raport_bot/<id>", methods=['POST', 'GET'])
def raport_bot(id):
    do_zalania = suma_wagi_netto()
    czas =  data_for_bot_report(id)[0]
    n = data_for_bot_report(id)[1]
    z = data_for_bot_report(id)[2]
    c = datetime.datetime.now()
    d = data_for_bot_report(id)[3]
    e = data_for_bot_report(id)[4]
    f = data_for_bot_report(id)[5]
    g = data_for_bot_report(id)[6]
    h = data_for_bot_report(id)[7]
    i = data_for_bot_report(id)[8]
    j = data_for_bot_report(id)[9]
    k = data_for_bot_report(id)[10]
    l = data_for_bot_report(id)[11]
    m = data_for_bot_report(id)[12]
    n = data_for_bot_report(id)[13]

    data = {
        'Casting_weight' : str(do_zalania),
        'Max_time_inside' : str(czas),
        'Flasks_to_casting' : str(n),       
        'Flasks_to_taken_out' : str(z),
        'Time of report' : str(c),
        'Leaks_or_additives' : str(d),
        'Mech_n' : str(e),
        'Mech_mass' : str(f),
        'Mech_avg' : str(g),
        'Man_n' : str(h),
        'Man_mass' : str(i),
        'Man_avg' : str(j),
        'Sum' : str(k),
        'Assembled_n' : str(l),
        'Assembled_sum' : str(m),
        'Assembled_avg' : str(n)
    }

    query = "INSERT INTO raporty_mes(casting_weight, max_time_inside, flasks_to_casting, flasks_to_taken_out, shift, leaks_or_additives, mech_n, mech_mass, mech_avg, man_n, man_mass, man_avg, sum_forms, assembled_n, assembled_sum, assembled_avg) VALUES(" + str(do_zalania) + "," + str(czas) + "," + str(n) + "," + str(z) + "," + str(id) + "," + str(d) + "," + str(e) + "," + str(f) + "," + str(g) + "," + str(h) + "," + str(i) + "," + str(j) + "," + str(k) + "," + str(l) + "," + str(m) + "," + str(n) + ")"
    query_update(query)
    # mes_azure_db(query)
    
    response = app.response_class(
        response=json.dumps(data),
        status=200,
        mimetype='application/json'
    )
    return response

@app.route("/raport_compacting", methods=['POST', 'GET'])
def raport_compacting():
    query = '''
    SELECT
        tab1.form_id,
        tab2.produkt_id job_id,
        tab2.prod_id produkt_id,
        tab1.czas time
    FROM
        lista_formowania_formy_historia_v2 tab1
    LEFT JOIN lista_formowania_formy_v2 tab2 ON
        tab1.form_id = tab2.id
    ORDER BY
        tab1.id
    DESC
    LIMIT 1;    
    '''
    res = query_db(query)
    return jsonify(res), 200

@app.route("/casting_report", methods=['POST', 'GET'])
def casting_report():
    casting_from = request.form.get("casting_from")
    casting_to = request.form.get("casting_to")

    if not casting_to and not casting_from:
        today = datetime.datetime.today().date()
        casting_to = today + timedelta(days=1)
        casting_from = today - timedelta(days=7)

    if request.form.get('leaks'):
        query = "SELECT id FROM lista_formowania_v2 WHERE item_status IN('casted', 'cooling', 'knockout') AND broken = 'tak' AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC" 
    elif request.form.get('addivies'):
        query = "SELECT id FROM lista_formowania_v2 WHERE item_status IN('casted', 'cooling', 'knockout') AND filtr = 'tak' AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    elif request.form.get('zlom'):
        query = "SELECT id FROM lista_formowania_v2 WHERE item_status IN('casted', 'cooling', 'knockout') AND repeated = '1' AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    elif request.form.get('all'):
        query = "SELECT id FROM lista_formowania_v2 WHERE item_status IN('casted', 'cooling', 'knockout') AND filtr = 'tak' AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' OR item_status IN('casted', 'cooling', 'knockout') AND broken = 'tak' AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' OR item_status IN('casted', 'cooling', 'knockout') AND repeated = '1' AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    else:
        query = "SELECT id FROM lista_formowania_v2 WHERE item_status IN('casted', 'cooling', 'knockout') AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"

    final_list_of_results = []
    counterweights = query_db(query)

    for item in counterweights:
        list_of_counterweights = items_data(item['id'])

        for item in list_of_counterweights:
            query = (
                "SELECT decyzja, wada, czas "
                "FROM `defects` "
                f"WHERE sn={int(item['sn'])} AND form_id={int(item['id'])} "
                "ORDER BY id ASC"
            )

            results = query_db(query)  # <- musi zwrócić listę dictów (0..N)

            if not results:
                item['data_defectu'] = '-'
                item['decyzja'] = '-'
                item['wada'] = '-'
                final_list_of_results.append(item)
                continue

            # data_defectu: np. ostatni czas (albo pierwszy — jak wolisz)
            item['data_defectu'] = str(results[-1].get('czas', '-'))

            # zbierz wszystkie niepuste wady/decyzje
            wady = [r.get('wada') for r in results if r.get('wada')]
            decyzje = [r.get('decyzja') for r in results if r.get('decyzja')]

            item['wada'] = ", ".join(wady) if wady else "-"
            item['decyzja'] = ", ".join(decyzje) if decyzje else "-"

            final_list_of_results.append(item)

    # save_castings_to_mysql(final_list_of_results)
    return render_template("casting_report.html", items=final_list_of_results, casting_from=casting_from, casting_to=casting_to, report_name="CASTING")


@app.route("/casting_report_tmp", methods=['POST', 'GET'])
def casting_report_tmp():
    casting_from = request.form.get("casting_from")
    casting_to = request.form.get("casting_to")

    if not casting_to and not casting_from:
        today = datetime.datetime.today().date()
        casting_to = today + timedelta(days=1)
        casting_from = today - timedelta(days=31)

    query = "SELECT * FROM casting_report_tmp"
    final_list_of_results = query_db(query)
    sql = "SELECT updated_at FROM casting_report_tmp ORDER BY updated_at DESC LIMIT 1"
    update_time = query_db(sql)[0]['updated_at']
    return render_template("casting_report_tmp.html", items=final_list_of_results, casting_from=casting_from, casting_to=casting_to, report_name="CASTING", update_time=update_time)

@app.route("/casting_report_tmp_update", methods=['POST', 'GET'])
def casting_report_tmp_update():
    print("Rozpoczęto procedurę aktualizacji casting_report_tmp:", datetime.datetime.now())

    casting_from = request.form.get("casting_from")
    casting_to = request.form.get("casting_to")

    if not casting_to and not casting_from:
        today = datetime.datetime.today().date()
        casting_to = today + timedelta(days=1)
        casting_from = today - timedelta(days=31)

    query = "SELECT id FROM lista_formowania_v2 WHERE item_status IN('casted', 'cooling', 'knockout') AND data_zalania BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"

    final_list_of_results = []
    counterweights = query_db(query)

    for item in counterweights:
        list_of_counterweights = items_data(item['id'])

        for item in list_of_counterweights:
            query = (
                "SELECT decyzja, wada, czas "
                "FROM `defects` "
                f"WHERE sn={int(item['sn'])} AND form_id={int(item['id'])} "
                "ORDER BY id ASC"
            )

            results = query_db(query)  # <- musi zwrócić listę dictów (0..N)

            if not results:
                item['data_defectu'] = '-'
                item['decyzja'] = '-'
                item['wada'] = '-'
                final_list_of_results.append(item)
                continue

            # data_defectu: np. ostatni czas (albo pierwszy — jak wolisz)
            item['data_defectu'] = str(results[-1].get('czas', '-'))

            # zbierz wszystkie niepuste wady/decyzje
            wady = [r.get('wada') for r in results if r.get('wada')]
            decyzje = [r.get('decyzja') for r in results if r.get('decyzja')]

            item['wada'] = ", ".join(wady) if wady else "-"
            item['decyzja'] = ", ".join(decyzje) if decyzje else "-"

            final_list_of_results.append(item)

    save_castings_to_mysql(final_list_of_results)
    print("Zakończono procedurę aktualizacji casting_report_tmp:", datetime.datetime.now())

    return f"<p>Casting Report updated!</p>"

@app.route("/casting_report_tmp_items_to_dispaly", methods=['POST', 'GET'])
def casting_report_tmp_items_to_dispaly():
    casting_from = request.form.get("casting_from")
    casting_to = request.form.get("casting_to")

    if not casting_to and not casting_from:
        today = datetime.datetime.today().date()
        casting_to = today + timedelta(days=1)
        casting_from = today - timedelta(days=31)

    if request.form.get('leaks'):
        query = "SELECT * FROM casting_report_tmp WHERE broken = '1' AND flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC" 
    elif request.form.get('addivies'):
        query = "SELECT * FROM casting_report_tmp WHERE refiled = '1' AND flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    elif request.form.get('zlom'):
        query = "SELECT * FROM casting_report_tmp WHERE scrap = '1' AND scrap_cast = '1' and flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    elif request.form.get('all'):
        query = "SELECT * FROM casting_report_tmp WHERE refiled = '1' AND flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' OR broken = '1' AND flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' OR scrap = '1' AND scrap_cast = '1' AND flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    else:
        query = "SELECT * FROM casting_report_tmp WHERE flooded_on BETWEEN '"  + str(casting_from) +  "' AND '" + str(casting_to) + "' ORDER BY id DESC"

    print(query)

    final_list_of_results = []
    final_list_of_results = query_db(query)
    sql = "SELECT updated_at FROM casting_report_tmp ORDER BY updated_at DESC LIMIT 1"
    update_time = query_db(sql)[0]['updated_at']
    return render_template("casting_report_tmp.html", items=final_list_of_results, casting_from=casting_from, casting_to=casting_to, report_name="CASTING", update_time=update_time)


@app.route("/find_product", methods=['POST', 'GET'])
def find_product():
    product = request.form['product']
    casting_from = request.form.get("defects_from")
    casting_to = request.form.get("defects_to")

    if not casting_to and not casting_from:
        today = datetime.datetime.today().date()
        casting_to = today
        casting_from = today - timedelta(days=180)

    query = "SELECT id FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab2.customer ='Still' AND tab2.nazwa='" + product + "' AND data_zalania BETWEEN '" + str(casting_from) + "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    final_list_of_results = []
    counterweights = query_db(query)

    for i in counterweights:
        list_of_counterweights = items_data(i['id'])

        for i in list_of_counterweights:
            try:
                query = "SELECT decyzja, wada, czas FROM `defects` WHERE sn=" + str(i['sn']) + " AND form_id=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            
            results = query_db_first(query)
            try:
                i['data_defectu'] = str(results['czas'])
            except TypeError:
                i['data_defectu'] = '-'
            try:
                i['decyzja'] = results['decyzja']
            except TypeError:
                i['decyzja'] = '-'
            try:
                i['wada'] = results['wada']
            except TypeError:
                i['wada'] = '-'

            final_list_of_results.append(i)
    
    
    for i in final_list_of_results:
        try:
            query = "SELECT * FROM `still_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
        except IndexError:
            continue
        res = query_db_first(query)
    
        try:
            i['result'] = res['result_inspection']
        except TypeError:
            i['result'] = '-'

        if i['result'] != '-':
            i['operator'] = res['operator']
            i['czas'] = res['czas']
            i['result'] = res['result_inspection']
            if res['trail'] == '1':
                i['trail'] = 'TAK'
            else:
                i['trail'] = 'NIE'
              
            if res['defect'] == None:
                i['defect'] = '-'
            else:
                i['defect'] = res['defect']
             
            i['customer'] = 'Still'

        else:
            i['operator'] = '-'
            i['czas'] = '-'
            i['result'] = '-'
            i['defect'] = '-'
            i['customer'] = 'Still'
        
        products = query_db("SELECT nazwa FROM `produkty`")

    return render_template("qa_report_still.html", items=final_list_of_results, customer='Still', products=products)

@app.route("/find_product_kion_polska", methods=['POST', 'GET'])
def find_product_kion_polska():
    product = request.form['product']
    casting_from = request.form.get("defects_from")
    casting_to = request.form.get("defects_to")

    if not casting_to and not casting_from:
        today = datetime.datetime.today().date()
        casting_to = today
        casting_from = today - timedelta(days=180)

    query = "SELECT id FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab2.customer ='Kion Polska' AND tab2.nazwa='" + product + "' AND data_zalania BETWEEN '" + str(casting_from) + "' AND '" + str(casting_to) + "' ORDER BY id DESC"
    final_list_of_results = []
    counterweights = query_db(query)

    for i in counterweights:
        list_of_counterweights = items_data(i['id'])

        for i in list_of_counterweights:
            try:
                query = "SELECT decyzja, wada, czas FROM `defects` WHERE sn=" + str(i['sn']) + " AND form_id=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            
            results = query_db_first(query)
            try:
                i['data_defectu'] = str(results['czas'])
            except TypeError:
                i['data_defectu'] = '-'
            try:
                i['decyzja'] = results['decyzja']
            except TypeError:
                i['decyzja'] = '-'
            try:
                i['wada'] = results['wada']
            except TypeError:
                i['wada'] = '-'

            final_list_of_results.append(i)
    
    
    for i in final_list_of_results:
        try:
            query = "SELECT * FROM `kion_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
        except IndexError:
            continue
        res = query_db_first(query)
    
        try:
            i['result'] = res['result_inspection']
        except TypeError:
            i['result'] = '-'

        if i['result'] != '-':
            i['operator'] = res['operator']
            i['czas'] = res['czas']
            i['result'] = res['result_inspection']
            if res['trail'] == '1':
                i['trail'] = 'TAK'
            else:
                i['trail'] = 'NIE'
              
            if res['defect'] == None:
                i['defect'] = '-'
            else:
                i['defect'] = res['defect']
             
            i['customer'] = 'Still'

        else:
            i['operator'] = '-'
            i['czas'] = '-'
            i['result'] = '-'
            i['defect'] = '-'
            i['customer'] = 'Still'
        
        products = query_db("SELECT nazwa FROM `produkty`")

    return render_template("qa_report_kion.html", items=final_list_of_results, customer='Still', products=products)

@app.route("/claims", methods=['POST', 'GET'])
def claims():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        products = query_db("SELECT DISTINCT nazwa FROM `produkty` WHere item_status='active' ORDER BY nazwa ASC")
        consumers = query_db("SELECT DISTINCT customer FROM `produkty` WHere item_status='active' ORDER BY customer ASC")
        items = query_db("SELECT * FROM reklamacje WHERE status='active' ORDER BY id DESC")
        return render_template("claims.html", products=products, consumers=consumers, items=items)


@app.route("/add_new_claim", methods=['POST', 'GET'])
def add_new_claim():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    
    else:
        serial = request.form['claim_sn'].strip()
        sql = f"SELECT * FROM reklamacje WHERE serial_no = '{serial}' and status='active'"
        result = query_db(sql)
        if len(result) != 0:
            flash(f"Reklamacja o numerze seryjnym {serial} już istnieje. Przejdź do zakładki 'Reklamacje', aby edytować istniejącą reklamację.")
            return redirect(url_for('claims'))
        
        if is_valid_serial_number(serial):
            prefix, sn = split_code(serial)
            sql = f"SELECT * FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn={sn}"
            data = query_db(sql)

            if not data:
                flash(f"Nie znaleziono produktu o numerze seryjnym: {serial}. Upewnij się, że numer seryjny jest poprawny i istnieje w bazie danych.")
                return redirect(request.referrer)

            sql = f"SELECT tab1.id, tab2.customer, tab2.nazwa FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.id = {data[0]['produkt_id']}"
            try:
                result = query_db(sql)
            except Exception as e:
                flash(f"Błąd podczas pobierania danych produktu: {e}")
                return redirect(request.referrer)

            product=result[0]['nazwa']
            customer=result[0]['customer']
            serial=serial

            sql = "INSERT INTO reklamacje (klient, serial_no, product) VALUES (%s, %s, %s)"
            result = query_update_new(sql, (customer, serial, product))  

            
            if result:
                try:
                    operator = session['user']
                    id_of_new_claim = query_db("SELECT id FROM reklamacje WHERE serial_no='" + serial + "' ORDER BY id DESC LIMIT 1")
                    id_of_new_claim = id_of_new_claim[0]['id']
                except (IndexError, KeyError):
                    flash(f"Błąd podczas zapisywania do tabeli audyt/historia nowo utworzonej reklamacji dla numeru seryjnego: {serial}")
                history_claims(id_of_new_claim, "new claim created", operator)
                form_id = data[0]['produkt_id']
                history_qa(form_id, sn, prefix, 'Complaint added', operator)
                
            return redirect(url_for('claims'))
        
        else:
            flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
            return redirect(request.referrer)


@app.route("/edit_claim/<serial>", methods=['POST', 'GET'])
def edit_claim(serial):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        prefix, sn = split_code(serial)

        sql = f"SELECT * FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn={sn}"
        data = query_db(sql)
        try:
            form_id = data[0]['produkt_id']
        except (IndexError, KeyError):
            flash(f"Błąd podczas pobierania ID reklamacji dla numeru seryjnego: {serial}")
            return redirect(request.referrer)

        sql = f"SELECT tab2.customer, tab2.nazwa FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.id = {form_id}"
        result = query_db(sql)
        try:
            product=result[0]['nazwa']
            customer=result[0]['customer']    
        except Exception as e:
            flash(f"Błąd podczas pobierania danych produktu: {e}")
            return redirect(request.referrer)
    

        sql = f"SELECT * FROM reklamacje WHERE serial_no='{serial}'"
        claim_details = query_db(sql)
        try:
            claim=claim_details[0]
        except (IndexError, KeyError):
            flash(f"Błąd podczas pobierania ID reklamacji dla numeru seryjnego: {serial}")
            return redirect(request.referrer)
        
        print(claim)

        attachments = query_db("SELECT * FROM attachements_claims WHERE prefix='" + prefix + "' AND sn=" + str(sn))
        return render_template("edit_claim.html", serial=serial, product=product, customer=customer, attachments=attachments, claim=claim)


@app.route('/save_complaint', methods=['POST'])
def save_complaint():

    # 📥 dane z formularza
    id = request.form.get('claim_system_id')
    id = id.strip() if id else None
    claim_id = request.form.get('claim_id')
    claim_id = claim_id.strip() if claim_id else None
    klient = request.form.get('client')
    klient = klient.strip() if klient else None
    serial_no = request.form.get('serial_no')
    serial_no = serial_no.strip() if serial_no else None
    product = request.form.get('product')
    product = product.strip() if product else None
    claim_no = request.form.get('claim_no')
    claim_no = claim_no.strip() if claim_no else None

    data_reklamacji = request.form.get('complaint_date')
    data_reklamacji = data_reklamacji.strip() if data_reklamacji else None
    data_powrotu = request.form.get('return_date')
    data_powrotu = data_powrotu.strip() if data_powrotu else None

    powod_reklamacji = request.form.get('complaint_reason')
    powod_reklamacji = powod_reklamacji.strip() if powod_reklamacji else None
    decyzja = request.form.get('customer_decision')
    decyzja = decyzja.strip() if decyzja else None

    koszt_przeciwwagi = request.form.get('koszt_przeciwwagi')
    koszt_przeciwwagi = koszt_przeciwwagi.strip() if koszt_przeciwwagi else None
    koszt_naprawy = request.form.get('koszt_naprawy')
    koszt_naprawy = koszt_naprawy.strip() if koszt_naprawy else None
    koszt_obslugi = request.form.get('koszt_obslugi')
    koszt_obslugi = koszt_obslugi.strip() if koszt_obslugi else None    
    koszt_transportu = request.form.get('koszt_transportu')
    koszt_transportu = koszt_transportu.strip() if koszt_transportu else None
    claim_status = request.form.get('claim_status')
    claim_status = claim_status.strip() if claim_status else None

    wyrob_wrocil = request.form.get('returned_product')
    wyrob_wrocil = wyrob_wrocil.strip() if wyrob_wrocil else None
    akceptacja = request.form.get('claim_accepted')
    akceptacja = akceptacja.strip() if akceptacja else None
    numer_faktury = request.form.get('invoice_number')
    numer_faktury = numer_faktury.strip() if numer_faktury else None

    # 💾 UPDATE zamiast INSERT
    sql = """
    UPDATE reklamacje SET
        claim_id = %s,
        klient = %s,
        serial_no = %s,
        product = %s,
        claim_no = %s,
        data_reklamacji = %s,
        data_powrotu = %s,
        powod_reklamacji = %s,
        decyzja_klienta = %s,
        koszt_przeciwwagi = %s,
        koszt_naprawy = %s,
        koszt_obslugi = %s,
        koszt_transportu = %s,
        wyrob_wrocil = %s,
        akceptacja = %s,
        claim_status = %s,
        invoice_number = %s
    WHERE id = %s
    """

    print(f"Executing SQL: {sql} with values: {(claim_id, klient, serial_no, product, claim_no, data_reklamacji, data_powrotu, powod_reklamacji, decyzja, koszt_przeciwwagi, koszt_naprawy, koszt_obslugi, koszt_transportu, wyrob_wrocil, akceptacja, claim_status, numer_faktury, id)}")
    # print("koszt_przeciwwagi:", koszt_przeciwwagi)
    # print("koszt_naprawy:", koszt_naprawy)
    # print("koszt_obslugi:", koszt_obslugi)
    # print("koszt_transportu:", koszt_transportu)

    result = query_update_new(sql, (claim_id, klient, serial_no, product, claim_no, data_reklamacji, data_powrotu, powod_reklamacji, decyzja, koszt_przeciwwagi, koszt_naprawy, koszt_obslugi, koszt_transportu, wyrob_wrocil, akceptacja, claim_status, numer_faktury, id ))

    if result:
        operator = session['user']
        history_claims(id, "update claim", operator)
        return redirect('/claims')
    else:
        flash(f"Wystąpił błąd podczas aktualizacji reklamacji o numerze seryjnym {serial_no}.")
    return redirect('/claims')


@app.route("/defects_sn", methods=['POST', 'GET'])
def defects_sn():
    try:
        serial = request.form['sn']
        serial = serial.upper()
    except KeyError:
        serial = 'ccc-111'
    serial = serial.replace("'", "")

    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer)
    
    serial = split_code(serial)
    prefix = serial[0]
    sn = serial[1]

    # sql = "SELECT DISTINCT tab2.* FROM `lista_formowania_formy_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN lista_formowania_sn tab3 ON tab2.id = tab3.produkt_id WHERE tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout') AND tab1.model1_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model2_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model3_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model4_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model5_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model6_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model7_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab3.param1 = '0' AND tab2.item_status IN('casted','cooling', 'knockout', 'grinding') AND tab1.model8_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' ORDER BY id DESC"
    sql = f"SELECT produkt_id id FROM lista_formowania_sn WHERE prefix ='{prefix}' AND sn={sn} AND param1='0'"
    counterweights = query_db(sql)
    final_list_of_results = []

    for cw in counterweights:
        list_of_counterweights = items_data(cw['id'])

        for item in list_of_counterweights:
            query = (
                "SELECT decyzja, wada, czas "
                "FROM `defects` "
                f"WHERE sn={int(item['sn'])} AND form_id={int(item['id'])} "
                "ORDER BY id ASC"
            )

            results = query_db(query)  # <- musi zwrócić listę dictów (0..N)

            if not results:
                item['data_defectu'] = '-'
                item['decyzja'] = '-'
                item['wada'] = '-'
                final_list_of_results.append(item)
                continue

            # data_defectu: np. ostatni czas (albo pierwszy — jak wolisz)
            item['data_defectu'] = str(results[-1].get('czas', '-'))

            # zbierz wszystkie niepuste wady/decyzje
            wady = [r.get('wada') for r in results if r.get('wada')]
            decyzje = [r.get('decyzja') for r in results if r.get('decyzja')]

            item['wada'] = ", ".join(wady) if wady else "-"
            item['decyzja'] = ", ".join(decyzje) if decyzje else "-"

            final_list_of_results.append(item)

    final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
    return render_template("casting_report.html", items=final_list_of_results_filtred_by_sn)

@app.route("/seearch_by_sn_cs_temp", methods=['POST', 'GET'])
def seearch_by_sn_cs_temp():
    try:
        serial = request.form['sn']
        serial = serial.upper()
    except KeyError:
        serial = 'ccc-111'
        
    serial = serial.replace("'", "")

    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer)
    
    serial = split_code(serial)
    prefix = serial[0]
    sn = serial[1]
    list_of_itmes = []
    query = f"SELECT * FROM `casting_report_tmp` WHERE prefix='{prefix}' AND sn={sn}"
    list_of_itmes = query_db(query)
    
    return render_template("casting_report_tmp.html", items=list_of_itmes)


@app.route("/grinding_sn", methods=['POST', 'GET'])
def grinding_sn():
    try:
        serial = request.form['sn']
        serial = serial.upper()
    except KeyError:
        serial = 'ccc-111'
    
    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer)
    
    serial = split_code(serial)
    prefix = serial[0]
    sn = serial[1]

    query = f"SELECT tab2.* FROM `lista_formowania_sn` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.prefix='{prefix}' AND tab1.sn={sn} AND tab1.param1='0' AND tab2.item_status IN('knockout')"
    # query = "SELECT DISTINCT tab2.* FROM `lista_formowania_formy_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model1_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model2_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model3_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model4_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model5_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model6_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.model7_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' OR tab2.item_status IN('casted','cooling', 'knockout', 'grinding') AND tab1.model8_sn=" + str(sn) + " AND tab1.prefix='" + prefix + "' ORDER BY id DESC"
    counterweights = query_db(query)

    print(query)

    for i in counterweights:
        query = "SELECT * FROM `grinding` WHERE prefix='" + prefix + "' AND sn=" + str(sn) + " AND item_id=" + str(i['id'])
        result = query_db(query)
        if len(result) > 0:
            counterweights = [x for x in counterweights if i['id'] != i['id']]

    final_list_of_results = []
    final_list_of_results_filtred_by_sn = []

    for i in counterweights:
        list_of_counterweights = items_data(i['id'])

        for i in list_of_counterweights:
            final_list_of_results.append(i)

    
        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))   
        final_list_of_results_filtred_by_sn[0]['Prefix'] = final_list_of_results_filtred_by_sn[0]['prefix'] 
        final_list_of_results_filtred_by_sn[0]['nazwa_produktu'] = final_list_of_results_filtred_by_sn[0]['product_name'] 
        final_list_of_results_filtred_by_sn[0]['waga_zeliwa'] = final_list_of_results_filtred_by_sn[0]['casting_mass'] 
        customer = query_db("SELECT customer FROM produkty WHERE prefix='" + prefix + "'")
        try:
            final_list_of_results_filtred_by_sn[0]['customer'] = customer[0]['customer']
        except IndexError:
            final_list_of_results_filtred_by_sn[0]['customer'] = '-'
        
    return render_template("grinding.html", items=final_list_of_results_filtred_by_sn)


@app.route("/qa_sn_search", methods=['POST', 'GET'])
def qa_sn_search():

    serial = (request.form.get('sn') if request.method == 'POST' else request.args.get('sn')) or ''
    serial = serial.upper()

    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer or url_for('quality'))

    prefix, numer = serial.split("-")
    numer = int(numer)

    if cast_removed_by_the_operator(prefix, numer):
        flash(f"Odlew S/N: {prefix}-{numer} został usunięty z formy na etapie skręcania form.")
        return redirect(request.referrer)

    if form_was_canceled(prefix, numer):
        flash(f"Wprawdzony numer seryjny należy do formy która została usunięta przez biuro odlewni: {serial}. Szczegóły w tabeli: lista_formowania_historia_v2")
        return redirect(request.referrer)

    query = f"SELECT produkt_id FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn='{numer}' AND param1='0' ORDER BY id DESC LIMIT 1"

    print(query)
    
    id1 = None
    id2 = None

    try:
        id1 = query_db(query)[0]['produkt_id']
    except IndexError:
        flash(f"Brak indexu: {serial}")
        return redirect(url_for('quality'))

    try:
        id2 = query_db(query)[1]['produkt_id']
    except IndexError:
        id2 == None

    print('ID odlewów 1', id1)
    print('ID odlewów 2', id2)
              
    
    if id1 and not id2:
        items=query_db("SELECT DISTINCT tab1.id, tab1.produkt_id, tab1.production_stage, tab1.operator, tab1.operator, tab1.czas, tab1.sn, tab1.prefix, tab2.nazwa_produktu, tab2.dni_do_wybicia, tab2.nr_kadzi, tab2.filtr, tab2.broken, tab2.temp_zeliwa, tab2.alias, tab2.data_zalania, tab2.komentarz, tab2.komentarz_formowanie, tab2.komentarz_rdzeniarnia, tab2.komentarz_zalew, tab2.komentarz_wybijanie FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN lista_formowania_sn tab3 ON tab1.produkt_id = tab3.produkt_id WHERE tab3.param1 = '0' AND tab2.id=" + str(id1))
        items = filter_items_quality(items, prefix, numer)
        flasks = adv_search_manscan(id1)
        data = {
            "nazwa" : items[0]['nazwa_produktu'],
            "system_id" : items[0]['produkt_id'],
            "sn" : serial
        }

        return render_template("quality.html", items=items, flasks=flasks, id=id, data=data)

    elif id1 and id2:
        items=query_db("SELECT DISTINCT tab1.id, tab1.produkt_id, tab1.production_stage, tab1.operator, tab1.operator, tab1.czas, tab1.sn, tab1.prefix, tab2.nazwa_produktu, tab2.dni_do_wybicia, tab2.nr_kadzi, tab2.filtr, tab2.broken, tab2.temp_zeliwa, tab2.alias, tab2.data_zalania, tab2.komentarz, tab2.komentarz_formowanie, tab2.komentarz_rdzeniarnia, tab2.komentarz_zalew, tab2.komentarz_wybijanie FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.id=" + str(id1))
        items = filter_items_quality(items, prefix, numer)
        flasks = adv_search_manscan(id1)
        data = {
            "nazwa" : items[0]['nazwa_produktu'],
            "system_id" : items[0]['produkt_id'],
            "sn" : serial
        }

        items2=query_db("SELECT tab1.id, tab1.produkt_id, tab1.production_stage, tab1.operator, tab1.operator, tab1.czas, tab1.sn, tab1.prefix, tab2.nazwa_produktu, tab2.dni_do_wybicia, tab2.nr_kadzi, tab2.filtr, tab2.broken, tab2.temp_zeliwa, tab2.alias, tab2.data_zalania, tab2.komentarz, tab2.komentarz_formowanie, tab2.komentarz_rdzeniarnia, tab2.komentarz_zalew, tab2.komentarz_wybijanie FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.id=" + str(id2))
        items2 = filter_items_quality(items2, prefix, numer)
        flasks2 = adv_search_manscan(id2)
        data2 = {
            "nazwa" : items2[0]['nazwa_produktu'],
            "system_id" : items2[0]['produkt_id'],
            "sn" : serial
        }

        return render_template("quality2.html", items=items, items2=items2, flasks=flasks, flasks2=flasks2, id=id1, id2=id2, data=data, data2=data2)

@app.route("/qa_sn_search_po/<id>", methods=['GET'])
def qa_sn_search_po(id):

    serial = id.replace(" ", "")
    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer)

    prefix, numer = serial.split("-")
    numer = int(numer)

    # query = f"SELECT DISTINCT produkt_id FROM lista_formowania_formy_v2 WHERE prefix='{prefix}' AND {numer} IN (model1_sn, model2_sn, model3_sn, model4_sn, model5_sn, model6_sn, model7_sn, model8_sn)"
    query = f"SELECT produkt_id FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn='{numer}' AND param1='0' ORDER BY id DESC LIMIT 1"

    try:
        id = query_db(query)[0]['produkt_id']
        try:
            id2 = query_db(query)[1]['produkt_id']
        except IndexError:
            pass
        
    except IndexError:
        flash(f"Brak indexu: {serial}")
        return redirect(request.referrer)
    
  
    items=query_db("SELECT tab1.id, tab1.produkt_id, tab1.production_stage, tab1.operator, tab1.operator, tab1.czas, tab1.sn, tab1.prefix, tab2.nazwa_produktu, tab2.dni_do_wybicia, tab2.nr_kadzi, tab2.filtr, tab2.broken, tab2.temp_zeliwa, tab2.alias, tab2.data_zalania, tab2.komentarz, tab2.komentarz_formowanie, tab2.komentarz_rdzeniarnia, tab2.komentarz_zalew, tab2.komentarz_wybijanie FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.id=" + str(id))
    items = filter_items_quality(items, prefix, numer)
    flasks = adv_search_manscan(id)
    data = {
            "nazwa" : items[0]['nazwa_produktu'],
            "system_id" : items[0]['produkt_id'],
            "sn" : serial
        }

    return render_template("quality.html", items=items, flasks=flasks, id=id, data=data)

###############################################################################################

@app.route("/defects_to_dispaly", methods=['POST'])
def defects_to_dispaly(): 
    defects_from = request.form.get("defects_from")
    defects_to = request.form.get("defects_to")

    if not defects_to and not defects_from:
        today = datetime.datetime.today().date()
        defects_to = today
        defects_from = today - timedelta(days=7)

    query = "SELECT distinct form_id id FROM defects WHERE czas BETWEEN '"  + str(defects_from) +  "' AND '" + str(defects_to) + "' order by id DESC"
    
    final_list_of_results = []
    counterweights = query_db(query)

    for cw in counterweights:
        list_of_counterweights = items_data(cw['id'])

        for item in list_of_counterweights:
            query = (
                "SELECT decyzja, wada, czas "
                "FROM `defects` "
                f"WHERE sn={int(item['sn'])} AND form_id={int(item['id'])} "
                "ORDER BY id ASC"
            )

            results = query_db(query)  # <- musi zwrócić listę dictów (0..N)

            if not results:
                item['data_defectu'] = '-'
                item['decyzja'] = '-'
                item['wada'] = '-'
                final_list_of_results.append(item)
                continue

            # data_defectu: np. ostatni czas (albo pierwszy — jak wolisz)
            item['data_defectu'] = str(results[-1].get('czas', '-'))

            # zbierz wszystkie niepuste wady/decyzje
            wady = [r.get('wada') for r in results if r.get('wada')]
            decyzje = [r.get('decyzja') for r in results if r.get('decyzja')]

            item['wada'] = ", ".join(wady) if wady else "-"
            item['decyzja'] = ", ".join(decyzje) if decyzje else "-"

            final_list_of_results.append(item)

    final_list_of_results = filter_decyzja(final_list_of_results)
    return render_template("casting_report.html", items=final_list_of_results, casting_from=defects_from, casting_to=defects_to, report_name="QA DEFECTS")

@app.route("/defects_to_dispaly_cs_tmp", methods=['POST'])
def defects_to_dispaly_cs_tmp(): 

    today = datetime.datetime.today().date()
    defects_to = today
    defects_from = today - timedelta(days=31)

    query = "SELECT distinct form_id id FROM defects WHERE czas BETWEEN '"  + str(defects_from) +  "' AND '" + str(defects_to) + "' order by id DESC"
    
    final_list_of_results = []
    counterweights = query_db(query)

    for cw in counterweights:
        list_of_counterweights = items_data(cw['id'])

        for item in list_of_counterweights:
            query = (
                "SELECT decyzja, wada, czas "
                "FROM `defects` "
                f"WHERE sn={int(item['sn'])} AND form_id={int(item['id'])} "
                "ORDER BY id ASC"
            )

            results = query_db(query)  # <- musi zwrócić listę dictów (0..N)

            if not results:
                item['data_defectu'] = '-'
                item['decyzja'] = '-'
                item['wada'] = '-'
                final_list_of_results.append(item)
                continue

            # data_defectu: np. ostatni czas (albo pierwszy — jak wolisz)
            item['data_defectu'] = str(results[-1].get('czas', '-'))

            # zbierz wszystkie niepuste wady/decyzje
            wady = [r.get('wada') for r in results if r.get('wada')]
            decyzje = [r.get('decyzja') for r in results if r.get('decyzja')]

            item['wada'] = ", ".join(wady) if wady else "-"
            item['decyzja'] = ", ".join(decyzje) if decyzje else "-"

            final_list_of_results.append(item)

    final_list_of_results = filter_decyzja(final_list_of_results)

    return render_template("casting_report_tmp.html", items=final_list_of_results, report_name="QA DEFECTS")

@app.route("/qa_report/<customer>", methods=['POST', 'GET'])
def qa_report(customer):

    query = "SELECT id FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab2.customer ='" + customer + "' ORDER BY id DESC LIMIT " + str(200)
    final_list_of_results = []
    counterweights = query_db(query)

    for i in counterweights:
        list_of_counterweights = items_data(i['id'])

        for i in list_of_counterweights:
            try:
                query = "SELECT decyzja, wada, czas FROM `defects` WHERE sn=" + str(i['sn']) + " AND form_id=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            
            results = query_db_first(query)

            try:
                i['data_defectu'] = str(results['czas'])
            except TypeError:
                i['data_defectu'] = '-'

            try:
                i['decyzja'] = results['decyzja']
            except TypeError:
                i['decyzja'] = '-'

            try:
                i['wada'] = results['wada']
            except TypeError:
                i['wada'] = '-'

            final_list_of_results.append(i)

    if customer == 'Liebherr':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `liebherr_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue

            res = query_db_first(query)

            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':

                i['lakier_na_sucho_pomiar'] = res['lakier_na_sucho_pomiar'] 
                i['pomiar_koloru_lab_pomiar'] = res['pomiar_koloru_lab_pomiar']
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer
                
                if res['waga_lhe'] == None:
                    i['waga_lhe'] = '-'
                else:
                    i['waga_lhe'] = res['waga_lhe']

                if res['polysk_ral_9005'] == None:
                    i['polysk_ral_9005'] = '-'
                else:
                    i['polysk_ral_9005'] = res['polysk_ral_9005']

                if res['lakier_na_sucho'] == '1':
                    i['lakier_na_sucho'] = 'OK'
                else:
                    i['lakier_na_sucho'] = 'NOK'

                if res['struktura'] == '1':
                    i['struktura'] = 'OK'
                else:
                    i['struktura'] = 'NOK'

                if res['jakosc_napisow'] == '1':
                    i['jakosc_napisow'] = 'OK'
                else:
                    i['jakosc_napisow'] = 'NOK'

                if res['pow_pod_naklejke'] == '1':
                    i['pow_pod_naklejke'] = 'OK'
                else:
                    i['pow_pod_naklejke'] = 'NOK'

                if res['pomiar_koloru_lab'] == '1':
                    i['pomiar_koloru_lab'] = 'OK'
                else:
                    i['pomiar_koloru_lab'] = 'NOK'

            else:
                i['lakier_na_sucho_pomiar'] = '-'
                i['lakier_na_sucho'] = '-'
                i['struktura'] = '-'
                i['jakosc_napisow'] = '-'
                i['pow_pod_naklejke'] = '-'
                i['pomiar_koloru_lab'] = '-'
                i['pomiar_koloru_lab_pomiar'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['waga_lhe'] = '-'
                i['polysk_ral_9005'] = '-'
                i['customer'] = customer

        return render_template("qa_report.html", items=final_list_of_results, customer=customer)

    elif customer == 'Mecalac France':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `mecalac_fr_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue

            res = query_db_first(query)

            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':
                i['lakier_na_sucho_pomiar'] = res['lakier_na_sucho_pomiar'] 
                if res['ocena_powierzchni_bp'] == '1':
                    i['ocena_powierzchni_bp'] = 'OK'
                else:
                    i['ocena_powierzchni_bp'] = 'NOK'
                if res['ocena_powierzchni_cnc'] == '1':
                    i['ocena_powierzchni_cnc'] = 'OK'
                else:
                    i['ocena_powierzchni_cnc'] = 'NOK'
                if res['jakosc_struktury'] == '1':
                    i['jakosc_struktury'] = 'OK'
                else:
                    i['jakosc_struktury'] = 'NOK'
                if res['czystosc'] == '1':
                    i['czystosc'] = 'OK'
                else:
                    i['czystosc'] = 'NOK'
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer

            else:
                i['lakier_na_sucho_pomiar'] = '-'
                i['ocena_powierzchni_bp'] = '-'
                i['ocena_powierzchni_cnc'] = '-'
                i['jakosc_struktury'] = '-'
                i['czystosc'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['customer'] = customer

        return render_template("qa_report_mec_fr.html", items=final_list_of_results, customer=customer)

    elif customer == 'Mitsubishi Spain':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `mitsubishi_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':
                if res['kontury'] == '1':
                    i['kontury'] = 'OK'
                else:
                    i['kontury'] = 'NOK'
                if res['ocena_powierzchni'] == '1':
                    i['ocena_powierzchni'] = 'OK'
                else:
                    i['ocena_powierzchni'] = 'NOK'

                i['polysk_ral_9005'] = res['polysk_ral_9005']
                i['polysk_mitsu_green'] = res['polysk_mitsu_green']
                i['kolor1'] = res['kolor1']
                i['kolor1_wynik'] = res['kolor1_wynik']
                i['kolor2'] = res['kolor2']
                i['kolor2_wynik'] = res['kolor2_wynik']
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer

            else:
                i['polysk_ral_9005'] = '-'
                i['polysk_mitsu_green'] = '-'
                i['kolor1'] = '-'
                i['kolor1_wynik'] = '-'
                i['kolor2'] = '-'
                i['kolor2_wynik'] = '-'
                i['kontury'] = '-'
                i['ocena_powierzchni'] = '-'
                i['result'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['customer'] = customer

 
        return render_template("qa_report_mit_sp.html", items=final_list_of_results, customer=customer)

    elif customer == 'Mitsubishi Finland':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `mitsubishi_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':
                if res['kontury'] == '1':
                    i['kontury'] = 'OK'
                else:
                    i['kontury'] = 'NOK'
                if res['ocena_powierzchni'] == '1':
                    i['ocena_powierzchni'] = 'OK'
                else:
                    i['ocena_powierzchni'] = 'NOK'

                i['polysk_ral_9005'] = res['polysk_ral_9005']
                i['polysk_mitsu_green'] = res['polysk_mitsu_green']
                i['kolor1'] = res['kolor1']
                i['kolor1_wynik'] = res['kolor1_wynik']
                i['kolor2'] = res['kolor2']
                i['kolor2_wynik'] = res['kolor2_wynik']
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer

            else:
                i['polysk_ral_9005'] = '-'
                i['polysk_mitsu_green'] = '-'
                i['kolor1'] = '-'
                i['kolor1_wynik'] = '-'
                i['kolor2'] = '-'
                i['kolor2_wynik'] = '-'
                i['kontury'] = '-'
                i['ocena_powierzchni'] = '-'
                i['result'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['customer'] = customer

        return render_template("qa_report_mit_fin.html", items=final_list_of_results, customer=customer)
    
    elif customer == 'Still':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `still_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result'] = res['result_inspection']
            except TypeError:
                i['result'] = '-'

            if i['result'] != '-':
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['result'] = res['result_inspection']
                if res['trail'] == '1':
                    i['trail'] = 'TAK'
                else:
                    i['trail'] = 'NIE'
              
                if res['defect'] == None:
                    i['defect'] = '-'
                else:
                    i['defect'] = res['defect']
             
                i['customer'] = customer

            else:
                i['operator'] = '-'
                i['czas'] = '-'
                i['result'] = '-'
                i['defect'] = '-'
                i['customer'] = customer
        
        products = query_db("SELECT nazwa FROM `produkty`")
        return render_template("qa_report_still.html", items=final_list_of_results, customer=customer, products=products)

    elif customer == 'Kion Polska':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `kion_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result'] = res['result_inspection']
            except TypeError:
                i['result'] = '-'

            if i['result'] != '-':
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['result'] = res['result_inspection']
                if res['trail'] == '1':
                    i['trail'] = 'TAK'
                else:
                    i['trail'] = 'NIE'
              
                if res['defect'] == None:
                    i['defect'] = '-'
                else:
                    i['defect'] = res['defect']
             
                i['customer'] = customer

            else:
                i['operator'] = '-'
                i['czas'] = '-'
                i['result'] = '-'
                i['defect'] = '-'
                i['customer'] = customer
        
        products = query_db("SELECT nazwa FROM `produkty`")
        return render_template("qa_report_kion.html", items=final_list_of_results, customer=customer, products=products)
    
    else:
        return render_template("no_form.html")

@app.route("/qa_report_sn", methods=['POST', 'GET'])
def qa_report_sn():
    try:
        serial = request.form['sn']
        serial = serial.upper()
    except KeyError:
        serial = 'ccc-111'
    serial = serial.replace("'", "")

    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer)
    
    serial = split_code(serial)
    prefix = serial[0]
    sn = serial[1]

    def czy_prefix_istnieje(prefix, lista):
        prefix = prefix.upper()
        return any(item.get('prefix', '').upper() == prefix for item in lista)

    customer = str(request.form['customer'])

    sql = "SELECT prefix FROM `produkty` where customer='" + customer + "'"
    prefix_lists = query_db(sql)

    if czy_prefix_istnieje(prefix, prefix_lists) == False:
        flash(f"Wprowadzono niewłaściwy numer seryjny: {serial}. ")
        url = '/qa_report/' + customer
        return redirect(url)
    
    query = "SELECT DISTINCT tab2.* FROM `lista_formowania_formy_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model1_sn =" + str(sn) + " OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model2_sn =" + str(sn) + " OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND  tab1.model3_sn =" + str(sn) + " OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model4_sn =" + str(sn) + " OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model5_sn =" + str(sn) + " OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model6_sn =" + str(sn) + " OR tab2.item_status IN('casted', 'cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model7_sn =" + str(sn) + " OR tab2.item_status IN('casted','cooling', 'knockout', 'grinding') AND tab1.prefix ='" + prefix + "' AND tab1.model8_sn =" + str(sn) + " ORDER BY id DESC"
    final_list_of_results = []

    counterweights = query_db(query)

    for i in counterweights:
        list_of_counterweights = items_data(i['id'])

        for i in list_of_counterweights:
            try:
                query = "SELECT decyzja, wada, data FROM `defects` WHERE sn=" + str(i['sn']) + " AND form_id=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            
            results = query_db_first(query)
            try:
                i['data_defectu'] = str(results['czas'])
            except TypeError:
                i['data_defectu'] = '-'


            try:
                i['decyzja'] = results['decyzja']
            except TypeError:
                i['decyzja'] = '-'

            try:
                i['wada'] = results['wada']
            except TypeError:
                i['wada'] = '-'

            final_list_of_results.append(i)

    if customer == 'Liebherr':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `liebherr_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue

            res = query_db_first(query)

            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':

                i['lakier_na_sucho_pomiar'] = res['lakier_na_sucho_pomiar'] 
                i['pomiar_koloru_lab_pomiar'] = res['pomiar_koloru_lab_pomiar']
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer
                
                if res['waga_lhe'] == None:
                    i['waga_lhe'] = '-'
                else:
                    i['waga_lhe'] = res['waga_lhe']

                if res['lakier_na_sucho'] == '1':
                    i['lakier_na_sucho'] = 'OK'
                else:
                    i['lakier_na_sucho'] = 'NOK'

                if res['struktura'] == '1':
                    i['struktura'] = 'OK'
                else:
                    i['struktura'] = 'NOK'

                if res['jakosc_napisow'] == '1':
                    i['jakosc_napisow'] = 'OK'
                else:
                    i['jakosc_napisow'] = 'NOK'

                if res['pow_pod_naklejke'] == '1':
                    i['pow_pod_naklejke'] = 'OK'
                else:
                    i['pow_pod_naklejke'] = 'NOK'

                if res['pomiar_koloru_lab'] == '1':
                    i['pomiar_koloru_lab'] = 'OK'
                else:
                    i['pomiar_koloru_lab'] = 'NOK'

            else:
                i['lakier_na_sucho_pomiar'] = '-'
                i['lakier_na_sucho'] = '-'
                i['struktura'] = '-'
                i['jakosc_napisow'] = '-'
                i['pow_pod_naklejke'] = '-'
                i['pomiar_koloru_lab'] = '-'
                i['pomiar_koloru_lab_pomiar'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['waga_lhe'] = '-'
                i['customer'] = customer

        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
        return render_template("qa_report.html", items=final_list_of_results_filtred_by_sn, customer=customer)

    elif customer == 'Mecalac France':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `mecalac_fr_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue

            res = query_db_first(query)

            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':
                i['lakier_na_sucho_pomiar'] = res['lakier_na_sucho_pomiar'] 
                if res['ocena_powierzchni_bp'] == '1':
                    i['ocena_powierzchni_bp'] = 'OK'
                else:
                    i['ocena_powierzchni_bp'] = 'NOK'
                if res['ocena_powierzchni_cnc'] == '1':
                    i['ocena_powierzchni_cnc'] = 'OK'
                else:
                    i['ocena_powierzchni_cnc'] = 'NOK'
                if res['jakosc_struktury'] == '1':
                    i['jakosc_struktury'] = 'OK'
                else:
                    i['jakosc_struktury'] = 'NOK'
                if res['czystosc'] == '1':
                    i['czystosc'] = 'OK'
                else:
                    i['czystosc'] = 'NOK'
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer

            else:
                i['lakier_na_sucho_pomiar'] = '-'
                i['ocena_powierzchni_bp'] = '-'
                i['ocena_powierzchni_cnc'] = '-'
                i['jakosc_struktury'] = '-'
                i['czystosc'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['customer'] = customer

        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
        return render_template("qa_report_mec_fr.html", items=final_list_of_results_filtred_by_sn, customer=customer)

    elif customer == 'Mitsubishi Spain':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `mitsubishi_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':
                if res['kontury'] == '1':
                    i['kontury'] = 'OK'
                else:
                    i['kontury'] = 'NOK'
                if res['ocena_powierzchni'] == '1':
                    i['ocena_powierzchni'] = 'OK'
                else:
                    i['ocena_powierzchni'] = 'NOK'

                i['polysk_ral_9005'] = res['polysk_ral_9005']
                i['polysk_mitsu_green'] = res['polysk_mitsu_green']
                i['kolor1'] = res['kolor1']
                i['kolor1_wynik'] = res['kolor1_wynik']
                i['kolor2'] = res['kolor2']
                i['kolor2_wynik'] = res['kolor2_wynik']
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer

            else:
                i['polysk_ral_9005'] = '-'
                i['polysk_mitsu_green'] = '-'
                i['kolor1'] = '-'
                i['kolor1_wynik'] = '-'
                i['kolor2'] = '-'
                i['kolor2_wynik'] = '-'
                i['kontury'] = '-'
                i['ocena_powierzchni'] = '-'
                i['result'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['customer'] = customer

        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
        return render_template("qa_report_mit_sp.html", items=final_list_of_results, customer=customer)

    elif customer == 'Mitsubishi Finland':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `mitsubishi_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result_inspection'] = res['result']
            except TypeError:
                i['result_inspection'] = '-'

            if i['result_inspection'] != '-':
                if res['kontury'] == '1':
                    i['kontury'] = 'OK'
                else:
                    i['kontury'] = 'NOK'
                if res['ocena_powierzchni'] == '1':
                    i['ocena_powierzchni'] = 'OK'
                else:
                    i['ocena_powierzchni'] = 'NOK'

                i['polysk_ral_9005'] = res['polysk_ral_9005']
                i['polysk_mitsu_green'] = res['polysk_mitsu_green']
                i['kolor1'] = res['kolor1']
                i['kolor1_wynik'] = res['kolor1_wynik']
                i['kolor2'] = res['kolor2']
                i['kolor2_wynik'] = res['kolor2_wynik']
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['customer'] = customer

            else:
                i['polysk_ral_9005'] = '-'
                i['polysk_mitsu_green'] = '-'
                i['kolor1'] = '-'
                i['kolor1_wynik'] = '-'
                i['kolor2'] = '-'
                i['kolor2_wynik'] = '-'
                i['kontury'] = '-'
                i['ocena_powierzchni'] = '-'
                i['result'] = '-'
                i['operator'] = '-'
                i['czas'] = '-'
                i['customer'] = customer

        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
        return render_template("qa_report_mit_fin.html", items=final_list_of_results_filtred_by_sn, customer=customer)

    elif customer == 'Still':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `still_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result'] = res['result_inspection']
            except TypeError:
                i['result'] = '-'

            if i['result'] != '-':
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['result'] = res['result_inspection']
                if res['trail'] == '1':
                    i['trail'] = 'TAK'
                else:
                    i['trail'] = 'NIE'
              
                if res['defect'] == None:
                    i['defect'] = '-'
                else:
                    i['trail'] = res['defect']
             
                i['customer'] = customer

            else:
                i['operator'] = '-'
                i['czas'] = '-'
                i['result'] = '-'
                i['defect'] = '-'
                i['customer'] = customer
        
        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
        return render_template("qa_report_still.html", items=final_list_of_results_filtred_by_sn, customer=customer)

    elif customer == 'Kion Polska':
        for i in final_list_of_results:
            try:
                query = "SELECT * FROM `kion_inspection` WHERE sn=" + str(i['sn']) + " AND ids=" + str(i['id']) + " ORDER BY id DESC"
            except IndexError:
                continue
            res = query_db_first(query)
    
            try:
                i['result'] = res['result_inspection']
            except TypeError:
                i['result'] = '-'

            if i['result'] != '-':
                i['operator'] = res['operator']
                i['czas'] = res['czas']
                i['result'] = res['result_inspection']
                if res['trail'] == '1':
                    i['trail'] = 'TAK'
                else:
                    i['trail'] = 'NIE'
              
                if res['defect'] == None:
                    i['defect'] = '-'
                else:
                    i['trail'] = res['defect']
             
                i['customer'] = customer

            else:
                i['operator'] = '-'
                i['czas'] = '-'
                i['result'] = '-'
                i['defect'] = '-'
                i['customer'] = customer
        
        final_list_of_results_filtred_by_sn = filter_by_sn_and_prefix(final_list_of_results, int(sn), str(prefix))
        return render_template("qa_report_kion.html", items=final_list_of_results_filtred_by_sn, customer=customer)
    
    else:
        return render_template("no_form.html")

@app.route("/mark_kion_polska_as_qa_ok", methods=["POST"])
def mark_kion_polska_as_qa_ok():
    data = request.get_json()
    operator = session['user']

    for i in data:
        ids = i['id']
        prefix, sn = str(i['SerialNo']).split('-')
        product = i['Product']
        customer = i['Customer']
        trail = i['Trail']
        if trail == 'Tak':
            trail = 1
        else:
            trail = 0

        query = "SELECT * FROM `kion_inspection` WHERE prefix='" + prefix + "' AND sn=" + sn + " AND ids=" + str(ids) + "  AND result_inspection in ('0', '1')"
        result = query_db(query)
        if len(result) > 0:
            print('skiped', prefix, '-', sn, 'from marking as qa_ok')
            continue

        query = "INSERT INTO `kion_inspection` (`ids`, `sn`, `prefix`, `customer`, `product`, `result_inspection`, `trail`, `operator`) VALUES (" + str(ids) + "," + str(sn) + ",'" + prefix + "','" + customer + "','" + product + "','1','" + str(trail)  + "','" + operator + "');"
        query_update(query)
        history_qa(ids, sn, prefix, 'qa_ok', operator)

    return jsonify({"status": "ok"})

@app.route("/mark_kion_polska_as_qa_nok", methods=["POST"])
def mark_kion_polska_as_qa_nok():
    data = json.loads(request.form.get("rows_data"))
    defect_type = request.form.get("defect_type")
    operator = session['user']
    inne = request.form.get("defect_other")

    if defect_type == 'inne':
        defect = inne
    else:
        defect = defect_type

    for i in data:
        ids = i['id']
        prefix, sn = str(i['SerialNo']).split('-')
        product = i['Product']
        customer = i['Customer']
        trail = i['Trail']
        if trail == 'Tak':
            trail = 1
        else:
            trail = 0

        #query = "SELECT * FROM `still_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn + " AND result_inspection in ('0', '1')"
        query = "SELECT * FROM `kion_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn + " AND ids=" + str(ids) + "  AND result_inspection in ('0', '1')"

        result = query_db(query)
        if len(result) > 0:
            print('skiped', prefix, '-', sn, 'from marking as qa_nok')
            continue

        query = "INSERT INTO `kion_inspection` (`ids`, `sn`, `prefix`, `customer`, `product`, `result_inspection`, `defect`, `trail`, `operator`) VALUES (" + str(ids) + "," + str(sn) + ",'" + prefix + "','" + customer + "','" + product + "','0', '" + defect + "', '" + str(trail)  + "','" + operator + "');"
        query_update(query)
        history_qa(ids, sn, prefix, 'qa_nok', operator)

    return redirect(request.referrer)

@app.route("/mark_still_as_qa_ok", methods=["POST"])
def mark_still_as_qa_ok():
    data = request.get_json()
    operator = session['user']

    for i in data:
        ids = i['id']
        prefix, sn = str(i['SerialNo']).split('-')
        product = i['Product']
        customer = i['Customer']
        trail = i['Trail']
        if trail == 'Tak':
            trail = 1
        else:
            trail = 0

        query = "SELECT * FROM `still_inspection` WHERE prefix='" + prefix + "' AND sn=" + sn + " AND ids=" + str(ids) + "  AND result_inspection in ('0', '1')"
        result = query_db(query)
        if len(result) > 0:
            print('skiped', prefix, '-', sn, 'from marking as qa_ok')
            continue

        query = "INSERT INTO `still_inspection` (`ids`, `sn`, `prefix`, `customer`, `product`, `result_inspection`, `trail`, `operator`) VALUES (" + str(ids) + "," + str(sn) + ",'" + prefix + "','" + customer + "','" + product + "','1','" + str(trail)  + "','" + operator + "');"
        query_update(query)
        history_qa(ids, sn, prefix, 'qa_ok', operator)

    return jsonify({"status": "ok"})


@app.route("/mark_still_as_qa_can", methods=["POST"])
def mark_still_as_qa_can():
    data = request.get_json()
    operator = session['user']

    for i in data:
        prefix, sn = str(i['SerialNo']).split('-')
        ids = i['id']
        trail = i['Trail']
        if trail == 'Tak':
            trail = 1
        else:
            trail = 0

        #query = "SELECT * FROM `still_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn + " AND result_inspection in ('0', '1')"
        query = "SELECT * FROM `still_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn + " AND ids=" + str(ids) + "  AND result_inspection in ('0', '1')"
        result = query_db(query)
        if len(result) == 0:
            print('skiped', prefix, '-', sn, 'from marking as canceled')
            continue

        #query = "UPDATE `still_inspection` SET `result_inspection`=NULL, `defect`=NULL, `operator`='"+ operator + "', czas=current_timestamp() WHERE `prefix`='" + prefix + "' AND sn=" + sn 
        query = "DELETE FROM `still_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn 
        query_update(query)
        history_qa(ids, sn, prefix, 'qa_canceled', operator)

    return jsonify({"status": "ok"})

@app.route("/mark_still_as_qa_nok", methods=["POST"])
def mark_still_as_qa_nok():
    data = json.loads(request.form.get("rows_data"))
    defect_type = request.form.get("defect_type")
    operator = session['user']
    inne = request.form.get("defect_other")

    if defect_type == 'inne':
        defect = inne
    else:
        defect = defect_type

    for i in data:
        ids = i['id']
        prefix, sn = str(i['SerialNo']).split('-')
        product = i['Product']
        customer = i['Customer']
        trail = i['Trail']
        if trail == 'Tak':
            trail = 1
        else:
            trail = 0

        #query = "SELECT * FROM `still_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn + " AND result_inspection in ('0', '1')"
        query = "SELECT * FROM `still_inspection` WHERE `prefix`='" + prefix + "' AND sn=" + sn + " AND ids=" + str(ids) + "  AND result_inspection in ('0', '1')"

        result = query_db(query)
        if len(result) > 0:
            print('skiped', prefix, '-', sn, 'from marking as qa_nok')
            continue

        query = "INSERT INTO `still_inspection` (`ids`, `sn`, `prefix`, `customer`, `product`, `result_inspection`, `defect`, `trail`, `operator`) VALUES (" + str(ids) + "," + str(sn) + ",'" + prefix + "','" + customer + "','" + product + "','0', '" + defect + "', '" + str(trail)  + "','" + operator + "');"
        query_update(query)
        history_qa(ids, sn, prefix, 'qa_nok', operator)

    return redirect(request.referrer)

@app.route("/raport_foundry/<arg>", methods=['POST', 'GET'])
def raport_foundry(arg):
    if arg == '1':
        cur = mysql.new_cursor()
        query = 'SELECT tab2.nazwa_produktu, tab1.production_stage, tab1.operator, tab1.czas FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.czas BETWEEN( SELECT CURRENT_DATE() + INTERVAL 360 MINUTE) AND( SELECT CURRENT_DATE() + INTERVAL 840 MINUTE)'
        res = query_db(query)
        for i in res:
            name = i['nazwa_produktu']
            status = i['production_stage']
            operator = i['operator']
            shift = '1'
            time = i['czas']
            query = "INSERT INTO foundry_shifts(name, status, operator, shift, time) VALUES('" +  name  + "','" + status  + "','" + operator + "','" + str(shift) + "','" + str(time) + "')"
            cur.execute(query)
        mysql.connection.commit()
        cur.close()
        return "Shift I report generated successfuly"

    if arg == '2':
        cur = mysql.new_cursor()
        query = 'SELECT tab2.nazwa_produktu, tab1.production_stage, tab1.operator, tab1.czas FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.czas BETWEEN (SELECT CURRENT_DATE() + INTERVAL 841 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 1320 MINUTE)'
        res = query_db(query)
        for i in res:
            name = i['nazwa_produktu']
            status = i['production_stage']
            operator = i['operator']
            shift = '2'
            time = i['czas']
            query = "INSERT INTO foundry_shifts(name, status, operator, shift, time) VALUES('" +  name  + "','" + status  + "','" + operator + "','" + str(shift) + "','" + str(time) + "')"
            cur.execute(query)
        mysql.connection.commit()
        cur.close()
        return "Shift II report generated successfuly"
      
    if arg == '3':
        cur = mysql.new_cursor()
        query = 'SELECT tab2.nazwa_produktu, tab1.production_stage, tab1.operator, tab1.czas FROM `lista_formowania_historia_v2` tab1 JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id WHERE tab1.czas BETWEEN(SELECT CURRENT_DATE() - INTERVAL 120 MINUTE) AND (SELECT CURRENT_DATE() + INTERVAL 360 MINUTE)'
        res = query_db(query)
        for i in res:
            name = i['nazwa_produktu']
            status = i['production_stage']
            operator = i['operator']
            shift = '3'
            time = i['czas']
            query = "INSERT INTO foundry_shifts(name, status, operator, shift, time) VALUES('" +  name  + "','" + status  + "','" + operator + "','" + str(shift) + "','" + str(time) + "')"
            cur.execute(query)
        mysql.connection.commit()
        cur.close()
        return "Shift III report generated successfuly"
        
    else:
        return "Bad argument!"   


@app.route("/cooling", methods=['POST', 'GET'])
def cooling():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #oblicz_czas_studzenia()
        formy_zalane = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'casted' OR item_status LIKE 'ready_for_cooling' ORDER BY data_ostatniej_modyfikacji DESC LIMIT 200")
        formy_zalane = wyswietl_czasy_studzenia_i_chlodzenia(formy_zalane)
        return render_template("cooling.html", formy_zalane=formy_zalane)
        

@app.route("/knockout", methods=['POST', 'GET'])
def knockout():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        # query1 = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.item_status, tab1.flask1, tab1.flask2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab1.data_ostatniej_modyfikacji, tab1.komentarz, tab1.komentarz_formowanie, tab1.komentarz_rdzeniarnia, tab1.zmodyfikowane_przez, tab1.dodane_przez, tab1.data_dodania, tab1.nr_kadzi FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'knockout' LIMIT 200")
        # query1 = replace_none_values(query1)
        oblicz_czas_chlodzenia()
        formy_do_wybicia = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'cooling' OR item_status LIKE 'knockout' LIMIT 200")
        formy_do_wybicia = wyswietl_czasy_studzenia_i_chlodzenia(formy_do_wybicia)
        #formy_wybite = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'grinding' LIMIT 200")
        #return render_template("knockout_operator_view.html", items_cooling=formy_do_wybicia, items_grinding=formy_wybite) 
        return render_template("knockout.html", items_cooling=formy_do_wybicia) 

@app.route("/grinding", methods=['POST', 'GET'])
def grinding():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:

        items = []
        knockout = query_db("SELECT produkt_id id FROM `lista_formowania_historia_v2` WHERE production_stage = 'knockout' ORDER by id desc LIMIT 200")

        for i in knockout:
            lista = generete_serials(i['id'])
            for k in lista:
                k.append(i['id'])
                item = query_db('SELECT tab1.id, tab1.nazwa_produktu, tab1.trail, tab1.alias, tab2.waga_zeliwa, tab2.customer FROM `lista_formowania_v2` tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.id=' + str(i['id']))
                item[0]['Prefix'] = k[0]
                item[0]['sn'] = k[1]
                items.append(item[0])

        lista_sn_obrobione = query_db("SELECT sn, prefix, item_id id FROM `grinding`")
        przeciwwagi_do_oczyszczenia = filtruj_items(lista_sn_obrobione, items)
        return render_template("grinding.html", items=przeciwwagi_do_oczyszczenia)
  

@app.route("/grinding_done", methods=['POST', 'GET'])
def grinding_done():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        items = query_db("SELECT * FROM `grinding` WHERE mode LIKE '0' OR mode LIKE '1' OR mode LIKE '2' Order by id DESC LIMIT 1000")
        operators = query_db("SELECT DISTINCT operator FROM `grinding`")
        return render_template("grinding_done.html", items=items, operators=operators, now=datetime.datetime.now()) 

@app.route("/grinding_rework", methods=['POST', 'GET'])
def grinding_rework():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        items = query_db("SELECT * FROM `grinding` WHERE mode LIKE '3' OR mode LIKE '4' Order by id DESC LIMIT 1000")
        operators = query_db("SELECT DISTINCT operator FROM `grinding`")
        return render_template("grinding_rework.html", items=items, now=datetime.datetime.now(), operators=operators) 

@app.route("/mark_as_grinded/<id>", methods=['POST'])
def mark_as_grinded(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_id = str(request.form['item_id'])
        item_prefix = str(request.form['item_prefix'])
        item_sn = str(request.form['item_sn'])
        item_nazwa_produktu = str(request.form['item_nazwa_produktu'])
        item_trail = str(request.form['item_trail'])
        item_waga_zeliwa = str(request.form['item_waga_zeliwa'])
        item_customer = str(request.form['item_customer'])
        operator = session['user']
        alias = str(request.form['item_alias'])
        if alias in (None, 'None', 'Null', ''):
            alias = '-'
        else:
            alias = alias
        grinding_mode = str(request.form['grinding_mode'])

        query = "SELECT * FROM `grinding` WHERE prefix='" + item_prefix + "' AND sn=" + item_sn + " AND alias='" + alias + "'"
        check = len(query_db(query))
        if  int(check) > 0:
            flash(f"Odlew o numerze seryjnym: {item_prefix}-{item_sn} został już oznaczony jako oszlifowany!")
            return redirect(url_for("grinding"))
        else:
            query = "INSERT INTO `grinding` (`item_id`, `prefix`, `sn`, `nazwa_produktu`, `trail`, `waga_zeliwa`, `mode`, `klient`, `operator`, `alias`) VALUES (" + str(item_id) + ",'" + str(item_prefix) + "'," + str(item_sn) + ",'" + str(item_nazwa_produktu) + "'," + str(item_trail) + "," + str(item_waga_zeliwa) + ",'" + str(grinding_mode) +  "','" + item_customer + "','" + operator + "','" + alias + "');"
            query_update(query)
            history_qa(item_id, item_sn, item_prefix, 'grinding', operator)
            return redirect(url_for("grinding"))

@app.route("/edit_grinding_item_dg/<id>", methods=['POST'])
def edit_grinding_item_dg(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_id = str(request.form['item_id'])
        item_prefix = str(request.form['item_prefix'])
        item_sn = str(request.form['item_sn'])
        operator = str(request.form['grinding_operator'])

        new_grinding_datetime = request.form.get("new_grinding_datetime")
        new_grinding_datetime_obj = datetime.datetime.strptime(new_grinding_datetime, "%Y-%m-%dT%H:%M")
        new_grinding_datetime_sql = new_grinding_datetime_obj.strftime("%Y-%m-%d %H:%M:%S")
        
        # print(item_id, item_prefix, item_sn, operator, new_grinding_datetime_sql)
        sql = "UPDATE `grinding` SET operator='" + operator + "', czas='" + new_grinding_datetime_sql + "' WHERE prefix='" + item_prefix + "' AND sn=" + item_sn + " AND item_id=" + str(item_id)
        query_update(sql)
        history_qa(item_id, item_sn, item_prefix, 'grinding-done-edited', operator)
        return redirect(url_for("grinding_done"))

@app.route("/edit_grinding_item_rew/<id>", methods=['POST'])
def edit_grinding_item_rew(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_id = str(request.form['item_id'])
        item_prefix = str(request.form['item_prefix'])
        item_sn = str(request.form['item_sn'])
        operator = str(request.form['grinding_operator'])

        new_grinding_datetime = request.form.get("new_grinding_datetime")
        new_grinding_datetime_obj = datetime.datetime.strptime(new_grinding_datetime, "%Y-%m-%dT%H:%M")
        new_grinding_datetime_sql = new_grinding_datetime_obj.strftime("%Y-%m-%d %H:%M:%S")
        
        # print(item_id, item_prefix, item_sn, operator, new_grinding_datetime_sql)
        sql = "UPDATE `grinding` SET operator='" + operator + "', czas='" + new_grinding_datetime_sql + "' WHERE prefix='" + item_prefix + "' AND sn=" + item_sn + " AND item_id=" + str(item_id)
        
        print(sql)
        query_update(sql)
        history_qa(item_id, item_sn, item_prefix, 'grinding-rework-edited', operator)
        return redirect(url_for("grinding_rework"))

@app.route("/mark_as_grinded_repair/<id>", methods=['POST'])
def mark_as_grinded_repair(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_id = str(request.form['item_id'])
        item_prefix = str(request.form['item_prefix'])
        item_sn = str(request.form['item_sn'])
        item_nazwa_produktu = str(request.form['item_nazwa_produktu'])
        item_trail = str(request.form['item_trail'])
        item_waga_zeliwa = str(request.form['item_waga_zeliwa'])
        item_customer = str(request.form['item_customer'])
        operator = session['user']
        grinding_mode = str(request.form['grinding_mode'])
        alias = str(request.form['item_alias'])
        if alias in (None, 'None', 'Null', ''):
            alias = '-'
        else:
            alias = alias

        query = "INSERT INTO `grinding` (`item_id`, `prefix`, `sn`, `nazwa_produktu`, `trail`, `waga_zeliwa`, `mode`, `klient`, `operator`, `alias`) VALUES (" + str(item_id) + ",'" + str(item_prefix) + "'," + str(item_sn) + ",'" + str(item_nazwa_produktu) + "'," + str(item_trail) + "," + str(item_waga_zeliwa) + ",'" + str(grinding_mode) +  "','" + item_customer + "','" + operator + "','" + alias + "');"
        query_update(query)
        history_qa(item_id, item_sn, item_prefix, 'grinding-repaired', operator)
        return redirect(url_for("grinding_done"))

# @app.route("/buffer", methods=['POST', 'GET'])
# def buffer():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         #query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'buffer' ORDER BY data_ostatniej_modyfikacji DESC LIMIT 200")
#         query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.item_status, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab1.data_ostatniej_modyfikacji, tab1.komentarz, tab1.komentarz_formowanie, tab1.komentarz_rdzeniarnia, tab1.zmodyfikowane_przez, tab1.dodane_przez, tab1.data_dodania, tab1.nr_kadzi FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status = 'buffer' LIMIT 200")
#         query = replace_none_values(query)
#         return render_template("buffer.html", items=query) 

@app.route("/products", methods=['POST', 'GET'])
@login_required(mode='biuro')
@ip_required('192.168.1.0/24', '192.168.170.0/24', '192.168.130.0/24')
def products():
    query = query_db("SELECT * FROM produkty WHERE item_status='active' ORDER BY nazwa DESC")    
    query2 = query_db("SELECT skrzynie_name FROM flasks ORDER BY skrzynie_name DESC")  
    return render_template("products.html", items=query, flasks=query2) 
    
@app.route("/product_details/<id>", methods=['POST', 'GET'])
def product_details(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        query = query_db("SELECT * FROM produkty WHERE item_status='active' AND produkt_id=" + str(id))
        query2 = query_db("SELECT tab2.nazwa nazwa1, tab3.nazwa nazwa2, tab4.nazwa nazwa3, tab5.nazwa nazwa4, tab2.id id_model1, tab3.id id_model2, tab4.id id_model3, tab5.id id_model4 FROM produkty tab1 LEFT JOIN tag_modele tab2 ON tab1.id_model1 = tab2.id LEFT JOIN tag_modele tab3 ON tab1.id_model2 = tab3.id LEFT JOIN tag_modele tab4 ON tab1.id_model3 = tab4.id LEFT JOIN tag_modele tab5 ON tab1.id_model4 = tab5.id WHERE tab1.produkt_id=" + str(id))
        query3 = query_db("SELECT skrzynia1, skrzynia2, skrzynia3, skrzynia4 FROM produkty WHERE item_status='active' AND produkt_id=" + str(id))
        query2 = replace_nulls(query2)
        query4 = '''
            SELECT
                tab2.skrzynie_name flask1_name,
                tab2.dim_x flask1_dim_x,
                tab2.dim_y flask1_dim_y,
                tab2.dim_z flask1_dim_z,
                tab2.type  flask1_type,
                tab3.skrzynie_name flask2_name,
                tab3.dim_x flask2_dim_x,
                tab3.dim_y flask2_dim_y,
                tab3.dim_z flask2_dim_z,
                tab3.type  flask2_type,
                tab4.skrzynie_name flask3_name,
                tab4.dim_x flask3_dim_x,
                tab4.dim_y flask3_dim_y,
                tab4.dim_z flask3_dim_z,
                tab4.type  flask3_type,
                tab5.skrzynie_name flask4_name,
                tab5.dim_x flask4_dim_x,
                tab5.dim_y flask4_dim_y,
                tab5.dim_z flask4_dim_z,
                tab5.type  flask4_type
            FROM
                produkty AS tab1
            LEFT JOIN flasks AS tab2
            ON
                tab1.skrzynia1 = tab2.skrzynie_name
            LEFT JOIN flasks AS tab3
            ON
                tab1.skrzynia2 = tab3.skrzynie_name
            LEFT JOIN flasks AS tab4
            ON
                tab1.skrzynia3 = tab4.skrzynie_name
            LEFT JOIN flasks AS tab5
            ON
                tab1.skrzynia4 = tab5.skrzynie_name
            WHERE
                tab1.produkt_id ='''+ str(id)
        query4 = query_db(query4)
        query4 = replace_nulls(query4)
        query5 = query_db("SELECT skrzynie_name FROM flasks ORDER BY skrzynie_name asc") 
        query6 = query_db("SELECT * FROM materialy_ogniotrwale")
        query7 = query_db("SELECT tab1.id as id, tab1.produkt_id, tab1.material_id, tab1.ilosc, tab2.id as id2, tab2.typ, tab2.nazwa, tab2.jednostka FROM `materialy_ogniotrwale_produkty` tab1 LEFT JOIN materialy_ogniotrwale tab2 ON tab1.material_id = tab2.id WHERE tab1.produkt_id=" + str(id))
        query8 = query_db("SELECT ID, nazwa FROM tag_modele ORDER BY id asc")
        query9 = query_db("SELECT id_model1, id_model2, id_model3, id_model4 FROM produkty WHERE produkt_id=" + str(id))
        query10 = query_db("SELECT customer FROM produkty WHERE produkt_id=" + str(id))
        query11 = query_db("SELECT customer FROM customers")
        list_of_consumers = remove_cutomer(query10, query11)
        return render_template("product_details.html", prod_details=query, pattern=query2, flasks=query4, skrzynie=query5, ref_id=id, skrzynie_def=query3[0], meterials=query6, materials_produkts=query7, modele=query8, model_def=query9[0], customer=query10[0], customers=list_of_consumers)
@app.route("/product_details_operator/<id>", methods=['POST', 'GET'])
def product_details_operator(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        query = query_db("SELECT id_produktu FROM lista_formowania_v2 WHERE id=" + str(id))
        res = query[0]['id_produktu']
        query1 = query_db("SELECT * FROM lista_formowania_v2 WHERE id=" + str(id))
        query2 = query_db("SELECT tab1.id as id, tab1.produkt_id, tab1.material_id, tab1.ilosc, tab2.id as id2, tab2.typ, tab2.nazwa, tab2.jednostka FROM `materialy_ogniotrwale_produkty` tab1 LEFT JOIN materialy_ogniotrwale tab2 ON tab1.material_id = tab2.id WHERE tab1.produkt_id=" + str(res))
        materials_without_filter = []
        for i in query2:
            if i['typ'] == 'Filtr':
                continue
            else:
                materials_without_filter.append(i)
        return render_template("product_details_operator.html", products=query1, materials=materials_without_filter)
    
@app.route("/product_details_operator_man/<id>", methods=['POST', 'GET'])
def product_details_operator_man(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        query = query_db("SELECT id_produktu FROM lista_formowania_v2 WHERE id=" + str(id))
        res = query[0]['id_produktu']
        query1 = query_db("SELECT * FROM lista_formowania_v2 WHERE id=" + str(id))
        query2 = query_db("SELECT tab1.id as id, tab1.produkt_id, tab1.material_id, tab1.ilosc, tab2.id as id2, tab2.typ, tab2.nazwa, tab2.jednostka FROM `materialy_ogniotrwale_produkty` tab1 LEFT JOIN materialy_ogniotrwale tab2 ON tab1.material_id = tab2.id WHERE tab1.produkt_id=" + str(res))
        return render_template("product_details_operator_man.html", products=query1, materials=query2)

@app.route("/product_fp_materials/<id>", methods=['POST', 'GET'])
def product_fp_materials(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        query = query_db("SELECT nazwa FROM produkty WHERE item_status='active' AND produkt_id=" + str(id))
        query2 = query_db("SELECT * FROM materialy_ogniotrwale")
        query3 = query_db("SELECT tab1.id as id, tab1.produkt_id, tab1.material_id, tab1.ilosc, tab2.id as id2, tab2.typ, tab2.nazwa, tab2.jednostka FROM `materialy_ogniotrwale_produkty` tab1 LEFT JOIN materialy_ogniotrwale tab2 ON tab1.material_id = tab2.id WHERE tab1.produkt_id=" + str(id))
        return render_template("product_fp_materials.html", name=query, materialy=query2, items=query3) 
    
@app.route("/edit_flask_in_produkt/<id>", methods=['POST', 'GET'])
def edit_flask_in_produkt(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        skrzynia1 =  str(request.form['skrzynia1']).strip()
        skrzynia2 =  str(request.form['skrzynia2']).strip()
        skrzynia3 =  str(request.form['skrzynia3']).strip()
        skrzynia4 =  str(request.form['skrzynia4']).strip()
        if skrzynia1 == '' or skrzynia1 == None:
            skrzynia1 = ''
        if skrzynia2 == '' or skrzynia2 == None:
            skrzynia2 = ''
        if skrzynia3 == '' or skrzynia3 == None:
            skrzynia3 = ''
        if skrzynia4 == '' or skrzynia4 == None:
            skrzynia4 = ''
        query = ("UPDATE produkty SET skrzynia1='" + str(skrzynia1) + "', skrzynia2='" + str(skrzynia2) + "', skrzynia3='" + str(skrzynia3) + "', skrzynia4='" + str(skrzynia4) + "' WHERE produkt_id=" + str(id))
        query_update(query)
        r = query_update(query)
        if r:
            flash(f'Zapis poprawny!')
            return redirect(url_for("product_details", id=id))
        else:
            flash(f'Błąd podczas zapisu!')
            return redirect(url_for("product_details", id=id))
    
@app.route("/edit_model_in_produkt/<id>", methods=['POST', 'GET'])
def edit_model_in_produkt(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        model1 =  str(request.form['model1']).strip()
        model2 =  str(request.form['model2']).strip()
        model3 =  str(request.form['model3']).strip()
        model4 =  str(request.form['model4']).strip()
        if model1 == '' or model1 == 'None' or model1 == None:
            model1 = 'Null'
        if model2 == '' or model2 == 'None' or model2 == None:
            model2 = 'Null'
        if model3 == '' or model3 == 'None' or model3 == None:
            model3 = 'Null'
        if model4 == '' or model4 == 'None' or model4 == None:
            model4 = 'Null'
        query = "UPDATE produkty SET id_model1=" + str(model1) + ", id_model2=" + str(model2) + ", id_model3=" + str(model3) + ", id_model4=" + str(model4) + " WHERE produkt_id=" + str(id)
        r = query_update(query)
        if r:
            flash(f'Zapis poprawny!')
            return redirect(url_for("product_details", id=id))
        else:
            flash(f'Błąd podczas zapisu!')
            return redirect(url_for("product_details", id=id))
    

    
@app.route("/edit_data_in_produkt/<id>", methods=['POST', 'GET'])
def edit_data_in_produkt(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        sztuk_w_formie =  str(request.form['sztuk_w_formie']).strip()
        nazwa =  str(request.form['nazwa']).strip()
        prefix =  str(request.form['prefix']).strip().upper()
        if len(prefix) == 0:
            prefix = 'XX'
        elif len(prefix) > 2:
            prefix = prefix[:2]
        else:
            prefix = prefix
        waga_zeliwa =  str(request.form['waga_zeliwa']).strip()
        waga_piasku =  str(request.form['waga_piasku']).strip()
        czas_studzenia =  str(request.form['czas_studzenia']).strip()
        dni_do_wybicia =  str(request.form['dni_do_wybicia']).strip()
        manual_forming =  str(request.form['manual_forming']).strip()
        customer =  str(request.form['customer']).strip()
        points =  str(request.form['points']).strip()
        if sztuk_w_formie == '' or sztuk_w_formie == 'None' or sztuk_w_formie == None:
            sztuk_w_formie = 0
        if nazwa == '' or nazwa == 'None' or nazwa == None:
            nazwa = ''
        if waga_zeliwa  == '' or waga_zeliwa  == 'None' or waga_zeliwa  == None:
            waga_zeliwa  = 0
        if waga_piasku == '' or waga_piasku == 'None' or waga_piasku == None:
            waga_piasku = 0
        if czas_studzenia == '' or czas_studzenia == 'None' or czas_studzenia == None:
            czas_studzenia = 0
        if dni_do_wybicia == '' or dni_do_wybicia == 'None' or dni_do_wybicia == None:
            dni_do_wybicia = 0
        if points == '' or points == 'None' or points == None:
            points = 1
        query = "UPDATE produkty SET sztuk=" + str(sztuk_w_formie) + ", nazwa='" + str(nazwa) + "', prefix='" + str(prefix) + "', waga_zeliwa=" + str(waga_zeliwa) + ", waga_piasku=" + str(waga_piasku) + ", czas_studzenia=" + str(czas_studzenia) + ", dni_do_wybicia=" + str(dni_do_wybicia) + ", manual_forming='" + str(manual_forming) + "', grinding_points='" + str(points) +  "', customer='" + customer + "' WHERE produkt_id=" + str(id) 
        r = query_update(query)
        if r:
            flash(f'Zapis poprawny! {nazwa}')
            return redirect(url_for("product_details", id=id))
        else:
            flash(f'Błąd podczas zapisu! {nazwa}')
            return redirect(url_for("product_details", id=id))

    
@app.route("/add_fp_material/<id>", methods=['POST', 'GET'])
def add_fp_material(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        material = str(request.form['material'])
        material = material.replace("'", "")
        ilosc = str(request.form['ilosc'])
        ilosc = ilosc.replace("'", "")
        query_update("INSERT INTO materialy_ogniotrwale_produkty(produkt_id, material_id, ilosc) VALUES(" + str(id) + "," + str(material) + "," + str(ilosc)+ ")")
        return redirect(url_for("product_details", id=id))

@app.route("/del_fp_material/<id>", methods=['POST', 'GET'])
def del_fp_material(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:     
        mat_to_del = str(request.form['mat_to_del'])
        mat_to_del = mat_to_del.replace("'", "")
        query = "DELETE FROM materialy_ogniotrwale_produkty WHERE id=" + str(int(mat_to_del)) + " AND produkt_id=" + str(int(id))
        query_update(query)
        return redirect(url_for("product_details", id=id))

@app.route("/database", methods=['POST', 'GET'])
def database():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db('SELECT p.produkt_id id_odlewu, p.nazwa nazwa_odlewu, p.id_model1 id_model1, p.id_model2 id_model2, p1.nazwa model_1, p2.nazwa model_2, p3.SAP_index1 SAP_index_1, p3.SAP_index2 SAP_index_2, p3.SAP_index3 SAP_index_3, p3.SAP_index4 SAP_index_4, p3.SAP_index5 SAP_index_5 FROM produkty p LEFT JOIN tag_modele p1 ON p.id_model1 = p1.ID LEFT JOIN tag_modele p2 ON p.id_model2 = p2.ID LEFT JOIN produkty_koncowe p3 ON p.produkt_id = p3.id_produktu ORDER BY produkt_id ASC ')
        return render_template("database.html", items=query) 

@app.route("/patterns", methods=['POST', 'GET'])
def patterns():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db('SELECT * FROM tag_modele')
        return render_template("patterns.html", items=query) 

@app.route("/id_model_error", methods=['POST', 'GET'])
def id_model_error():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        nazwa = 'test'
        return render_template("id_model_error.html", nazwa = nazwa) 

#######################################################
################# Widoki Akordy  ####################
#######################################################

@app.route("/grinding_sheefts", methods=['GET'])
def grinding_sheefts():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:

        #casts = query_db("SELECT nazwa, produkt_id, grinding_points FROM produkty")
        res = query_db("SELECT * FROM `grinding_sheefts` WHERE status='active'")
        return render_template("grinding_sheefts.html", items=res) 

@app.route("/search_casting_item", methods=['POST'])
def grinding_sheefts_search():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        item = str(request.form['search'])
        item = item.replace("'", "")
        res = query_db("SELECT tab1.* FROM `grinding_sheefts` tab1 LEFT JOIN akord tab2 ON tab1.id = tab2.akord_id WHERE tab2.status = 'active' AND tab2.comment LIKE '" + item + "'")
        return render_template("grinding_sheefts_search.html", items=res, item=item) 

@app.route("/edit_akord/<id>", methods=['GET'])
def edit_akord(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        res = query_db("SELECT nazwa, grinding_points FROM produkty")
        op = query_db("SELECT name FROM operator_grinding WHERE status='active'")
        ent = query_db("SELECT * FROM akord WHERE status='active' AND akord_id=" + str(id))
        return render_template("edit_akord.html", items=res, operators=op, akords=ent, idx=id) 

@app.route("/add_akord_item/<id>", methods=['POST'])
def add_akord_item(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        operator = str(request.form['operator'])
        operator = operator.replace("'", "")
        produkt = str(request.form['produkt'])
        produkt = produkt.replace("'", "")
        factor = str(request.form['factor'])
        factor = factor.replace("'", "")
        parts = produkt.split("___")
        produkt = parts[0]
        points = parts[1]
        leader = session['user']
        comment_akord = str(request.form['comment_akord'])
        comment_akord = comment_akord.replace("'", "")
        uwagi = str(request.form['uwagi_akord'])
        uwagi = uwagi.replace("'", "")
        ip = request.remote_addr

        if points == 'None' or points == None:
            points = 0
        if factor == 'None' or factor == None or factor == '':
            factor = 1
        try:
            float(factor) >= 10
        except ValueError:
            flash(f'Nieprawidłowa wartość współczynika. Współczynik musi być liczbą dziesiętną z przedziału 1.00 - 9.99')
            return redirect(request.referrer)
        
        query_update("INSERT INTO akord(akord_id, operator, item, factor, points, leader, comment, uwagi) VALUES('" + str(id) + "','" + operator + "','" + produkt + "','" + str(factor) + "'," + str(points) + ",'" + leader + "','" + comment_akord + "','" + uwagi + "')")
        r = query_db("SELECT id FROM akord ORDER BY id desc LIMIT 1")
        try:
            item_id = r[0]['id']
        except IndexError:
            item_id = 0

        akord_history(leader, ip, 'akord_added', item_id)

        return redirect(request.referrer)



# @app.route("/edit_shipment/<id>", methods=['POST'])
# def edit_shipment(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE `shipments` SET status='inactive' WHERE id=" + str(id)
#         query_update(query)
#         return redirect(request.referrer)

@app.route("/add_akord", methods=['POST'])
def add_akord():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        # leader = str(request.form['leader'])
        # leader = leader.replace("'", "")
        data = str(request.form['data'])
        data = data.replace("'", "")
        zmiana = str(request.form['zmiana'])
        zmiana = zmiana.replace("'", "")
        leader = session['user']
        ip = request.remote_addr

        query_update("INSERT INTO grinding_sheefts(leader, data, sheeft) VALUES('" + leader + "','" + data + "'," + str(zmiana) + ")")

        r = query_db("SELECT id FROM grinding_sheefts ORDER BY id desc LIMIT 1")
        try:
            item_id = r[0]['id']
        except IndexError:
            item_id = 0
            
        akord_history(leader, ip, 'gr_sheefts_added', item_id)
        return redirect(request.referrer)

@app.route("/del_akord/<id>", methods=['POST'])
def del_akord(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        query_update("UPDATE grinding_sheefts SET status='inactive' WHERE id=" + str(id))
        leader = session['user']
        ip = request.remote_addr            
        akord_history(leader, ip, 'gr_sheefts_del', id)
        return redirect(request.referrer)

@app.route("/del_akord_entry/<id>", methods=['POST'])
def del_akord_entry(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    if session['user_id'] not in (25,26,27,28):
        flash(f'Access denided.')
        return redirect(url_for('login'))
    else:
        query_update("UPDATE akord SET status='inactive' WHERE id=" + str(id))
        leader = session['user']
        ip = request.remote_addr            
        akord_history(leader, ip, 'akord_del', id)
        return redirect(request.referrer)

@app.route("/akord")
def show_table():
 
    query = "SELECT operator as Operator, item as Productname, points as Points, factor Faktor, czas 'Time'  FROM `akord` WHERE status = 'active' AND akord_id = (SELECT id FROM grinding_sheefts WHERE status = 'active' ORDER by id desc LIMIT 1)"
    with mysql.connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            df = pd.DataFrame(rows, columns=columns)

    shift_data = query_db("SELECT * FROM `grinding_sheefts` WHERE status = 'active' ORDER BY id DESC LIMIT 1")
    data = shift_data[0]['data']
    data = str(data)[0:10]
    sheeft = shift_data[0]['sheeft']
    leader = query_db("SELECT name FROM operator_grinding WHERE function='leader' AND status='active' AND short='" + shift_data[0]['leader'] + "'")
    leader = leader[0]['name']
    score = query_db("SELECT operator, ROUND(SUM(points * factor), 2) suma FROM akord WHERE status = 'active' AND akord_id = (SELECT id FROM `grinding_sheefts` WHERE status = 'active' ORDER BY id DESC LIMIT 1) group by operator;")
    scores_table = generate_table_with_grinding_scores(score, leader)

    # Konwersja do HTML
    html_table = df.to_html(index=False, escape=False, border=1)

    html_page = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">

        <title>Wyniki zapytania SQL</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                padding: 20px;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
            }}
            th, td {{
                border: 1px solid #000;
                padding: 8px;
                text-align: left;
            }}
            th {{
                background-color: #f2f2f2;
            }}
        </style>
    <html>
        <h2>Raport:  </h2>
        {html_table}
    </html>
    """

    html_page_teams = f"""
    <html>
        <p style="font-size: 2rem"><u>Manual grinding report: {data} Shift: {sheeft} </u></p></br>
        {scores_table}
        <br>
        {html_table}
        </br>
        
    </html>
    """
    html_table = html_table.replace("\"", "'")
    pa_request(html_page_teams)
    return render_template_string(html_page_teams)

#######################################################
################# kontrola jakości  ###################
#######################################################

@app.route("/dashboard", methods=['POST', 'GET'])
def dashboard():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        if request.method == 'POST':
            n_items =  str(request.form['n_items']).strip()
        else:
            n_items = str(500)
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.id_model1 id_model1, tab1.id_model2 id_model2, tab1.id_model3 id_model3, tab1.id_model4 id_model4, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab1.broken, tab1.filtr, tab1.repeated, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id ORDER BY tab1.id DESC LIMIT " + n_items)
        query = replace_none_values(query)
        total = query_db("SELECT count(*) as n from lista_formowania_v2")
        formed = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'formed'")
        casted = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'casted'")
        knockout = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'knockout'")
        return render_template("dashboard.html", items=query, total=total[0]['n'], formed=formed[0]['n'], casted=casted[0]['n'], knockout=knockout[0]['n']) 


@app.route("/quality", methods=['POST', 'GET'])
def quality():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        if request.args.get('sn'):
            return qa_sn_search()
        data = {
            "nazwa" : '-',
            "system_id" : '-',
            "sn" : '-'
        }

        return render_template("quality.html", data=data) 

@app.route("/quality2", methods=['POST', 'GET'])
def quality2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        data = {
            "nazwa" : '-',
            "system_id" : '-',
            "sn" : '-'
        }

        data2 = {
            "nazwa" : '-',
            "system_id" : '-',
            "sn" : '-'
        }
        return render_template("quality2.html", data=data, data2=data2) 


@app.route("/defects", methods=['POST', 'GET'])
def defects():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        data = query_db("SELECT tab1.*, tab3.prefix FROM defects tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.form_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id ORDER BY tab1.id DESC LIMIT 1000")
        operators = query_db("SELECT DISTINCT Operator FROM defects")
        msg="Recent 1000 defects"
        return render_template("defects.html", data=data, operators=operators, info=msg)

@app.route("/defects_all", methods=['POST', 'GET'])
def defects_all():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        data = query_db("SELECT tab1.*, tab3.prefix FROM defects tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.form_id = tab2.id LEFT JOIN produkty tab3 ON tab2.id_produktu = tab3.produkt_id ORDER BY tab1.id DESC")
        operators = query_db("SELECT DISTINCT Operator FROM defects")
        count = query_db("SELECT DISTINCT count(form_id) n   FROM defects")
        msg="All defects: " + str(count[0]['n'])
        return render_template("defects.html", data=data, operators=operators, info=msg)
    
@app.route("/search_defect_by_sn", methods=['POST'])
def search_defect_by_sn():
    if not g.user:
        flash(f'Login required.')
    try:
        serial = request.form['sn']
        serial = serial.upper()
    except KeyError:
        serial = 'ccc-111'
    serial = serial.replace("'", "")

    if not is_valid_serial_number(serial):
        flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
        return redirect(request.referrer)

    params = serial.split('-')
    prefix = params[0]
    sn = params[1]
    
    data = query_db("SELECT * FROM defects_with_prefix WHERE prefix='" + prefix + "' AND sn='" + str(sn) + "'")
    return render_template("defects.html", data=data) 

@app.route("/search_defect_by_name", methods=['POST'])
def search_defect_by_name():
    if not g.user:
        flash(f'Login required.')
    
    name = request.form['name']
    name = name.strip()
    name = name.replace("'", "")
    
    data = query_db("SELECT * FROM defects_with_prefix WHERE product LIKE '%" + name + "%'")
    return render_template("defects.html", data=data) 


@app.route("/search_defect_by_operator", methods=['POST'])
def search_defect_by_operator():
    if not g.user:
        flash(f'Login required.')

    operator = request.form['search_operator']
    if operator == None:
        operator = 'xxx'

    data = query_db("SELECT * FROM defects_with_prefix WHERE Operator='" + operator + "'")
    return render_template("defects.html", data=data) 
    
@app.route("/kontrszlif", methods=['POST', 'GET'])
def kontrszlif():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        if request.method == 'POST':
            n_items =  str(request.form['n_items']).strip()
        else:
            n_items = str(500)

        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.id_model1 id_model1, tab1.id_model2 id_model2, tab1.id_model3 id_model3, tab1.id_model4 id_model4, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab1.broken, tab1.filtr, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id ORDER BY tab1.id DESC LIMIT " + n_items)
        query = replace_none_values(query)
        total = query_db("SELECT count(*) as n from lista_formowania_v2")
        formed = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'formed'")
        casted = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'casted'")
        knockout = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'knockout'")
        return render_template("kontrszlif.html", items=query, total=total[0]['n'], formed=formed[0]['n'], casted=casted[0]['n'], knockout=knockout[0]['n']) 

@app.route("/item_history/<id>", methods=['POST', 'GET'])
def item_history(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #query = query_db("SELECT * FROM `lista_formowania_historia_v2` WHERE produkt_id=" + str(id))
        query=query_db("SELECT tab1.id, tab1.produkt_id, tab1.production_stage, tab1.operator, tab1.czas, tab2.nazwa_produktu, tab2.dni_do_wybicia, tab2.nr_kadzi, tab2.filtr, tab2.broken, tab2.temp_zeliwa, tab2.data_zalania, tab2.komentarz, tab2.komentarz_formowanie, tab2.komentarz_rdzeniarnia, tab2.komentarz_zalew, tab2.komentarz_wybijanie FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.id=" + str(id))
        total = query_db("SELECT count(*) as n from lista_formowania_v2")
        formed = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'formed'")
        casted = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'casted'")
        knockout = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'knockout'")
        f = adv_search(id)
        return render_template("item_history.html", items=query, total=total[0]['n'], formed=formed[0]['n'], casted=casted[0]['n'], knockout=knockout[0]['n'], flasks=f, id=id) 
    
@app.route("/defects_item/<id>", methods=['POST', 'GET'])
def defects_item(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        params = id.split('_')
        ids = params[0]
        sn = params[1]
        query = "SELECT * FROM attachements WHERE form_id=" + str(ids) + " AND sn=" + str(sn)
        res = query_db(query)
        query = "SELECT * FROM defects WHERE form_id=" + str(ids) + " AND sn=" + str(sn)
        res2 = query_db(query)
        defnum = defect_n(1)
        query3 = "SELECT nazwa_produktu FROM lista_formowania_v2 WHERE id=" + str(ids)
        res3 = query_db(query3)
        res3 = res3[0]['nazwa_produktu']
        return render_template("defects_item.html", item_idsn_glob=id, attachments=res, defects=res2, defnum=defnum, nazwa=res3)
    
@app.route("/add_inspection_liebherr", methods=['POST'])
def add_inspection_liebherr():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        w1 = str(request.form['w1-liebherr'])
        w1 = w1.replace("'", "")
        d1 = str(request.form['d1-liebherr'])
        if d1 == 'OK':
            d1 = 1
        else:
            d1 = 0
        d2 = str(request.form['d2-liebherr'])
        if d2 == 'OK':
            d2 = 1
        else:
            d2 = 0
        d3 = str(request.form['d3-liebherr'])
        if d3 == 'OK':
            d3 = 1
        else:
            d3 = 0
        d4 = str(request.form['d4-liebherr'])
        if d4 == 'OK':
            d4 = 1
        else:
            d4 = 0
        d5 = str(request.form['d5-liebherr'])
        if d5 == 'OK':
            d5 = 1
        else:
            d5 = 0
        d6 = str(request.form['d6-liebherr'])
        if d6 == 'OK':
            d6 = 1
        else:
            d6 = 0

        w2 = str(request.form['w2-liebherr'])
        w2 = w2.replace("'", "")
        w2 = w2.replace(",", ".")

        w3 = str(request.form['w3-liebherr'])
        w3 = w3.replace("'", "")
        if len(w3) == 0:
            w3 = 0

        ids = str(request.form['ids'])
        ids = ids.replace("'", "")
        prefix = str(request.form['prefix'])
        prefix = prefix.replace("'", "")
        sn = str(request.form['sn'])
        sn = sn.replace("'", "")
        polysk_ral = str(request.form['polysk_ral_9005'])
        if len(polysk_ral) == 0:
            polysk_ral = 'NULL'

        operator = session['user']

        total_inspection_sum = int(d1) + int(d2) + int(d3) + int(d4) + int(d5) + int(d6)

        if total_inspection_sum == 6:
            total_inspection_result = 1
            history_qa(ids, sn, prefix, 'qa_ok', operator)
        else:
            total_inspection_result = 0
            history_qa(ids, sn, prefix, 'qa_nok', operator)

        query = "INSERT INTO liebherr_inspection(ids, prefix, sn, lakier_na_sucho_pomiar, lakier_na_sucho, struktura, jakosc_napisow, pow_pod_naklejke, pomiar_koloru_lab, pomiar_koloru_lab_pomiar, waga_lhe, polysk_ral_9005, result, operator) VALUES (" + str(ids) + ",'" + str(prefix) + "'," + str(sn) + ",'" + str(w1) + "','" + str(d1) + "','" + str(d2) + "','" + str(d3) + "','" + str(d4) +  "','" + str(d5) +  "','" + str(w2) + "'," + str(w3) + "," + str(polysk_ral) + ",'" + str(total_inspection_result) +  "','" + operator + "')"
        print(query)
        query_update(query)
        return redirect('/qa_report/Liebherr')

@app.route("/add_inspection_mecalac_fr", methods=['POST'])
def add_inspection_mecalac_fr():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        lakier_na_sucho = str(request.form['lakier_na_sucho'])

        porowatosc = str(request.form['porowatosc'])
        if porowatosc == 'OK':
            porowatosc = 1
        else:
            porowatosc = 0
        numery = str(request.form['numery'])
        if numery == 'OK':
            numery = 1
        else:
            numery = 0
        struktura = str(request.form['struktura'])
        if struktura == 'OK':
            struktura = 1
        else:
            struktura = 0
        czystosc = str(request.form['czystosc'])
        if czystosc == 'OK':
            czystosc = 1
        else:
            czystosc = 0

        total_inspection_sum = porowatosc + numery + struktura + czystosc
        if total_inspection_sum == 4:
            result = 1
        else:
            result = 0
       
        ids = str(request.form['ids'])
        ids = ids.replace("'", "")
        prefix = str(request.form['prefix'])
        prefix = prefix.replace("'", "")
        sn = str(request.form['sn'])
        sn = sn.replace("'", "")
        operator = session['user']

        if total_inspection_sum == 4:
            result = 1
            history_qa(ids, sn, prefix, 'qa_ok', operator)
        else:
            result = 0
            history_qa(ids, sn, prefix, 'qa_nok', operator)

        query = "INSERT INTO mecalac_fr_inspection(ids, prefix, sn, lakier_na_sucho_pomiar, ocena_powierzchni_bp, ocena_powierzchni_cnc, jakosc_struktury, czystosc, result, operator) VALUES (" + str(ids) + ",'" + str(prefix) + "'," + str(sn) + ",'" + str(lakier_na_sucho) + "','" + str(porowatosc) + "','" + str(numery) + "','" + str(struktura) + "','" + str(czystosc) +  "','" + str(result) + "','" + operator + "')"
        query_update(query)

        return redirect('/qa_report/Mecalac France')


@app.route("/add_inspection_mit", methods=['POST'])
def add_inspection_mitsubishi():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        ids = str(request.form['ids'])
        prefix = str(request.form['prefix'])
        sn = str(request.form['sn'])
        klient = str(request.form['klient'])
        operator = session['user']
    
        wynik_polysk_ral = str(request.form['wynik_polysk_ral'])
        wynik_polysk_ral = wynik_polysk_ral.replace("'", "")
        if len(wynik_polysk_ral) == 0:
            wynik_polysk_ral = 'Null'

        wynik_polysk_gre = str(request.form['wynik_polysk_gre'])
        wynik_polysk_gre = wynik_polysk_gre.replace("'", "")
        if len(wynik_polysk_gre) == 0:
            wynik_polysk_gre = 'Null'

        kolor1 = str(request.form['kolor1'])
        kolor1 = kolor1.replace("'", "")
        if len(kolor1) == 0:
            kolor1 = 'None'

        kolor2 = str(request.form['kolor2'])
        kolor2 = kolor2.replace("'", "")
        if len(kolor2) == 0:
            kolor2 = 'None'

        kolor1_wynik = str(request.form['kolor1_wynik'])
        kolor1_wynik = kolor1_wynik.replace("'", "")
        kolor1_wynik = kolor1_wynik.replace(",", ".")
        if len(kolor1_wynik) == 0:
            kolor1_wynik = 'Null'

        kolor2_wynik = str(request.form['kolor2_wynik'])
        kolor2_wynik = kolor2_wynik.replace("'", "")
        kolor2_wynik = kolor2_wynik.replace(",", ".")
        if len(kolor2_wynik) == 0:
            kolor2_wynik = 'Null'

        wynik_kontury = str(request.form['wynik_kontury'])
        if wynik_kontury == 'OK':
            wynik_kontury = 1
        else:
            wynik_kontury = 0

        wynik_ocena_pow = str(request.form['wynik_ocena_pow'])
        if wynik_ocena_pow == 'OK':
            wynik_ocena_pow = 1
        else:
            wynik_ocena_pow = 0

        total_inspection_sum = wynik_ocena_pow + wynik_kontury
        if total_inspection_sum == 2:
            result = 1
            history_qa(ids, sn, prefix, 'qa_ok', operator)
        else:
            result = 0
            history_qa(ids, sn, prefix, 'qa_nok', operator)

        # print(wynik_polysk_ral)
        # print(wynik_polysk_gre)
        # print(kolor1)
        # print(kolor2)
        # print(kolor1_wynik)
        # print(kolor2_wynik)
        # print(wynik_kontury)
        # print(wynik_ocena_pow)
        # print(result)

        query = "INSERT INTO mitsubishi_inspection(ids, prefix, sn, customer, polysk_ral_9005, polysk_mitsu_green, kolor1, kolor1_wynik, kolor2, kolor2_wynik, kontury, ocena_powierzchni, result, operator) VALUES (" + str(ids) + ",'" + str(prefix) + "','" + str(sn) + "','" + str(klient) + "'," + str(wynik_polysk_ral) + "," + str(wynik_polysk_gre) + ",'" + str(kolor1) + "'," + str(kolor1_wynik) + ",'" + str(kolor2) +  "'," + str(kolor2_wynik) + ",'" + str(wynik_kontury) + "','" + str(wynik_ocena_pow) + "','" + str(result) + "','" + operator + "')"

        query_update(query)
        link = '/qa_report/' + klient
        return redirect(link)

@app.route("/qa_item/<id>", methods=['POST', 'GET'])
def qa_item(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        params = id.split('_')
        ids = params[0]
        prefix = params[1]
        sn = params[2]
        return render_template("qa_item.html", ids=ids, sn=sn, prefix=prefix)

@app.route("/qa_item_mit/<id>", methods=['POST', 'GET'])
def qa_item_mit(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        params = id.split('_')
        ids = params[0]
        prefix = params[1]
        sn = params[2]
        customer = params[3]
        return render_template("qa_item_mit.html", ids=ids, sn=sn, prefix=prefix, customer=customer)

@app.route("/qa_item_mec_fr/<id>", methods=['POST', 'GET'])
def qa_item_mec_fr(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        params = id.split('_')
        ids = params[0]
        prefix = params[1]
        sn = params[2]
        return render_template("qa_item_mec_fr.html", ids=ids, sn=sn, prefix=prefix)
    
@app.route('/uploads/<filename>')
def download_file(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)

@app.route('/delete_attachment/<filename>', methods=['GET'])
def delete_attachment(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        os.remove(filepath)
        query = "DELETE FROM attachements WHERE path LIKE'" + filename + "'"
        query_update(query)

        operator = session['user']
        operation = 'delete_attachment: ' + filepath
        defects_history(0, operation, operator)
    except FileNotFoundError:
        flash(f'File {filename} not found.', 'error')
    except Exception as e:
        flash(f'An error occurred while deleting the file: {str(e)}', 'error')
    return redirect(request.referrer)

@app.route('/delete_attachment_claims/<filename>', methods=['GET'])
def delete_attachment_claims(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        os.remove(filepath)
        query = "DELETE FROM attachements_claims WHERE file LIKE'" + filename + "'"
        result = query_update(query)
        operator = session['user']
        operation = 'delete_attachment: ' + filename
        if result:
            history_claims(0, operation, operator)

    except FileNotFoundError:
        flash(f'File {filename} not found.', 'error')
    except Exception as e:
        flash(f'An error occurred while deleting the file: {str(e)}', 'error')
    return redirect(request.referrer)

@app.route('/upload_file', methods=['POST'])
def upload_file():
    item_idsn = request.form['item_idsn']
    if request.method == 'POST':
        if 'file' not in request.files:
            return 'No file part'
        file = request.files['file']
        
        if file.filename == '':
            return 'No selected file'
        
        if file and allowed_file(file.filename):
            file_hash = generate_file_hash(file)[0:12]
            filename = file.filename
            name, ext = os.path.splitext(filename)
            filename = f"{name}_{file_hash}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            params = item_idsn.split('_')
            id = params[0]
            sn = params[1]
            query = "INSERT INTO attachements(sn, form_id, path) VALUES(" + str(sn) + "," + str(id) + ",'" + filename + "')"
            if len(item_idsn) != 0:
                query_update(query)
                operator = session['user']
            operation = 'add_attachment: ' + filename + '_' + item_idsn
            defects_history(0, operation, operator)
            return redirect(request.referrer)
        else:   
            flash(f'file {filename} unallowed!')
            url = '/defects_item/' + str(id) + '_' + str(sn) 
            query = "SELECT path attachemnts WHERE id=" + str(id) + " AND sn=" + str(sn)
            files = query_db(query)
            return redirect(url)

@app.route('/upload_file_claims', methods=['POST'])
def upload_file_claims():
    serial = request.form['serial']
    prefix, sn = split_code(serial)
    category = request.form['category']

    if request.method == 'POST':
        if 'file' not in request.files:
            return 'No file part'
        file = request.files['file']
        
        if file.filename == '':
            return 'No selected file'
        
        if file and allowed_file(file.filename):
            file_hash = generate_file_hash(file)[0:12]
            filename = file.filename
            name, ext = os.path.splitext(filename)
            filename = f"claim_{name}_{file_hash}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            sql = "SELECT produkt_id FROM lista_formowania_sn WHERE prefix='" + prefix + "' AND sn='" + str(sn) + "'"
            result = query_db(sql)

            try:
                form_id = result[0]['produkt_id']
            except IndexError:
                form_id = 0

            try:
                id_of_claim = query_db("SELECT id FROM reklamacje WHERE serial_no='" + serial + "' ORDER BY id DESC LIMIT 1")[0]['id']
            except (IndexError, KeyError):
                flash(f"Błąd podczas pobierania ID nowo utworzonej reklamacji dla numeru seryjnego: {serial}")
                return redirect(request.referrer)

            query = "INSERT INTO attachements_claims(prefix, sn, form_id, file, category) VALUES('" + str(prefix) + "','" + str(sn) + "','" + str(form_id) + "','" + filename + "','" + category + "')"
            query_update(query)
            url = '/edit_claim/' + prefix + '-' + str(sn)
            operator = session['user']
            history_claims(id_of_claim, 'add_attachment_claims: ' + filename, operator)
            return redirect(url)
        
        else:   
            flash(f'file {filename} unallowed!')
            url = '/defects_item/' + str(id) + '_' + str(sn) 
            query = "SELECT path attachemnts WHERE id=" + str(id) + " AND sn=" + str(sn)
            files = query_db(query)
            return redirect(url)

@app.route("/def_add_comment/<id>", methods=['POST', 'GET'])
def def_add_comment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        defkom = str(request.form['defkom'])
        defkom = defkom.replace("'", "")
        query = "UPDATE `attachements` SET comment='" + defkom + "' WHERE id=" + str(id)
        query_update(query)
        return redirect(request.referrer)

@app.route("/cliam_add_comment/<id>", methods=['POST', 'GET'])
def claim_add_comment(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        comment_claims = str(request.form['comment_claims'])
        comment_claims = comment_claims.replace("'", "")
        query = "UPDATE `attachements_claims` SET comment='" + comment_claims + "' WHERE id=" + str(id)
        query_update(query)
        return redirect(request.referrer)

@app.route("/add_defect/<id>", methods=['POST'])
def add_defect(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        params = id.split('_')
        ids = params[0]
        sn = params[1]
        defect_date = str(request.form['defect_date'])
        defect_date = defect_date.replace("'", "")
        decyzja = str(request.form['decyzja'])
        decyzja = decyzja.replace("'", "")
        miejsce = str(request.form['miejsce'])
        miejsce = miejsce.replace("'", "")     
        rodzaj_braku = str(request.form['rodzaj_braku'])
        rodzaj_braku = rodzaj_braku.replace("'", "")   
        nazwa_produktu = str(request.form['nazwa_produktu'])
        nazwa_produktu = nazwa_produktu.replace("'", "")  
        operator = session['user']

        # if cond_zlom == 1:
            # flash(f'Do złomu nie można przypisać dodatkowych defektów.')
            # return redirect(request.referrer)

        # elif cond_def >= 1 and decyzja == 'złomować':
        #     return redirect(request.referrer)
        
        if decyzja != 'złomować':
            nr_karta_braku = 'N-' + str(defect_n())
        else:
            nr_karta_braku = 'Z-' + str(defect_n())

        query = "INSERT INTO `defects`(sn, form_id, karta_brakow, data, wada, miejsce, decyzja, product, operator) VALUES('" + str(sn) + "','" + str(ids) + "','" + nr_karta_braku + "','" + defect_date + "','" + rodzaj_braku + "','" + miejsce + "','" + decyzja + "','" + nazwa_produktu + "','" + operator + "')"
        query_update(query)
        defect_id = check_id_in_db('defects')
        defects_history(defect_id, 'add_new_defect', operator)
        return redirect(request.referrer)

@app.route("/edit_defect/<id>", methods=['POST'])
def edit_defect(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        kartabr = str(request.form['kartabr'])
        kartabr = kartabr.replace("'", "")
        defect_date = str(request.form['defect_date'])
        defect_date = defect_date.replace("'", "")
        #decyzja = str(request.form['decyzja'])
        #decyzja = decyzja.replace("'", "")
        #operator = str(request.form['operator'])
        #operator = operator.replace("'", "")
        operator = session['user']
        miejsce = str(request.form['miejsce'])
        miejsce = miejsce.replace("'", "")     
        rodzaj_braku = str(request.form['rodzaj_braku'])
        rodzaj_braku = rodzaj_braku.replace("'", "")   
        # klient = str(request.form['klient'])
        # klient = klient.replace("'", "") 
        # part = str(request.form['part'])
        # part = part.replace("'", "")        
        #query = "UPDATE `defects` SET karta_brakow='" + kartabr + "', data='" + defect_date + "',decyzja='" + decyzja + "',miejsce='" + miejsce + "',wada='" + rodzaj_braku + "',part_no='" + part + "',klient='" + klient + "',czas=current_timestamp() WHERE id=" + str(id)
        query = "UPDATE `defects` SET karta_brakow='" + kartabr + "', data='" + defect_date + "',miejsce='" + miejsce + "',wada='" + rodzaj_braku + "',part_no='" + "',operator='" + operator + "',czas=current_timestamp() WHERE id=" + str(id)
        query_update(query)
        defects_history(id, 'edit_defect', operator)
        return redirect(request.referrer)
    
@app.route("/del_defect/<id>", methods=['GET'])
def del_defect(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = "DELETE FROM defects WHERE id=" + str(id)
        query_update(query)
        operator = session['user']
        defects_history(id, 'del_defect', operator)
        return redirect(request.referrer)
    
@app.route("/karta_braku/<id>", methods=['POST', 'GET'])
def karta_braku(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = "SELECT * FROM defects WHERE id=" + str(id)
        res = query_db(query)
        return render_template("karta_braku.html",item=res[0])
        
@app.route("/item_history_quality/<id>", methods=['POST', 'GET'])
def item_history_quality(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
      
        query=query_db("SELECT tab1.id, tab1.produkt_id, tab1.production_stage, tab1.operator, tab1.czas, tab2.nazwa_produktu, tab2.dni_do_wybicia, tab2.nr_kadzi, tab2.filtr, tab2.broken, tab2.temp_zeliwa, tab2.data_zalania, tab2.komentarz, tab2.komentarz_formowanie, tab2.komentarz_rdzeniarnia, tab2.komentarz_zalew, tab2.komentarz_wybijanie FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab2.id=" + str(id))
        total = query_db("SELECT count(*) as n from lista_formowania_v2")
        formed = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'formed'")
        casted = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'casted'")
        knockout = query_db("SELECT count(*) as n from lista_formowania_v2 where item_status = 'knockout'")
        #f = adv_search(id)
        f = adv_search_manscan(id)
        return render_template("item_history_quality.html", items=query, total=total[0]['n'], formed=formed[0]['n'], casted=casted[0]['n'], knockout=knockout[0]['n'], flasks=f, id=id) 

#######################################################
################ Widoki operatorzy ####################
#######################################################

@app.route("/forming_operator_view", methods=['POST', 'GET'])
def forming_operator_view():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.trail, tab1.id_model1 id_model1, tab1.id_model2 id_model2, tab1.id_model3 id_model3, tab1.id_model4 id_model4, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'new' AND tab3.manual_forming = '0' ORDER BY tab1.id DESC LIMIT 200")
        query = replace_none_values(query)
        return render_template("forming_operator_view.html", items=query) 


@app.route("/forming_operator_view2", methods=['POST', 'GET'])
def forming_operator_view2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE zaformowano = '1' LIMIT 200 ")
        query = replace_none_values(query)
        return render_template("forming_operator_view2.html", items=query) 
    
@app.route("/forming_operator_view3/<id>", methods=['POST', 'GET'])
def forming_operator_view3(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        fasks_doubled = [3, 35, 36, 43, 44]
        query = query_db("SELECT tab1.*, tab2.prefix FROM lista_formowania_formy_v2 tab1 LEFT JOIN produkty tab2 ON tab1.prod_id = tab2.produkt_id WHERE tab1.produkt_id=" + str(id))
        operators = query_db("SELECT ImieNazwisko FROM operator_foundry WHERE status='active' AND function='auto'")
        comment = query_db("SELECT komentarz FROM lista_formowania_v2 WHERE id=" + str(id))[0]['komentarz']
        defects = query_db("SELECT defect FROM assembley_defects WHERE status='active'")
        return render_template("forming_operator_view3.html", items=query, fasks_doubled=fasks_doubled, operators=operators, comment=comment, defects=defects) 
    
@app.route("/forming_operator_m_view3/<id>", methods=['POST', 'GET'])
def forming_operator_m_view3(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        operators = query_db("SELECT ImieNazwisko FROM operator_foundry WHERE status='active' AND function='manual'")
        query = query_db("SELECT tab1.*, tab2.prefix FROM lista_formowania_formy_v2 tab1 LEFT JOIN produkty tab2 ON tab1.prod_id = tab2.produkt_id WHERE tab1.produkt_id=" + str(id))
        comment = query_db("SELECT komentarz FROM lista_formowania_v2 WHERE id=" + str(id))[0]['komentarz']
        defects = query_db("SELECT defect FROM assembley_defects WHERE status='active'")
        return render_template("forming_operator_m_view3.html", items=query, operators=operators, coment=comment, defects=defects)
    
@app.route("/forming_operator_view5/<id>", methods=['POST', 'GET'])
def forming_operator_view5(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        return render_template("forming_operator_view5.html", items=query) 
    
@app.route("/forming_operator_view4", methods=['POST', 'GET'])
def forming_operator_view4():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #query = query_db("SELECT distinct tab1.id, tab1.nazwa_produktu, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1,  tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'formed' ORDER BY tab1.id DESC LIMIT 200")
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.trail, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'formed' AND tab3.manual_forming = '0' ORDER BY tab1.id DESC LIMIT 200")
        #query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'formed' ORDER BY data_dodania DESC LIMIT 200")
        query = replace_none_values(query)
        return render_template("forming_operator_view4.html", items=query) 
    
@app.route("/forming_operator_view6", methods=['POST', 'GET'])
def forming_operator_view6():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #query = query_db("SELECT distinct tab1.id, tab1.nazwa_produktu, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1,  tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'new' ORDER BY tab1.id DESC LIMIT 200 ")
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.trail, tab1.id_model1 id_model1, tab1.id_model2 id_model2, tab1.id_model3 id_model3, tab1.id_model4 id_model4, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'new' ORDER BY tab1.id DESC LIMIT 200")
        query = patterns_on_the_line(query)
        query = replace_none_values(query)
        return render_template("forming_operator_view6.html", items=query) 
    
@app.route("/forming_operator_m_view4", methods=['POST', 'GET'])
def forming_operator_m_view4():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #query = query_db("SELECT distinct tab1.id, tab1.nazwa_produktu, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1,  tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'formed' ORDER BY tab1.id DESC LIMIT 200")
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.alias, tab1.item_status, tab1.trail, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'formed' AND tab3.manual_forming = '1' ORDER BY tab1.id DESC LIMIT 200")
        #query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'formed' ORDER BY data_dodania DESC LIMIT 200")
        query = replace_none_values(query)
        return render_template("forming_operator_m_view4.html", items=query) 
    
@app.route("/forming_operator_m_view2", methods=['POST', 'GET'])
def forming_operator_m_view2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #query = query_db("SELECT distinct tab1.id, tab1.nazwa_produktu, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1,  tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'formed' ORDER BY tab1.id DESC LIMIT 200")
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.trail, tab1.alias, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'assembled' AND tab3.manual_forming = '1' ORDER BY tab1.id DESC LIMIT 200")
        #query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'formed' ORDER BY data_dodania DESC LIMIT 200")
        query = replace_none_values(query)
        return render_template("forming_operator_m_view2.html", items=query) 
    
@app.route("/forming_operator_m_view", methods=['POST', 'GET'])
def forming_operator_m_view():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.item_status, tab1.trail, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'new'AND tab3.manual_forming = '1' ORDER BY tab1.id DESC LIMIT 200")
        query = replace_none_values(query)
        return render_template("forming_operator_m_view.html", items=query) 

@app.route("/cores_operator_view", methods=['POST', 'GET'])
def cores_operator_view():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #sql = "SELECT tab1.* FROM `lista_formowania_sn` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id LEFT JOIN produkty tab3 on tab2.id_produktu = tab3.produkt_id WHERE tab2.item_status = 'formed' AND tab3.manual_forming = '0'"
        sql = """
            SELECT 
                GROUP_CONCAT(tab1.id ORDER BY tab1.id SEPARATOR ', ') AS ids,
                tab1.produkt_id id,
                MAX(tab1.nazwa_produktu) AS nazwa_produktu,
                MAX(tab1.alias) AS alias,
                MAX(tab1.trail) AS trail,
                GROUP_CONCAT(CONCAT(tab1.prefix, '-', tab1.sn) ORDER BY tab1.sn SEPARATOR ', ') AS serial,
                MAX(tab1.czas_dodania) AS czas_dodania
            FROM lista_formowania_sn tab1
            LEFT JOIN lista_formowania_v2 tab2 
                ON tab1.produkt_id = tab2.id
            LEFT JOIN produkty tab3 
                ON tab2.id_produktu = tab3.produkt_id
            WHERE tab2.item_status = 'formed' 
            AND tab1.param1 = '0'
            AND tab3.manual_forming = '0'
            GROUP BY tab1.produkt_id
            ORDER BY tab1.produkt_id;
        """
        items = query_db(sql)


        for row in items:
            if row['serial']:
                row['serial'] = row['serial'].split(', ')
            else:
                row['serial'] = []

    return render_template("cores_operator_view.html", items=items) 

@app.route("/remove_from_flask", methods=['POST'])
def remove_from_flask():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        selected_value = request.form.get('item_to_remove_from_form')
        print(selected_value)

        data, form_id = selected_value.split('_')
        prefix, sn = data.split('-')

        sql = "SELECT * FROM `lista_formowania_sn` WHERE produkt_id=" + str(form_id) + " AND param1='0'"
        n = len(query_db(sql))
        
        if n == 1:
            flash("Nie można z formy usunąć wszytkich odelwów!")
            return redirect(request.referrer)
        
        sql = "UPDATE `lista_formowania_sn` set param1='1' WHERE produkt_id=" + str(form_id) + " AND sn=" + str(sn) + " AND prefix='" + prefix + "'"
        query_update(sql)

        return redirect(request.referrer)
    
@app.route("/reset_forms_in_flask/<id>", methods=['GET'])
def reset_forms_in_flask(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sql = "UPDATE `lista_formowania_sn` set param1='0' WHERE produkt_id=" + str(id) 
        query_update(sql)
        return redirect(request.referrer)
    
@app.route("/cores_operator_view_form/<id>", methods=['POST', 'GET'])
def cores_operator_view_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sql = "SELECT concat(prefix, '-', sn) serial FROM `lista_formowania_sn` WHERE produkt_id=" + str(id)
        serial = query_db(sql)
        for i in serial:
            print(i)

        komentarz = query_db("SELECT komentarz FROM `lista_formowania_v2` WHERE id=" + str(id))
        defects = query_db("SELECT defect FROM assembley_defects WHERE status='active'")

        return render_template("cores_operator_view_form.html", item=id, serial=serial[0]['serial'],  komentarz=komentarz[0]['komentarz'], defects=defects) 
    
@app.route("/cores_operator_view_m_form/<id>", methods=['POST', 'GET'])
def cores_operator_view_m_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT distinct tab2.model1_sn, tab1.prefix, tab1.komentarz FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'formed' AND tab1.id=" + str(id))
        defects = query_db("SELECT defect FROM assembley_defects WHERE status='active'")
        comment = query[0]['komentarz']
        return render_template("cores_operator_view_m_form.html", item=id, item_id=query[0]['model1_sn'], prefix=query[0]['prefix'], defects=defects, comment=comment) 

@app.route("/cores_operator_view2", methods=['POST', 'GET'])
def cores_operator_view2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        forms_ready = query_db("SELECT DISTINCT tab1.id id, tab1.nazwa_produktu, tab1.prefix, tab1.alias, tab1.trail, tab1.item_status, tab1.data_dodania, tab1.data_ostatniej_modyfikacji, tab1.flask2, tab1.item_status, tab1.komentarz_flag, tab1.komentarz, tab1.id_model1, tab1.id_model2, tab2.model1_sn, tab2.model2_sn, tab2.model3_sn, tab2.model4_sn, tab2.model5_sn, tab2.model6_sn, tab2.model7_sn, tab2.model8_sn, tab3.manual_forming FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id LEFT JOIN produkty tab3 ON tab2.prod_id = tab3.produkt_id WHERE tab1.item_status LIKE 'assembled' AND tab3.manual_forming='0' ORDER BY tab1.id DESC LIMIT 200")
        for items in forms_ready:
            items['serials']  = oblicz_numery_seryjne(items['id'])

        forms_ready = replace_none_values(forms_ready)
        return render_template("cores_operator_view2.html", items=forms_ready) 

@app.route("/cores_operator_view3", methods=['POST', 'GET'])
def cores_operator_view3():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_v2 tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.item_status LIKE 'new' ORDER BY id DESC LIMIT 200")
        return render_template("cores_operator_view3.html", items=query) 
    
@app.route("/cores_operator_view4/<id>", methods=['POST', 'GET'])
def cores_operator_view4(id):
    try:
        id = int(id)
    except ValueError:
        id = 0
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = query_db("SELECT * FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(id))
        return render_template("cores_operator_view4.html", items=query) 

# @app.route("/foundry_operator_view", methods=['POST', 'GET'])
# def foundry_operator_view():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = query_db("SELECT * FROM lista_formowania_v2 WHERE item_status LIKE 'assembled' ORDER BY data_ostatniej_modyfikacji DESC LIMIT 200")
#         return render_template("foundry_operator_view.html", items=query) 
    
#############################################################################

@app.route("/foundry_operator_view2", methods=['POST', 'GET'])
def foundry_operator_view2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        sql = """
            SELECT 
                tab1.id,
                tab1.nazwa_produktu,
                tab2.czas_studzenia,
                tab2.dni_do_wybicia,
                tab1.data_ostatniej_modyfikacji,
                tab1.data_zalania,
                MAX(tab3.trail) AS trail
            FROM lista_formowania_v2 AS tab1
            LEFT JOIN produkty AS tab2 
                ON tab1.id_produktu = tab2.produkt_id
            LEFT JOIN lista_formowania_sn AS tab3 
                ON tab1.id = tab3.produkt_id
            WHERE tab1.item_status = 'assembled'
            GROUP BY 
                tab1.id,
                tab1.nazwa_produktu,
                tab2.waga_zeliwa
            ORDER BY tab1.id DESC
            LIMIT 200
            """
        formy_do_zalania = query_db(sql)     

        for i in formy_do_zalania:
            print(i['id'], i['nazwa_produktu'], i['czas_studzenia'], i['dni_do_wybicia'], i['data_ostatniej_modyfikacji'], i['data_zalania'], i['trail'])
            print('-----------------------------')
        
        for i in formy_do_zalania:
            i['waga_netto'] = suma_wagi_formy_netto(i['id'])

        for i in formy_do_zalania:
            i['numery_seryjne'] = oblicz_numery_seryjne(i['id'])



        wyswitl_czas_od_zmontowania(formy_do_zalania)
        formy_do_zalania = wyswietl_czasy_studzenia_i_chlodzenia(formy_do_zalania)


        suma = suma_wagi_netto()
        suma = x = round(suma, 1)

        # formy_zalane = query_db("SELECT DISTINCT tab1.id, tab1.nazwa_produktu, tab1.prefix, tab1.alias, tab1.trail, tab1.komentarz, tab2.model1_sn, tab1.data_zalania, tab1.czas_studzenia, tab1.dni_do_wybicia, tab1.data_ostatniej_modyfikacji, tab1.nr_kadzi, tab1.broken, tab1.filtr, tab1.temp_zeliwa, tab1.data_dodania, tab1.zmodyfikowane_przez FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'casted' OR tab1.item_status LIKE 'ready_for_cooling' ORDER BY tab1.id DESC LIMIT 200;")
        sql = """
            SELECT 
                tab1.id,
                tab1.nazwa_produktu,
                tab1.nr_kadzi,
                tab1.filtr,
                tab1.broken,
                tab1.temp_zeliwa,
                tab1.data_zalania,
                tab1.data_dodania,
                tab1.zmodyfikowane_przez,
                tab2.czas_studzenia,
                tab2.dni_do_wybicia,
                tab1.data_ostatniej_modyfikacji,
                tab1.data_zalania,
                MAX(tab3.trail) AS trail
            FROM lista_formowania_v2 AS tab1
            LEFT JOIN produkty AS tab2 
                ON tab1.id_produktu = tab2.produkt_id
            LEFT JOIN lista_formowania_sn AS tab3 
                ON tab1.id = tab3.produkt_id
            WHERE tab1.item_status = 'casted'
            GROUP BY 
                tab1.id,
                tab1.nazwa_produktu,
                tab2.waga_zeliwa
            ORDER BY tab1.id DESC
            LIMIT 200
            """
        formy_zalane = query_db(sql)

        for i in formy_zalane:
            i['numery_seryjne'] = oblicz_numery_seryjne(i['id'])
        formy_zalane = wyswietl_czasy_studzenia_i_chlodzenia(formy_zalane)


        ###############################
        # mafi do załadowania waga form
        ###############################

        mafi_to_display =[]
        mafi = query_db("SELECT SerialNumber, (CarryingCapacity * 1000) carry FROM mafi WHERE status LIKE 'available' order by SerialNumber ASC")
        for i in mafi:
            formy_na_mafi = query_db("SELECT * FROM `mafi_load` where id_mafi =" + str(i['SerialNumber']) + " AND mafi_status LIKE 'load'")
            waga_form_na_mafi = 0
            for k in formy_na_mafi:
                waga_formy = suma_wagi_formy_netto(k['id_form'])
                waga_form_na_mafi += waga_formy
                i['carry_actual'] = waga_form_na_mafi
            mafi_to_display.append(i)

        for k in mafi_to_display:
            query = "SELECT id_form id FROM mafi_load WHERE mafi_status='load' AND id_mafi=" + str(k['SerialNumber'])
            rows = query_db(query)
            k['formy'] = ''
            forms_on_mafi_actual = []
            for i in rows:
                data = oblicz_numery_seryjne(i['id'])
                print(i['id'], data)
                nazwa = generete_form_name(i['id'])
                forms_on_mafi_actual.append([nazwa, data])
                k['formy'] = forms_on_mafi_actual

        ##################
        # mafi do wybicia
        ##################
        
        mafi_to_display_closed =[]
        mafi_closed = query_db("SELECT SerialNumber, (CarryingCapacity * 1000) carry FROM mafi WHERE status LIKE 'in_use' order by SerialNumber ASC")
        for i in mafi_closed:
            formy_na_mafi = query_db("SELECT * FROM `mafi_load` where id_mafi =" + str(i['SerialNumber']) + " AND mafi_status LIKE 'load' OR mafi_status LIKE 'ready_to_knockout' AND id_mafi =" + str(i['SerialNumber']))
            waga_form_na_mafi = 0
            for k in formy_na_mafi:
                waga_formy = suma_wagi_formy_netto(k['id_form'])
                waga_form_na_mafi += waga_formy
                i['carry_actual'] = waga_form_na_mafi
            mafi_to_display_closed.append(i)

        for k in mafi_to_display_closed:
            query = "SELECT id_form id FROM mafi_load WHERE mafi_status='load' AND id_mafi=" + str(k['SerialNumber']) + " OR mafi_status='ready_to_knockout' AND id_mafi=" + str(k['SerialNumber'])
            rows = query_db(query)
            k['formy'] = ''
            forms_on_mafi_actual = []
            for i in rows:
                data = oblicz_numery_seryjne(i['id'])
                nazwa = generete_form_name(i['id'])
                forms_on_mafi_actual.append([nazwa, data])
                k['formy'] = forms_on_mafi_actual
                            
        return render_template("foundry_operator_view2.html", formy_do_zalania=formy_do_zalania, formy_zalane=formy_zalane, suma=suma, mafi=mafi, mafi_to_display=mafi_to_display, mafi_to_display_closed=mafi_to_display_closed) 
    
@app.get("/api/mafi/form")
def mafi_form():
    id_mafi = request.args.get("id_mafi", "").strip()

    # Walidacja (opcjonalnie): tylko cyfry
    if not id_mafi.isdigit():
        return jsonify({"error": "id_mafi must be a number"}), 400
    
    rows = query_db("SELECT id_form id FROM mafi_load WHERE mafi_status='load' AND id_mafi=" + str(id_mafi))
    res = []
    for i in rows:
        data = generete_serials(i['id'])
        nazwa = generete_form_name(i['id'])
        result = ", ".join(f"{a}-{b}" for a, b in data)
        result = nazwa + ' -> ' + result
        res.append(result)

    # wszystkie elementy jako multiline string
    id_form = "\n".join(str(r) for r in res) if res else ""
    
    return jsonify({"id_mafi": id_mafi, "form": id_form})


################################################################################

@app.route("/knockout_operator_view", methods=['POST', 'GET'])
def knockout_operator_view():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))        
    else:
        oblicz_czas_chlodzenia()         
        #mafi = query_db("SELECT id, id_mafi, id_form, czas, trail FROM mafi_load WHERE mafi_status LIKE 'load' OR mafi_status LIKE 'ready_to_knockout' group by id_mafi")
        mafi = query_db("SELECT ml.* FROM mafi_load ml JOIN (SELECT id_mafi, MAX(czas) AS max_czas FROM mafi_load WHERE mafi_status IN ('load', 'ready_to_knockout') GROUP BY id_mafi) AS sub ON ml.id_mafi = sub.id_mafi AND ml.czas = sub.max_czas WHERE ml.mafi_status IN ('load', 'ready_to_knockout');")
        forms_cooling = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'load'")
        forms_cooling_idx = []
        forms_ready_to_knockout = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'ready_to_knockout'")
        forms_ready_to_knockout_idx = []
        mafi_to_knockout = []        
        #forms_knockout = flasks_knockout()

        #forms_knockout = replace_none_values(forms_knockout)
        items = query_db("SELECT produkt_id, nazwa FROM produkty")

        for i in forms_cooling:
            forms_cooling_idx.append(i['id_mafi'])

        for i in forms_ready_to_knockout:
            forms_ready_to_knockout_idx.append(i['id_mafi'])

        for i in forms_ready_to_knockout_idx:
            if i not in forms_cooling_idx:
                mafi_to_knockout.append(i)

        for i in mafi:
            if i['id_mafi'] in mafi_to_knockout:
                i['status'] = 'ready_to_knockout'
            else:
                i['status'] = 'cooling'

        for i in mafi:
            query = "SELECT DISTINCT id_mafi, id_form FROM mafi_load WHERE mafi_status LIKE 'ready_to_knockout' AND id_mafi=" + str(i['id_mafi'])
            res = query_db(query)
            for k in res:
                res2 = query_db('SELECT trail, alias FROM lista_formowania_v2 WHERE id=' + str(k['id_form']))
                
                for z in res2:
                 
                    if z['trail'] == '1':
                        query_update("UPDATE mafi_load SET trail='1' WHERE id_mafi=" + str(k['id_mafi']) + " AND mafi_status='ready_to_knockout'")
                        print("Updated mafi:", k['id_mafi'], " form:", k['id_form']," is trail")
                    if z['alias']:
                        query_update("UPDATE mafi_load SET alias='1' WHERE id_mafi=" + str(k['id_mafi']) + " AND mafi_status='ready_to_knockout'")
                        print("Updated mafi:", k['id_mafi'], " form:", k['id_form']," is outline / repeated")

        mafi = remove_duplicates_by_id_mafi(mafi)
        #return render_template("knockout_operator_view.html", mafi=mafi, forms_knockout=forms_knockout, items=items) 
        return render_template("knockout_operator_view.html", mafi=mafi, items=items) 

    
@app.route("/knockout_mafi_forms/<id>", methods=['POST', 'GET'])
def knockout_mafi_forms(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        oblicz_czas_chlodzenia()  
        mafi = query_db("SELECT id, id_mafi, id_form from mafi_load WHERE mafi_status <> 'unload' AND id_mafi=" + str(id))
        forms = []
        for i in mafi:
            items = query_db("SELECT DISTINCT tab1.id id, tab1.nazwa_produktu, tab1.item_status, tab1.prefix, tab1.komentarz, tab1.trail, tab1.data_zalania, tab1.trail, tab2.czas_studzenia, tab2.dni_do_wybicia FROM lista_formowania_v2 AS tab1 LEFT JOIN produkty AS tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.id=" + str(i['id_form']))
            for i in items:
                i['numery_seryjne'] = oblicz_numery_seryjne(i['id'])
            forms.append(wyswietl_czasy_studzenia_i_chlodzenia(items))

        forms_final = []
        for i in forms:
            forms_final.append(i[0])
            
        return render_template("knockout_mafi_forms.html", forms=forms_final) 
       
@app.route("/sn_error", methods=['GET'])
def sn_error():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        return render_template("sn_error.html") 
    
@app.route("/sn_error2", methods=['GET'])
def sn_error2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        return render_template("sn_error2.html") 

@app.route("/sn_error5", methods=['GET'])
def sn_error5():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        return render_template("sn_error5.html") 

@app.route("/no_form", methods=['GET'])
def no_form():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        return render_template("no_form.html") 

#######################################################
################ Operacje na formach ##################
#######################################################


@app.route("/bulk_delete", methods=['POST'])
def bulk_delete():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        start_date = str(request.form['start_date'])
        start_date = start_date.replace("'", "")
        stop_date = str(request.form['stop_date'])
        stop_date = stop_date.replace("'", "")
        if len(start_date) == 0 or len(stop_date) == 0:
            flash(f'Podano niewłaściwe daty')
            return redirect(url_for('forming'))
        else:
            query = "Select id FROM lista_formowania_v2  WHERE data_dodania BETWEEN '" + start_date + "' AND '" + stop_date + "' AND item_status = 'new'"   
            query = query_db(query)
            for i in query:
                query1 = "DELETE FROM lista_formowania_v2 WHERE id=" + str(i['id'])
                query_update(query1)
                query2 = "DELETE FROM lista_formowania_formy_v2 WHERE produkt_id=" + str(i['id'])
                query_update(query2)
                query3 = "Update lista_formowania_historia_v2 SET production_stage='canceled' WHERE produkt_id=" + str(i['id'])
                query_update(query3)   

            return redirect(url_for('forming'))

# EDYCJA ASETU PANEL ADMINA LINIA AUTOMATYCZNA 

@app.route("/edit_item_forming/<id>", methods=['POST', 'GET'])
def edit_item_forming(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        #item_status = str(request.form['item_status'])
        #item_status = item_status.replace("'", "")
        item_status = 'new'
        user = session["user"]
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1
        trail = str(request.form['trail'])
        trail = trail.replace("'", "")
        #nr_formowania = str(request.form['nr_formowania'])
        #query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', komentarz='" + komentarz + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query = "UPDATE lista_formowania_v2 SET komentarz='" + komentarz + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp(), trail='" + str(trail) + "' WHERE id=" + id
        query_update(query)
        #query = "UPDATE semafor_linia_automatyczna SET semafor='1', czas=current_timestamp()"
        #query_update(query)   
        history(id, 'zmiana_trail', user)
        return redirect(url_for('forming'))

@app.route("/edit_casted_form/<id>", methods=['POST'])
def edit_casted_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        user = session["user"]
        nr_kadzi = str(request.form['nr_kadzi'])
        nr_kadzi = nr_kadzi.replace("'", "")
        temp_zeliwa = str(request.form['temp_zeliwa'])
        temp_zeliwa = temp_zeliwa.replace("'", "")
        dolewka = str(request.form['filtr'])
        dolewka = dolewka.replace("'", "")
        wyciek = str(request.form['broken'])
        wyciek = wyciek.replace("'", "")
        query = "UPDATE lista_formowania_v2 SET nr_kadzi=" + str(nr_kadzi) + ", temp_zeliwa=" + str(temp_zeliwa) + ", filtr='" + dolewka + "', broken='" + wyciek + "', zmodyfikowane_przez='" + user + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query) 
        history(id, 'edit_costed_form', user)
        return redirect(request.referrer)

# EDYCJA ASETU PANEL ADMINA RDZENIARNIA 

@app.route("/edit_item_cores/<id>", methods=['POST', 'GET'])
def edit_item_cores(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_status = str(request.form['item_status'])
        item_status = item_status.replace("'", "")
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1
        nr_formowania = 'NULL'
        query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', nr_formowania='" + nr_formowania + "', komentarz='" + komentarz + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query) 
        user = session["user"]
        history(id, item_status, user)
        return redirect(url_for('cores'))

# EDYCJA ASETU PANEL ADMINA ODLEANIA 

@app.route("/edit_item_foundry/<id>", methods=['POST', 'GET'])
def edit_item_foundry(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_status = str(request.form['item_status'])
        item_status = item_status.replace("'", "")
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1
        flask1 = str(request.form['flask1'])
        flask1 = flask1.replace("'", "").replace("-", "")
        flask2 = str(request.form['flask2'])
        flask2 = flask2.replace("'", "").replace("-", "")
        nr_formowania = 'NULL'
        user = session["user"]
        query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', nr_formowania='" + nr_formowania + "', komentarz='" + komentarz + "', flask1='" + flask1 + "', flask2='" + flask2 + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + user + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        history(id, item_status, user)
        return redirect(url_for('foundry'))

# EDYCJA ASETU PANEL ADMINA WIATA 

@app.route("/edit_item_cooling/<id>", methods=['POST', 'GET'])
def edit_item_cooling(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_status = str(request.form['item_status'])
        item_status = item_status.replace("'", "")
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1
        flask1 = str(request.form['flask1'])
        flask1 = flask1.replace("'", "").replace("-", "")
        flask2 = str(request.form['flask2'])
        flask2 = flask2.replace("'", "").replace("-", "")
        nr_formowania = 'NULL'
        query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', nr_formowania='" + nr_formowania + "', komentarz='" + komentarz + "', flask1='" + flask1 + "', flask2='" + flask2 + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        user = session["user"]
        history(id, item_status, user)
        return redirect(url_for('cooling'))

# EDYCJA ASETU PANEL ADMINA WYBIJANIE 

@app.route("/edit_item_knockout/<id>", methods=['POST', 'GET'])
def edit_item_knockout(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_status = str(request.form['item_status'])
        item_status = item_status.replace("'", "")
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1
        flask1 = str(request.form['flask1'])
        flask1 = flask1.replace("'", "").replace("-", "")
        flask2 = str(request.form['flask2'])
        flask2 = flask2.replace("'", "").replace("-", "")
        nr_formowania = 'NULL'
        query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', nr_formowania='" + nr_formowania + "', komentarz='" + komentarz + "', flask1='" + flask1 + "', flask2='" + flask2 + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        user = session["user"]
        history(id, item_status, user)
        return redirect(url_for('knockout'))

# # EDYCJA ASETU PANEL ADMINA BUFOR 

# @app.route("/edit_item_buffer/<id>", methods=['POST', 'GET'])
# def edit_item_buffer(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         item_status = str(request.form['item_status'])
#         item_status = item_status.replace("'", "")
#         query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         if item_status == 'new':
#             query = "UPDATE lista_formowania_formy_v2 SET zaformowano='0' WHERE produkt_id=" + id
#             print('ok1')
#             query_update(query)
#         else:
#             query = "UPDATE lista_formowania_formy_v2 SET zaformowano='1' WHERE produkt_id=" + id
#             query_update(query) 
#             print('ok2')           
#         return redirect(url_for('buffer'))

# EDYCJA ASETU PANEL ADMINA OCZYSZCZANIE

@app.route("/edit_item_grinding/<id>", methods=['POST', 'GET'])
def edit_item_grinding(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        item_status = str(request.form['item_status'])
        item_status = item_status.replace("'", "")
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1
        flask1 = str(request.form['flask1'])
        flask1 = flask1.replace("'", "").replace("-", "")
        flask2 = str(request.form['flask2'])
        flask2 = flask2.replace("'", "").replace("-", "")
        nr_formowania = 'NULL'
        query = "UPDATE lista_formowania_v2 SET item_status='" + item_status + "', nr_formowania='" + nr_formowania + "', komentarz='" + komentarz + "', flask1='" + flask1 + "', flask2='" + flask2 + "', komentarz_flag='" + str(komentarz_flag) + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        user = session["user"]
        history(id, item_status, user)
        return redirect(url_for('grinding'))

# PRZENIESIENIE DO BUFORA POJEDYŃCZEGO ASETU
@app.route("/remove_from_forming_list_by_office/<id>", methods=['POST', 'GET'])
def remove_from_forming_list_by_office(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        remove_item_from_forming_list(id)
        remove_item_from_sn_list(id)
        history(id, 'canceled', session['user'])
        return redirect(url_for('forming'))

# PRZENIESIENIE DO BUFORA POJEDYŃCZEGO ASETU
@app.route("/remove_from_forming_list_on_all_stages", methods=['POST', 'GET'])
def remove_from_forming_list_on_all_stages():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        serial = request.form.get('ns_form_aps')
        if serial is None:
            flash("Wystąpił nieoczekiwany błąd!")
            return redirect(url_for('forming'))     
        
        serial = serial.upper()
           
        if not is_valid_serial_number(serial):
            flash(f"Wprawdzony numer seryjny posiada błądny format: {serial}. Prawidłowy format to: AB-1234")
            return redirect(request.referrer)

        prefix, numer = serial.split("-")
        numer = int(numer)
        query = f"SELECT produkt_id FROM lista_formowania_sn WHERE prefix='{prefix}' AND sn='{numer}'"
        try:
            id = query_db(query)[0]['produkt_id']
        except IndexError:
            flash(f"Wprawdzony numer seryjny nie istnieje: {serial}.")
            return redirect(request.referrer)

        remove_item_from_forming_list_aps(id)
        history(id, 'canceled by office', session['user'])

    return redirect(url_for('forming'))
    
# @app.route("/move_to_buffer/<id>", methods=['POST', 'GET'])
# def move_to_buffer(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
#         query_update(query)
#         return redirect(url_for('forming'))
    
# @app.route("/move_to_buffer_cores/<id>", methods=['POST', 'GET'])
# def move_to_buffer_cores(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
#         print(query)
#         query_update(query)
#         return redirect(url_for('cores'))
    
# @app.route("/move_to_buffer_foundry/<id>", methods=['POST', 'GET'])
# def move_to_buffer_foundry(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
#         print(query)
#         query_update(query)
#         return redirect(url_for('foundry'))
    
# @app.route("/move_to_buffer_cooling/<id>", methods=['POST', 'GET'])
# def move_to_buffer_cooling(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
#         print(query)
#         query_update(query)
#         return redirect(url_for('cooling'))
    
# @app.route("/move_to_buffer_knockout/<id>", methods=['POST', 'GET'])
# def move_to_buffer_knockout(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
#         print(query)
#         query_update(query)
#         return redirect(url_for('knockout'))
    
# @app.route("/move_to_buffer_grinding/<id>", methods=['POST', 'GET'])
# def move_to_buffer_grinding(id):
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#         query_update(query)
#         query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
#         print(query)
#         query_update(query)
#         return redirect(url_for('grinding'))

# KASOWANIE PRODUCKTU / ZMIANA STATUSU NA NIEAKTYWNY

@app.route("/delete_product/<id>", methods=['POST', 'GET'])
def delete_product(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = "UPDATE lista_formowania_v2 SET item_status='canceled' WHERE id=" + id
        query_update(query)
        query = "UPDATE lista_formowania_formy_v2 SET zaformowano='2', czas_ostatniej_modyfiakcji=current_timestamp(), operator='" + str(session["user"]) + "' WHERE produkt_id=" + id
        query_update(query)
        return redirect(url_for('buffer'))

# DODAWANIA PRODUKTU DO BAZY DANYCH PRODUKTÓW

@app.route("/add_produkt", methods=['POST'])
def add_product():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        nazwa =  str(request.form['nazwa'])
        # waga_piasku =  str(request.form['waga_piasku'])
        # sztuk =  str(request.form['sztuk'])
        # sztuk_rdzeni =  str(request.form['sztuk_rdzeni'])
        # nazwa_rdzenia =  str(request.form['nazwa_rdzenia'])
        # waga_rdzeni =  str(request.form['waga_rdzeni'])
        # dni_do_wybicia =  str(request.form['dni_do_wybicia'])
        # filtr =  str(request.form['filtr'])
        # uklad_wlwwody =  str(request.form['uklad_wlwwody'])
        # filtry =  str(request.form['filtry'])
        # rdzeni =  str(request.form['rdzeni'])
        # fi =  str(request.form['fi'])
        # sznur =  str(request.form['sznur'])
        # waga_zeliwa =  str(request.form['waga_zeliwa'])
        # skrzynia1 =  str(request.form['skrzynia1'])
        # skrzynia2 =  str(request.form['skrzynia2'])
        # skrzynia3 =  str(request.form['skrzynia3'])
        # skrzynia4 =  str(request.form['skrzynia4'])
        # id_model1 =  str(request.form['id_model1'])
        # id_model2 =  str(request.form['id_model2'])

        #query = "INSERT INTO produkty(nazwa, waga_piasku, sztuk, sztuk_rdzeni, nazwa_rdzenia, waga_rdzeni, dni_do_wybicia, filtr, rdzeni, uklad_wlwwody, filtry, fi, sznur, skrzynia1, skrzynia2, skrzynia3, skrzynia4, waga_zeliwa, id_model1, id_model2, last_modification_by, last_modification_date) VALUES('" + nazwa + "','" + waga_piasku + "','" + sztuk + "','" + sztuk_rdzeni + "','" + nazwa_rdzenia + "','" + waga_rdzeni + "','" + dni_do_wybicia + "','" + filtr + "'," + rdzeni + ",'" + uklad_wlwwody + "','" + filtry + "'," + fi + "," + sznur + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "','" + skrzynia4 + "'," + waga_zeliwa + "," + id_model1 + "," + id_model1 + ",'" + str(session["user"]) + "',current_timestamp())"
        query = "INSERT INTO produkty(nazwa, last_modification_by, last_modification_date) VALUES('" + nazwa + "','" + str(session["user"]) + "',current_timestamp())"
        query_update(query)
        return redirect(url_for('products'))  
    
# EDYCJA PRODUKTU DO BAZY DANYCH PRODUKTÓW

@app.route("/edit_produkt/<id>", methods=['POST'])
def edit_produkt(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        nazwa =  str(request.form['nazwa']).strip()
        waga_piasku =  str(request.form['waga_piasku']).strip()
        sztuk =  str(request.form['sztuk']).strip()
        sztuk_rdzeni =  str(request.form['sztuk_rdzeni']).strip()
        nazwa_rdzenia =  str(request.form['nazwa_rdzenia']).strip()
        waga_rdzeni =  str(request.form['waga_rdzeni']).strip()
        dni_do_wybicia =  str(request.form['dni_do_wybicia']).strip()
        filtr =  str(request.form['filtr']).strip()
        uklad_wlwwody =  str(request.form['uklad_wlwwody']).strip()
        filtry =  str(request.form['filtry']).strip()
        rdzeni =  str(request.form['rdzeni']).strip()
        fi =  str(request.form['fi']).strip()
        sznur =  str(request.form['sznur']).strip()
        waga_zeliwa =  str(request.form['waga_zeliwa']).strip()
        czas_studzenia =  str(request.form['czas_studzenia']).strip()
        skrzynia1 =  str(request.form['skrzynia1']).strip()
        skrzynia2 =  str(request.form['skrzynia2']).strip()
        skrzynia3 =  str(request.form['skrzynia3']).strip()
        skrzynia4 =  str(request.form['skrzynia4']).strip()
        id_model1 =  str(request.form['id_model1']).strip()
        id_model2 =  str(request.form['id_model2']).strip()
        id_model3 =  str(request.form['id_model3']).strip()
        id_model4 =  str(request.form['id_model4']).strip()
        counter =  str(request.form['counter']).strip()

        if waga_zeliwa == '' or waga_zeliwa == None:
            waga_zeliwa = 0  
        if sznur == '' or sznur == None:
            sznur = 0  
        if fi == '' or fi == None:
            fi = 0
        if rdzeni == '' or rdzeni == None:
            rdzeni = 0 
        if filtry == '' or filtry == None:
            filtry = 'NULL'  
        if uklad_wlwwody == '' or uklad_wlwwody == None:
            uklad_wlwwody = 'NULL'  
        if filtr == '' or filtr == None:
            filtr = 'NULL'  
        if czas_studzenia == '' or czas_studzenia == None:
            czas_studzenia = 0
        if dni_do_wybicia == '' or dni_do_wybicia == None:
            dni_do_wybicia = 0
        if waga_rdzeni == '' or waga_rdzeni == None:
            waga_rdzeni = 0  
        if nazwa_rdzenia == '' or nazwa_rdzenia == None:
            nazwa_rdzenia = 'NULL'  
        if sztuk_rdzeni == '' or sztuk_rdzeni == None:
            sztuk_rdzeni = 0  
        if sztuk == '' or sztuk == None:
            sztuk = 0      
        if nazwa == '' or nazwa == None:
            nazwa = 'NULL'
        if waga_piasku == '' or waga_piasku == None:
            waga_piasku = 0
        if fi == '' or fi == None:
            fi = 0
        if id_model1 == '' or id_model1 == None:
            id_model1 = 0
        if id_model2 == '' or id_model2 == None:
            id_model2 = 0
        if id_model3 == '' or id_model3 == None:
            id_model3 = 0
        if id_model4 == '' or id_model4 == None:
            id_model4 = 0
        if skrzynia1 == '' or skrzynia1 == None:
            skrzynia1 = 'NULL'
        if skrzynia2 == '' or skrzynia2 == None:
            skrzynia2 = 'NULL'
        if skrzynia3 == '' or skrzynia3 == None:
            skrzynia3 = 'NULL'
        if skrzynia4 == '' or skrzynia4 == None:
            skrzynia4 = 'NULL'
        if counter == '' or counter == None:
            counter = 0

        query = "UPDATE `produkty` SET counter='" + str(counter) + "', nazwa='" + str(nazwa) + "', waga_piasku='" + str(waga_piasku) + "', sztuk='" + str(sztuk) + "', sztuk_rdzeni='" + str(sztuk_rdzeni) + "', nazwa_rdzenia='" + str(nazwa_rdzenia) + "', waga_rdzeni='" + str(waga_rdzeni) + "', dni_do_wybicia='" + str(dni_do_wybicia) + "', czas_studzenia='" + str(czas_studzenia) + "', filtr='" + str(filtr) + "', rdzeni='" + str(rdzeni) + "', uklad_wlwwody='" + str(uklad_wlwwody) + "', filtry='" + str(filtry) + "', fi='" + str(fi) + "', sznur='" + str(sznur) + "', waga_zeliwa='" + str(waga_zeliwa) + "', skrzynia1='" + str(skrzynia1) + "', skrzynia2='" + str(skrzynia2) + "', skrzynia3='" + str(skrzynia3) + "', skrzynia4='" + str(skrzynia4) + "', waga_zeliwa='" + str(waga_piasku) + "', id_model1=" + str(id_model1) + ", id_model2=" + str(id_model2) + ", id_model3=" + str(id_model3) + ", id_model4=" + str(id_model4) + ", last_modification_by='" + str(session["user"]) + "', last_modification_date=current_timestamp() WHERE produkt_id=" + str(id)
        query_update(query)
        return redirect(url_for('products'))  

# MASOWE PRZESUWANIE DO BUFORA

@app.route("/move_to_buffer2", methods=['POST'])
def move_to_buffer2():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        days = str(request.form['days'])
        query = "UPDATE lista_formowania_v2 SET item_status='buffer', data_ostatniej_modyfikacji=current_timestamp(), zmodyfikowane_przez='" + str(session["user"]) + "' WHERE data_dodania <= CURDATE() - " + days + ""
        query_update(query)
        flash(f'Operacja wykonana poprawnie.')
        return redirect(url_for('forming'))  

# DODAWANIE DO LISTY FORMOWANIA LINIA AUTOMATYCZNA - PANEL ADMINA 
def sprawdz_liczbe_wykonan(liczba_wykonan, limit, nazwa_funkcji):
    if liczba_wykonan > limit:
        flash(f"Nieprawidłowe wywołanie {nazwa_funkcji}()")
        return False
    return True


@app.route("/add_to_forming_list", methods=['POST'])
def add_to_forming_list():
     if not g.user:
         flash(f'Login required.')
         return redirect(url_for('login'))
     else:
         komentarz = str(request.form['komentarz'])
         komentarz = komentarz.replace("'", "")
         if len(komentarz.replace(" ", "")) == 0:
             komentarz_flag = 0
         else:
             komentarz_flag = 1
         nazwa = request.form['nazwa']
         id_query = "SELECT produkt_id, prefix FROM produkty WHERE nazwa LIKE '" + nazwa + "' AND item_status = 'active'"
         id = query_db_first(id_query)
         id = id['produkt_id']
         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id) + "'"
         produkt_data = query_db(query)
         id_model1 = str(produkt_data[0]['id_model1'])
         id_model2 = str(produkt_data[0]['id_model2'])
         id_model3 = str(produkt_data[0]['id_model3'])
         id_model4 = str(produkt_data[0]['id_model4'])
         prefix = str(produkt_data[0]['prefix'])
         query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
         query_model_names = query_model_names.replace('None', 'NULL')
         query_model_names = query_db(query_model_names)
         if id_model1 == 'None' or id_model1 == '':
             id_model1 = 'NULL'
         if id_model2 == 'None' or id_model2 == '':
             id_model2 = 'NULL'
         if id_model3 == 'None' or id_model3 == '':
             id_model3 = 'NULL'
         if id_model4 == 'None' or id_model4 == '':
             id_model4 = 'NULL'
         sztuk_na_model = str(produkt_data[0]['sztuk'])
         czas_studzenia = str(produkt_data[0]['czas_studzenia'])
         skrzynia1 = str(produkt_data[0]['skrzynia1'])
         if skrzynia1 == 'None' or skrzynia1 == '':
             skrzynia1 = 'NULL'
         skrzynia2 = str(produkt_data[0]['skrzynia2'])
         if skrzynia2 == 'None' or skrzynia2 == '':
             skrzynia2 = 'NULL'
         skrzynia3 = str(produkt_data[0]['skrzynia3'])
         if skrzynia3 == 'None' or skrzynia3 == '':
             skrzynia3 = 'NULL'
         skrzynia4 = str(produkt_data[0]['skrzynia4'])
         if skrzynia4 == 'None' or skrzynia4 == '':
             skrzynia4 = 'NULL'
         q = int(request.form['quantity'])
         nazwa_produktu = str(produkt_data[0]['nazwa'])
         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
         item_status = 'new'
         user = session["user"]
         if request.form.get('trail'):
            trail = '1'
         else: 
            trail = '0' 
        
         if prefix == 'XX' or prefix == 'None':
            flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
            return redirect(url_for('forming'))

         if produkt_data[0]['sztuk'] == 0:
             return redirect(url_for('sn_error5'))

        #  global nazwa_prod
        #  nazwa_prod = nazwa
         if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
             return redirect(url_for('id_model_error'))

         for n in range(q):
             if not sprawdz_liczbe_wykonan(n + 1, q, "add_to_forming_list"):
                 return redirect(url_for('forming'))
             add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
             produkt_id = str(get_produkt_id('new')['id'])
             formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
             nadaj_nr_seryjny(id)
             add_sn_based_on_forms(produkt_id)
             history(produkt_id, 'new', user)
         return redirect(url_for('forming'))


@app.route("/add_to_forming_list_from_production_orders", methods=['POST'])
def add_to_forming_list_from_production_orders():
     if not g.user:
         flash(f'Login required.')
         return redirect(url_for('login'))
     else:
        index_sap = request.form['item_index']
        # global nazwa_prod

        if index_sap == '705651':
            # ------------------------------------------
            # Dodanie produktu id=64 i id=67
            # ------------------------------------------
            unique_id_po = request.form['unique_id']
            quantity = int(request.form['quantity_po'])

            query = "SELECT * FROM produkty WHERE produkt_id=64"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=64

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            # ------------------------------------------
            # Dodanie id=67
            # ------------------------------------------
            
            query = "SELECT * FROM produkty WHERE produkt_id=67"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""
            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=67

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            return redirect(url_for('forming'))

        elif index_sap == '705638':
            # ------------------------------------------
            # Dodanie produktu id=64 i id=65
            # ------------------------------------------
            print("705638 -> produkty: 64 i 65")
            unique_id_po = request.form['unique_id']
            quantity = int(request.form['quantity_po'])

            query = "SELECT * FROM produkty WHERE produkt_id=64"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=64

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            # ------------------------------------------
            # Dodanie produktu id=65
            # ------------------------------------------
            query = "SELECT * FROM produkty WHERE produkt_id=65"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=65

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            return redirect(url_for('forming'))

        elif index_sap == '705639':
            print("705638 -> produkty: 66 i 68")
            # ------------------------------------------
            # Dodanie produktu id=66 i id=68
            # ------------------------------------------
            unique_id_po = request.form['unique_id']
            quantity = int(request.form['quantity_po'])

            query = "SELECT * FROM produkty WHERE produkt_id=66"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=66

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            # ------------------------------------------
            # Dodanie produktu id=68
            # ------------------------------------------
            query = "SELECT * FROM produkty WHERE produkt_id=68"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=68
            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            return redirect(url_for('forming'))

        elif index_sap == '705637':
            # ------------------------------------------
            # Dodanie produktu id=64 i id=67
            # ------------------------------------------
            unique_id_po = request.form['unique_id']
            quantity = int(request.form['quantity_po'])

            query = "SELECT * FROM produkty WHERE produkt_id=64"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=64

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            # ------------------------------------------
            # Dodanie produktu id=67
            # ------------------------------------------
            query = "SELECT * FROM produkty WHERE produkt_id=67"
            produkt_data = query_db(query)
            id_model1 = str(produkt_data[0]['id_model1'])
            id_model2 = str(produkt_data[0]['id_model2'])
            id_model3 = str(produkt_data[0]['id_model3'])
            id_model4 = str(produkt_data[0]['id_model4'])
            prefix = str(produkt_data[0]['prefix'])
            query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
            query_model_names = query_model_names.replace('None', 'NULL')
            query_model_names = query_db(query_model_names)
            if id_model1 == 'None' or id_model1 == '':
                id_model1 = 'NULL'
            if id_model2 == 'None' or id_model2 == '':
                id_model2 = 'NULL'
            if id_model3 == 'None' or id_model3 == '':
                id_model3 = 'NULL'
            if id_model4 == 'None' or id_model4 == '':
                id_model4 = 'NULL'
            sztuk_na_model = str(produkt_data[0]['sztuk'])

            ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
            ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

            czas_studzenia = str(produkt_data[0]['czas_studzenia'])
            skrzynia1 = str(produkt_data[0]['skrzynia1'])
            if skrzynia1 == 'None' or skrzynia1 == '':
                skrzynia1 = 'NULL'
            skrzynia2 = str(produkt_data[0]['skrzynia2'])
            if skrzynia2 == 'None' or skrzynia2 == '':
                skrzynia2 = 'NULL'
            skrzynia3 = str(produkt_data[0]['skrzynia3'])
            if skrzynia3 == 'None' or skrzynia3 == '':
                skrzynia3 = 'NULL'
            skrzynia4 = str(produkt_data[0]['skrzynia4'])
            if skrzynia4 == 'None' or skrzynia4 == '':
                skrzynia4 = 'NULL'

            nazwa_produktu = str(produkt_data[0]['nazwa'])
            dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
            item_status = 'new'
            user = session["user"]
            komentarz=""

            if request.form.get('trail'):
                trail = '1'
            else: 
                trail = '0' 
            
            if prefix == 'XX' or prefix == 'None':
                flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
                return redirect(url_for('forming'))

            if produkt_data[0]['sztuk'] == 0:
                return redirect(url_for('sn_error5'))

            # global nazwa_prod
            # nazwa_prod = nazwa
            if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
                return redirect(url_for('id_model_error'))

            id=67

            for n in range(ilosc_form):
                if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                    return redirect(url_for('forming'))
                add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
                produkt_id = str(get_produkt_id('new')['id'])
                formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
                nadaj_nr_seryjny(id)
                add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
                history(produkt_id, 'new', user)

            return redirect(url_for('forming'))

        # -------------------------------------
        # Dodawanie pozostalych produktów
        # -------------------------------------

        else:
            try:
                unique_id_po = request.form['unique_id']
                nazwa = request.form['nazwa_odlew']
                id = int(request.form['index_odlew'])
                quantity = int(request.form['quantity_po'])

                print('Uniqe id:', unique_id_po)
                print('Nazwa:', nazwa)
                print('id:', id)
                print('Ilość:', quantity)
        
            except Exception as e:
                flash(f'Odlew nie został dodany! Błąd w danych wejściowych formularza: {str(e)}')
                return redirect(url_for('forming'))


        query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id) + "'"
        produkt_data = query_db(query)
        id_model1 = str(produkt_data[0]['id_model1'])
        id_model2 = str(produkt_data[0]['id_model2'])
        id_model3 = str(produkt_data[0]['id_model3'])
        id_model4 = str(produkt_data[0]['id_model4'])
        prefix = str(produkt_data[0]['prefix'])
        query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
        query_model_names = query_model_names.replace('None', 'NULL')
        query_model_names = query_db(query_model_names)
        if id_model1 == 'None' or id_model1 == '':
            id_model1 = 'NULL'
        if id_model2 == 'None' or id_model2 == '':
            id_model2 = 'NULL'
        if id_model3 == 'None' or id_model3 == '':
            id_model3 = 'NULL'
        if id_model4 == 'None' or id_model4 == '':
            id_model4 = 'NULL'
        sztuk_na_model = str(produkt_data[0]['sztuk'])

        ilosc_form_do_zasypania = int(quantity) / int(sztuk_na_model)
        ilosc_form = int(ilosc_form_do_zasypania) if ilosc_form_do_zasypania.is_integer() else int(ilosc_form_do_zasypania) + 1

        czas_studzenia = str(produkt_data[0]['czas_studzenia'])
        skrzynia1 = str(produkt_data[0]['skrzynia1'])
        if skrzynia1 == 'None' or skrzynia1 == '':
           skrzynia1 = 'NULL'
        skrzynia2 = str(produkt_data[0]['skrzynia2'])
        if skrzynia2 == 'None' or skrzynia2 == '':
           skrzynia2 = 'NULL'
        skrzynia3 = str(produkt_data[0]['skrzynia3'])
        if skrzynia3 == 'None' or skrzynia3 == '':
           skrzynia3 = 'NULL'
        skrzynia4 = str(produkt_data[0]['skrzynia4'])
        if skrzynia4 == 'None' or skrzynia4 == '':
           skrzynia4 = 'NULL'

        nazwa_produktu = str(produkt_data[0]['nazwa'])
        dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
        item_status = 'new'
        user = session["user"]
        komentarz=""

        if request.form.get('trail'):
            trail = '1'
        else: 
            trail = '0' 
        
        if prefix == 'XX' or prefix == 'None':
            flash(f"Prefix dla produktu: {nazwa} nie został ustawiony. Ustaw prefix w bazie danych produktów.")
            return redirect(url_for('forming'))

        if produkt_data[0]['sztuk'] == 0:
             return redirect(url_for('sn_error5'))

        # global nazwa_prod
        # nazwa_prod = nazwa
        if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
            return redirect(url_for('id_model_error'))


        for n in range(ilosc_form):
            if not sprawdz_liczbe_wykonan(n + 1, ilosc_form, "add_to_forming_list_production_orders"):
                return redirect(url_for('forming'))
            add_item_to_forming_list(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
            produkt_id = str(get_produkt_id('new')['id'])
            formy_do_zasypania(produkt_id, id, query_model_names, prefix, session["user"])
            nadaj_nr_seryjny(id)
            add_sn_based_on_forms_production_orders(produkt_id, unique_id_po)
            history(produkt_id, 'new', user)

        return redirect(url_for('forming'))

@app.route("/add_to_forming_list_outline", methods=['POST'])
def add_to_forming_list_outline():        
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        nazwa = request.form['product']
        item_status = 'formed'
        # item_status = request.form['stage']
        alias = request.form['sn']
        prefix, serial = alias.split('-')
        if request.form.get('trail'):
            trail = '1'
        else: 
            trail = '0' 
        komentarz = ""
        if len(komentarz.replace(" ", "")) == 0:
            komentarz_flag = 0
        else:
            komentarz_flag = 1

        outlines = query_db("SELECT * FROM lista_formowania_v2 WHERE alias='" + alias + "'")
        if len(outlines) > 0:
            flash(f"Forma: {alias} została juz dodana")
            return redirect(url_for('forming'))
            

        id_query = "SELECT produkt_id, prefix FROM produkty WHERE nazwa LIKE '" + nazwa + "' AND item_status = 'active'"
        id = query_db_first(id_query)['produkt_id']

        prefix_db = query_db_first(id_query)['prefix']
        if prefix != prefix_db:
            flash(f"Wprowadzony prefix: {prefix} nie odpowiada prefixowi przypisanemu do produku {nazwa} w bazie: {prefix_db}.")
            return redirect(url_for('forming'))            
        
        produkt_data = query_db("SELECT * FROM produkty WHERE produkt_id = '" + str(id) + "'")
        id_model1 = str(produkt_data[0]['id_model1'])
        id_model2 = str(produkt_data[0]['id_model2']) 
        id_model3 = str(produkt_data[0]['id_model3'])
        id_model4 = str(produkt_data[0]['id_model4']) 

        # prefix = str(produkt_data[0]['prefix']) 
        query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
        query_model_names = query_model_names.replace('None', 'NULL')
        query_model_names = query_db(query_model_names) 
        if id_model1 == 'None' or id_model1 == '':
            id_model1 = 'NULL'
        if id_model2 == 'None' or id_model2 == '':
            id_model2 = 'NULL'
        if id_model3 == 'None' or id_model3 == '':
            id_model3 = 'NULL'
        if id_model4 == 'None' or id_model4 == '':
            id_model4 = 'NULL'
        sztuk_na_model = str(produkt_data[0]['sztuk'])
        czas_studzenia = str(produkt_data[0]['czas_studzenia'])
        skrzynia1 = str(produkt_data[0]['skrzynia1'])
        if skrzynia1 == 'None' or skrzynia1 == '':
            skrzynia1 = 'NULL'
        skrzynia2 = str(produkt_data[0]['skrzynia2'])
        if skrzynia2 == 'None' or skrzynia2 == '':
            skrzynia2 = 'NULL'
        skrzynia3 = str(produkt_data[0]['skrzynia3'])
        if skrzynia3 == 'None' or skrzynia3 == '':
            skrzynia3 = 'NULL'
        skrzynia4 = str(produkt_data[0]['skrzynia4'])
        if skrzynia4 == 'None' or skrzynia4 == '':
            skrzynia4 = 'NULL'

        nazwa_produktu = str(produkt_data[0]['nazwa'])
        dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
        item_status = 'formed'
        user = session["user"]
        komentarz=""

        if produkt_data[0]['sztuk'] == 0:
            return redirect(url_for('sn_error5')) 

        # global nazwa_prod
        # nazwa_prod = nazwa
        if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
            return redirect(url_for('id_model_error'))  

        add_item_to_forming_list_outline(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, prefix, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail, alias)
        produkt_id = str(get_produkt_id('formed')['id'])

        formy_do_zasypania_outline(produkt_id, id, query_model_names, prefix, session["user"], alias)
        nadaj_nr_seryjny_outline(id, prefix, serial)
        add_sn_based_on_forms(produkt_id)
        history(produkt_id, item_status, user)

    return redirect(url_for('forming'))  
    
# @app.route("/add_to_forming_list_again", methods=['POST'])
# def add_to_forming_list_again():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         komentarz = str(request.form['komentarz'])
#         komentarz = komentarz.replace("'", "")
#         if len(komentarz.replace(" ", "")) == 0:
#             komentarz_flag = 0
#         else:
#             komentarz_flag = 1
#         nazwa = request.form['nazwa']
#         id_query = "SELECT produkt_id FROM produkty WHERE nazwa LIKE '" + nazwa + "' AND  item_status = 'active'"
#         id = query_db_first(id_query)
#         id = id['produkt_id']
#         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id) + "'"
#         produkt_data = query_db(query)
#         id_model1 = str(produkt_data[0]['id_model1'])
#         id_model2 = str(produkt_data[0]['id_model2']) 
#         id_model3 = str(produkt_data[0]['id_model3'])
#         id_model4 = str(produkt_data[0]['id_model4']) 
#         prefix = str(produkt_data[0]['prefix']) 
#         query_model_names = "SELECT nazwa, id FROM tag_modele WHERE ID IN(" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + ")"
#         query_model_names = query_model_names.replace('None', 'NULL')
#         query_model_names = query_db(query_model_names) 
#         if id_model1 == 'None' or id_model1 == '':
#             id_model1 = 'NULL'
#         if id_model2 == 'None' or id_model2 == '':
#             id_model2 = 'NULL'
#         if id_model3 == 'None' or id_model3 == '':
#             id_model3 = 'NULL'
#         if id_model4 == 'None' or id_model4 == '':
#             id_model4 = 'NULL'
#         sztuk_na_model = str(produkt_data[0]['sztuk'])
#         skrzynia1 = str(produkt_data[0]['skrzynia1'])
#         if skrzynia1 == 'None' or skrzynia1 == '':
#             skrzynia1 = 'NULL'
#         skrzynia2 = str(produkt_data[0]['skrzynia2'])
#         if skrzynia2 == 'None' or skrzynia2 == '':
#             skrzynia2 = 'NULL'
#         skrzynia3 = str(produkt_data[0]['skrzynia3'])
#         if skrzynia3 == 'None' or skrzynia3 == '':
#             skrzynia3 = 'NULL'
#         skrzynia4 = str(produkt_data[0]['skrzynia4'])
#         if skrzynia4 == 'None' or skrzynia4 == '':
#             skrzynia4 = 'NULL'
#         q = int(request.form['quantity'])
#         nazwa_produktu = str(produkt_data[0]['nazwa'])
#         czas_studzenia = str(produkt_data[0]['czas_studzenia'])
#         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
#         item_status = 'new'
#         user = session["user"]

#         if request.form.get('trail'):
#             trail = '1'
#         else: 
#             trail = '0'

#         global nazwa_prod
#         nazwa_prod = nazwa
#         if id_model1 == 'NULL' and id_model2 == 'NULL' or id_model1 == 'None' and id_model2 == 'None':
#             return redirect(url_for('id_model_error'))  

#         if produkt_data[0]['sztuk'] == 0:
#             return redirect(url_for('sn_error5')) 
        
#         for n in range(q):
#             add_item_to_forming_list_again(str(id), id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia1, skrzynia2, skrzynia3, skrzynia4, nazwa_produktu, dni_do_wybicia, czas_studzenia, item_status, komentarz, user, trail)
#             produkt_id = str(get_produkt_id('new')['id'])
#             formy_do_zasypania_again(produkt_id, id, query_model_names, prefix, session["user"])
#             history(produkt_id, 'new', str(session["user"]))
#         return redirect(url_for('forming'))  

# # DODAWANE DO LISTY FORMOWANIA RDZENIARNIA - PALEN ADMINA

# @app.route("/add_to_forming_list_cores", methods=['POST'])
# def add_to_forming_list_cores():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         nazwa = request.form['nazwa']
#         id_query = "SELECT produkt_id FROM produkty WHERE nazwa LIKE '" + nazwa + "'"
#         id = query_db_first(id_query)
#         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id['produkt_id']) + "'"
#         produkt_data = query_db(query)
#         id_model1 = str(produkt_data[0]['id_model1'])
#         id_model2 = str(produkt_data[0]['id_model2']) 
#         id_model3 = str(produkt_data[0]['id_model3'])
#         id_model4 = str(produkt_data[0]['id_model4']) 
#         if id_model1 == 'None' or id_model1 == '':
#             id_model1 = 'NULL'
#         if id_model2 == 'None' or id_model2 == '':
#             id_model2 = 'NULL'
#         if id_model3 == 'None' or id_model3 == '':
#             id_model3 = 'NULL'
#         if id_model4 == 'None' or id_model4 == '':
#             id_model4 = 'NULL'
#         sztuk_na_model = str(produkt_data[0]['sztuk'])
#         skrzynia1 = str(produkt_data[0]['skrzynia1'])
#         if skrzynia1 == 'None' or skrzynia1 == '':
#             skrzynia1 = 'NULL'
#         skrzynia2 = str(produkt_data[0]['skrzynia2'])
#         if skrzynia2 == 'None' or skrzynia2 == '':
#             skrzynia2 = 'NULL'
#         skrzynia3 = str(produkt_data[0]['skrzynia3'])
#         if skrzynia3 == 'None' or skrzynia3 == '':
#             skrzynia3 = 'NULL'
#         skrzynia4 = str(produkt_data[0]['skrzynia4'])
#         if skrzynia4 == 'None' or skrzynia4 == '':
#             skrzynia4 = 'NULL'
#         ilosc_sztuk = str('1')
#         n = int(request.form['quantity'])
#         nazwa_produktu = str(produkt_data[0]['nazwa'])
#         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
#         item_status = 'formed'
#         query = "INSERT INTO lista_formowania_v2(id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, dni_do_wybicia, item_status, dodane_przez, zmodyfikowane_przez) VALUES (" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "'," + skrzynia4 + "," + ilosc_sztuk + ",'" + nazwa_produktu + "'," + dni_do_wybicia + ",'" + item_status + "','" + str(session["user"]) + "'," + "'" + str(session["user"]) + "'" + ")"
#         for n in range(n):
#             query_update(query)
#             produkt_id = str(get_produkt_id('formed')['id'])
#             history(produkt_id, 'formed', str(session["user"]))

#         return redirect(url_for('cores'))  

# DODAWANE DO LISTY ZALEWU - PALEN ADMINA 

# @app.route("/add_to_casting_list", methods=['POST'])
# def add_to_casting_list():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         nazwa = request.form['nazwa']
#         id_query = "SELECT produkt_id FROM produkty WHERE nazwa LIKE '" + nazwa + "'"
#         id = query_db_first(id_query)
#         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id['produkt_id']) + "'"
#         produkt_data = query_db(query)
#         id_model1 = str(produkt_data[0]['id_model1'])
#         id_model2 = str(produkt_data[0]['id_model2']) 
#         id_model3 = str(produkt_data[0]['id_model3'])
#         id_model4 = str(produkt_data[0]['id_model4']) 
#         if id_model1 == 'None' or id_model1 == '':
#             id_model1 = 'NULL'
#         if id_model2 == 'None' or id_model2 == '':
#             id_model2 = 'NULL'
#         if id_model3 == 'None' or id_model3 == '':
#             id_model3 = 'NULL'
#         if id_model4 == 'None' or id_model4 == '':
#             id_model4 = 'NULL'
#         sztuk_na_model = str(produkt_data[0]['sztuk'])
#         skrzynia1 = str(produkt_data[0]['skrzynia1'])
#         if skrzynia1 == 'None' or skrzynia1 == '':
#             skrzynia1 = 'NULL'
#         skrzynia2 = str(produkt_data[0]['skrzynia2'])
#         if skrzynia2 == 'None' or skrzynia2 == '':
#             skrzynia2 = 'NULL'
#         skrzynia3 = str(produkt_data[0]['skrzynia3'])
#         if skrzynia3 == 'None' or skrzynia3 == '':
#             skrzynia3 = 'NULL'
#         skrzynia4 = str(produkt_data[0]['skrzynia4'])
#         if skrzynia4 == 'None' or skrzynia4 == '':
#             skrzynia4 = 'NULL'
#         ilosc_sztuk = str('1')
#         n = int(request.form['quantity'])
#         nazwa_produktu = str(produkt_data[0]['nazwa'])
#         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
#         item_status = 'assembled'
#         query = "INSERT INTO lista_formowania_v2(id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, dni_do_wybicia, item_status, dodane_przez, zmodyfikowane_przez) VALUES (" + id_model1 + "," + id_model2 +  "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "'," + skrzynia4 + "," + ilosc_sztuk + ",'" + nazwa_produktu + "'," + dni_do_wybicia + ",'" + item_status + "','" + str(session["user"]) + "'," + "'" + str(session["user"]) + "'" + ")"
#         for n in range(n):
#             query_update(query)
#             produkt_id = str(get_produkt_id('new')['id'])
#             history(produkt_id, 'assembled', str(session["user"]))
       
#         return redirect(url_for('foundry'))  

# DODAWANE DO LISTY CHŁODZENIA - PALEN ADMINA

# @app.route("/add_to_cooling_list", methods=['POST'])
# def add_to_cooling_list():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         nazwa = request.form['nazwa']
#         id_query = "SELECT produkt_id FROM produkty WHERE nazwa LIKE '" + nazwa + "'"
#         id = query_db_first(id_query)
#         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id['produkt_id']) + "'"
#         produkt_data = query_db(query)
#         id_model1 = str(produkt_data[0]['id_model1'])
#         id_model2 = str(produkt_data[0]['id_model2']) 
#         id_model3 = str(produkt_data[0]['id_model3'])
#         id_model4 = str(produkt_data[0]['id_model4']) 
#         if id_model1 == 'None' or id_model1 == '':
#             id_model1 = 'NULL'
#         if id_model2 == 'None' or id_model2 == '':
#             id_model2 = 'NULL'
#         if id_model3 == 'None' or id_model3 == '':
#             id_model3 = 'NULL'
#         if id_model4 == 'None' or id_model4 == '':
#             id_model4 = 'NULL'
#         sztuk_na_model = str(produkt_data[0]['sztuk'])
#         skrzynia1 = str(produkt_data[0]['skrzynia1'])
#         if skrzynia1 == 'None' or skrzynia1 == '':
#             skrzynia1 = 'NULL'
#         skrzynia2 = str(produkt_data[0]['skrzynia2'])
#         if skrzynia2 == 'None' or skrzynia2 == '':
#             skrzynia2 = 'NULL'
#         skrzynia3 = str(produkt_data[0]['skrzynia3'])
#         if skrzynia3 == 'None' or skrzynia3 == '':
#             skrzynia3 = 'NULL'
#         skrzynia4 = str(produkt_data[0]['skrzynia4'])
#         if skrzynia4 == 'None' or skrzynia4 == '':
#             skrzynia4 = 'NULL'
#         ilosc_sztuk = str('1')
#         n = int(request.form['quantity'])
#         nazwa_produktu = str(produkt_data[0]['nazwa'])
#         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
#         item_status = 'casted'
#         query = "INSERT INTO lista_formowania_v2(id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, dni_do_wybicia, item_status, dodane_przez, zmodyfikowane_przez) VALUES (" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "'," + skrzynia4 + "," + ilosc_sztuk + ",'" + nazwa_produktu + "'," + dni_do_wybicia + ",'" + item_status + "','" + str(session["user"]) + "'," + "'" + str(session["user"]) + "'" + ")"
#         for n in range(n):
#             query_update(query)
#             produkt_id = str(get_produkt_id('new')['id'])
#             history(produkt_id, 'assembled', str(session["user"]))

#         return redirect(url_for('cooling'))  

# # DODAWANIE DO LISTY WYBIJANIA - PANEL ADMINA

# @app.route("/add_to_knockout_list", methods=['POST'])
# def add_to_knockout_list():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         nazwa = request.form['nazwa']
#         id_query = "SELECT produkt_id FROM produkty WHERE nazwa LIKE '" + nazwa + "'"
#         id = query_db_first(id_query)
#         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id['produkt_id']) + "'"
#         produkt_data = query_db(query)
#         id_model1 = str(produkt_data[0]['id_model1'])
#         id_model2 = str(produkt_data[0]['id_model2']) 
#         id_model3 = str(produkt_data[0]['id_model3'])
#         id_model4 = str(produkt_data[0]['id_model4']) 
#         if id_model1 == 'None' or id_model1 == '':
#             id_model1 = 'NULL'
#         if id_model2 == 'None' or id_model2 == '':
#             id_model2 = 'NULL'
#         if id_model3 == 'None' or id_model3 == '':
#             id_model3 = 'NULL'
#         if id_model4 == 'None' or id_model4 == '':
#             id_model4 = 'NULL'
#         sztuk_na_model = str(produkt_data[0]['sztuk'])
#         skrzynia1 = str(produkt_data[0]['skrzynia1'])
#         if skrzynia1 == 'None' or skrzynia1 == '':
#             skrzynia1 = 'NULL'
#         skrzynia2 = str(produkt_data[0]['skrzynia2'])
#         if skrzynia2 == 'None' or skrzynia2 == '':
#             skrzynia2 = 'NULL'
#         skrzynia3 = str(produkt_data[0]['skrzynia3'])
#         if skrzynia3 == 'None' or skrzynia3 == '':
#             skrzynia3 = 'NULL'
#         skrzynia4 = str(produkt_data[0]['skrzynia4'])
#         if skrzynia4 == 'None' or skrzynia4 == '':
#             skrzynia4 = 'NULL'
#         ilosc_sztuk = str('1')
#         n = int(request.form['quantity'])
#         nazwa_produktu = str(produkt_data[0]['nazwa'])
#         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
#         item_status = 'knockout'
#         query = "INSERT INTO lista_formowania_v2(id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, dni_do_wybicia, item_status, dodane_przez, zmodyfikowane_przez) VALUES (" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "'," + skrzynia4 + "," + ilosc_sztuk + ",'" + nazwa_produktu + "'," + dni_do_wybicia + ",'" + item_status + "','" + str(session["user"]) + "'," + "'" + str(session["user"]) + "'" + ")"
#         for n in range(n):
#             query_update(query)
#             produkt_id = str(get_produkt_id('new')['id'])
#             history(produkt_id, 'casted', str(session["user"]))
        
#         return redirect(url_for('knockout'))  

# # DODAWANE DO LISTY OCZYSZCZANIA - PALEN ADMINA 

# @app.route("/add_to_grinding", methods=['POST'])
# def add_to_grinding():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         nazwa = request.form['nazwa']
#         id_query = "SELECT produkt_id FROM produkty WHERE nazwa LIKE '" + nazwa + "'"
#         id = query_db_first(id_query)
#         query = "SELECT * FROM produkty WHERE produkt_id = '" + str(id['produkt_id']) + "'"
#         produkt_data = query_db(query)
#         id_model1 = str(produkt_data[0]['id_model1'])
#         id_model2 = str(produkt_data[0]['id_model2']) 
#         id_model3 = str(produkt_data[0]['id_model3'])
#         id_model4 = str(produkt_data[0]['id_model4']) 
#         if id_model1 == 'None' or id_model1 == '':
#             id_model1 = 'NULL'
#         if id_model2 == 'None' or id_model2 == '':
#             id_model2 = 'NULL'
#         if id_model3 == 'None' or id_model3 == '':
#             id_model3 = 'NULL'
#         if id_model4 == 'None' or id_model4 == '':
#             id_model4 = 'NULL'
#         sztuk_na_model = str(produkt_data[0]['sztuk'])
#         skrzynia1 = str(produkt_data[0]['skrzynia1'])
#         if skrzynia1 == 'None' or skrzynia1 == '':
#             skrzynia1 = 'NULL'
#         skrzynia2 = str(produkt_data[0]['skrzynia2'])
#         if skrzynia2 == 'None' or skrzynia2 == '':
#             skrzynia2 = 'NULL'
#         skrzynia3 = str(produkt_data[0]['skrzynia3'])
#         if skrzynia3 == 'None' or skrzynia3 == '':
#             skrzynia3 = 'NULL'
#         skrzynia4 = str(produkt_data[0]['skrzynia4'])
#         if skrzynia4 == 'None' or skrzynia4 == '':
#             skrzynia4 = 'NULL'
#         ilosc_sztuk = str('1')
#         n = int(request.form['quantity'])
#         nazwa_produktu = str(produkt_data[0]['nazwa'])
#         dni_do_wybicia = str(produkt_data[0]['dni_do_wybicia'])
#         item_status = 'grinding'
#         query = "INSERT INTO lista_formowania_v2(id_model1, id_model2, id_model3, id_model4, sztuk_na_model, skrzynia_1, skrzynia_2, skrzynia_3, skrzynia_4, ilosc_sztuk, nazwa_produktu, dni_do_wybicia, item_status, dodane_przez, zmodyfikowane_przez) VALUES (" + id_model1 + "," + id_model2 + "," + id_model3 + "," + id_model4 + "," + sztuk_na_model + ",'" + skrzynia1 + "','" + skrzynia2 + "','" + skrzynia3 + "'," + skrzynia4 + "," + ilosc_sztuk + ",'" + nazwa_produktu + "'," + dni_do_wybicia + ",'" + item_status + "','" + str(session["user"]) + "'," + "'" + str(session["user"]) + "'" + ")"
#         for n in range(n - 1):
#             query_update(query)
#             produkt_id = str(get_produkt_id('new')['id'])
#             history(produkt_id, 'knockout', str(session["user"]))
        
#         return redirect(url_for('grinding')) 

# USUWANIE PRODUKTU

@app.route("/delete_produkt/<id>", methods=['POST'])
def delete_produkt(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = "UPDATE produkty SET item_status='inactive', last_modification_by='" + str(session["user"]) + "', last_modification_date=current_timestamp() WHERE produkt_id=" + id
        query_update(query)
        return redirect(url_for('products'))

#######################################################
############# Operacje na asetach OPERATORZY ##########
#######################################################

@app.route("/mark_as_formed/<id>", methods=['POST'])
def mark_as_formed(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        nr_formowania = str(request.form['nr_formowania'])
        nr_formowania = nr_formowania.replace("'", "")
        komentarz_form = str(request.form['komentarz_formowanie'])
        komentarz_form = komentarz_form.replace("'", "")
        nazwap = str(request.form['nazwap'])
        nazwap = nazwap.strip()
        if sn_validation(nr_formowania, nazwap):
            query_update("UPDATE lista_formowania_v2 SET item_status='formed', nr_formowania='" + nr_formowania + "', komentarz_formowanie='" + komentarz_form + "', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id)
            query_update("UPDATE semafor_linia_automatyczna SET semafor='1', czas=current_timestamp()")    
            history(id, 'formed', str(session["user"]))   
            return redirect(url_for('forming_operator_view'))
        else:
            return redirect(url_for('sn_error'))
        
@app.route("/mark_as_formed_form/<id>", methods=['POST'])
def mark_as_formed_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        try:
            nr_formowania1 = str(request.form['nr_formowania1'])
            nr_formowania1 = nr_formowania1.replace("'", "")
            nr_formowania1 = extracting_digits(nr_formowania1)
            nr_formowania1 = replace_with_null(nr_formowania1)
        except KeyError:
            nr_formowania1 = '0'

        try:
            nr_formowania2 = str(request.form['nr_formowania2'])
            nr_formowania2 = nr_formowania2.replace("'", "")
            nr_formowania2 = extracting_digits(nr_formowania2)
            nr_formowania2 = replace_with_null(nr_formowania2)
        except KeyError:
            nr_formowania2 = '0'

        try:
            nr_formowania3 = str(request.form['nr_formowania3'])
            nr_formowania3 = nr_formowania3.replace("'", "")
            nr_formowania3 = extracting_digits(nr_formowania3)
            nr_formowania3 = replace_with_null(nr_formowania3)
        except KeyError:
            nr_formowania3 = '0'
        try:
            nr_formowania4 = str(request.form['nr_formowania4'])
            nr_formowania4 = nr_formowania4.replace("'", "")
            nr_formowania4 = extracting_digits(nr_formowania4)
            nr_formowania4 = replace_with_null(nr_formowania4)
        except KeyError:
            nr_formowania4 = '0'

        try:
            nr_formowania5 = str(request.form['nr_formowania5'])
            nr_formowania5 = nr_formowania5.replace("'", "")
            nr_formowania5 = extracting_digits(nr_formowania5)
            nr_formowania5 = replace_with_null(nr_formowania5)
        except KeyError:
            nr_formowania5 = '0'

        try:
            nr_formowania6 = str(request.form['nr_formowania6'])
            nr_formowania6 = nr_formowania6.replace("'", "")
            nr_formowania6 = extracting_digits(nr_formowania6)
            nr_formowania6 = replace_with_null(nr_formowania6)
        except KeyError:
            nr_formowania6 = '0'

        try:
            nr_formowania7 = str(request.form['nr_formowania7'])
            nr_formowania7 = nr_formowania7.replace("'", "")
            nr_formowania7 = extracting_digits(nr_formowania7)
            nr_formowania7 = replace_with_null(nr_formowania7)
        except KeyError:
            nr_formowania7 = '0'

        try:
            nr_formowania8 = str(request.form['nr_formowania8'])
            nr_formowania8 = nr_formowania8.replace("'", "")
            nr_formowania8 = extracting_digits(nr_formowania8)
            nr_formowania8 = replace_with_null(nr_formowania8)
        except KeyError:
            nr_formowania8 = '0'

        form_id = str(request.form['form_id'])
    
        # komentarz_form = str(request.form['komentarz_formowanie'])
        # komentarz_form = komentarz_form.replace("'", "")
        komentarz_form = "-"

        produkt_id = str(request.form['produkt_id'])
        produkt_id = produkt_id.replace("'", "")

        model_id = str(request.form['model_id'])
        model_id = model_id.replace("'", "")

        user = str(request.form['operator'])
        user = user.replace("'", "")

        defect_forming = str(request.form['defect'])
        defect_forming = defect_forming.replace("'", "")

        rfid_tag = str(request.form['rfid_tag'])
        rfid_tag = rfid_tag.replace("'", "")

        query = 'SELECT prod_id FROM lista_formowania_formy_v2 WHERE id=' + str(form_id)
        prod_id = query_db(query)[0]['prod_id']

        # Sprawdza czy prawidlowy TAG
        if check_tag_in_db(rfid_tag):
            if replace_with_null(nr_formowania1).strip() == 'NULL' and replace_with_null(nr_formowania2).strip() == 'NULL' and replace_with_null(nr_formowania3).strip() == 'NULL' and replace_with_null(nr_formowania4).strip() == 'NULL' and replace_with_null(nr_formowania5).strip() == 'NULL' and replace_with_null(nr_formowania6).strip() == 'NULL' and replace_with_null(nr_formowania7).strip() == 'NULL' and replace_with_null(nr_formowania8).strip() == 'NULL':
                return render_template('sn_error2.html', id=produkt_id)

            # sprawdza n/s
            sn_numbers_list = [nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8]
            if sn_validation_forms(model_id, prod_id, produkt_id, sn_numbers_list) == False:
                data_list = [nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8, komentarz_form, form_id, produkt_id]
                return render_template('sn_error3.html', data_list=data_list)

            # sprawdza n/s
            if fields_validation_forms(produkt_id) == False:
                return render_template('sn_error4.html', id=produkt_id)
            
            # Dodaje TAG do bazy danych
            add_tag_gate_mf(form_id, produkt_id, model_id, rfid_tag)

            # Oznacza formę jako zafomowana
            forma_zasypana(komentarz_form, nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8, form_id, produkt_id, defect_forming, user) 
            history_forms(id, 'formed', user)
            update_semafor()

        else:
            flash(f'Brak id skrzyni w bazie danych.')
            url='/forming_operator_view3/' + str(produkt_id)
            return redirect(url)            
        
        if remove_from_forming_list(produkt_id):
            query = "UPDATE lista_formowania_v2 SET item_status='formed', data_zaformowania=current_timestamp(), nr_formowania='NULL', komentarz_formowanie='NULL', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + produkt_id
            query_update(query)
            history(produkt_id, 'formed', user)
            update_counter_based_on_operator_entry(produkt_id)
            update_sand_temp('auto', produkt_id)    
            return redirect(url_for('forming_operator_view'))
        else:
            url='/forming_operator_view3/' + str(produkt_id)
            #history_forms(id, 'formed', user)
            return redirect(url)

@app.route("/mark_as_formed_m_form/<id>", methods=['POST'])
def mark_as_formed_m_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        try:
            nr_formowania1 = str(request.form['nr_formowania1'])
            nr_formowania1 = nr_formowania1.replace("'", "")
            nr_formowania1 = extracting_digits(nr_formowania1)
            nr_formowania1 = replace_with_null(nr_formowania1)
        except KeyError:
            nr_formowania1 = '0'

        try:
            nr_formowania2 = str(request.form['nr_formowania2'])
            nr_formowania2 = nr_formowania2.replace("'", "")
            nr_formowania2 = extracting_digits(nr_formowania2)
            nr_formowania2 = replace_with_null(nr_formowania2)
        except KeyError:
            nr_formowania2 = '0'

        try:
            nr_formowania3 = str(request.form['nr_formowania3'])
            nr_formowania3 = nr_formowania3.replace("'", "")
            nr_formowania3 = extracting_digits(nr_formowania3)
            nr_formowania3 = replace_with_null(nr_formowania3)
        except KeyError:
            nr_formowania3 = '0'
        try:
            nr_formowania4 = str(request.form['nr_formowania4'])
            nr_formowania4 = nr_formowania4.replace("'", "")
            nr_formowania4 = extracting_digits(nr_formowania4)
            nr_formowania4 = replace_with_null(nr_formowania4)
        except KeyError:
            nr_formowania4 = '0'

        try:
            nr_formowania5 = str(request.form['nr_formowania5'])
            nr_formowania5 = nr_formowania5.replace("'", "")
            nr_formowania5 = extracting_digits(nr_formowania5)
            nr_formowania5 = replace_with_null(nr_formowania5)
        except KeyError:
            nr_formowania5 = '0'

        try:
            nr_formowania6 = str(request.form['nr_formowania6'])
            nr_formowania6 = nr_formowania6.replace("'", "")
            nr_formowania6 = extracting_digits(nr_formowania6)
            nr_formowania6 = replace_with_null(nr_formowania6)
        except KeyError:
            nr_formowania6 = '0'

        try:
            nr_formowania7 = str(request.form['nr_formowania7'])
            nr_formowania7 = nr_formowania7.replace("'", "")
            nr_formowania7 = extracting_digits(nr_formowania7)
            nr_formowania7 = replace_with_null(nr_formowania7)
        except KeyError:
            nr_formowania7 = '0'

        try:
            nr_formowania8 = str(request.form['nr_formowania8'])
            nr_formowania8 = nr_formowania8.replace("'", "")
            nr_formowania8 = extracting_digits(nr_formowania8)
            nr_formowania8 = replace_with_null(nr_formowania8)
        except KeyError:
            nr_formowania8 = '0'

        form_id = str(request.form['form_id'])
    
        # komentarz_form = str(request.form['komentarz_formowanie'])
        # komentarz_form = komentarz_form.replace("'", "")
        komentarz_form = '-'

        # defect_forming = str(request.form['defect'])
        # defect_forming = defect_forming.replace("'", "")
        defect_forming = '-'

        produkt_id = str(request.form['produkt_id'])
        produkt_id = produkt_id.replace("'", "")

        model_id = str(request.form['model_id'])
        model_id = model_id.replace("'", "")

        user = str(request.form['operator'])
        user = user.replace("'", "")

        query = 'SELECT prod_id FROM lista_formowania_formy_v2 WHERE id=' + str(form_id)
        prod_id = query_db(query)[0]['prod_id']

        if replace_with_null(nr_formowania1).strip() == 'NULL' and replace_with_null(nr_formowania2).strip() == 'NULL' and replace_with_null(nr_formowania3).strip() == 'NULL' and replace_with_null(nr_formowania4).strip() == 'NULL' and replace_with_null(nr_formowania5).strip() == 'NULL' and replace_with_null(nr_formowania6).strip() == 'NULL' and replace_with_null(nr_formowania7).strip() == 'NULL' and replace_with_null(nr_formowania8).strip() == 'NULL':
            return render_template('sn_error2.html', id=produkt_id)

        sn_numbers_list = [nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8]
        if sn_validation_forms(model_id, prod_id, produkt_id, sn_numbers_list) == False:
            data_list = [nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8, komentarz_form, form_id, produkt_id]
            return render_template('sn_error3.html', data_list=data_list)

        if fields_validation_forms(produkt_id) == False:
            return render_template('sn_error4.html', id=produkt_id)
        
        #forma_zasypana(komentarz_form, nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8, form_id, produkt_id, user)
        forma_zasypana(komentarz_form, nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8, form_id, produkt_id, defect_forming, user) 
        history_forms(id, 'formed', user)
        update_semafor()
    
        if remove_from_forming_list(produkt_id):
            query = "UPDATE lista_formowania_v2 SET item_status='formed', data_zaformowania=current_timestamp(), nr_formowania='NULL', komentarz_formowanie='NULL', zmodyfikowane_przez='" + user + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + produkt_id
            query_update(query)
            history(produkt_id, 'formed', user)
            update_counter_based_on_operator_entry(produkt_id)
            update_sand_temp('man', produkt_id)
            return redirect(url_for('forming_operator_m_view'))
        else:
            url='/forming_operator_m_view3/' + str(produkt_id)
            #history_forms(id, 'formed', user)
            return redirect(url)
        
@app.route("/mark_as_formed_form_sv/<id>", methods=['POST'])
def mark_as_formed_form_sv(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        nr_formowania1 = str(request.form['nr_formowania1'])
        nr_formowania1 = nr_formowania1.replace("'", "")
        nr_formowania1 = replace_with_null(nr_formowania1)

        nr_formowania2 = str(request.form['nr_formowania2'])
        nr_formowania2 = nr_formowania2.replace("'", "")
        nr_formowania2 = replace_with_null(nr_formowania2)

        nr_formowania3 = str(request.form['nr_formowania3'])
        nr_formowania3 = nr_formowania3.replace("'", "")
        nr_formowania3 = replace_with_null(nr_formowania3)

        nr_formowania4 = str(request.form['nr_formowania4'])
        nr_formowania4 = nr_formowania4.replace("'", "")
        nr_formowania4 = replace_with_null(nr_formowania4)

        nr_formowania5 = str(request.form['nr_formowania5'])
        nr_formowania5 = nr_formowania5.replace("'", "")
        nr_formowania5 = replace_with_null(nr_formowania5)

        nr_formowania6 = str(request.form['nr_formowania6'])
        nr_formowania6 = nr_formowania6.replace("'", "")
        nr_formowania6 = replace_with_null(nr_formowania6)

        nr_formowania7 = str(request.form['nr_formowania7'])
        nr_formowania7 = nr_formowania7.replace("'", "")
        nr_formowania7 = replace_with_null(nr_formowania7)

        nr_formowania8 = str(request.form['nr_formowania8'])
        nr_formowania8 = nr_formowania8.replace("'", "")
        nr_formowania8 = replace_with_null(nr_formowania8)

        form_id = str(request.form['form_id'])
        form_id = form_id.replace("'", "")

        komentarz_form = str(request.form['komentarz_formowanie'])
        komentarz_form = komentarz_form.replace("'", "")

        produkt_id = str(request.form['produkt_id'])
        produkt_id = produkt_id.replace("'", "")

        if fields_validation_forms(produkt_id) == False:
            return render_template('sn_error4.html', id=produkt_id)

        forma_zasypana('Zdublowane id skrzyni. Wprowadzono za zgodą operatora.', nr_formowania1, nr_formowania2, nr_formowania3, nr_formowania4, nr_formowania5, nr_formowania6, nr_formowania7, nr_formowania8, form_id, produkt_id)
        update_semafor()
        if remove_from_forming_list(produkt_id):
            history(produkt_id, 'formed', str(session["user"])) 
            return redirect(url_for('forming_operator_view'))
        else:
            url='/forming_operator_view3/' + str(produkt_id)
            return redirect(url)
        
@app.route("/delete_frame/<id>", methods=['POST'])
def delete_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        form_id = str(request.form['form_id'])
        form_id = form_id.replace("'", "")
        produkt_id = str(request.form['produkt_id'])
        produkt_id = produkt_id.replace("'", "")
        user = str(session["user"])
        delete_frame(form_id)
        history_forms(id, 'canceled', user)
        url='/forming_operator_view3/' + str(produkt_id)
        return redirect(url)

@app.route("/mark_as_assembled/<id>", methods=['POST'])
def mark_as_assembled(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        komentarz_rdzen = str(request.form['komentarz_rdzen'])
        komentarz_rdzen = komentarz_rdzen.replace("'", "")
        # frame1 = str(request.form['frame1'])
        # frame1 = frame1.replace("'", "")
        # if frame1 == "":
        #     frame1 = 'NULL'
        frame1 = 'NULL'
        frame2 = str(request.form['frame2'])
        frame2 = frame2.replace("'", "")
        if frame2 == "":
            frame2 = 'NULL'
        user = session["user"]
        mark_item_as_assembled(id, komentarz_rdzen, frame1, frame2, user)
        history(id, 'assembled', user)  
        return redirect(url_for('cores_operator_view'))
    
@app.route("/mark_as_m_assembled/<id>", methods=['POST'])
def mark_as_m_assembled(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        komentarz_rdzen = str(request.form['komentarz_rdzen'])
        komentarz_rdzen = komentarz_rdzen.replace("'", "")
        frame1 = 'NULL'
        frame2 = str(request.form['frame2'])
        frame2 = frame2.replace("'", "")
        if frame2 == "":
            frame2 = 'NULL'
        user = session["user"]
        mark_item_as_assembled(id, komentarz_rdzen, frame1, frame2, user)
        history(id, 'assembled', user)  
        return redirect(url_for('cores_operator_m_view'))

@app.route("/mark_as_assembled_operator_form/<id>", methods=['POST'])
def mark_as_assembled_operator_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        komentarz_rdzen = str(request.form['komentarz_rdzen'])
        komentarz_rdzen = komentarz_rdzen.replace("'", "")
        frame1 = 'NULL'
        frame2 = str(request.form['frame2'])
        frame2 = frame2.replace("'", "")
        # defect = str(request.form['defect'])
        # defect = defect.replace("'", "")
        selectedOptions = str(request.form['selectedOptions'])
        defect = selectedOptions.replace("'", "")
        if frame2 == "":
            frame2 = 'NULL'
        if defect == '' or defect == None:
            flash(f'Opcja defekt jest wymagana.')
            return redirect(request.referrer)
        user = session["user"]
        mark_item_as_assembled(id, komentarz_rdzen, frame1, frame2, user, defect)
        history(id, 'assembled', user)  
        return redirect(url_for('cores_operator_view'))
    
@app.route("/mark_as_assembled_operator_m_form/<id>", methods=['POST'])
def mark_as_assembled_operator_m_form(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        komentarz_rdzen = request.form.get('komentarz_rdzen', '').replace("'", "").strip() or '-'
        frame1 = 'NULL'
        frame2 = str(request.form['frame2'])
        frame2 = frame2.replace("'", "")
        # defect = str(request.form['defect'])
        # defect = defect.replace("'", "")
        selectedOptions = str(request.form['selectedOptions'])
        defect = selectedOptions.replace("'", "")
        if frame2 == "":
            frame2 = 'NULL'
        if defect == '' or defect == None:
            flash(f'Opcja defekt jest wymagana.')
            return redirect(request.referrer)
        user = session["user"]
        mark_item_as_assembled(id, komentarz_rdzen, frame1, frame2, user, defect)
        history(id, 'assembled', user)  
        return redirect(url_for('forming_operator_m_view4'))

@app.route("/mark_as_knockout/<id>", methods=['POST'])
def mark_as_knockout(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        query = "UPDATE lista_formowania_v2 SET item_status='grinding', data_wybicia=current_timestamp(), komentarz_wybijanie='" + str(komentarz) + "', data_wybicia=current_timestamp(), zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        user = session["user"]
        history(id, 'knockout', user)
        return redirect(url_for('knockout_operator_view'))
    
@app.route("/mark_mafi_as_unloaded/<id>", methods=['POST'])
def mark_mafi_as_unloaded(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = "SELECT id_form FROM mafi_load WHERE mafi_status NOT LIKE 'unload' AND id_mafi=" + str(id) 
        r = query_db(query)
        user = session["user"]
        query = "UPDATE mafi_load SET mafi_status='unload', user2='" + user + "' WHERE id_mafi=" + str(id)
        query_update(query)
        query = "UPDATE mafi SET Status='available' WHERE SerialNumber=" + str(id)
        query_update(query)
        for i in r:
            query = "UPDATE lista_formowania_v2 SET item_status='knockout' WHERE id=" + str(i['id_form'])
            query_update(query)
            history(i['id_form'], 'knockout', user)
        return redirect(url_for('knockout_operator_view'))
    
@app.route("/mark_form_as_unloaded/<id>", methods=['POST', 'GET'])
def mark_form_as_unloaded(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        user = session["user"]
        query = "UPDATE mafi_load SET mafi_status='unload', user2='" + user + "' WHERE id_form=" + str(id)
        query_update(query)
        query = "UPDATE lista_formowania_v2 SET item_status='knockout' WHERE id=" + str(id)
        query_update(query)
        history(id, 'knockout', user)
        query = "SELECT id_mafi FROM mafi_load WHERE id_form="+ str(id)
        id_mafi = query_db(query)
        query = "SELECT count(*) n FROM mafi_load WHERE mafi_status = 'load' AND id_mafi="+ str(id_mafi[0]['id_mafi'])
        res = query_db(query)
        if str(res[0]['n']) == '0':
            query = "UPDATE mafi SET Status = 'available' WHERE SerialNumber=" + str(id_mafi[0]['id_mafi'])
            query_update(query)
        query = "SELECT mafi FROM lista_formowania_v2 WHERE id=" + str(id)
        form_id = query_db(query)
        form_id = form_id[0]['mafi']
        url = '/knockout_mafi_forms/' + str(form_id)
        return redirect(url)
    
@app.route("/mark_as_knockout_admin/<id>", methods=['POST'])
def mark_as_knockout_admin(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        query = "UPDATE lista_formowania_v2 SET item_status='grinding', data_wybicia=current_timestamp(), komentarz_wybijanie='" + str(komentarz) + "', data_wybicia=current_timestamp(), zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        user = session["user"]
        history(id, 'knockout', user)
        return redirect(url_for('knockout'))
    
@app.route("/mark_as_taken_outside/<id>", methods=['POST'])
def mark_as_taken_outside(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:            
        mafi_id = str(request.form['mafi'])
        formy_na_mafi = query_db("SELECT * FROM `mafi_load` where id_mafi =" + str(mafi_id) + " AND mafi_status LIKE 'load'")

        chech_double_load = query_db("SELECT * FROM `mafi_load` where id_mafi =" + str(mafi_id) + " AND mafi_status LIKE 'load' AND id_form='" + str(id) + "'")
        if len(chech_double_load) > 0:
            flash(f'Nie można załadować jednej formy na dwóch różnych platformach MAFI!')
            return redirect(url_for('foundry_operator_view2'))

        waga_form_na_mafi = 0
        for i in formy_na_mafi:
            query = "SELECT (tab2.waga_piasku + (tab2.sztuk * tab2.waga_zeliwa)) masa_formy FROM `lista_formowania_v2` tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.id =" + str(i['id_form'])
            waga_formy = query_db(query)[0]['masa_formy']
            waga_form_na_mafi += waga_formy
        
        query = "SELECT (tab2.waga_piasku + (tab2.sztuk * tab2.waga_zeliwa)) masa_formy FROM `lista_formowania_v2` tab1 LEFT JOIN produkty tab2 ON tab1.id_produktu = tab2.produkt_id WHERE tab1.id =" + str(id)

        try:
            waga_nowej_formy = query_db(query)[0]['masa_formy']
        except IndexError:
            waga_nowej_formy = 0
        waga_form_na_mafi = waga_form_na_mafi + waga_nowej_formy

        try:
            mafi_capacity = query_db("SELECT CarryingCapacity FROM mafi WHERE SerialNumber=" + mafi_id)
            mafi_capacity = mafi_capacity[0]['CarryingCapacity'] * 1000
        except (IndexError, ValueError):
            mafi_capacity = 0
            print('Nosnosc mafi:', mafi_capacity, '. Waga form na mafi:', waga_form_na_mafi )

        if mafi_id == '0':
            print('Wariant 1 -> Mafi 0')
            komentarz_wywoz = str(request.form['komentarz_wywoz'])
            komentarz_wywoz = komentarz_wywoz.replace("'", "")
            query = "UPDATE lista_formowania_v2 SET item_status='cooling', zmodyfikowane_przez='" + str(session["user"]) + "', komentarz_wywoz='" + komentarz_wywoz + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
            query_update(query)
            user = session["user"]
            query = "INSERT INTO mafi_load(id_form, id_mafi, mafi_status, user) VALUES(" + str(id) + "," + mafi_id + ",'load','" + str(session["user"]) + "')"
            query_update(query)
            query = "UPDATE lista_formowania_v2 SET mafi=" + mafi_id + " WHERE id=" + str(id)
            query_update(query)
            history(id, 'cooling', user)
            if request.form.get('lock_mafi'):
                query = "UPDATE mafi SET Status='in_use' WHERE SerialNumber=" + str(mafi_id)
                query_update(query)
            return redirect(url_for('foundry_operator_view2'))        

        elif mafi_capacity < waga_form_na_mafi:
            # komentarz_wywoz = str(request.form['komentarz_wywoz'])
            # komentarz_wywoz = komentarz_wywoz.replace("'", "")
            # print('Wariant 2 -> Ładowonośc mafi została przekorczona !!!')
            # query = "UPDATE lista_formowania_v2 SET item_status='cooling', zmodyfikowane_przez='" + str(session["user"]) + "', komentarz_wywoz='" + komentarz_wywoz + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
            # query_update(query)
            # user = session["user"]
            # query = "INSERT INTO mafi_load(id_form, id_mafi, mafi_status, user) VALUES(" + str(id) + "," + mafi_id + ",'load','" + str(session["user"]) + "')"
            # query_update(query)
            # query = "UPDATE lista_formowania_v2 SET mafi=" + mafi_id + " WHERE id=" + str(id)
            # query_update(query)
            # history(id, 'cooling', user)
            # query = "UPDATE mafi SET Status='in_use' WHERE SerialNumber=" + str(mafi_id)
            # query_update(query)
            
            komentarz_wywoz = str(request.form['komentarz_wywoz'])
            komentarz_wywoz = komentarz_wywoz.replace("'", "")
            print('Wariant 2 -> Ładowonośc mafi została przekorczona !!!')
            query = "UPDATE lista_formowania_v2 SET item_status='cooling', zmodyfikowane_przez='" + str(session["user"]) + "', komentarz_wywoz='" + komentarz_wywoz + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
            query_update(query)
            user = session["user"]
            query = "INSERT INTO mafi_load(id_form, id_mafi, mafi_status, user) VALUES(" + str(id) + "," + mafi_id + ",'load','" + str(session["user"]) + "')"
            query_update(query)
            query = "UPDATE lista_formowania_v2 SET mafi=" + mafi_id + " WHERE id=" + str(id)
            query_update(query)
            history(id, 'cooling', user)
            if request.form.get('lock_mafi'):
                query = "UPDATE mafi SET Status='in_use' WHERE SerialNumber=" + str(mafi_id)
                query_update(query)
            flash(f'Przekoczenie dopuszczalengo obciążenia platformy id={mafi_id} !!!')
            return redirect(url_for('foundry_operator_view2'))
            
        else:
            komentarz_wywoz = str(request.form['komentarz_wywoz'])
            komentarz_wywoz = komentarz_wywoz.replace("'", "")
            print('Wariant 3 -> Ładowonośc mafi nie przekorczona')
            query = "UPDATE lista_formowania_v2 SET item_status='cooling', zmodyfikowane_przez='" + str(session["user"]) + "', komentarz_wywoz='" + komentarz_wywoz + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
            query_update(query)
            user = session["user"]
            query = "INSERT INTO mafi_load(id_form, id_mafi, mafi_status, user) VALUES(" + str(id) + "," + mafi_id + ",'load','" + str(session["user"]) + "')"
            query_update(query)
            query = "UPDATE lista_formowania_v2 SET mafi=" + mafi_id + " WHERE id=" + str(id)
            query_update(query)
            history(id, 'cooling', user)
            if request.form.get('lock_mafi'):
                query = "UPDATE mafi SET Status='in_use' WHERE SerialNumber=" + str(mafi_id)
                query_update(query)
            return redirect(url_for('foundry_operator_view2'))

@app.route("/mark_mafi_as_load_manual/<id>", methods=['GET'])
def mark_mafi_as_load_manual(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:        
        query = "UPDATE mafi SET Status='in_use' WHERE SerialNumber=" + str(id)
        query_update(query)
        return redirect(url_for('foundry_operator_view2'))

@app.route("/mark_mafi_as_unload_manual/<id>", methods=['GET'])
def mark_mafi_as_unload_manual(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:        
        query = "UPDATE mafi SET Status='available' WHERE SerialNumber=" + str(id)
        query_update(query)
        return redirect(url_for('foundry_operator_view2'))
    
@app.route("/mark_as_taken_outside_admin/<id>", methods=['GET'])
def mark_as_taken_outside_admin(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        query = "UPDATE lista_formowania_v2 SET item_status='cooling', zmodyfikowane_przez='" + str(session["user"]) + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        #count_waiting_time(id)
        user = session["user"]
        history(id, 'cooling', user)
        return redirect(url_for('cooling'))

@app.route("/mark_as_casted/<id>", methods=['POST'])
def mark_as_casted(id):
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        if request.form.get('zlom'):
            zlom_field = str(1)
        else:
            zlom_field = str(0)
        nr_kadzi = str(request.form['nr_kadzi'])
        nr_kadzi = nr_kadzi.replace("'", "")
        kadz_odzlakowania = str(request.form['kadz_odzlakowania'])
        kadz_odzlakowania = kadz_odzlakowania.replace("'", "")
        komentarz = str(request.form['komentarz'])
        komentarz = komentarz.replace("'", "")
        fl_time = str(request.form['fl_time'])
        fl_time = fl_time.replace("'", "")
        fe_temp = str(request.form['fe_temp'])
        fe_temp = fe_temp.replace("'", "")
        filtr = str(request.form['filtr'])
        filtr = filtr.replace("'", "")
        broken = str(request.form['broken'])
        broken = broken.replace("'", "")
        operator = str(request.form['operator'])
        operator = operator.replace("'", "")
        query = "UPDATE lista_formowania_v2 SET item_status='casted', nr_kadzi='" + nr_kadzi + "', kadz_odzlakowania='" + kadz_odzlakowania +  "', czas_zalewania='" + fl_time + "', temp_zeliwa='" + fe_temp + "', filtr='" + filtr + "', broken='" + broken + "', repeated='" + zlom_field + "', komentarz_zalew='" + komentarz + "', data_zalania=current_timestamp(), zmodyfikowane_przez='" + operator + "', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
        query_update(query)
        #print(query)
        history(id, 'casted', operator)
        return redirect(url_for('foundry_operator_view2'))
    
@app.route("/semafor")
def semafor():
    if not g.user:
        flash(f'Login required.')
        return redirect(url_for('login'))
    else:
        update_semafor_manual()
        return render_template('sn_info_semafor.html')

#######################################################
######## Generowanie nr seryjnego skrzyni  ############
#######################################################

@app.route("/flask_id_gen")
def flask_id_gen():
    query = "SELECT counter, czas FROM licznik_skrzyn ORDER BY id DESC LIMIT 1"
    res = query_db_first(query)
    counter  = int(res['counter'])
    current_day = datetime.datetime.today().strftime('%d') 
    czas_from_db = str((res['czas']))[8:10]

    if current_day == czas_from_db:
        counter = counter + 1
        query = "INSERT INTO licznik_skrzyn (counter, operator, czas) VALUES (" + str(counter) + ",'" + str(session["user"]) + "', current_timestamp())"
        query_update(query)
    else:
        counter = 1
        query = "INSERT INTO licznik_skrzyn (counter, operator, czas) VALUES (" + str(counter) + ",'" + str(session["user"]) + "', current_timestamp())"
        query_update(query)

    falsk_id = datetime.datetime.today().strftime('%d/%m') + '/' + str(counter)
    response = { 'flask_id': falsk_id }
    return jsonify(response), 200

@app.route("/flask_on_mafi", methods=['GET', 'POST'])
def falsk_on_mafi():
    produkt_id = str(request.form['produkt_id'])
    produkt_id = produkt_id.replace("'", "")
    query = "SELECT tab1.id_mafi as mafi_id FROM mafi_load AS tab1 LEFT JOIN lista_formowania_v2 AS tab2 ON tab1.id_form = tab2.id WHERE tab1.mafi_status IN ('ready_to_knockout', 'load') AND tab2.id_produktu =" + str(produkt_id)
    res = query_db(query)
    response = []
    output = unique(res)
    for i in output:
        response.append({'ID MAFI' : i['mafi_id']})
    if len(response) == 0:
        response.append({'ID MAFI' : 'Nie odnaleziono mafi o podymym id produktu.'})
    return jsonify(response), 200


#######################################################
################ Pulpit informacyjny ##################
#######################################################

@app.route("/foundry_production_status")
def foundry_production_status():
    response = []
    query = "SELECT count(*) AS ilosc_form FROM lista_formowania_v2 WHERE item_status = 'new'"
    forming_new_count = query_db(query)
    query = "SELECT TIMESTAMPDIFF(HOUR, data_ostatniej_modyfikacji, NOW()) AS roznica_w_godzinach FROM lista_formowania_v2 WHERE item_status = 'new' ORDER BY data_ostatniej_modyfikacji ASC LIMIT 1;"
    forming_new_time_diff = query_db(query)
    query = "SELECT DISTINCT count(*) AS ilosc_form FROM lista_formowania_v2 WHERE item_status LIKE 'formed'"
    assambling_items_count = query_db(query)
    formy_do_zalania = suma_wagi_netto()
    formy_do_zalania = round(formy_do_zalania, 0)
    formy_do_zalania = round(formy_do_zalania, 0)
    casted_items_count = query_db("SELECT count(*) AS formy FROM lista_formowania_v2 WHERE item_status LIKE 'casted' LIMIT 200;")
    formy_zalane = query_db("SELECT DISTINCT tab1.data_zalania, tab1.czas_studzenia, tab1.dni_do_wybicia, tab1.data_ostatniej_modyfikacji FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'casted' OR tab1.item_status LIKE 'ready_for_cooling' ORDER BY tab1.id DESC LIMIT 200;")
    formy_do_zalania_liczba = query_db("SELECT count(*) n FROM lista_formowania_v2 WHERE item_status LIKE 'assembled' ORDER BY id DESC LIMIT 200;")   
    # mafi = query_db("SELECT id, id_mafi, id_form, czas, trail FROM mafi_load WHERE mafi_status LIKE 'load' OR mafi_status LIKE 'ready_to_knockout' group by id_mafi")
    forms_cooling = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'load'")
    forms_cooling_idx = []
    forms_ready_to_knockout = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'ready_to_knockout'")
    forms_ready_to_knockout_idx = []
    mafi_to_knockout = []        
    forms_knockout = flasks_knockout()

    forms_knockout = replace_none_values(forms_knockout)
    items = query_db("SELECT produkt_id, nazwa FROM produkty")

    for i in forms_cooling:
        forms_cooling_idx.append(i['id_mafi'])

    for i in forms_ready_to_knockout:
        forms_ready_to_knockout_idx.append(i['id_mafi'])

    for i in forms_ready_to_knockout_idx:
        if i not in forms_cooling_idx:
            mafi_to_knockout.append(i)

    mafi_display = []
    for i in mafi_to_knockout:
        mafi_loaded = query_db("SELECT * FROM lista_formowania_v2 WHERE mafi=" + str(i) + " ORDER BY id DESC LIMIT 1")
        delta = mafi_loaded[0]['data_ostatniej_modyfikacji']
        if roznica_w_minutach(delta) / 60 >= 24:
            mafi_display.append(delta)
    
    mafi_delay_under_24h_count = len(mafi_display)
        
    # forms_ready_to_knockout = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'ready_to_knockout'")
    # mafi_delay = []
    # for i in forms_ready_to_knockout:
    #     res = query_db("SELECT czas FROM mafi_load WHERE id_mafi="+ str(i['id_mafi']) + " ORDER BY id DESC LIMIT 1")
    #     try:
    #         mafi_delay.append(res[0]['czas'])
    #     except (IndexError, TypeError):
    #         mafi_delay = []
    # try:
    #     mafi_delay_under_24h_count = len([i for i in mafi_delay if roznica_w_minutach(i) / 60 >= 24])
    # except (IndexError, TypeError):
    #     mafi_delay_under_24h_count = 0

    try:
        time_in_foundry = sorted([roznica_w_minutach(i['data_zalania']) for i in formy_zalane],reverse=True)
    except (IndexError, TypeError):
        time_in_foundry = 0

    try:
        forming_list_new_items = forming_new_count[0]['ilosc_form']
    except (IndexError, TypeError):
        forming_list_new_items = 0

    try:
        forming_new_time_diff = forming_new_time_diff[0]['roznica_w_godzinach']
    except (IndexError, TypeError):
        forming_new_time_diff = 0

    try:
        assambling_items_count = assambling_items_count[0]['ilosc_form']
    except (IndexError, TypeError):
        assambling_items_count = 0

    try:
        formy_do_zalania_tonaz = int(formy_do_zalania)
    except (IndexError, TypeError):
        formy_do_zalania_tonaz = 0

    try:
        casted_items_count =  casted_items_count[0]['formy']
    except (IndexError, TypeError):
        casted_items_count = 0

    try:
        foundry_dwell_time =  time_in_foundry[0]
    except (IndexError, TypeError):
        foundry_dwell_time = 0

    # flagi

    if forming_list_new_items >= 50:
        forming_list_new_items_flag = 'success'
    elif forming_list_new_items < 50 and forming_list_new_items >= 25:
        forming_list_new_items_flag = 'warning'
    else:
        forming_list_new_items_flag = "danger"


    if forming_new_time_diff <= 12:
        forming_new_time_diff_flag = 'success'
    elif forming_new_time_diff > 12 and forming_new_time_diff <= 24:
        forming_new_time_diff_flag = 'warning'
    else:
        forming_new_time_diff_flag = "danger"


    if assambling_items_count <= 5:
        assambling_items_count_flag = 'success'
    elif assambling_items_count >= 6 and assambling_items_count <= 10:
        assambling_items_count_flag = 'warning'
    else:
        assambling_items_count_flag = "danger"


    if formy_do_zalania_tonaz <= 200:
        formy_do_zalania_tonaz_flag = 'success'
    else:
        formy_do_zalania_tonaz_flag = "danger"


    if casted_items_count <= 5:
        casted_items_count_flag = 'success'
    elif casted_items_count >= 6 and casted_items_count <= 10:
        casted_items_count_flag = 'warning'
    else:
        casted_items_count_flag = "danger"

    
    if foundry_dwell_time <= 2880:
        foundry_dwell_time_flag = 'success'
    elif foundry_dwell_time >= 2881 and foundry_dwell_time <= 4320:
        foundry_dwell_time_flag = 'warning'
    else:
        foundry_dwell_time_flag = "danger"

    if mafi_delay_under_24h_count > 0:
        mafi_delay_under_24h_count_flag = 'danger'
    else:
        mafi_delay_under_24h_count_flag = "success"

    response.append({
        'forming_list_new_items' : forming_list_new_items,
        'forming_list_new_items_flag' : forming_list_new_items_flag,
        'forming_new_time_diff' : forming_new_time_diff,
        'forming_new_time_diff_flag' : forming_new_time_diff_flag,
        'assambling_items_count' : assambling_items_count,
        'assambling_items_count_flag' : assambling_items_count_flag,
        'formy_do_zalania_tonaz' : formy_do_zalania_tonaz,
        'formy_do_zalania_tonaz_flag' : formy_do_zalania_tonaz_flag,
        'casted_items_count' : casted_items_count,
        'casted_items_count_flag' : casted_items_count_flag, 
        'foundry_dwell_time' : foundry_dwell_time,
        'foundry_dwell_time_flag' : foundry_dwell_time_flag,
        'mafi_delay_under_24h_count': mafi_delay_under_24h_count,
        'mafi_delay_under_24h_count_flag': mafi_delay_under_24h_count_flag,
        'formy_do_zalania_liczba' : formy_do_zalania_liczba[0]['n']
    })
  
    #return jsonify(response), 200
    return render_template('foundry_production_status.html', response=response[0])


@app.route("/foundry_production_status_kiosk")
def foundry_production_status_kiosk():
    response = []
    query = "SELECT count(*) AS ilosc_form FROM lista_formowania_v2 WHERE item_status = 'new'"
    forming_new_count = query_db(query)
    query = "SELECT TIMESTAMPDIFF(HOUR, data_ostatniej_modyfikacji, NOW()) AS roznica_w_godzinach FROM lista_formowania_v2 WHERE item_status = 'new' ORDER BY data_ostatniej_modyfikacji ASC LIMIT 1;"
    forming_new_time_diff = query_db(query)
    query = "SELECT DISTINCT count(*) AS ilosc_form FROM lista_formowania_v2 WHERE item_status LIKE 'formed'"
    assambling_items_count = query_db(query)
    formy_do_zalania = suma_wagi_netto()
    formy_do_zalania = round(formy_do_zalania, 0)
    formy_do_zalania = round(formy_do_zalania, 0)
    casted_items_count = query_db("SELECT count(*) AS formy FROM lista_formowania_v2 WHERE item_status LIKE 'casted' LIMIT 200;")
    formy_zalane = query_db("SELECT DISTINCT tab1.data_zalania, tab1.czas_studzenia, tab1.dni_do_wybicia, tab1.data_ostatniej_modyfikacji FROM lista_formowania_v2 AS tab1 LEFT JOIN lista_formowania_formy_v2 AS tab2 ON tab1.id = tab2.produkt_id WHERE tab1.item_status LIKE 'casted' OR tab1.item_status LIKE 'ready_for_cooling' ORDER BY tab1.id DESC LIMIT 200;")
    formy_do_zalania_liczba = query_db("SELECT count(*) n FROM lista_formowania_v2 WHERE item_status LIKE 'assembled' ORDER BY id DESC LIMIT 200;")   
    # mafi = query_db("SELECT id, id_mafi, id_form, czas, trail FROM mafi_load WHERE mafi_status LIKE 'load' OR mafi_status LIKE 'ready_to_knockout' group by id_mafi")
    forms_cooling = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'load'")
    forms_cooling_idx = []
    forms_ready_to_knockout = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'ready_to_knockout'")
    forms_ready_to_knockout_idx = []
    mafi_to_knockout = []        
    forms_knockout = flasks_knockout()

    forms_knockout = replace_none_values(forms_knockout)
    products = query_db("SELECT nazwa FROM produkty where item_status = 'active'")
    items = query_db("SELECT produkt_id, nazwa FROM produkty")

    for i in forms_cooling:
        forms_cooling_idx.append(i['id_mafi'])

    for i in forms_ready_to_knockout:
        forms_ready_to_knockout_idx.append(i['id_mafi'])

    for i in forms_ready_to_knockout_idx:
        if i not in forms_cooling_idx:
            mafi_to_knockout.append(i)

    mafi_display = []
    for i in mafi_to_knockout:
        mafi_loaded = query_db("SELECT * FROM lista_formowania_v2 WHERE mafi=" + str(i) + " ORDER BY id DESC LIMIT 1")
        delta = mafi_loaded[0]['data_ostatniej_modyfikacji']
        if roznica_w_minutach(delta) / 60 >= 24:
            mafi_display.append(delta)
    
    mafi_delay_under_24h_count = len(mafi_display)
        
    # forms_ready_to_knockout = query_db("SELECT DISTINCT id_mafi FROM mafi_load WHERE mafi_status LIKE 'ready_to_knockout'")
    # mafi_delay = []
    # for i in forms_ready_to_knockout:
    #     res = query_db("SELECT czas FROM mafi_load WHERE id_mafi="+ str(i['id_mafi']) + " ORDER BY id DESC LIMIT 1")
    #     try:
    #         mafi_delay.append(res[0]['czas'])
    #     except (IndexError, TypeError):
    #         mafi_delay = []
    # try:
    #     mafi_delay_under_24h_count = len([i for i in mafi_delay if roznica_w_minutach(i) / 60 >= 24])
    # except (IndexError, TypeError):
    #     mafi_delay_under_24h_count = 0

    try:
        time_in_foundry = sorted([roznica_w_minutach(i['data_zalania']) for i in formy_zalane],reverse=True)
    except (IndexError, TypeError):
        time_in_foundry = 0

    try:
        forming_list_new_items = forming_new_count[0]['ilosc_form']
    except (IndexError, TypeError):
        forming_list_new_items = 0

    try:
        forming_new_time_diff = forming_new_time_diff[0]['roznica_w_godzinach']
    except (IndexError, TypeError):
        forming_new_time_diff = 0

    try:
        assambling_items_count = assambling_items_count[0]['ilosc_form']
    except (IndexError, TypeError):
        assambling_items_count = 0

    try:
        formy_do_zalania_tonaz = int(formy_do_zalania)
    except (IndexError, TypeError):
        formy_do_zalania_tonaz = 0

    try:
        casted_items_count =  casted_items_count[0]['formy']
    except (IndexError, TypeError):
        casted_items_count = 0

    try:
        foundry_dwell_time =  time_in_foundry[0]
    except (IndexError, TypeError):
        foundry_dwell_time = 0

    # flagi

    if forming_list_new_items >= 50:
        forming_list_new_items_flag = 'success'
    elif forming_list_new_items < 50 and forming_list_new_items >= 25:
        forming_list_new_items_flag = 'warning'
    else:
        forming_list_new_items_flag = "danger"


    if forming_new_time_diff <= 12:
        forming_new_time_diff_flag = 'success'
    elif forming_new_time_diff > 12 and forming_new_time_diff <= 24:
        forming_new_time_diff_flag = 'warning'
    else:
        forming_new_time_diff_flag = "danger"


    if assambling_items_count <= 5:
        assambling_items_count_flag = 'success'
    elif assambling_items_count >= 6 and assambling_items_count <= 10:
        assambling_items_count_flag = 'warning'
    else:
        assambling_items_count_flag = "danger"


    if formy_do_zalania_tonaz <= 200:
        formy_do_zalania_tonaz_flag = 'success'
    else:
        formy_do_zalania_tonaz_flag = "danger"


    if casted_items_count <= 5:
        casted_items_count_flag = 'success'
    elif casted_items_count >= 6 and casted_items_count <= 10:
        casted_items_count_flag = 'warning'
    else:
        casted_items_count_flag = "danger"

    
    if foundry_dwell_time <= 2880:
        foundry_dwell_time_flag = 'success'
    elif foundry_dwell_time >= 2881 and foundry_dwell_time <= 4320:
        foundry_dwell_time_flag = 'warning'
    else:
        foundry_dwell_time_flag = "danger"

    if mafi_delay_under_24h_count > 0:
        mafi_delay_under_24h_count_flag = 'danger'
    else:
        mafi_delay_under_24h_count_flag = "success"

    response.append({
        'forming_list_new_items' : forming_list_new_items,
        'forming_list_new_items_flag' : forming_list_new_items_flag,
        'forming_new_time_diff' : forming_new_time_diff,
        'forming_new_time_diff_flag' : forming_new_time_diff_flag,
        'assambling_items_count' : assambling_items_count,
        'assambling_items_count_flag' : assambling_items_count_flag,
        'formy_do_zalania_tonaz' : formy_do_zalania_tonaz,
        'formy_do_zalania_tonaz_flag' : formy_do_zalania_tonaz_flag,
        'casted_items_count' : casted_items_count,
        'casted_items_count_flag' : casted_items_count_flag, 
        'foundry_dwell_time' : foundry_dwell_time,
        'foundry_dwell_time_flag' : foundry_dwell_time_flag,
        'mafi_delay_under_24h_count': mafi_delay_under_24h_count,
        'mafi_delay_under_24h_count_flag': mafi_delay_under_24h_count_flag,
        'formy_do_zalania_liczba' : formy_do_zalania_liczba[0]['n']
    })
  
    #return jsonify(response), 200
    return render_template('foundry_production_status_kiosk.html', response=response[0], products=products)

@app.route('/api/concat', methods=['POST'])
def concat():
    payload = request.get_json(silent=True) or {}
    try:
        product = str(payload.get('a', '')).strip()
        date1 = str(payload.get('b', '')).strip()
        date2 = str(payload.get('c', '')).strip()

        query = "SELECT count(*) total_products FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.czas BETWEEN '" + date1 + "' AND '" + date2 + "' AND tab2.nazwa_produktu = '" + product + "' and tab1.production_stage = 'casted'; "
        total_products = query_db(query)
        total_products = int(total_products[0]['total_products']) 
        query = "SELECT sztuk FROM produkty WHERE nazwa ='" + product + "'"
        sztuk = query_db(query)
        sztuk = int(sztuk[0]['sztuk'])
        items_producted = total_products * sztuk

        if total_products == 0:
            result = 'No items found for given conditions.'
            return jsonify({'defects': result, 'rework': result, 'scrap': result})

        query = "SELECT tab2.id FROM `lista_formowania_historia_v2` tab1 LEFT JOIN lista_formowania_v2 tab2 ON tab1.produkt_id = tab2.id WHERE tab1.czas BETWEEN '" + date1 + "' AND '" + date2 + "' AND tab2.nazwa_produktu = '" + product + "' and tab1.production_stage = 'casted'"
        res = query_db(query)

        defects = 0
        rework = 0

        for i in res:
            query = "SELECT id FROM defects WHERE form_id=" + str(i['id'])
            idx = len(query_db(query))
            defects = defects + idx
            query = "SELECT id FROM defects WHERE form_id=" + str(i['id']) + " AND decyzja NOT LIKE 'złomować'"
            idy = len(query_db(query))
            rework = rework + idy


        if defects == 0:
            #print('all:', items_producted)
            #print('defects:', defects)
            #print('rework:', rework)
            result = '0.0%'
            return jsonify({'defects': result, 'rework': result,  'scrap': result})
        
        #print('all:', items_producted)
        #print('defects:', defects)
        #print('rework:', rework)

        # defect_items = defects
        # rework_items = rework
        # scrap_items = defects - rework        

        scrap = str(((defects - rework) / items_producted) * 100)[0:4] + '%'
        reworks = str((rework / items_producted) * 100)[0:4] + '%'
        defects = str((defects / items_producted) * 100)[0:4] + '%'

        #return jsonify({'defects': defects, 'rework': reworks, 'scrap': scrap, 'total' : items_producted, 'defect_items' : defect_items, 'scrap_items' : scrap_items, 'rework_items' : rework_items})
        return jsonify({'defects': defects, 'rework': reworks, 'scrap': scrap})
    
    except Exception as e:
        return jsonify({'error': 'Invalid input', 'details': str(e)}), 400

# @app.route('/api/concat', methods=['POST'])
# def concat():
#     payload = request.get_json(silent=True) or {}
#     try:
#         product = str(payload.get('a', '')).strip()
#         date1 = str(payload.get('b', '')).strip()
#         date2 = str(payload.get('c', '')).strip()

#         query = "SELECT COUNT(*) total_products FROM `lista_formowania_v2` WHERE nazwa_produktu = '" + product + "' AND data_dodania BETWEEN '" + date1 + "' AND '" + date2 + "' AND item_status IN ('casted', 'knockout', 'cooling', 'outside', 'ready_for_cooling');"
#         total_products = query_db(query)
#         total_products = int(total_products[0]['total_products']) 
#         query = "SELECT sztuk FROM produkty WHERE nazwa ='" + product + "'"
#         sztuk = query_db(query)
#         sztuk = int(sztuk[0]['sztuk'])
#         items_producted = total_products * sztuk

#         if total_products == 0:
#             result = 'No items found for given conditions.'
#             return jsonify({'defects': result, 'rework': result})

#         query = "SELECT id FROM `lista_formowania_v2` WHERE nazwa_produktu = '" + product + "' AND data_dodania BETWEEN '" + date1 + "' AND '" + date2 + "' AND item_status IN ('casted', 'knockout', 'cooling', 'outside', 'ready_for_cooling')"
#         res = query_db(query)

#         defects = 0
#         rework = 0
#         for i in res:
#             query = "SELECT id FROM defects WHERE form_id=" + str(i['id'])
#             idx = len(query_db(query))
#             defects = defects + idx
#             query = "SELECT id FROM defects WHERE form_id=" + str(i['id']) + " AND decyzja NOT LIKE 'złomować'"
#             print(query)
#             idx = len(query_db(query))

#             rework = rework + idx

#         if defects == 0:
#             result = 'No defects found in given conditins.'
#             return jsonify({'defects': result, 'rework': result})

#         reworks = str(rework / defects * 100) + '%'
#         defects = str(defects / items_producted * 100) + '%'
#         return jsonify({'defects': defects, 'rework': reworks})
    
#     except Exception as e:
#         return jsonify({'error': 'Invalid input', 'details': str(e)}), 400
    
#######################################################
############# Obilczenia czasu chłodzenia  ############
#######################################################

# @app.route("/calculate_cooling_times_manual")
# def calculate_cooling_times():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "SELECT id, data_ostatniej_modyfikacji, dni_do_wybicia FROM lista_formowania_v2 WHERE item_status LIKE 'casted'"
#         for i in query_db(query):
#             id = str(i['id'])
#             data_ostatniej_modyfikacji = i['data_ostatniej_modyfikacji']
#             dni_do_wybicia = i['dni_do_wybicia']
#             new_date = data_ostatniej_modyfikacji + datetime.timedelta(days = int(dni_do_wybicia))
#             new_date2 = datetime.datetime.timestamp(new_date)
#             now_date2 = datetime.datetime.now().timestamp()
#             new_date2 = str(new_date2)[0:9]
#             now_date2 = str(now_date2)[0:9]
#             if (int(new_date2) <= int(now_date2)):
#                 print('status changed to knockout')
#                 query = "UPDATE lista_formowania_v2 SET item_status='knockout', zmodyfikowane_przez='system', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#                 query_update(query)
#         return redirect(url_for('cooling'))

# @app.route("/calculate_cooling_times_foundry_operator")
# def calculate_cooling_times_manual_operator():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "SELECT id, data_ostatniej_modyfikacji, dni_do_wybicia FROM lista_formowania_v2 WHERE item_status LIKE 'casted'"
#         for i in query_db(query):
#             id = str(i['id'])
#             data_ostatniej_modyfikacji = i['data_ostatniej_modyfikacji']
#             dni_do_wybicia = i['dni_do_wybicia']
#             new_date = data_ostatniej_modyfikacji + datetime.timedelta(days = int(dni_do_wybicia))
#             new_date2 = datetime.datetime.timestamp(new_date)
#             now_date2 = datetime.datetime.now().timestamp()
#             new_date2 = str(new_date2)[0:9]
#             now_date2 = str(now_date2)[0:9]
#             if (int(new_date2) <= int(now_date2)):
#                 print('status changed to knockout')
#                 query = "UPDATE lista_formowania_v2 SET item_status='knockout', zmodyfikowane_przez='system', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#                 query_update(query)
#         return redirect(url_for('foundry_operator_view2'))
    
# @app.route("/calculate_cooling_times_kn_operator")
# def calculate_cooling_times_kn_operator():
#     if not g.user:
#         flash(f'Login required.')
#         return redirect(url_for('login'))
#     else:
#         query = "SELECT id, data_ostatniej_modyfikacji, dni_do_wybicia FROM lista_formowania_v2 WHERE item_status LIKE 'casted'"
#         for i in query_db(query):
#             id = str(i['id'])
#             data_ostatniej_modyfikacji = i['data_ostatniej_modyfikacji']
#             dni_do_wybicia = i['dni_do_wybicia']
#             new_date = data_ostatniej_modyfikacji + datetime.timedelta(days = int(dni_do_wybicia))
#             new_date2 = datetime.datetime.timestamp(new_date)
#             now_date2 = datetime.datetime.now().timestamp()
#             new_date2 = str(new_date2)[0:9]
#             now_date2 = str(now_date2)[0:9]
#             if (int(new_date2) <= int(now_date2)):
#                 print('status changed to knockout')
#                 query = "UPDATE lista_formowania_v2 SET item_status='knockout', zmodyfikowane_przez='system', data_ostatniej_modyfikacji=current_timestamp() WHERE id=" + id
#                 query_update(query)
#         return redirect(url_for('knockout_operator_view'))

# @app.route("/import_csv")
# def import_csv():
#     file_path = os.path.join(app.root_path, "import", "dane.csv")
#     rows = []

#     with open(file_path, "r", encoding="utf-8") as file:

#         lines = file.readlines()

#         # pomijamy pierwszy wiersz - nagłówek
#         for line in lines[1:]:

#             x = line.strip().split(",")

#             row = {
#                 "Nr zam. sprz.": x[0],
#                 "Nr zam. klienta": x[1],
#                 "Kod PH": x[2],
#                 "PH": x[3],
#                 "Index": x[4],
#                 "Grupa materiałów": x[5],
#                 "Opis nazwa": x[6],

#                 "Ilosc": x[7] + "," + x[8],
#                 "Waga jedn.": x[9] + "," + x[10],
#                 "Waga całk.": x[11] + "," + x[12],

#                 "Nr katalog": x[13],
#                 "Nr rys": x[14],
#                 "Nr bud.": x[15],
#                 "Nr poz.": x[16],
#                 "Nr STILL": x[17],
#                 "Nr seq.": x[18],

#                 "D. prod.": x[19],
#                 "D. mal.": x[20],
#                 "D. obr.": x[21],
#                 "D. szlif.": x[22],
#                 "D. wybij.": x[23],
#                 "D. form.": x[24]
#             }

#             rows.append(row)

#     df = pd.DataFrame(rows)

#     return jsonify(
#         df.to_dict(orient="records")
#     )

#######################################################################################################
###################################### Wywołnie main ##################################################
#######################################################################################################

if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(host="0.0.0.0", port=5555, debug=True)












