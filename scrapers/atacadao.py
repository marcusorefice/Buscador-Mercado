import os
import json
import warnings
import asyncio
import urllib.parse
from curl_cffi import requests
from datetime import datetime
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file, MAPA_PARA_APP, CATEGORIAS_IGNORADAS, formatar_nome_categoria

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'atacadao_spec.json')
CONFIG = read_json_file(SPEC_FILE)

# ==========================================
# CONFIGURAÇÕES DO ATACADÃO
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "Atacadão")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.atacadao.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
SELLER_ID = REGIONALIZATION.get("seller_id", "atacadaobr633")
REGION_ID = REGIONALIZATION.get("region_id", "U1cjYXRhY2FkYW9icjYzMw==")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-772")
CLUSTER_OFERTAS = REGIONALIZATION.get("cluster_ofertas", "312")

PAGINATION = CONFIG.get("pagination", {})
PAGE_SIZE = PAGINATION.get("page_size", 50)
MAX_PAGES = PAGINATION.get("max_pages", 40)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome")

async def buscar_pagina_atacadao(session, offset, sem):
    async with sem:
        variables = {
            "first": PAGE_SIZE, "after": str(offset), "sort": "score_desc", "term": "",
            "selectedFacets": [
                {"key": "productClusterIds", "value": CLUSTER_OFERTAS},
                {"key": "region-id", "value": REGION_ID},
                {"key": "channel", "value": f'{{"salesChannel":"1","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'},
                {"key": "locale", "value": "pt-BR"}
            ]
        }
        variables_str = urllib.parse.quote(json.dumps(variables, separators=(',', ':')))
        url = f"{URL_BASE}?operationName=ProductsQuery&variables={variables_str}"
        try:
            response = await session.get(url, timeout=15)
            return response.json().get('data', {}).get('search', {}).get('products', {}).get('edges', [])
        except Exception as e:
            logger.error(f"  [{NOME_MERCADO}] Erro na página com offset {offset}: {e}")
            return []

async def motor_extracao_atacadao():
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO} Jundiaí...")
    lista_final = []
    offsets_alvo = [i * PAGE_SIZE for i in range(MAX_PAGES)] 
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    cookie_str = f'{{"salesChannel":"1","postalCode":"{CEP_JUNDIAI}","seller":"{SELLER_ID}"}}'
    sem = asyncio.Semaphore(10) # Limita a 10 requisições simultâneas

    async with requests.AsyncSession(impersonate=IMPERSONATE) as session:
        session.cookies.set("regionalization", cookie_str, domain="www.atacadao.com.br")
        tarefas = [buscar_pagina_atacadao(session, off, sem) for off in offsets_alvo]
        resultados = await asyncio.gather(*tarefas)
        
        for bloco in resultados:
            for edge in bloco:
                p = edge.get('node', {})
                try:
                    nome_cru = str(p.get('name', '')).upper().strip()
                    if not nome_cru: continue

                    # --- CAPTURA DE IMAGEM (SCANNER EM PROFUNDIDADE) ---
                    imagem_url = ""
                    items_list = p.get('items', [])
                    if items_list and isinstance(items_list, list) and len(items_list) > 0:
                        images = items_list[0].get('images', [])
                        if images and isinstance(images, list) and len(images) > 0:
                            imagem_url = images[0].get('imageUrl') or images[0].get('url')
                    
                    if not imagem_url:
                        img_node = p.get('image')
                        if isinstance(img_node, list) and len(img_node) > 0:
                            imagem_url = img_node[0].get('url')
                        elif isinstance(img_node, str):
                            imagem_url = img_node

                    imagem_url = imagem_url if imagem_url else "SEM IMAGEM"

                    # --- LÓGICA DE TAXONOMIA ---
                    cat_tree = p.get('categoryTree', [])
                    cat_site = ""
                    subcategoria = "N/A"
                    tipo_produto = "N/A"

                    if isinstance(cat_tree, list) and cat_tree:
                        if len(cat_tree) > 0: cat_site = cat_tree[0].get('name', '').upper()
                        if len(cat_tree) > 1: subcategoria = formatar_nome_categoria(cat_tree[1].get('name', 'N/A'))
                        if len(cat_tree) > 2: tipo_produto = formatar_nome_categoria(cat_tree[2].get('name', 'N/A'))

                    if cat_site in CATEGORIAS_IGNORADAS:
                        continue # Pula para o próximo produto

                    categoria = MAPA_PARA_APP.get(cat_site, padronizar_categoria(nome_cru, cat_site))

                    marca_str = p.get('brand', {}).get('name', 'OUTROS') if isinstance(p.get('brand'), dict) else str(p.get('brand', 'OUTROS'))
                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                    # --- LÓGICA DE PREÇO ---
                    offers_node = p.get('offers', {}) or {}
                    p_varejo = float(offers_node.get('highPrice', 0.0))
                    p_atacado = float(offers_node.get('lowPrice', p_varejo))
                    
                    if p_atacado <= 0: continue
                    if p_varejo == 0: p_varejo = p_atacado

                    condicao = "1 UN"
                    offers_list = offers_node.get('offers', [])
                    for oferta in offers_list:
                        if float(oferta.get('price', 0)) == p_atacado and int(oferta.get('minQuantity', 0)) > 1:
                            condicao = f"A PARTIR DE {oferta['minQuantity']} UN"
                            break
                    
                    lista_final.append({
                        "Mercado": NOME_MERCADO, 
                        "Categoria": categoria, 
                        "subcategoria": subcategoria,
                        "tipo_produto": tipo_produto,
                        "Produto": nome_limpo,
                        "Marca": marca_str.upper(), 
                        "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, 
                        "Medida": med, 
                        "Unidade": "UN", 
                        "Condição": condicao,
                        "Validade": "VER NO SITE", 
                        "Data_Hora": agora, 
                        "Link_Imagem": imagem_url
                    })
                except: continue

    # Deduplicação por nome do produto
    lista_unica = list({v['Produto']: v for v in lista_final}.values())
    logger.info(f"✅ Total de {len(lista_unica)} produtos processados no {NOME_MERCADO}.")
    return lista_unica

async def extrair_dados():
    """Ponto de entrada para o main.py"""
    return await motor_extracao_atacadao()
