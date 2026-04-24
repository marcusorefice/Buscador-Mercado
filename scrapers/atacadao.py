import os
import json
import warnings
import urllib.parse
import asyncio
from curl_cffi.requests import AsyncSession
import random
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
API_GRAPHQL_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_GRAPHQL_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
SELLER_ID = REGIONALIZATION.get("seller_id", "atacadaobr633")
REGION_ID = REGIONALIZATION.get("region_id", "U1cjYXRhY2FkYW9icjYzMw==")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-772")
CLUSTER_OFERTAS = REGIONALIZATION.get("cluster_ofertas", "312")

PAGINATION = CONFIG.get("pagination", {})
PAGE_SIZE = PAGINATION.get("page_size", 50)
MAX_PAGES = PAGINATION.get("max_pages", 100)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("playwright_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CONCURRENCY = TECHNICAL_DEPS.get("concurrency", 10)


async def motor_extracao_atacadao():
    """Motor de extração principal para o Atacadão, usando paralelismo e offset."""
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO} (Estratégia: GraphQL + Paralelismo)...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    cookie_str = f'{{"salesChannel":"1","postalCode":"{CEP_JUNDIAI}","seller":"{SELLER_ID}"}}'
    
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.atacadao.com.br/catalogo",
        "Origin": "https://www.atacadao.com.br"
    }

    PAGE_SIZE = 50
    # Limita o número de conexões simultâneas para não estourar o firewall (vem do seu spec file)
    sem = asyncio.Semaphore(CONCURRENCY) 

    async def extrair_pagina(session, offset, is_first=False):
        """Função interna para buscar e processar uma única página concorrentemente."""
        async with sem:
            if not is_first:
                # Pequeno micro-delay apenas para descolar as requisições paralelas
                await asyncio.sleep(random.uniform(0.1, 0.6))
                
            variables = {
                "first": PAGE_SIZE, 
                "after": str(offset), 
                "sort": "score_desc", 
                "term": "",
                "selectedFacets": [
                    {"key": "productClusterIds", "value": CLUSTER_OFERTAS},                    
                    {"key": "channel", "value": f'{{"salesChannel":"1","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'},
                    {"key": "locale", "value": "pt-BR"}
                ]
            }
            
            params = {
                "operationName": "ProductsQuery",
                "variables": json.dumps(variables, separators=(',', ':'))
            }
            url_get = f"{URL_BASE}?{urllib.parse.urlencode(params)}"

            try:
                response = await session.get(url_get, timeout=45)
                response.raise_for_status()
                response_json = response.json()

                search_data = (response_json.get('data') or {}).get('search')
                products_data = (search_data or {}).get('products')
                
                if not products_data:
                    return [], 0

                bloco_produtos = products_data.get('edges', [])
                total_items = products_data.get('pageInfo', {}).get('totalCount', 0) if is_first else 0
                
                produtos_extraidos = []
                for edge in bloco_produtos:
                    p = edge.get('node', {})
                    if not p: continue

                    try:
                        nome_cru = str(p.get('name', '')).upper().strip()
                        if not nome_cru: continue

                        ean = str(p.get('gtin', 'N/A')).strip()
                        imagens = p.get('image', [])
                        imagem_url = imagens[0].get('url', "SEM IMAGEM") if imagens else "SEM IMAGEM"

                        cat_tree = p.get('breadcrumbList', {}).get('itemListElement', [])
                        cat_site, subcategoria, tipo_produto = "", "N/A", "N/A"
                        
                        if cat_tree and isinstance(cat_tree, list):
                            if len(cat_tree) > 0: cat_site = cat_tree[0].get('name', '').upper()
                            if len(cat_tree) > 1: subcategoria = formatar_nome_categoria(cat_tree[1].get('name', 'N/A'))
                            if len(cat_tree) > 2: tipo_produto = formatar_nome_categoria(cat_tree[2].get('name', 'N/A'))

                        if cat_site in CATEGORIAS_IGNORADAS: continue

                        full_context = f"{nome_cru} {cat_site}"
                        categoria = MAPA_PARA_APP.get(cat_site, padronizar_categoria(full_context, cat_site))
                        
                        marca_obj = p.get('brand', {})
                        marca_str = marca_obj.get('name', 'OUTROS').upper() if isinstance(marca_obj, dict) else str(marca_obj or 'OUTROS').upper()

                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                        ofertas_container = p.get('offers', {})
                        lista_ofertas = ofertas_container.get('offers', [{}])
                        offer = lista_ofertas[0] if lista_ofertas else {}
                        
                        p_atacado = float(offer.get('price', 0.0))
                        p_varejo = float(offer.get('listPrice', p_atacado))

                        if p_atacado <= 0: continue
                        if p_varejo <= 0 or p_varejo < p_atacado: p_varejo = p_atacado

                        condicao = "OFERTA" if p_atacado < p_varejo else "1 UN"

                        produtos_extraidos.append({
                            "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": categoria,
                            "subcategoria": subcategoria, "tipo_produto": tipo_produto,
                            "Produto": nome_limpo, "Marca": marca_str,
                            "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','), "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                            "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                            "Condição": condicao, "Data_Hora": agora, "Link_Imagem": imagem_url
                        })
                    except Exception as e:
                        continue
                
                return produtos_extraidos, total_items
            except Exception as e:
                logger.error(f"   [{NOME_MERCADO}] Erro ao processar offset {offset}: {e}")
                return [], 0

    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        session.cookies.set("regionalization", urllib.parse.quote(cookie_str), domain=urllib.parse.urlparse(URL_BASE).hostname)
        
        # PASSO 1: Faz a requisição inicial para descobrir o total de itens
        produtos_iniciais, total_items = await extrair_pagina(session, 0, is_first=True)
        lista_final.extend(produtos_iniciais)
        
        if total_items > PAGE_SIZE:
            logger.info(f"   - API informou {total_items} produtos. Disparando tarefas paralelas para o restante do catálogo...")
            
            # PASSO 2: Prepara todos os offsets restantes matematicamente
            offsets = [offset for offset in range(PAGE_SIZE, total_items, PAGE_SIZE)]
            
            # PASSO 3: Executa as requisições simultaneamente (limitadas pelo Semaphore)
            tarefas = [extrair_pagina(session, off) for off in offsets]
            resultados = await asyncio.gather(*tarefas)
            
            for res, _ in resultados:
                lista_final.extend(res)

    logger.info(f"✅ Extração paralela concluída. {len(lista_final)} itens brutos capturados.")
    return list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())

async def extrair_dados():
    """Ponto de entrada para o orquestrador (main.py)."""
    return await motor_extracao_atacadao()