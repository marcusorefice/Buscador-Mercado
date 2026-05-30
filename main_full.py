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
from utils import setup_logging, write_json_file, read_json_file

logger = setup_logging()
DATA_DIR = "data"
ARQUIVO_CHECKPOINT = os.path.join(DATA_DIR, "checkpoint_full.json")
ARQUIVO_FILA_IA = os.path.join(DATA_DIR, "pendentes_ia.json")

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
    
    # Cria a pasta data se não existir
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # 1. Carrega o checkpoint (Apenas metadados, sem os produtos para economizar RAM/Disco)
    checkpoint = read_json_file(ARQUIVO_CHECKPOINT, default_value={"mercados_concluidos": [], "totais": {}})
    mercados_concluidos = set(checkpoint.get("mercados_concluidos", []))
    resumo_geral = checkpoint.get("totais", {})
    
    if mercados_concluidos:
        logger.info(f"🔄 Retomando extração. Mercados já seguros no disco: {', '.join(mercados_concluidos)}")

    scrapers_full = [
        (atacadao_full, "Atacadão (Full)"),
        (carrefour_full, "Carrefour (Full)"),
        (boa_full, "Boa Supermercados (Full)"),
        (covabra_full, "Covabra (Full)"),
        (dom_olivio_full, "Dom Olívio (Full)"),
        (oba_full, "Oba Hortifruti (Full)"),
        # (paodeacucar_full, "Pão de Açúcar (Full)"),
        # (svicente_full, "São Vicente (Full)")
    ]

    # 2. Processa mercado por mercado
    for modulo, nome_mercado_label in scrapers_full:
        mercado_base = nome_mercado_label.replace(" (Full)", "").strip()
        
        if mercado_base in mercados_concluidos:
            logger.info(f"⏭️ Pulando {nome_mercado_label}: Já coletado com sucesso nesta sessão.")
            continue
            
        _, produtos_brutos = await processar_mercado_full(modulo, nome_mercado_label)
        
        if produtos_brutos:
            # Marca a origem para que o passo 5 saiba que é seguro fazer a limpeza profunda do banco
            for p in produtos_brutos:
                p["Scraper_Origem"] = "FULL"
                
            resumo_geral[nome_mercado_label] = len(produtos_brutos)
            
            # 3. Atualiza o checkpoint leve
            mercados_concluidos.add(mercado_base)
            checkpoint["mercados_concluidos"] = list(mercados_concluidos)
            checkpoint["totais"] = resumo_geral
            write_json_file(ARQUIVO_CHECKPOINT, checkpoint)
            
            # 4. Joga os dados desse mercado direto na fila do passo 4 (IA / DB)!
            fila_ia = read_json_file(ARQUIVO_FILA_IA, default_value=[])
            fila_ia.extend(produtos_brutos)
            write_json_file(ARQUIVO_FILA_IA, fila_ia)
            
            logger.info(f"💾 Progresso salvo! {len(produtos_brutos)} itens do {mercado_base} enviados para o 'pendentes_ia.json'.")

    logger.info("\n" + "="*50)
    logger.info("📦 Processo de extração finalizado.")
    logger.info("👉 PRÓXIMO PASSO: Execute 'python 4_resolver_pendentes.py' e depois o passo 5 para enviar ao Banco de Dados!")
    logger.info("="*50 + "\n")

    logger.info("📊 RESUMO FINAL DA COLETA DE CATÁLOGO:")
    for m, q in resumo_geral.items():
        logger.info(f"  - {m}: {q} produtos coletados")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
