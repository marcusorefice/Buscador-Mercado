import psycopg2
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
    conn = psycopg2.connect(DB_URL)
    init_db(conn)
    cursor = conn.cursor()

    # 1. Sincronizar Biblioteca Ouro
    if os.path.exists(BIBLIOTECA_PATH):
        with open(BIBLIOTECA_PATH, 'r', encoding='utf-8') as f:
            biblioteca = json.load(f)
            
        print(f"Sincronizando {len(biblioteca)} 'Produtos Ouro' para o banco de dados...")
        for ean, info in biblioteca.items():
            tags_list = info.get("tags", [])
            tags_str = ", ".join(tags_list) if isinstance(tags_list, list) else str(tags_list)
            
            cursor.execute('''
                INSERT INTO produtos (ean, nome_comum, marca, categoria, subcategoria, tipo_produto, imagem, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ean) DO UPDATE SET
                    nome_comum=excluded.nome_comum,
                    marca=excluded.marca,
                    categoria=excluded.categoria,
                    subcategoria=excluded.subcategoria,
                    tipo_produto=excluded.tipo_produto,
                    imagem=excluded.imagem,
                    tags=excluded.tags
            ''', (
                ean, 
                info.get("nome_comum", ""), 
                info.get("marca", ""), 
                info.get("Categoria", "OUTROS"), 
                info.get("subcategoria", ""), 
                info.get("tipo_produto", ""), 
                info.get("imagem", ""),
                tags_str
            ))
        conn.commit()

    # 2. Sincronizar Ofertas Atuais e Histórico
    if os.path.exists(ITENS_CRUS_PATH):
        with open(ITENS_CRUS_PATH, 'r', encoding='utf-8') as f:
            itens_crus = json.load(f)

        print(f"Atualizando as ofertas diarias e o historico com {len(itens_crus)} itens...")
        
        hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

            condicao = item.get("Condicao", item.get("Condição", ""))
            data_extracao = item.get("Data_Hora", hoje)

            # Grava/Atualiza na vitrine de hoje
            cursor.execute('''
                INSERT INTO ofertas_atuais (ean, mercado, nome_original, preco_varejo, preco_atacado, condicao, data_atualizacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ean, mercado) DO UPDATE SET
                    nome_original=excluded.nome_original,
                    preco_varejo=excluded.preco_varejo,
                    preco_atacado=excluded.preco_atacado,
                    condicao=excluded.condicao,
                    data_atualizacao=excluded.data_atualizacao
            ''', (ean, mercado, nome_original, p_varejo, p_atacado, condicao, data_extracao))

            # Verifica se o preço mudou para gravar no Histórico
            cursor.execute('''
                SELECT preco_varejo, preco_atacado FROM historico_precos 
                WHERE ean = %s AND mercado = %s 
                ORDER BY id DESC LIMIT 1
            ''', (ean, mercado))
            ultimo = cursor.fetchone()
            
            # Só insere uma nova linha no histórico se for o primeiro registro ou se o preço for diferente do anterior
            if not ultimo or float(ultimo[0]) != p_varejo or float(ultimo[1]) != p_atacado:
                cursor.execute('''
                    INSERT INTO historico_precos (ean, mercado, preco_varejo, preco_atacado, data_hora)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (ean, mercado, p_varejo, p_atacado, data_extracao))
                
        conn.commit()
        print("Banco de dados PostgreSQL atualizado com sucesso!")
    else:
        print("Arquivo 'itens_prontos_para_comparar.json' nao encontrado. Voce rodou o passo 4?")
    
    conn.close()

if __name__ == "__main__":
    main()