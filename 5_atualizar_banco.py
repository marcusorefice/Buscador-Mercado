import psycopg2
import sqlite3
import json
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from psycopg2.extras import execute_batch, execute_values
from sincronizar_typesense import sincronizar_com_typesense
from ofertas_sql import atualizar_visoes
from utils import parse_preco, normalizar_data_iso, read_json_file

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# Definir os caminhos dos arquivos
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# URL do Banco de Dados Supabase (PostgreSQL)
DB_URL = os.getenv("DATABASE_URL")
BIBLIOTECA_PATH = os.path.join(DATA_DIR, "biblioteca_produtos.json")
ITENS_CRUS_PATH = os.path.join(DATA_DIR, "itens_prontos_para_comparar.json")
# Correções manuais de EAN (ex: mercado que usa o EAN da garrafa para a lata)
CORRECOES_EAN_PATH = os.path.join(os.path.dirname(__file__), "specs", "correcoes_ean.json")

def _executar_opcional(conn, sql, descricao):
    """Executa um comando de manutenção que pode falhar sem derrubar o processo (ex: falta de permissão)."""
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"⚠️ Não foi possível {descricao}: {e}")

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

    # --- MIGRAÇÃO DE DATAS: dd/mm/AAAA -> AAAA-MM-DD (texto ISO ordena corretamente) ---
    # Só afeta linhas antigas; depois da primeira execução não encontra mais nada.
    _executar_opcional(conn, r"""
        UPDATE historico_precos
        SET data_hora = to_char(to_timestamp(data_hora, 'DD/MM/YYYY HH24:MI:SS'), 'YYYY-MM-DD HH24:MI:SS')
        WHERE data_hora ~ '^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$'
    """, "migrar datas do histórico")
    _executar_opcional(conn, r"""
        UPDATE ofertas_atuais
        SET data_atualizacao = to_char(to_timestamp(data_atualizacao, 'DD/MM/YYYY HH24:MI:SS'), 'YYYY-MM-DD HH24:MI:SS')
        WHERE data_atualizacao ~ '^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$'
    """, "migrar datas das ofertas")

    # --- ÍNDICES ---
    _executar_opcional(conn, "CREATE INDEX IF NOT EXISTS idx_hist_ean_mercado_id ON historico_precos (ean, mercado, id DESC)", "criar índice do histórico")
    _executar_opcional(conn, "CREATE INDEX IF NOT EXISTS idx_ofertas_mercado ON ofertas_atuais (mercado)", "criar índice de mercado")
    # Busca com ILIKE '%termo%' só usa índice com pg_trgm (trigramas)
    _executar_opcional(conn, "CREATE EXTENSION IF NOT EXISTS pg_trgm", "ativar a extensão pg_trgm")
    for tabela, coluna in [("produtos", "nome_comum"), ("produtos", "marca"), ("produtos", "tags"), ("ofertas_atuais", "nome_original")]:
        _executar_opcional(
            conn,
            f"CREATE INDEX IF NOT EXISTS idx_trgm_{tabela}_{coluna} ON {tabela} USING gin ({coluna} gin_trgm_ops)",
            f"criar índice de busca em {tabela}.{coluna}"
        )

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

    # Migração de datas dd/mm/AAAA -> AAAA-MM-DD
    for tabela, coluna in [("historico_precos", "data_hora"), ("ofertas_atuais", "data_atualizacao")]:
        cursor.execute(f'''
            UPDATE {tabela}
            SET {coluna} = substr({coluna}, 7, 4) || '-' || substr({coluna}, 4, 2) || '-' || substr({coluna}, 1, 2) || substr({coluna}, 11)
            WHERE {coluna} GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]*'
        ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_ean_mercado_id ON historico_precos (ean, mercado, id)")
    conn.commit()

def carregar_correcoes_ean():
    correcoes = read_json_file(CORRECOES_EAN_PATH, default_value=[])
    return correcoes if isinstance(correcoes, list) else []

def aplicar_correcoes_ean(ean, nome_original, correcoes):
    nome_upper = str(nome_original).upper()
    for c in correcoes:
        if ean == c.get("ean_errado") and str(c.get("nome_contem", "")).upper() in nome_upper:
            return c.get("ean_correto", ean)
    return ean

def preparar_ofertas(itens_crus, correcoes):
    """
    Converte os itens do passo 4 em linhas de oferta, uma por (ean, mercado).
    Retorna (ofertas_por_chave, eans_por_mercado, mercados_full).
    """
    hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ofertas = {}
    eans_por_mercado = {}
    mercados_full = set()

    for item in itens_crus:
        ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        if ean in ("N/A", "", "None", "nan") or (not ean.isdigit() and not ean.startswith("INT_") and '_' not in ean):
            continue

        mercado = item.get("Mercado", "Desconhecido")
        nome_original = item.get("Produto", item.get("nome_comum", ""))

        p_varejo = parse_preco(item.get("Preco_Varejo", item.get("Preço Varejo", 0)))
        p_atacado = parse_preco(item.get("Preco_Atacado", item.get("Preço Atacado", 0)))
        if p_varejo == 0 and p_atacado == 0:
            continue

        ean = aplicar_correcoes_ean(ean, nome_original, correcoes)

        eans_por_mercado.setdefault(mercado, set()).add(ean)
        if item.get("Scraper_Origem") == "FULL":
            mercados_full.add(mercado)

        # Se o mesmo (ean, mercado) aparecer duas vezes no lote, o último vence
        # (o Postgres não aceita o mesmo registro duas vezes num único INSERT ... ON CONFLICT).
        ofertas[(ean, mercado)] = (
            ean, mercado, nome_original, p_varejo, p_atacado,
            str(item.get("Qtd_Valor", "1")), str(item.get("Medida", "UN")), str(item.get("Unidade", "UN")),
            item.get("Condicao", item.get("Condição", "")),
            normalizar_data_iso(item.get("Data_Hora")) if item.get("Data_Hora") else hoje,
            item.get("Link_PDP", ""),
        )
    return ofertas, eans_por_mercado, mercados_full

def calcular_novos_historicos(ofertas, ultimos_precos):
    """Só gera linha de histórico se for o primeiro registro ou se o preço mudou."""
    novos = []
    for (ean, mercado), o in ofertas.items():
        p_varejo, p_atacado, data_extracao = o[3], o[4], o[9]
        ultimo = ultimos_precos.get((ean, mercado))
        if (not ultimo
                or round(float(ultimo[0] or 0), 2) != round(p_varejo, 2)
                or round(float(ultimo[1] or 0), 2) != round(p_atacado, 2)):
            novos.append((ean, mercado, p_varejo, p_atacado, data_extracao))
    return novos

SQL_UPSERT_OFERTA_COLUNAS = "ean, mercado, nome_original, preco_varejo, preco_atacado, qtd_valor, medida, unidade, condicao, data_atualizacao, link_pdp"
SQL_UPSERT_OFERTA_CONFLITO = '''
    ON CONFLICT (ean, mercado) DO UPDATE SET
        nome_original=excluded.nome_original, preco_varejo=excluded.preco_varejo, preco_atacado=excluded.preco_atacado,
        qtd_valor=excluded.qtd_valor, medida=excluded.medida, unidade=excluded.unidade,
        condicao=excluded.condicao, data_atualizacao=excluded.data_atualizacao, link_pdp=excluded.link_pdp
'''

def main():
    logger.info("Conectando ao banco de dados PostgreSQL na nuvem (Supabase)...")
    conn_pg = psycopg2.connect(DB_URL)
    init_db(conn_pg)
    cursor_pg = conn_pg.cursor()

    local_db_path = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")
    logger.info("Conectando ao banco de dados local SQLite (Espelho VSCode)...")
    conn_sl = sqlite3.connect(local_db_path)
    init_sqlite_db(conn_sl)
    cursor_sl = conn_sl.cursor()

    # 1. Sincronizar Biblioteca Ouro
    if os.path.exists(BIBLIOTECA_PATH):
        with open(BIBLIOTECA_PATH, 'r', encoding='utf-8') as f:
            biblioteca = json.load(f)

        logger.info(f"Sincronizando {len(biblioteca)} 'Produtos Ouro' para os bancos de dados...")

        params_list = []
        for ean, info in biblioteca.items():
            tags_list = info.get("tags", [])
            tags_str = ", ".join(tags_list) if isinstance(tags_list, list) else str(tags_list)

            params_list.append((
                ean,
                info.get("nome_comum", ""),
                info.get("marca", ""),
                info.get("Categoria", "OUTROS"),
                info.get("subcategoria", ""),
                info.get("tipo_produto", ""),
                info.get("imagem", ""),
                tags_str
            ))

        logger.info("Enviando lote para PostgreSQL (Supabase)...")
        execute_batch(cursor_pg, '''
            INSERT INTO produtos (ean, nome_comum, marca, categoria, subcategoria, tipo_produto, imagem, tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ean) DO UPDATE SET
                nome_comum=excluded.nome_comum, marca=excluded.marca, categoria=excluded.categoria,
                subcategoria=excluded.subcategoria, tipo_produto=excluded.tipo_produto,
                imagem=excluded.imagem, tags=excluded.tags
        ''', params_list, page_size=1000)
        conn_pg.commit()
        logger.info("Sincronização PostgreSQL concluída.")

        logger.info("Enviando lote para SQLite (Local)...")
        cursor_sl.executemany('''
            INSERT INTO produtos (ean, nome_comum, marca, categoria, subcategoria, tipo_produto, imagem, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ean) DO UPDATE SET
                nome_comum=excluded.nome_comum, marca=excluded.marca, categoria=excluded.categoria,
                subcategoria=excluded.subcategoria, tipo_produto=excluded.tipo_produto,
                imagem=excluded.imagem, tags=excluded.tags
        ''', params_list)
        conn_sl.commit()
        logger.info("Sincronização SQLite concluída.")

    # 2. Sincronizar Ofertas Atuais e Histórico (tudo em lote: poucas idas ao banco em vez de ~4 por item)
    if os.path.exists(ITENS_CRUS_PATH):
        with open(ITENS_CRUS_PATH, 'r', encoding='utf-8') as f:
            itens_crus = json.load(f)

        logger.info(f"Atualizando as ofertas diarias e o historico com {len(itens_crus)} itens...")

        ofertas, eans_processados_por_mercado, mercados_full = preparar_ofertas(itens_crus, carregar_correcoes_ean())
        linhas_ofertas = list(ofertas.values())
        mercados = list(eans_processados_por_mercado.keys())
        logger.info(f"  {len(linhas_ofertas)} ofertas únicas (ean + mercado) em {len(mercados)} mercados.")

        try:
            # --- 2a. Upsert das ofertas ---
            logger.info("  Enviando ofertas para PostgreSQL...")
            execute_values(cursor_pg,
                f"INSERT INTO ofertas_atuais ({SQL_UPSERT_OFERTA_COLUNAS}) VALUES %s {SQL_UPSERT_OFERTA_CONFLITO}",
                linhas_ofertas, page_size=1000)
            logger.info("  Enviando ofertas para SQLite...")
            cursor_sl.executemany(
                f"INSERT INTO ofertas_atuais ({SQL_UPSERT_OFERTA_COLUNAS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) {SQL_UPSERT_OFERTA_CONFLITO}",
                linhas_ofertas)

            # --- 2b. Histórico: busca o último preço de cada (ean, mercado) numa única consulta ---
            cursor_pg.execute('''
                SELECT DISTINCT ON (ean, mercado) ean, mercado, preco_varejo, preco_atacado
                FROM historico_precos
                WHERE mercado = ANY(%s)
                ORDER BY ean, mercado, id DESC
            ''', (mercados,))
            ultimos_pg = {(r[0], r[1]): (r[2], r[3]) for r in cursor_pg.fetchall()}
            novos_pg = calcular_novos_historicos(ofertas, ultimos_pg)
            execute_values(cursor_pg,
                "INSERT INTO historico_precos (ean, mercado, preco_varejo, preco_atacado, data_hora) VALUES %s",
                novos_pg, page_size=1000)

            cursor_sl.execute('''
                SELECT h.ean, h.mercado, h.preco_varejo, h.preco_atacado
                FROM historico_precos h
                JOIN (SELECT MAX(id) AS id FROM historico_precos GROUP BY ean, mercado) u ON u.id = h.id
            ''')
            ultimos_sl = {(r[0], r[1]): (r[2], r[3]) for r in cursor_sl.fetchall()}
            novos_sl = calcular_novos_historicos(ofertas, ultimos_sl)
            cursor_sl.executemany(
                "INSERT INTO historico_precos (ean, mercado, preco_varejo, preco_atacado, data_hora) VALUES (?, ?, ?, ?, ?)",
                novos_sl)
            logger.info(f"  📈 {len(novos_pg)} mudanças de preço registradas no histórico.")

            # --- LIMPEZA DE OFERTAS INATIVAS / ESGOTADAS ---
            total_removidos = 0
            cursor_sl.execute("CREATE TEMP TABLE IF NOT EXISTS eans_ativos (ean TEXT PRIMARY KEY)")
            for mercado_nome, eans_ativos in eans_processados_por_mercado.items():
                # Proteção: Se a raspagem trouxe pouquíssimos itens, pode ter sido um erro/teste.
                # Ignoramos a exclusão para não apagar todo o mercado por acidente.
                if len(eans_ativos) < 500:
                    logger.warning(f"⚠️ Limpeza ignorada para '{mercado_nome}' (apenas {len(eans_ativos)} itens processados, protegendo contra falha de scraper).")
                    continue

                # Proteção contra deleção em massa pelas raspagens diárias (que pegam só algumas ofertas)
                if mercado_nome not in mercados_full:
                    logger.info(f"⏩ Limpeza ignorada para '{mercado_nome}' (Coleta diária/parcial não deleta o catálogo base do banco).")
                    continue

                cursor_pg.execute('''
                    DELETE FROM ofertas_atuais
                    WHERE mercado = %s AND NOT (ean = ANY(%s))
                ''', (mercado_nome, list(eans_ativos)))
                total_removidos += cursor_pg.rowcount

                # SQLite tem limite de parâmetros por comando, então usa uma tabela temporária
                cursor_sl.execute("DELETE FROM eans_ativos")
                cursor_sl.executemany("INSERT OR IGNORE INTO eans_ativos (ean) VALUES (?)", [(e,) for e in eans_ativos])
                cursor_sl.execute('''
                    DELETE FROM ofertas_atuais
                    WHERE mercado = ? AND ean NOT IN (SELECT ean FROM eans_ativos)
                ''', (mercado_nome,))

            if total_removidos > 0:
                logger.info(f"🧹 Limpeza concluída: {total_removidos} ofertas antigas/esgotadas foram removidas do banco!")

            conn_pg.commit()
            conn_sl.commit()
        except Exception:
            conn_pg.rollback()
            conn_sl.rollback()
            logger.error("❌ Erro ao atualizar as ofertas. Nada foi gravado e o arquivo de staging foi mantido.")
            raise

        logger.info("Bancos de dados PostgreSQL e SQLite (Local) atualizados com sucesso!")

        # --- LIMPEZA DA ÁREA DE STAGING ---
        try:
            os.remove(ITENS_CRUS_PATH)
            logger.info("🗑️ Arquivo 'itens_prontos_para_comparar.json' deletado com sucesso (Staging limpo)!")
        except Exception as e:
            logger.warning(f"⚠️ Aviso: Não foi possível deletar o arquivo temporário: {e}")
    else:
        logger.warning("Arquivo 'itens_prontos_para_comparar.json' nao encontrado. Voce rodou o passo 4?")

    # --- RECALCULA AS OFERTAS VÁLIDAS E O RESUMO DE PREÇOS QUE O APP LÊ (ver ofertas_sql.py) ---
    try:
        with conn_pg.cursor() as cursor_visoes:
            atualizar_visoes(cursor_visoes)
        conn_pg.commit()
        logger.info("📊 Resumo de preços do app recalculado.")
    except Exception as e:
        conn_pg.rollback()
        logger.error(f"⚠️ Erro ao recalcular o resumo de preços (o app continua com o anterior): {e}")

    conn_pg.close()
    conn_sl.close()

    # --- ATUALIZA O TYPESENSE AUTOMATICAMENTE ---
    try:
        sincronizar_com_typesense()
    except Exception as e:
        logger.error(f"⚠️ Erro ao sincronizar com Typesense: {e}")

if __name__ == "__main__":
    main()
