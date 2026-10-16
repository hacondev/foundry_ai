###############################################################################################################################
################################################# Users class def #############################################################
###############################################################################################################################

class User:
    def __init__(self, id, username, password, mode='null'):
        self.id = id
        self.username = username
        self.password = password
        self.mode = mode

    def __repr__(self):
        return self.username
    
users = []
    
###############################################################################################################################
###################################################### Users ##################################################################
###############################################################################################################################
# 60

# biuro
users.append(User(id=1, username='admin', password='pass', mode='biuro'))  
users.append(User(id=2, username='biuro', password='pass', mode='biuro')) 
users.append(User(id=3, username='magda', password='pass', mode='biuro'))  

# formiernia mechnaiczna
users.append(User(id=4, username='formiernia', password='111111', mode='formiernia')) 

# rdzeniarnia
users.append(User(id=5, username='rdzeniarnia', password='2222', mode="rdzeniarnia")) 
#users.append(User(id=6, username='tlewandowski', password='3241', mode="rdzeniarnia")) 
users.append(User(id=7, username='wolejnik', password='2341', mode="rdzeniarnia")) 
#users.append(User(id=8, username='tkostrzewski', password='4123', mode="rdzeniarnia")) 
users.append(User(id=55, username='dnawolski', password='4455', mode="rdzeniarnia")) 

# formiernia ręczna (forma)
users.append(User(id=9, username='wwojcik', password='2314', mode="forman")) 
users.append(User(id=10, username='louaddi', password='1324', mode="forman")) 
users.append(User(id=11, username='mszajna', password='4213', mode="forman")) 
users.append(User(id=14, username='forman', password='5555', mode="forman"))
users.append(User(id=14, username='llewan', password='8877', mode="forman"))

# odlewnia
users.append(User(id=12, username='odlewnia', password='333333', mode="odlewnia")) 

# wybijanie
users.append(User(id=29, username='MSzumierz', password='444333', mode="wybijanie"))
users.append(User(id=30, username='JOgłoza', password='222555', mode="wybijanie"))
users.append(User(id=31, username='DPanfilovskyi', password='555333', mode="wybijanie"))
users.append(User(id=32, username='TKostrzewski', password='666444', mode="wybijanie"))
users.append(User(id=33, username='VDolia', password='888999', mode="wybijanie"))
users.append(User(id=13, username='wybijanie', password='444444', mode="wybijanie")) 

# wysylka
users.append(User(id=36, username='TPalaszewski', password='222333', mode="wysylka"))
users.append(User(id=37, username='WHintz', password='666555', mode="wysylka"))
users.append(User(id=38, username='MCiesielski', password='333666', mode="wysylka"))
users.append(User(id=39, username='MWozniak', password='888555', mode="wysylka"))

# kontrola jakosci
users.append(User(id=19, username='TN', password='5522', mode="kontrola"))
users.append(User(id=20, username='WM', password='7447', mode="kontrola"))
users.append(User(id=21, username='ZR', password='9911', mode="kontrola"))
users.append(User(id=23, username='AK', password='7777', mode="kontrola"))
users.append(User(id=24, username='MF', password='7777', mode="kontrola"))
users.append(User(id=53, username='TF', password='5555', mode="kontrola"))
users.append(User(id=54, username='MP', password='4444', mode="kontrola"))
users.append(User(id=60, username='MM', password='5566', mode="kontrola"))

# kontrola jakosci + szlifiernia
#users.append(User(id=18, username='TM', password='7760', mode="kontrszlif"))
users.append(User(id=18, username='TM', password='7760', mode="kontrola"))

# Braki / mechaniczny
users.append(User(id=35, username='MW', password='335577', mode="mechaniczny"))
users.append(User(id=25, username='TL', password='222333', mode="mechaniczny"))
users.append(User(id=26, username='MG', password='444555', mode="mechaniczny"))
users.append(User(id=28, username='WZ', password='666999', mode="mechaniczny"))

# Braki / malarnia
users.append(User(id=34, username='JS', password='996633', mode="mechaniczny"))

# Akordy / szlifiernia
users.append(User(id=27, username='TZ', password='666333', mode="szlifiernia_akordy"))

# Mafi
users.append(User(id=16, username='wysylka', password='pass', mode="mafi"))

# Szlifiernia / ręczna
users.append(User(id=40, username='VSh', password='1212', mode="grinding"))
users.append(User(id=41, username='RKh', password='2121', mode="grinding"))
users.append(User(id=42, username='VMe', password='3434', mode="grinding"))
users.append(User(id=43, username='YBa', password='4545', mode="grinding"))
users.append(User(id=44, username='VZh', password='6565', mode="grinding"))
users.append(User(id=45, username='IMe', password='7667', mode="grinding"))
users.append(User(id=46, username='SKa', password='7666', mode="grinding"))
users.append(User(id=47, username='SBi', password='5454', mode="grinding"))
users.append(User(id=48, username='DAn', password='2288', mode="grinding"))
users.append(User(id=52, username='Isi', password='2244', mode="grinding"))
users.append(User(id=56, username='DKu', password='4545', mode="grinding"))
users.append(User(id=57, username='DKr', password='9898', mode="grinding"))
users.append(User(id=58, username='YBo', password='8787', mode="grinding"))

# Szlifiernia / roboty
users.append(User(id=49, username='KLi', password='3399', mode="grinding"))
users.append(User(id=50, username='OHu', password='4411', mode="grinding"))
users.append(User(id=51, username='AUl', password='2255', mode="grinding"))
users.append(User(id=59, username='KPi', password='2233', mode="grinding"))
