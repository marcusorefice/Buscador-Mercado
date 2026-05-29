import psycopg2
import sqlite3
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Definir os caminhos dos arquivos
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# URL do Banco de Dados Supabase (PostgreSQL)
DB_URL = os.getenv("DATABASE_URL")
BIBLIOTECA_PATH = os.path.join(DATA_DIR, "biblioteca_produtos.json")
ITENS_CRUS_PATH = os.path.join(DATA_DIR, "itens_prontos_para_comparar.json")

def init_db(conn):
    cursor = conn.cursor()
    
    # Tabela Produtos (Sua Biblioteca Ouro)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS produtos (
        ean TEXT PRIMARY KEY,
        nome_comum TEXT,
        marca TEXT,
        categoria TEXT,
        subcategoria TEXT,
        tipo_produto TEXT,
        imagem TEXT,
        tags TEXT
    )
    ''')

    # Tabela Ofertas Atuais (O que os scrapers coletaram por último)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ofertas_atuais (
        ean TEXT,
        mercado TEXT,
        nome_original TEXT,
        preco_varejo NUMERIC,
        preco_atacado NUMERIC,
        condicao TEXT,
        data_atualizacao TEXT,
        PRIMARY KEY (ean, mercado)
    )
    ''')
    
    # Tenta adicionar as colunas novas, ignorando erro se já existirem
    for col_name in ["link_pdp", "qtd_valor", "medida", "unidade"]:
        try:
            cursor.execute(f"ALTER TABLE ofertas_atuais ADD COLUMN {col_name} TEXT;")
            conn.commit()
        except Exception:
            conn.rollback()

    # Tabela Histórico de Preços (Para gráficos de variação de preço futuro)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS historico_precos (
        id SERIAL PRIMARY KEY,
        ean TEXT,
        mercado TEXT,
        preco_varejo NUMERIC,
        preco_atacado NUMERIC,
        data_hora TEXT
    )
    ''')
    conn.commit()

def init_sqlite_db(conn):
    """Cria e atualiza as tabelas no banco de dados local (SQLite)"""
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS produtos (
        ean TEXT PRIMARY KEY, nome_comum TEXT, marca TEXT, categoria TEXT,
        subcategoria TEXT, tipo_produto TEXT, imagem TEXT, tags TEXT
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ofertas_atuais (
        ean TEXT, mercado TEXT, nome_original TEXT, preco_varejo REAL, preco_atacado REAL,
        condicao TEXT, data_atualizacao TEXT, PRIMARY KEY (ean, mercado)
    )''')
    
    for col_name in ["link_pdp", "qtd_valor", "medida", "unidade"]:
        try:
            cursor.execute(f"ALTER TABLE ofertas_atuais ADD COLUMN {col_name} TEXT;")
            conn.commit()
        except Exception:
            pass

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS historico_precos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ean TEXT, mercado TEXT, preco_varejo REAL, preco_atacado REAL, data_hora TEXT
    )''')
    conn.commit()

def extract_number(price_str):
    """Limpa a string de preço vinda do scraper para garantir que seja um Float válido no Banco"""
    if not price_str or price_str in ("N/A", "None", ""):
        return 0.0
    if isinstance(price_str, (int, float)):
        return float(price_str)
    
    s = str(price_str).upper().replace("R$", "").strip()
    # Corrige formatação de milhares se houver (ex: 1.200,50 -> 1200.50)
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

def main():
    print(f"Conectando ao banco de dados PostgreSQL na nuvem (Supabase)...")
    conn_pg = psycopg2.connect(DB_URL)
    init_db(conn_pg)
    cursor_pg = conn_pg.cursor()
    
    local_db_path = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")
    print(f"Conectando ao banco de dados local SQLite (Espelho VSCode)...")
    conn_sl = sqlite3.connect(local_db_path)
    init_sqlite_db(conn_sl)
    cursor_sl = conn_sl.cursor()

    # 1. Sincronizar Biblioteca Ouro
    if os.path.exists(BIBLIOTECA_PATH):
        with open(BIBLIOTECA_PATH, 'r', encoding='utf-8') as f:
            biblioteca = json.load(f)
            
        print(f"Sincronizando {len(biblioteca)} 'Produtos Ouro' para os bancos de dados...")
        for ean, info in biblioteca.items():
            tags_list = info.get("tags", [])
            tags_str = ", ".join(tags_list) if isinstance(tags_list, list) else str(tags_list)
            
            params = (
                ean, 
                info.get("nome_comum", ""), 
                info.get("marca", ""), 
                info.get("Categoria", "OUTROS"), 
                info.get("subcategoria", ""), 
                info.get("tipo_produto", ""), 
                info.get("imagem", ""),
                tags_str
            )
            
            # Supabase
            cursor_pg.execute('''
                INSERT INTO produtos (ean, nome_comum, marca, categoria, subcategoria, tipo_produto, imagem, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ean) DO UPDATE SET
                    nome_comum=excluded.nome_comum, marca=excluded.marca, categoria=excluded.categoria,
                    subcategoria=excluded.subcategoria, tipo_produto=excluded.tipo_produto,
                    imagem=excluded.imagem, tags=excluded.tags
            ''', params)
            
            # SQLite (Local)
            cursor_sl.execute('''
                INSERT INTO produtos (ean, nome_comum, marca, categoria, subcategoria, tipo_produto, imagem, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ean) DO UPDATE SET
                    nome_comum=excluded.nome_comum, marca=excluded.marca, categoria=excluded.categoria,
                    subcategoria=excluded.subcategoria, tipo_produto=excluded.tipo_produto,
                    imagem=excluded.imagem, tags=excluded.tags
            ''', params)
            
        conn_pg.commit()
        conn_sl.commit()

    # 2. Sincronizar Ofertas Atuais e Histórico
    if os.path.exists(ITENS_CRUS_PATH):
        with open(ITENS_CRUS_PATH, 'r', encoding='utf-8') as f:
            itens_crus = json.load(f)

        print(f"Atualizando as ofertas diarias e o historico com {len(itens_crus)} itens...")
        
        hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Rastreador de produtos ativos de cada mercado na raspagem atual
        eans_processados_por_mercado = {}
        scraper_origem_por_mercado = {}

        for item in itens_crus:
            ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
            if ean in ("N/A", "", "None", "nan") or not ean.isdigit():
                continue

            mercado = item.get("Mercado", "Desconhecido")
            nome_original = item.get("Produto", item.get("nome_comum", ""))
            
            p_varejo_str = item.get("Preco_Varejo", item.get("Preço Varejo", 0))
            p_atacado_str = item.get("Preco_Atacado", item.get("Preço Atacado", 0))
            
            p_varejo = extract_number(p_varejo_str)
            p_atacado = extract_number(p_atacado_str)
            
            if p_varejo == 0 and p_atacado == 0:
                continue
                
            if mercado not in eans_processados_por_mercado:
                eans_processados_por_mercado[mercado] = set()
                scraper_origem_por_mercado[mercado] = False
                
            eans_processados_por_mercado[mercado].add(ean)
            if item.get("Scraper_Origem") == "FULL":
                scraper_origem_por_mercado[mercado] = True

            condicao = item.get("Condicao", item.get("Condição", ""))
            data_extracao = item.get("Data_Hora", hoje)
            link_pdp = item.get("Link_PDP", "")
            
            qtd_valor = str(item.get("Qtd_Valor", "1"))
            medida = str(item.get("Medida", "UN"))
            unidade = str(item.get("Unidade", "UN"))
            
            params_oferta = (ean, mercado, nome_original, p_varejo, p_atacado, qtd_valor, medida, unidade, condicao, data_extracao, link_pdp)

            # Supabase
            cursor_pg.execute('''
                INSERT INTO ofertas_atuais (ean, mercado, nome_original, preco_varejo, preco_atacado, qtd_valor, medida, unidade, condicao, data_atualizacao, link_pdp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ean, mercado) DO UPDATE SET
                    nome_original=excluded.nome_original, preco_varejo=excluded.preco_varejo, preco_atacado=excluded.preco_atacado,
                    qtd_valor=excluded.qtd_valor, medida=excluded.medida, unidade=excluded.unidade,
                    condicao=excluded.condicao, data_atualizacao=excluded.data_atualizacao, link_pdp=excluded.link_pdp
            ''', params_oferta)
            
            # SQLite (Local)
            cursor_sl.execute('''
                INSERT INTO ofertas_atuais (ean, mercado, nome_original, preco_varejo, preco_atacado, qtd_valor, medida, unidade, condicao, data_atualizacao, link_pdp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ean, mercado) DO UPDATE SET
                    nome_original=excluded.nome_original, preco_varejo=excluded.preco_varejo, preco_atacado=excluded.preco_atacado,
                    qtd_valor=excluded.qtd_valor, medida=excluded.medida, unidade=excluded.unidade,
                    condicao=excluded.condicao, data_atualizacao=excluded.data_atualizacao, link_pdp=excluded.link_pdp
            ''', params_oferta)

            # Verifica se o preço mudou para gravar no Histórico
            cursor_pg.execute('''
                SELECT preco_varejo, preco_atacado FROM historico_precos 
                WHERE ean = %s AND mercado = %s 
                ORDER BY id DESC LIMIT 1
            ''', (ean, mercado))
            ultimo_pg = cursor_pg.fetchone()
            
            # Só insere uma nova linha no histórico se for o primeiro registro ou se o preço for diferente do anterior
            if not ultimo_pg or float(ultimo_pg[0]) != p_varejo or float(ultimo_pg[1]) != p_atacado:
                cursor_pg.execute('''
                    INSERT INTO historico_precos (ean, mercado, preco_varejo, preco_atacado, data_hora)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (ean, mercado, p_varejo, p_atacado, data_extracao))
                
            cursor_sl.execute('''
                SELECT preco_varejo, preco_atacado FROM historico_precos 
                WHERE ean = ? AND mercado = ? 
                ORDER BY id DESC LIMIT 1
            ''', (ean, mercado))
            ultimo_sl = cursor_sl.fetchone()
            if not ultimo_sl or float(ultimo_sl[0]) != p_varejo or float(ultimo_sl[1]) != p_atacado:
                cursor_sl.execute('''
                    INSERT INTO historico_precos (ean, mercado, preco_varejo, preco_atacado, data_hora)
                    VALUES (?, ?, ?, ?, ?)
                ''', (ean, mercado, p_varejo, p_atacado, data_extracao))
                
        # --- LIMPEZA DE OFERTAS INATIVAS / ESGOTADAS ---
        total_removidos = 0
        for mercado_nome, eans_ativos in eans_processados_por_mercado.items():
            # Proteção: Se a raspagem trouxe pouquíssimos itens, pode ter sido um erro/teste. 
            # Ignoramos a exclusão para não apagar todo o mercado por acidente.
            if len(eans_ativos) < 20:
                print(f"⚠️ Limpeza ignorada para '{mercado_nome}' (apenas {len(eans_ativos)} itens processados, protegendo contra falha de scraper).")
                continue
                
            # Proteção contra deleção em massa pelas raspagens diárias (que pegam só algumas ofertas)
            if not scraper_origem_por_mercado.get(mercado_nome, False):
                print(f"⏩ Limpeza ignorada para '{mercado_nome}' (Coleta diária/parcial não deleta o catálogo base do banco).")
                continue
            
            # Deleta no Postgres
            cursor_pg.execute('''
                DELETE FROM ofertas_atuais 
                WHERE mercado = %s AND ean NOT IN %s
            ''', (mercado_nome, tuple(eans_ativos)))
            
            # Deleta no SQLite Local
            placeholders = ','.join(['?'] * len(eans_ativos))
            cursor_sl.execute(f'''
                DELETE FROM ofertas_atuais 
                WHERE mercado = ? AND ean NOT IN ({placeholders})
            ''', (mercado_nome, *tuple(eans_ativos)))
            
            total_removidos += cursor_pg.rowcount
            
        if total_removidos > 0:
            print(f"🧹 Limpeza concluída: {total_removidos} ofertas antigas/esgotadas foram removidas do banco!")

        conn_pg.commit()
        conn_sl.commit()
        print("Bancos de dados PostgreSQL e SQLite (Local) atualizados com sucesso!")
        
        # --- LIMPEZA DA ÁREA DE STAGING ---
        try:
            os.remove(ITENS_CRUS_PATH)
            print("🗑️ Arquivo 'itens_prontos_para_comparar.json' deletado com sucesso (Staging limpo)!")
        except Exception as e:
            print(f"⚠️ Aviso: Não foi possível deletar o arquivo temporário: {e}")
    else:
        print("Arquivo 'itens_prontos_para_comparar.json' nao encontrado. Voce rodou o passo 4?")
    
    conn_pg.close()
    conn_sl.close()

if __name__ == "__main__":
    main()