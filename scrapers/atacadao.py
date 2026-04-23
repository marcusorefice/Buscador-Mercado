import os
import json
import warnings
import asyncio
import urllib.parse
from playwright.async_api import async_playwright
from curl_cffi import requests
from datetime import datetime
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file, MAPA_PARA_APP, CATEGORIAS_IGNORADAS, formatar_nome_categoria

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES E QUERY (ESSENCIAL)
# ==========================================
# Definimos a query exatamente como o site pede para garantir que os campos venham preenchidos
GRAPHQL_QUERY = """
query ProductsQuery($term: String, $selectedFacets: [SelectedFacetInput], $first: Int, $after: String, $sort: String) {
  search(term: $term, selectedFacets: $selectedFacets, first: $first, after: $after, sort: $sort) {
    products {
      edges {
        node {
          name
          brand { name }
          image { url }
          offers {
            highPrice
            lowPrice
            offers {
              price
              minQuantity
            }
          }
          breadcrumbList {
            itemListElement {
              name
              position
            }
          }
        }
      }
    }
  }
}
"""

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
URL_BASE = f"{BASE_URL_CONFIG}/api/graphql"

REGIONALIZATION = CONFIG.get("regionalization", {})
SELLER_ID = REGIONALIZATION.get("seller_id", "atacadaobr633")
REGION_ID = REGIONALIZATION.get("region_id", "U1cjYXRhY2FkYW9icjYzMw==")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-772")
CLUSTER_OFERTAS = REGIONALIZATION.get("cluster_ofertas", "312")

PAGINATION = CONFIG.get("pagination", {})
PAGE_SIZE = PAGINATION.get("page_size", 50)
MAX_PAGES = PAGINATION.get("max_pages", 100) # Aumentado de 40 para 100

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome")
PLAYWRIGHT_USER_AGENT = TECHNICAL_DEPS.get("playwright_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

async def buscar_pagina_atacadao(session, offset, sem):
    async with sem:
        payload = {
            "operationName": "ProductsQuery",
            "variables": {
                "first": PAGE_SIZE,
                "after": str(offset),
                "sort": "score_desc",
                "term": "",
                "selectedFacets": [
                    {"key": "productClusterIds", "value": CLUSTER_OFERTAS},
                    {"key": "region-id", "value": REGION_ID},
                    {"key": "channel", "value": f'{{"salesChannel":"1","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'},
                    {"key": "locale", "value": "pt-BR"}
                ]
            },
            "query": GRAPHQL_QUERY
        }

        try:
            # Mudança crucial: Usar POST em vez de GET para GraphQL
            response = await session.post(URL_BASE, json=payload, timeout=20)
            data = response.json()
            return data.get('data', {}).get('search', {}).get('products', {}).get('edges', [])
        except Exception as e:
            logger.error(f"  [{NOME_MERCADO}] Erro no offset {offset}: {e}")
            return []

async def motor_extracao_atacadao():
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO}...")

    lista_final = []
    offsets_alvo = [i * PAGE_SIZE for i in range(MAX_PAGES)] 
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    # Cookie de regionalização é vital para o preço bater com a região
    cookie_regional = urllib.parse.quote(json.dumps({
        "salesChannel": "1",
        "postalCode": CEP_JUNDIAI,
        "seller": SELLER_ID,
        "regionId": REGION_ID
    }))

    sem = asyncio.Semaphore(5) # Reduzi para 5 para evitar bloqueios por concorrência

    async with requests.AsyncSession(impersonate=IMPERSONATE) as session:
        session.cookies.set("regionalization", cookie_regional, domain="www.atacadao.com.br")
        
        tarefas = [buscar_pagina_atacadao(session, off, sem) for off in offsets_alvo]
        resultados = await asyncio.gather(*tarefas)
        
        for bloco in resultados:
            for edge in bloco:
                p = edge.get('node', {})
                try:
                    nome_cru = str(p.get('name', '')).upper().strip()
                    if not nome_cru: continue

                    # --- IMAGEM (Baseado no seu JSON) ---
                    # No JSON: image: [{"url": "..."}]
                    imagens = p.get('image', [])
                    imagem_url = imagens[0].get('url') if imagens else "SEM IMAGEM"

                    # --- TAXONOMIA (Baseado no breadcrumbList do JSON) ---
                    breadcrumb = p.get('breadcrumbList', {}).get('itemListElement', [])
                    # Filtramos apenas os nomes das categorias (excluindo o nome do produto no final)
                    cat_names = [item.get('name') for item in breadcrumb if item.get('position', 0) < len(breadcrumb)]
                    
                    cat_site = cat_names[0].upper() if len(cat_names) > 0 else "OUTROS"
                    subcategoria = formatar_nome_categoria(cat_names[1]) if len(cat_names) > 1 else "N/A"
                    tipo_produto = formatar_nome_categoria(cat_names[2]) if len(cat_names) > 2 else "N/A"

                    if cat_site in CATEGORIAS_IGNORADAS: continue

                    # Usa o contexto completo para uma categorização mais precisa, evitando erros da API de origem.
                    full_context = f"{nome_cru} {cat_site} {subcategoria} {tipo_produto}"
                    categoria = padronizar_categoria(full_context, cat_site)
                    
                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                    # --- PREÇOS ---
                    offers_node = p.get('offers', {})
                    p_varejo = float(offers_node.get('highPrice', 0.0))
                    p_atacado = float(offers_node.get('lowPrice', p_varejo))
                    
                    if p_atacado <= 0: continue

                    # Lógica de condição de atacado
                    condicao = "1 UN"
                    for oferta in offers_node.get('offers', []):
                        if float(oferta.get('price', 0)) == p_atacado and int(oferta.get('minQuantity', 0)) > 1:
                            condicao = f"A PARTIR DE {oferta['minQuantity']} UN"
                            break
                    
                    marca_str = p.get('brand', {}).get('name', 'OUTROS').upper()
                    lista_final.append({
                        "Mercado": NOME_MERCADO, 
                        "Categoria": categoria, 
                        "subcategoria": subcategoria,
                        "tipo_produto": tipo_produto,
                        "Produto": nome_limpo,
                        "Marca": marca_str, 
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
                except Exception as e:
                    continue

    lista_unica = list({v['Produto'] + v['Preço Atacado']: v for v in lista_final}.values())
    logger.info(f"✅ Total de {len(lista_unica)} produtos processados.")
    return lista_unica

async def extrair_dados():
    """Ponto de entrada para o main.py"""
    return await motor_extracao_atacadao()
