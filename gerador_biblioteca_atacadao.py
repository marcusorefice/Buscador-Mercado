import asyncio
import json
import os
import sys
import urllib.parse
import random
import re
from datetime import datetime
from curl_cffi.requests import AsyncSession

# Configuração de diretórios
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils import (
    criar_entrada_biblioteca, setup_logging, write_json_file, read_json_file,
    extrair_medidas_inteligente, formatar_nome_categoria, CATEGORIAS_IGNORADAS,
    normalizar_taxonomia_grabit
)
from scrapers.atacadao import (
    NOME_MERCADO, URL_LEGACY, USER_AGENT, IMPERSONATE, CONCURRENCY
)

logger = setup_logging(log_file=os.path.join('data', 'gerador_biblioteca.log'))
CATEGORIAS_CACHE_FILE = os.path.join('data', 'mapeamento_categorias_atacadao.json')

async def mapear_categorias_atacadao(session: AsyncSession, force_update=False):
    """
    Mapeia a árvore de categorias capturando os IDs numéricos necessários para a API Legada.
    Utiliza um cache local para evitar requisições repetidas.
    """
    # 1. Tenta carregar do cache primeiro
    if not force_update and os.path.exists(CATEGORIAS_CACHE_FILE):
        logger.info(f"🗺️  Mapeamento de categorias carregado do cache '{os.path.basename(CATEGORIAS_CACHE_FILE)}'.")
        cached_data = read_json_file(CATEGORIAS_CACHE_FILE)
        if cached_data:
            # Para forçar a atualização, delete o arquivo ou rode com --force-update
            return cached_data

    logger.info("🗺️  Mapeando árvore de categorias do Atacadão (via API de Catálogo)...")
    URL_TREE = "https://www.atacadao.com.br/api/catalog_system/pub/category/tree/3"
    
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        response = await session.get(URL_TREE, headers=headers, timeout=60)
        response.raise_for_status()
        tree = response.json()

        categorias_identificadas = []
        
        def extrair_recursivo(nodes):
            for node in nodes:
                # Armazenamos o ID e o Nome. Usaremos o ID para a busca fq=C:ID
                categorias_identificadas.append({
                    'id': node['id'], 
                    'name': node.get('name', 'desconhecida').lower()
                })
                if node.get('children'):
                    extrair_recursivo(node['children'])

        extrair_recursivo(tree)
        # Remove duplicatas de IDs
        unique_categories = list({c['id']: c for c in categorias_identificadas}.values())

        # 2. Salva o resultado no cache
        write_json_file(CATEGORIAS_CACHE_FILE, unique_categories)
        logger.info(f"   - Mapeamento salvo em '{os.path.basename(CATEGORIAS_CACHE_FILE)}' para uso futuro.")
            
        logger.info(f"   - Mapeamento concluído. {len(unique_categories)} categorias (IDs) encontradas.")
        return unique_categories

    except Exception as e:
        logger.error(f"   - Falha ao mapear categorias: {e}")
        return []

async def extrair_produtos_legado_por_categoria(session: AsyncSession, category: dict, sem: asyncio.Semaphore, agora: str):
    """
    Extrai produtos usando fq=C:ID, lidando com status 206 e paginação VTEX.
    """
    produtos_da_categoria = []
    cat_id = category['id']
    cat_name = category['name']
    
    offset = 0
    PAGE_SIZE_LEGACY = 49 
    MAX_ITEMS = 2500 # Limite padrão da VTEX por ramificação

    while offset < MAX_ITEMS:
        async with sem:
            start = offset
            end = offset + PAGE_SIZE_LEGACY
            # fq=C:{id} é o filtro correto para a API Legada. sc=1 garante estoque da loja.
            url = f"{URL_LEGACY}?fq=C:{cat_id}&_from={start}&_to={end}"

            try:
                res = await session.get(url, timeout=45)
                
                # Tratamento de Rate Limit (429)
                if res.status_code == 429:
                    logger.warning(f"⚠️ Rate Limit no ID {cat_id}. Aguardando...")
                    await asyncio.sleep(5)
                    continue

                # Status 200 ou 206 são sucessos na VTEX
                if res.status_code not in [200, 206]:
                    break

                bloco = res.json()
                if not bloco:
                    break

                for p in bloco:
                    try:
                        nome_cru = str(p.get('productName', '')).upper().strip()
                        items = p.get('items', [])
                        if not items: continue
                        item = items[0]

                        # Captura de EAN resiliente (campo ean ou referenceId)
                        ean_real = "N/A"
                        if item.get('ean') and str(item['ean']).isdigit():
                            ean_real = str(item['ean']).strip()
                        else:
                            ref_ids = item.get('referenceId', [])
                            for ref in ref_ids:
                                if ref.get('Key') == 'EAN' or str(ref.get('Value', '')).isdigit():
                                    val = str(ref.get('Value', '')).strip()
                                    if len(val) >= 12:
                                        ean_real = val
                                        break

                        offer = item.get('sellers', [{}])[0].get('commertialOffer', {})
                        p_atacado = float(offer.get('Price', 0.0))

                        # Taxonomia básica do site
                        cat_tree = p.get('categories', ["/"])[0].strip('/').split('/')
                        cat_site = cat_tree[0].upper() if cat_tree else "GERAL"
                        
                        if cat_site in CATEGORIAS_IGNORADAS: continue

                        marca = p.get('brand', 'OUTROS').upper()
                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                        produtos_da_categoria.append({
                            "Mercado": NOME_MERCADO, "EAN": ean_real, "Categoria": cat_site,
                            "subcategoria": formatar_nome_categoria(cat_tree[1]) if len(cat_tree) > 1 else "N/A",
                            "tipo_produto": formatar_nome_categoria(cat_tree[2]) if len(cat_tree) > 2 else "N/A",
                            "Produto": nome_limpo, "Marca": marca,
                            "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                            "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                            "Data_Hora": agora, "Link_Imagem": item.get('images', [{}])[0].get('imageUrl', '')
                        })
                    except: continue

                offset += len(bloco)
                if len(bloco) < (PAGE_SIZE_LEGACY + 1): break # Fim das páginas
                await asyncio.sleep(random.uniform(0.1, 0.3))

            except Exception as e:
                logger.error(f"❌ Erro na extração do ID {cat_id}: {e}")
                break

    return produtos_da_categoria

async def motor_extracao_catalogo_completo_atacadao(force_update_categories=False):
    """
    Orquestra a extração de todas as categorias mapeadas.
    """
    logger.info(f"🚀 Iniciando extração guiada por IDs para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # Configura cookie de canal de vendas para Jundiaí/Nacional
        cookie = urllib.parse.quote('{"salesChannel":"1"}')
        session.cookies.set("regionalization", cookie, domain=".atacadao.com.br")
        
        categorias = await mapear_categorias_atacadao(session, force_update=force_update_categories)
        if not categorias: return []

        # Limita a concorrência para não ser banido (CONCURRENCY ideal: 3 a 5)
        sem = asyncio.Semaphore(5) 
        tarefas = [extrair_produtos_legado_por_categoria(session, cat, sem, agora) for cat in categorias]
        
        resultados = await asyncio.gather(*tarefas)
        for r in resultados: lista_final.extend(r)

    # Deduplicação por EAN e Nome
    return list({f"{v['EAN']}_{v['Produto']}": v for v in lista_final if v['EAN'] != "N/A"}.values())

async def gerar_biblioteca_mercado():
    """
    Gera o arquivo biblioteca_atacado.json com os dados normalizados.
    """
    logger.info(f"🚀 Gerando biblioteca Atacadão...")

    try:
        force_update = '--force-update' in sys.argv
        produtos_brutos = await motor_extracao_catalogo_completo_atacadao(force_update_categories=force_update)
        if not produtos_brutos:
            logger.warning("Nenhum produto capturado.")
            return

        logger.info(f"⚙️  Normalizando {len(produtos_brutos)} itens com regras GrabIt...")
        
        biblioteca_final = {}
        for p in produtos_brutos:
            # Aplica suas regras de correção (ex: Sorvete em Congelados)
            cat, sub, tipo = normalizar_taxonomia_grabit(
                p["Produto"], p["Marca"], p["Categoria"], p["subcategoria"], p["tipo_produto"], p["EAN"], {}, NOME_MERCADO
            )
            p["Categoria"], p["subcategoria"], p["tipo_produto"] = cat, sub, tipo
            
            chave, entrada = criar_entrada_biblioteca(p)
            if chave: biblioteca_final[chave] = entrada

        write_json_file("biblioteca_atacado.json", biblioteca_final)
        logger.info(f"🏆 Biblioteca salva com {len(biblioteca_final)} itens.")

    except Exception as e:
        logger.error(f"❌ Erro crítico: {e}", exc_info=True)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(gerar_biblioteca_mercado())