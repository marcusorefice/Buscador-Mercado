import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import sqlite3
import pandas as pd

try:
    conn = sqlite3.connect('data/monitoramento_Jundiai.db')
    
    query = '''
        SELECT Mercado, Data_Hora, COUNT(*) as Quantidade
        FROM ofertas
        GROUP BY Mercado, Data_Hora
        ORDER BY Data_Hora DESC
    '''
    df = pd.read_sql_query(query, conn)
    
    if df.empty:
        print('O banco de dados de ofertas está vazio.')
    else:
        # Get only the most recent scrape per market
        idx_latest = df.groupby('Mercado')['Data_Hora'].idxmax()
        latest_per_market = df.loc[idx_latest]
        
        print('--- Resumo das últimas extrações por Mercado ---')
        for index, row in latest_per_market.iterrows():
            print(f"{row['Mercado']}: {row['Quantidade']} itens (Data: {row['Data_Hora']})")
    
    conn.close()
except Exception as e:
    print(f'Erro: {e}')
