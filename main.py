import os
import asyncio
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

from utils import ler_json_seguro, salvar_json_atomico, ArquivoCorrompidoError, setup_logging, exibir_resumo_coleta

logger = setup_logging()

DATA_DIR = "data"


# ==========================================
# PROCESSO PRINCIPAL (ORQUESTRADOR)
# ==========================================

async def processar_mercado(modulo, nome_mercado):
    """
    Função principal que aciona o scraper do mercado.
    Retorna apenas os produtos brutos. Toda a lógica de IA, cruzamento de EAN 
    e salvamento em banco foi movida para as etapas seguintes do pipeline.
    """
    import time
    try:
        logger.info(f"🛒 Coletando dados de: {nome_mercado}")
        start_time = time.time()
        produtos_brutos = await modulo.extrair_dados()
        end_time = time.time()
        duration = end_time - start_time
        
        if not produtos_brutos:
            logger.warning(f"⚠️ {nome_mercado}: Nenhuma oferta capturada. Tempo: {duration:.2f}s")
            return nome_mercado, [], duration
        
        logger.info(f"✅ {nome_mercado}: {len(produtos_brutos)} itens coletados em {duration:.2f} segundos.")
        return nome_mercado, produtos_brutos, duration
    except Exception as e:
        logger.error(f"❌ Erro no scraper {nome_mercado}: {e}")
        return nome_mercado, [], 0.0

async def main():
    logger.info(f"🚀 INICIANDO SCRAPERS (FASE 1/3) - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # ---------------------------------------------------------
    # ETAPA 1: MERCADOS COM DADOS ESTRUTURADOS (API / JSON)
    # ---------------------------------------------------------
    scrapers_api = [
        (atacadao, "Atacadão"),
        (carrefour, "Carrefour"),
        (boa, "Boa Supermercados"),
        (paodeacucar, "Pão de Açúcar"),
        (covabra, "Covabra"),
        (oba, "Oba Hortifruti"),
        (dom_olivio, "Dom Olívio"),
        (svicente, "S. Vicente"),
    ]

    logger.info("\n=== ETAPA 1: COLETANDO DADOS ESTRUTURADOS (API) ===")
    
    # Executa todos os scrapers de API em paralelo
    tarefas_api = [processar_mercado(modulo, nome_mercado) for modulo, nome_mercado in scrapers_api]
    resultados_api = await asyncio.gather(*tarefas_api)
    
    todos_itens_crus = []
    resumo_geral = {}

    for nome_mercado, produtos_brutos, duration in resultados_api:
        resumo_geral[nome_mercado] = {"qtd": len(produtos_brutos), "tempo": duration}
        if produtos_brutos:
            todos_itens_crus.extend(produtos_brutos)

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
    
    for nome_mercado, produtos_brutos, duration in resultados_ia:
        resumo_geral[nome_mercado] = {"qtd": len(produtos_brutos), "tempo": duration}
        if produtos_brutos:
            todos_itens_crus.extend(produtos_brutos)

    # ---------------------------------------------------------
    # ETAPA 3: NORMALIZAÇÃO DE PREÇOS (HOTFIX PARA 100G vs KG)
    # ---------------------------------------------------------
    # (Removido: A correção agora é feita na raiz pelo unitMultiplier no próprio scraper do Boa)
    itens_corrigidos = todos_itens_crus

    if itens_corrigidos:
        arquivo_pendentes = os.path.join(DATA_DIR, "pendentes_ia.json")
        # Acrescenta à fila em vez de sobrescrever: ela pode ter itens do main_full.py
        # ou sobras do passo 4 que ainda não foram processados.
        try:
            fila = ler_json_seguro(arquivo_pendentes, [])
        except ArquivoCorrompidoError as e:
            arquivo_pendentes = os.path.join(DATA_DIR, f"resgate_diario_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            logger.error(f"❌ {e}. Os itens desta coleta serão salvos em '{arquivo_pendentes}'.")
            fila = []
        fila.extend(itens_corrigidos)
        salvar_json_atomico(arquivo_pendentes, fila)
        
        logger.info("\n" + "="*50)
        logger.info(f"📦 Sucesso! {len(itens_corrigidos)} itens totais raspados salvos em 'pendentes_ia.json'.")
        logger.info("👉 PRÓXIMO PASSO: Execute 'python 4_resolver_pendentes.py' para cruzar os EANs com a Biblioteca.")
        logger.info("="*50 + "\n")
    else:
        logger.warning("Nenhum item foi coletado pelos scrapers nesta execução.")

    exibir_resumo_coleta(resumo_geral, logger)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())