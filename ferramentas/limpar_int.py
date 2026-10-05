import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import psycopg2
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
local_db_path = os.path.join("data", "monitoramento_Jundiai.db")

# ATENÇÃO: desde o casamento de nomes, os INT_ são grupos legítimos de produtos sem EAN
# (o mesmo produto em vários mercados). Este script apaga TODOS do banco; eles voltam no próximo passo 4 + 5.
resposta = input("Isso apaga do banco todos os produtos sem EAN (INT_). Continuar? [s/N] ")
if resposta.strip().lower() != "s":
    raise SystemExit("Cancelado.")

print("🧹 Iniciando a Limpeza de EANs 'INT_' do Banco de Dados...")

# --- SUPABASE (POSTGRESQL) ---
if DB_URL:
    try:
        conn_pg = psycopg2.connect(DB_URL)
        cursor_pg = conn_pg.cursor()
        
        cursor_pg.execute("DELETE FROM ofertas_atuais WHERE ean LIKE 'INT_%'")
        removidos_ofertas = cursor_pg.rowcount
        
        cursor_pg.execute("DELETE FROM produtos WHERE ean LIKE 'INT_%'")
        removidos_produtos = cursor_pg.rowcount
        
        conn_pg.commit()
        conn_pg.close()
        print(f"☁️ Supabase: {removidos_ofertas} ofertas e {removidos_produtos} produtos INT_ apagados!")
    except Exception as e:
        print(f"Erro no Supabase: {e}")

# --- SQLITE (LOCAL) ---
if os.path.exists(local_db_path):
    try:
        conn_sl = sqlite3.connect(local_db_path)
        cursor_sl = conn_sl.cursor()
        
        cursor_sl.execute("DELETE FROM ofertas_atuais WHERE ean LIKE 'INT_%'")
        removidos_ofertas_sl = cursor_sl.rowcount
        
        cursor_sl.execute("DELETE FROM produtos WHERE ean LIKE 'INT_%'")
        removidos_produtos_sl = cursor_sl.rowcount
        
        conn_sl.commit()
        conn_sl.close()
        print(f"💻 SQLite Local: {removidos_ofertas_sl} ofertas e {removidos_produtos_sl} produtos INT_ apagados!")
    except Exception as e:
        print(f"Erro no SQLite: {e}")

print("\n✅ Limpeza concluída com sucesso! Todos os EANs internos foram removidos do banco.")
print("💡 Dica: Rode 'python sincronizar_typesense.py' depois para refletir isso no buscador.")
