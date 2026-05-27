import os
import asyncio
from datetime import datetime
import scrapers.atacadao_full as atacadao_full
import scrapers.carrefour_full as carrefour_full
import scrapers.boa_full as boa_full
import scrapers.covabra_full as covabra_full
import scrapers.dom_olivio_full as dom_olivio_full
import scrapers.oba_full as oba_full
import scrapers.paodeacucar_full as paodeacucar_full
import scrapers.svicente_full as svicente_full
from utils import setup_logging, write_json_file

logger = setup_logging()
DATA_DIR = "data"

async def processar_mercado_full(modulo, nome_mercado):
    try:
        logger.info(f"🛒 Iniciando COLETA COMPLETA de: {nome_mercado}")
        produtos_brutos = await modulo.extrair_dados()
        
        if not produtos_brutos:
            logger.warning(f"⚠️ {nome_mercado}: Nenhum produto capturado.")
            return nome_mercado, []
        
        logger.info(f"✅ {nome_mercado}: {len(produtos_brutos)} itens totais do catálogo coletados.")
        return nome_mercado, produtos_brutos
    except Exception as e:
        logger.error(f"❌ Erro no scraper full {nome_mercado}: {e}")
        return nome_mercado, []

async def main():
    logger.info(f"🚀 INICIANDO SCRAPERS FULL CATALOG - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    scrapers_full = [
        (atacadao_full, "Atacadão (Full)"),
        (carrefour_full, "Carrefour (Full)"),
        (boa_full, "Boa Supermercados (Full)"),
        (covabra_full, "Covabra (Full)"),
        (dom_olivio_full, "Dom Olívio (Full)"),
        (oba_full, "Oba Hortifruti (Full)"),
        (paodeacucar_full, "Pão de Açúcar (Full)"),
        (svicente_full, "São Vicente (Full)")
    ]

    tarefas = [processar_mercado_full(modulo, nome_mercado) for modulo, nome_mercado in scrapers_full]
    resultados = await asyncio.gather(*tarefas)
    
    todos_itens_crus = []
    resumo_geral = {}

    for nome_mercado, produtos_brutos in resultados:
        if produtos_brutos:
            todos_itens_crus.extend(produtos_brutos)
            resumo_geral[nome_mercado] = len(produtos_brutos)

    if todos_itens_crus:
        arquivo_pendentes = os.path.join(DATA_DIR, "catalogo_base_pendentes.json")
        
        # Cria a pasta data se não existir
        os.makedirs(DATA_DIR, exist_ok=True)
        
        write_json_file(arquivo_pendentes, todos_itens_crus)
        
        logger.info("\n" + "="*50)
        logger.info(f"📦 Sucesso! {len(todos_itens_crus)} itens totais raspados salvos em '{arquivo_pendentes}'.")
        logger.info("👉 Este arquivo agora pode ser processado para alimentar sua base de dados mestre de produtos!")
        logger.info("="*50 + "\n")
    else:
        logger.warning("Nenhum item foi coletado pelos scrapers full nesta execução.")

    logger.info("📊 RESUMO FINAL DA COLETA DE CATÁLOGO:")
    for m, q in resumo_geral.items():
        logger.info(f"  - {m}: {q} produtos coletados")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
