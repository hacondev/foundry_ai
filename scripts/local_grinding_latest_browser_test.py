"""Browser verification of the real /grinding route on disposable SQLite data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_grinding_pending import GrindingPendingTests
from flask import Flask, g, session, request, render_template, redirect, url_for, flash, jsonify
case = GrindingPendingTests(); case.setUp()
db = case.db
for table in ['lista_formowania_sn', 'lista_formowania_v2']:
    db.execute('DELETE FROM ' + table)
scenarios = [
    (1, 'AB', 100, 'Widoczny: ostatni knockout'),
    (2, 'AB', 101, 'Ukryty: ostatni grinding'),
    (3, 'AB', 102, 'Ukryty: ostatni qa_ok'),
    (4, 'AB', 103, 'Ukryty: jest w grinding'),
    (5, 'AB', 104, 'Ukryty: nowszy status calej formy'),
    (6, 'AB', 105, 'Widoczny: ponowny knockout'),
    (7, 'AB', 106, 'Widoczny: ostatni knockout calej formy'),
    (7, 'CD', 106, 'Ukryty: nowszy status innego prefiksu'),
]
for form_id, prefix, sn, name in scenarios:
    db.execute('INSERT OR IGNORE INTO lista_formowania_v2 VALUES (?, ?, ?, ?, ?)',(form_id,name,'0','',10))
    db.execute('INSERT INTO lista_formowania_sn (produkt_id,prefix,sn) VALUES (?,?,?)',(form_id,prefix,sn))
events = [
    (1, None,None,'knockout'),
    (2,None,None,'knockout'), (2,'AB',101,'grinding'),
    (3,None,None,'knockout'), (3,'AB',102,'qa_ok'),
    (4,None,None,'knockout'),
    (5,'AB',104,'knockout'), (5,None,None,'shipment'),
    (6,'AB',105,'qa_ok'), (6,'AB',105,'knockout'),
    (7,'AB',106,'qa_ok'), (7,None,None,'knockout'), (7,'CD',106,'grinding'),
]
for i,(form,prefix,sn,stage) in enumerate(events,1):
    db.execute('INSERT INTO lista_formowania_historia_v2 VALUES (?,?,?,?,?)',(i,form,prefix,sn,stage))
db.execute("INSERT INTO grinding VALUES (4,'AB',103)")
app = Flask(__name__,template_folder=str(Path('templates').resolve()),static_folder=str(Path('static').resolve()))
app.secret_key='disposable-local-sqlite'
case.route.__globals__.update(g=g,session=session,request=request,render_template=render_template,redirect=redirect,url_for=url_for,flash=flash)
@app.before_request
def test_user():
    session['user']='WZ';g.user='WZ'
app.add_url_rule('/grinding',view_func=case.route,methods=['GET'])
@app.get('/audit')
def audit():
    return jsonify(expected=['AB-100','AB-105','AB-106'],history=[dict(r) for r in db.execute('SELECT * FROM lista_formowania_historia_v2')],processed=[dict(r) for r in db.execute('SELECT * FROM grinding')])
app.run(host='127.0.0.1',port=5099,debug=False,threaded=False,use_reloader=False)
