import asyncio
import json
import urllib.parse
import os
import re
import warnings
from datetime import datetime
import curl_cffi
from curl_cffi.requests import AsyncSession
from utils import (
    aplicar_taxonomia_inteligente,
    extrair_medidas_inteligente, 
    setup_logging, 
    read_json_file, 
    MAPA_PARA_APP, 
    CATEGORIAS_IGNORADAS,
    formatar_nome_categoria
) 

# Silencia avisos para um log mais limpo
warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES TÉCNICAS (NÃO ALTERAR)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'boa_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Boa Supermercados")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.boasupermercados.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
REGION_ID = REGIONALIZATION.get("region_id", "v2.BD821CBD8067F03D236A5416A87F4B3B")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-745")
SALES_CHANNEL_SHELF = REGIONALIZATION.get("channel", "1")
SALES_CHANNEL_PRICE = REGIONALIZATION.get("price_channel", "2") # Canal 2 é essencial para Clube +Amigo em Jundiaí
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "2510")

# Limite de páginas fixo para garantir estabilidade, já que a API não informa o total de forma confiável.
MAX_PAGES = 25

# Hashes da API GraphQL (devem estar no spec file para manutenção)
API_HASHES = CONFIG.get("api_hashes", {})
GET_PRODUCTS_HASH = API_HASHES.get("get_products", "ae50c5a735b1464f0ba48be4f2b32f7289ce6284")
CLIENT_PRODUCT_HASH = API_HASHES.get("client_product", "47aa22eb750cb2c529e5eeafb921bfeadb67db71")

# Semáforos preventivos para evitar Bloqueio/404
PAGE_SEMAPHORE = asyncio.Semaphore(2)
API_SEMAPHORE = asyncio.Semaphore(5)
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")

async def _buscar_preco_calculado(session: AsyncSession, product_id: str, retries=3, delay=1.0) -> tuple[float, float, str]:
    """Consulta o preço real e o EAN/GTIN com um sistema de retentativas para erros de servidor."""
    async with API_SEMAPHORE:
        variables = {
            "locator": [
                {"key": "id", "value": str(product_id)},
                {"key": "channel", "value": json.dumps({"salesChannel": SALES_CHANNEL_PRICE, "regionId": REGION_ID}, separators=(',',':'))},
                {"key": "locale", "value": "pt-BR"}
            ]
        }
        params = {
            "operationName": "ClientProductQuery",
            "operationHash": CLIENT_PRODUCT_HASH,
            "variables": json.dumps(variables, separators=(',', ':'))
        }
        url = f"{URL_BASE}?" + urllib.parse.urlencode(params)
        
        for tentativa in range(retries):
            try:
                res = await session.get(url, timeout=10)
                res.raise_for_status() # Lança exceção para status 4xx/5xx
                data = res.json()
                if not isinstance(data, dict):
                    logger.warning(f"Resposta inesperada (não é um dict) para o produto ID {product_id}.")
                    return 0.0, 0.0, 'N/A'
                
                p_data = data.get('data', {}).get('product', {})
                
                # Extração do GTIN/EAN, que só está disponível na chamada detalhada.
                ean = str(p_data.get('gtin', '')).strip()
                if not ean or ean == '0':
                    ean = str(p_data.get('ean', 'N/A')).strip()
                if not ean or ean == '0':
                    ean = 'N/A'

                offers = p_data.get('offers', {})
                if offers:
                    list_price = float(offers.get('offers', [{}])[0].get('listPrice', 0.0))
                    price = float(offers.get('lowPrice', 0.0))
                    return list_price, price, ean
                
                return 0.0, 0.0, ean # Retorna o EAN mesmo se não houver oferta

            except (asyncio.TimeoutError, curl_cffi.requests.errors.RequestsError) as e:
                if tentativa < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Erro final ao buscar preço para ID {product_id} após {retries} tentativas: {e}")
            except Exception as e:
                logger.error(f"Erro inesperado ao buscar preço para ID {product_id}: {e}", exc_info=True)
                break # Sai do loop de retentativas para erros não relacionados à rede/HTTP

        return 0.0, 0.0, 'N/A'

async def _processar_edges(session: AsyncSession, edges: list, pagina_num: int):
    """Processa uma lista de 'edges' da API, busca preços e retorna produtos formatados."""
    if not edges:
        return []
    
    try:
        # Busca preços detalhados para todos os itens da página
        tarefas_precos = [_buscar_preco_calculado(session, e['node']['id']) for e in edges]
        precos_finais = await asyncio.gather(*tarefas_precos)

        lista_final = []
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        def get_last_path_part(path_str: str) -> str:
            """Extrai a última parte de um caminho URL (ex: /A/B/ -> B)"""
            if not isinstance(path_str, str): return ""
            parts = [part for part in path_str.split('/') if part]
            return parts[-1] if parts else ""

        for edge, (v_varejo, v_atacado, ean_detalhado) in zip(edges, precos_finais):
            try:
                p = edge['node']
                # Prioriza o EAN/GTIN da chamada detalhada, pois é mais confiável.
                ean = ean_detalhado if ean_detalhado not in ['N/A', ''] else str(p.get('ean', 'N/A')).strip()
                nome_cru = p['name'].upper().strip()
                
                # Definição de Preços (Fallback para a vitrine se o detalhado falhar)
                p_v = v_varejo if v_varejo > 0 else float(p.get('offers', {}).get('highPrice', 0.0))
                p_a = v_atacado if v_atacado > 0 else float(p.get('offers', {}).get('lowPrice', p_v))
                
                if p_v <= 0 and p_a <= 0: continue
                if p_v <= 0: p_v = p_a
                if p_a > 0 and p_v < p_a: p_v = p_a # Garante que varejo não seja menor que atacado

                # Lógica de Condição Especial (Jundiaí)
                condicao = "1 UN"
                selos = [d['name'].upper() for d in p.get('clusterHighlights', [])]
                selo_cartonista = any('CARTONISTA' in s or 'OFF' in s for s in selos)
                if p_a < p_v:
                    condicao = "EXCLUSIVO CARTÃO BOA" if selo_cartonista else "CLUBE +AMIGO CPF"

                # --- TRATAMENTO DE CATEGORIAS (HIERARQUIA) --- #
                # O 'categoryTree' para o Boa é uma lista de strings de caminho (ex: '/BEBIDAS/').
                cat_tree = p.get('categoryTree', [])
                categorias_extraidas = [get_last_path_part(c).upper() for c in cat_tree]

                # LÓGICA DE CATEGORIA: Hierarquia direta a pedido do usuário (Nível 1 -> Categoria, Nível 2 -> Sub, etc.)
                cat_site_cru = categorias_extraidas[0] if categorias_extraidas and categorias_extraidas[0] else "OUTROS"
                subcategoria_cru = formatar_nome_categoria(categorias_extraidas[1]) if len(categorias_extraidas) > 1 else "N/A"
                tipo_prod_cru = formatar_nome_categoria(categorias_extraidas[2]) if len(categorias_extraidas) > 2 else "N/A"
                
                if cat_site_cru in CATEGORIAS_IGNORADAS: continue
                
                cat_site_mapeada = MAPA_PARA_APP.get(cat_site_cru, formatar_nome_categoria(cat_site_cru))
                categoria, subcategoria, tipo_produto = aplicar_taxonomia_inteligente(nome_cru, cat_site_mapeada, subcategoria_cru, tipo_prod_cru)

                # Medidas e Imagem #
                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                img = p.get('image', [{}])[0].get('url', 'SEM IMAGEM')
                if img.startswith("//"): img = "https:" + img

                lista_final.append({
                    "Mercado": NOME_MERCADO,
                    "EAN": ean,
                    "Categoria": categoria,
                    "subcategoria": subcategoria,
                    "tipo_produto": tipo_produto,
                    "Produto": nome_limpo,
                    "Marca": p.get('brand', {}).get('name', 'OUTROS').upper(),
                    "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                    "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                    "Qtd_Valor": qv, "Medida": med, "Unidade": "UN", "Condição": condicao, "Data_Hora": agora, "Link_Imagem": img
                })
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Erro ao processar um produto na página {pagina_num}: {e}. Produto: {p.get('name', 'N/A')}")
                continue # Continua para o próximo produto na página

        return lista_final
    except Exception as e:
        logger.error(f"Erro inesperado no processamento dos produtos da página {pagina_num}: {e}", exc_info=True)
        return []

async def _extrair_pagina_completa(session: AsyncSession, pagina: int):
    """Extrai vitrine e preços de uma página específica"""
    async with PAGE_SEMAPHORE:
        try:
            variables_shelf = {
                "input": {
                    "activeSalesChannel": SALES_CHANNEL_SHELF, 
                    "postalCode": CEP_JUNDIAI, 
                    "page": pagina,
                    "sort": "score_desc", 
                    "term": "", 
                    "selectedFacets": [{"key": "productclusterids", "value": CLUSTER_ID}]
                }
            }
            params_shelf = {
                "operationName": "GetProductsQuery",
                "operationHash": GET_PRODUCTS_HASH,
                "variables": json.dumps(variables_shelf, separators=(',', ':'))
            }
            url_shelf = f"{URL_BASE}?" + urllib.parse.urlencode(params_shelf)
            
            res = await session.get(url_shelf, timeout=15)
            res.raise_for_status()
            
            res_json = res.json()
            if not isinstance(res_json, dict):
                logger.warning(f"Resposta da vitrine (página {pagina}) não é um dict.")
                return []
            
            edges = res_json.get('data', {}).get('getProducts', {}).get('data', {}).get('products', {}).get('edges', [])
            if not edges:
                logger.info(f"Página {pagina} do {NOME_MERCADO} não retornou produtos. Fim da lista.")
                return []

            return await _processar_edges(session, edges, pagina)
        except (asyncio.TimeoutError, json.JSONDecodeError, curl_cffi.requests.errors.RequestsError) as e:
            logger.error(f"Erro ao extrair página completa {pagina} do {NOME_MERCADO}: {e}")
            return []
        except Exception as e:
            logger.error(f"Erro inesperado ao extrair página completa {pagina} do {NOME_MERCADO}: {e}", exc_info=True)
            return []

async def motor_extracao_boa():
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO} Jundiaí (Páginas Fixas: {MAX_PAGES})...")
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # Processa todas as páginas respeitando o semáforo de 2 em 2
        tarefas = [_extrair_pagina_completa(session, p) for p in range(1, MAX_PAGES + 1)]
        resultados = await asyncio.gather(*tarefas)
        
        lista_achatada = [item for sublist in resultados for item in sublist]
    
    # Deduplicação Final
    if not lista_achatada:
        logger.warning(f"Nenhum produto foi capturado para o {NOME_MERCADO}.")
        return []
        
    lista_unica = list({f"{v['Produto']}_{v['Marca']}": v for v in lista_achatada}.values())
    logger.info(f"✅ Finalizado! {len(lista_unica)} produtos capturados no Boa Jundiaí.")
    return lista_unica

async def extrair_dados():
    """Interface para o Orquestrador Main"""
    return await motor_extracao_boa()
