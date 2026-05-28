import pandas as pd
import sqlite3
import os
import asyncio
import unicodedata
from datetime import datetime

# Importações dos scrapers
import scrapers.paodeacucar as paodeacucar
import scrapers.atacadao as atacadao
import scrapers.boa as boa
import scrapers.carrefour as carrefour
import scrapers.svicente as svicente
import scrapers.covabra as covabra
import scrapers.dom_olivio as dom_olivio
import scrapers.oba as oba
import scrapers.tenda as tenda
import scrapers.assai as assai
import scrapers.fort as fort
import scrapers.roldao as roldao
import scrapers.tauste as tauste

from utils import read_json_file, write_json_file, setup_logging, validar_e_limpar_produtos, criar_entrada_biblioteca, enriquecer_ean_produtos_async
from classificador_ia import classificar_taxonomia_com_ia_async, carregar_biblioteca, salvar_biblioteca, gerar_id_unico, resolver_conflitos_ia_async

logger = setup_logging()

DATA_DIR = "data"
DB_NOME = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")

# ==========================================
# FUNÇÕES DE SUPORTE (DATABASE E EXCEL)
# ==========================================

def garantir_tabela_ofertas(db_path):
    """Garante que o diretório de dados e as tabelas 'ofertas' e 'historico_precos' no banco de dados existam."""
    data_dir = os.path.dirname(db_path)
    if data_dir and not os.path.exists(data_dir):
        os.makedirs(data_dir)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Cria a tabela de ofertas (snapshot atual)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ofertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Mercado TEXT,
            EAN TEXT,
            Categoria TEXT,
            subcategoria TEXT,
            tipo_produto TEXT,
            Produto TEXT,
            Marca TEXT,
            Preco_Varejo TEXT, 
            Preco_Atacado TEXT, 
            Qtd_Valor TEXT,
            Medida TEXT,
            Unidade TEXT,
            Condicao TEXT,
            Data_Hora TEXT,
            Link_Imagem TEXT,
            UNIQUE(Mercado, Produto, Qtd_Valor, Medida)
        )
    ''')
    
    # Cria a tabela de histórico de preços
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_precos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Mercado TEXT,
            EAN TEXT,
            Produto TEXT,
            Preco_Varejo TEXT,
            Preco_Atacado TEXT,
            Data_Hora TEXT
        )
    ''')
    
    # --- CRIAÇÃO DE ÍNDICES PARA OTIMIZAÇÃO (PERFORMANCE) ---
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ofertas_ean ON ofertas(EAN);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ofertas_mercado ON ofertas(Mercado);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ofertas_categoria ON ofertas(Categoria);')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_historico_ean ON historico_precos(EAN);')

    conn.commit()
    conn.close()

def salvar_dados_mercado(produtos, nome_mercado):
    """(Desativado) A persistência no banco e no excel agora é feita exclusivamente pelo script 5_atualizar_banco.py."""
    pass

# ==========================================
# PROCESSO PRINCIPAL (ORQUESTRADOR)
# ==========================================

async def processar_mercado(modulo, nome_mercado):
    """
    Função principal que aciona o scraper do mercado.
    Retorna apenas os produtos brutos. Toda a lógica de IA, cruzamento de EAN 
    e salvamento em banco foi movida para as etapas seguintes do pipeline.
    """
    try:
        logger.info(f"🛒 Coletando dados de: {nome_mercado}")
        produtos_brutos = await modulo.extrair_dados()
        
        if not produtos_brutos:
            logger.warning(f"⚠️ {nome_mercado}: Nenhuma oferta capturada.")
            return nome_mercado, []
        
        logger.info(f"✅ {nome_mercado}: {len(produtos_brutos)} itens coletados.")
        return nome_mercado, produtos_brutos
    except Exception as e:
        logger.error(f"❌ Erro no scraper {nome_mercado}: {e}")
        return nome_mercado, []

async def main():
    logger.info(f"🚀 INICIANDO SCRAPERS (FASE 1/3) - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # ---------------------------------------------------------
    # ETAPA 1: MERCADOS COM DADOS ESTRUTURADOS (API / JSON)
    # ---------------------------------------------------------
    scrapers_api = [
        # (atacadao, "Atacadão"),
        # (carrefour, "Carrefour"),
        (boa, "Boa Supermercados"),
        # (paodeacucar, "Pão de Açúcar"),
        # (covabra, "Covabra"),
        # (oba, "Oba Hortifruti"),
        # (dom_olivio, "Dom Olívio"),
        # (svicente, "S. Vicente"),
    ]

    logger.info("\n=== ETAPA 1: COLETANDO DADOS ESTRUTURADOS (API) ===")
    
    # Executa todos os scrapers de API em paralelo
    tarefas_api = [processar_mercado(modulo, nome_mercado) for modulo, nome_mercado in scrapers_api]
    resultados_api = await asyncio.gather(*tarefas_api)
    
    todos_itens_crus = []
    resumo_geral = {}

    for nome_mercado, produtos_brutos in resultados_api:
        if produtos_brutos:
            todos_itens_crus.extend(produtos_brutos)
            resumo_geral[nome_mercado] = len(produtos_brutos)

    # ---------------------------------------------------------
    # ETAPA 2: MERCADOS COM DADOS NÃO ESTRUTURADOS (IMAGEM/IA)
    # ---------------------------------------------------------
    scrapers_ia = [
        # (assai, "Assaí Atacadista"),
        # (fort, "Fort Atacadista"),
        # (roldao, "Roldão Atacadista"),
        # (tauste, "Tauste Supermercado"),
        # (tenda, "Tenda Atacado"),
    ]

    logger.info("\n=== ETAPA 2: COLETANDO DADOS NÃO ESTRUTURADOS (IMAGEM/IA) ===")
    
    tarefas_ia = [processar_mercado(modulo, nome_mercado) for modulo, nome_mercado in scrapers_ia]
    resultados_ia = await asyncio.gather(*tarefas_ia)
    
    for nome_mercado, produtos_brutos in resultados_ia:
        if produtos_brutos:
            todos_itens_crus.extend(produtos_brutos)
            resumo_geral[nome_mercado] = len(produtos_brutos)

    # ---------------------------------------------------------
    # ETAPA 3: NORMALIZAÇÃO DE PREÇOS (HOTFIX PARA 100G vs KG)
    # ---------------------------------------------------------
    # (Removido: A correção agora é feita na raiz pelo unitMultiplier no próprio scraper do Boa)
    itens_corrigidos = todos_itens_crus

    if itens_corrigidos:
        arquivo_pendentes = os.path.join(DATA_DIR, "pendentes_ia.json")
        write_json_file(arquivo_pendentes, itens_corrigidos)
        
        logger.info("\n" + "="*50)
        logger.info(f"📦 Sucesso! {len(itens_corrigidos)} itens totais raspados salvos em 'pendentes_ia.json'.")
        logger.info("👉 PRÓXIMO PASSO: Execute 'python 4_resolver_pendentes.py' para cruzar os EANs com a Biblioteca.")
        logger.info("="*50 + "\n")
    else:
        logger.warning("Nenhum item foi coletado pelos scrapers nesta execução.")

    logger.info("📊 RESUMO FINAL DA COLETA:")
    for m, q in resumo_geral.items():
        logger.info(f"  - {m}: {q} produtos coletados")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())