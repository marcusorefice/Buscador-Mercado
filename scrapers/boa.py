import asyncio
import json
import urllib.parse
import os
import re
import warnings
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file, MAPA_PARA_APP, CATEGORIAS_IGNORADAS

# Oculta avisos de depreciação para manter o terminal limpo
warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'boa_spec.json')
CONFIG = read_json_file(SPEC_FILE)

# ==========================================
# CONFIGURAÇÕES DO BOA
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "Boa Supermercados")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.boasupermercados.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
REGION_ID = REGIONALIZATION.get("region_id", "v2.BD821CBD8067F03D236A5416A87F4B3B")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-745")
SALES_CHANNEL = REGIONALIZATION.get("channel", "1")
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "2510")

MAX_PAGES = CONFIG.get("pagination", {}).get("max_pages", 12)

CONCURRENCY = CONFIG.get("technical_dependencies", {}).get("concurrency", {})
try:
    PAGE_SEMAPHORE = int(CONCURRENCY.get("page_semaphore", 5))
except (ValueError, TypeError):
    logger.warning(f"Valor de 'page_semaphore' inválido. Usando valor padrão 5.")
    PAGE_SEMAPHORE = 5
try:
    API_SEMAPHORE = int(CONCURRENCY.get("api_semaphore", 15))
except (ValueError, TypeError):
    logger.warning(f"Valor de 'api_semaphore' inválido. Usando valor padrão 15.")
    API_SEMAPHORE = 15
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")

async def _buscar_preco_calculado(session: AsyncSession, product_id: str, sem_api: asyncio.Semaphore):
    """Consulta a API ClientQuery para pegar o preço já processado pelo servidor"""
    async with sem_api:
        variables = {
            "locator": [
                {"key": "id", "value": str(product_id)},
                {"key": "channel", "value": json.dumps({"salesChannel": "2", "regionId": REGION_ID})},
                {"key": "locale", "value": "pt-BR"}
            ]
        }
        params = {
            "operationName": "ClientProductQuery",
            "operationHash": "47aa22eb750cb2c529e5eeafb921bfeadb67db71",
            "variables": json.dumps(variables, separators=(',', ':'))
        }
        url = f"{URL_BASE}?" + urllib.parse.urlencode(params)
        
        try:
            res = await session.get(url, timeout=10)
            if res.status_code == 200:
                p_data = res.json().get('data', {}).get('product', {})
                offers = p_data.get('offers', {})
                if offers:
                    list_price = float(offers.get('offers', [{}])[0].get('listPrice', 0.0))
                    price = float(offers.get('lowPrice', 0.0))
                    return list_price, price
        except Exception as e:
            logger.error(f"  [{NOME_MERCADO}] Erro ao buscar preço para ID {product_id}: {e}")
            pass
        return 0.0, 0.0

async def _extrair_pagina_completa(session: AsyncSession, pagina: int, sem_pag: asyncio.Semaphore, sem_api: asyncio.Semaphore):
    """Extrai os produtos de uma página da vitrine"""
    async with sem_pag:
        try:
            variables_shelf = {
                "input": {
                    "activeSalesChannel": SALES_CHANNEL, 
                    "postalCode": CEP_JUNDIAI, 
                    "page": pagina,
                    "sort": "score_desc", 
                    "term": "", 
                    "selectedFacets": [{"key": "productclusterids", "value": CLUSTER_ID}]
                }
            }
            params_shelf = {
                "operationName": "GetProductsQuery",
                "operationHash": "ae50c5a735b1464f0ba48be4f2b32f7289ce6284",
                "variables": json.dumps(variables_shelf, separators=(',', ':'))
            }
            url_shelf = f"{URL_BASE}?" + urllib.parse.urlencode(params_shelf)
            
            res = await session.get(url_shelf, timeout=15)
            edges = res.json().get('data', {}).get('getProducts', {}).get('data', {}).get('products', {}).get('edges', [])
            if not edges: return []

            tarefas_precos = [_buscar_preco_calculado(session, e['node']['id'], sem_api) for e in edges]
            precos_finais = await asyncio.gather(*tarefas_precos)

            lista_final = []
            agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            for e, (v_varejo, v_atacado) in zip(edges, precos_finais):
                p = e['node']
                nome_cru = p['name'].upper().strip()
                p_v = v_varejo if v_varejo > 0 else float(p.get('offers', {}).get('highPrice', 0.0))
                p_a = v_atacado if v_atacado > 0 else float(p.get('offers', {}).get('lowPrice', p_v))
                
                if p_v <= 0 and p_a <= 0: continue
                if p_v <= 0: p_v = p_a
                if p_v < p_a: p_v = p_a

                condicao = "1 UN"
                selos = [d['name'].upper() for d in p.get('clusterHighlights', [])]
                selo_cartonista = any('CARTONISTA' in s or 'OFF' in s for s in selos)

                if p_a < p_v:
                    condicao = "EXCLUSIVO CARTÃO BOA" if selo_cartonista else "CLUBE +AMIGO CPF"
                elif selo_cartonista:
                    for s in selos:
                        match = re.search(r'(\d+)', s)
                        if match:
                            p_a = p_v * (1 - (int(match.group(1)) / 100.0))
                            condicao = "EXCLUSIVO CARTÃO BOA"
                            break

                # --- NOVA LÓGICA DE TAXONOMIA ---
                cat_tree = p.get('categoryTree', [])
                cat_site = ""
                subcategoria = "N/A"
                tipo_produto = "N/A"

                if isinstance(cat_tree, list) and cat_tree:
                    if len(cat_tree) > 0: cat_site = cat_tree[0].get('name', '').upper()
                    if len(cat_tree) > 1: subcategoria = cat_tree[1].get('name', 'N/A').upper()
                    if len(cat_tree) > 2: tipo_produto = cat_tree[2].get('name', 'N/A').upper()
                
                if cat_site in CATEGORIAS_IGNORADAS:
                    continue

                categoria = MAPA_PARA_APP.get(cat_site, padronizar_categoria(nome_cru, cat_site))

                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                
                # Lógica de extração de imagem mais robusta
                img = 'SEM IMAGEM'
                image_data = p.get('image')
                if isinstance(image_data, list) and image_data:
                    first_image = image_data[0]
                    if isinstance(first_image, dict):
                        img = first_image.get('url', 'SEM IMAGEM')
                    elif isinstance(first_image, str):
                        img = first_image
                if img.startswith("//"): img = "https:" + img

                # Lógica de extração de marca mais robusta
                marca_data = p.get('brand')
                marca = marca_data.get('name', 'OUTROS') if isinstance(marca_data, dict) else str(marca_data or 'OUTROS')

                lista_final.append({
                    "Mercado": NOME_MERCADO, "Categoria": categoria,
                    "subcategoria": subcategoria, "tipo_produto": tipo_produto,
                    "Produto": nome_limpo, "Marca": marca.upper(),
                    "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','), "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                    "Qtd_Valor": qv, "Medida": med, "Unidade": "UN", "Condição": condicao,
                    "Validade": "VER NO SITE", "Data_Hora": agora, "Link_Imagem": img
                })
            return lista_final
        except Exception as e:
            logger.error(f"  [{NOME_MERCADO}] Erro ao extrair página {pagina}: {e}")
            return []

async def motor_extracao_boa():
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO} Jundiaí...")
    sem_pag, sem_api = asyncio.Semaphore(PAGE_SEMAPHORE), asyncio.Semaphore(API_SEMAPHORE)
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        tarefas = [_extrair_pagina_completa(session, p, sem_pag, sem_api) for p in range(1, MAX_PAGES + 1)]
        resultados = await asyncio.gather(*tarefas)
        lista = [item for sublist in resultados for item in sublist]
    lista_unica = list({v['Produto']: v for v in lista}.values())
    logger.info(f"✅ Finalizado! {len(lista_unica)} produtos do {NOME_MERCADO} capturados.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_boa()