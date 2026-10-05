import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import sqlite3

db_path = 'd:/Mercado/data/monitoramento_Jundiai.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT Mercado, Produto, EAN FROM ofertas WHERE EAN IN ('2005100000002', '2373700000006', '2122100000006')")
rows = c.fetchall()
for r in rows:
    print(f'Mercado: {r[0]} | Produto: {r[1]} | EAN: {r[2]}')
