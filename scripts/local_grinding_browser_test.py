"""Local browser fixture. AST-loaded handlers; SQLite only, no main import."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_grinding_actions import GrindingActionAudit
from flask import g, session, render_template, jsonify
import datetime
case = GrindingActionAudit(); case.setUp()
app = case.app
app.static_folder = str(Path(__file__).resolve().parents[1] / 'static')
case.seed()
case.db.execute("INSERT INTO grinding SELECT 11,2,'CD',101,'Rework fixture',trail,waga_zeliwa,'3',klient,operator,alias,czas FROM grinding WHERE id=10")
@app.before_request
def local_user():
    session['user']='WZ'; g.user='WZ'
def view(name):
    if name == 'grinding':
        items=[]
        for prefix in ['AB','CD']:
            exists=case.db.execute('SELECT 1 FROM grinding WHERE item_id=3 AND prefix=? AND sn=200',(prefix,)).fetchone()
            if not exists:
                items.append(dict(id=3,Prefix=prefix,sn=200,nazwa_produktu="Test O'Brien "+prefix,trail='0',alias='-',waga_zeliwa=250,customer="Client O'Brien"))
    else:
        modes=('0','1','2') if name=='grinding_done' else ('3','4')
        items=[dict(r) for r in case.db.execute('SELECT * FROM grinding WHERE mode IN ('+','.join('?' for _ in modes)+') ORDER BY id DESC',modes)]
        for item in items:
            item['czas']=datetime.datetime.fromisoformat(item['czas']) if item['czas'] else datetime.datetime(2026,11,1,10)
    return render_template(name+'.html',items=items,operators=[{'operator':'WZ'},{'operator':"O'Brien"}],now=datetime.datetime(2026,11,1,10),search='',page=1,pages=1,total=len(items),first=1,last=len(items))
for name in ['grinding','grinding_done','grinding_rework']:
    app.view_functions[name]=lambda name=name:view(name)
@app.get('/audit')
def audit():
    return jsonify(records=[dict(r) for r in case.db.execute('SELECT * FROM grinding ORDER BY id')],history=[dict(r) for r in case.db.execute('SELECT * FROM lista_formowania_historia_v2')])
app.run(host='127.0.0.1',port=5099,debug=False,threaded=False,use_reloader=False)

