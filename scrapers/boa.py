import asyncio
import json
import urllib.parse
import os
import re
import warnings
from datetime import datetime
import curl_cffi
from curl_cffi.requests import AsyncSession
from utils import parse_preco, setup_logging, read_json_file

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
REGION_ID = REGIONALIZATION.get("region_id", "v2.EBEC2773AEB7AB10BA5DC9345C78B236")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-745")
SALES_CHANNEL_SHELF = REGIONALIZATION.get("channel", "1")
SALES_CHANNEL_PRICE = REGIONALIZATION.get("price_channel", "2") # Canal 2 é essencial para Clube +Amigo em Jundiaí
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "2510")

# Páginas por varredura na estratégia dupla
MAX_PAGES = 25

# Hashes da API GraphQL (devem estar no spec file para manutenção)
API_HASHES = CONFIG.get("api_hashes", {})
GET_PRODUCTS_HASH = API_HASHES.get("get_products", "ae50c5a735b1464f0ba48be4f2b32f7289ce6284")
CLIENT_PRODUCT_HASH = API_HASHES.get("client_product", "47aa22eb750cb2c529e5eeafb921bfeadb67db71")

# Semáforos preventivos para evitar Bloqueio/404
PAGE_SEMAPHORE = asyncio.Semaphore(4)
API_SEMAPHORE = asyncio.Semaphore(10)
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")

async def _buscar_preco_calculado(session: AsyncSession, product_id: str, retries=3, delay=1.0) -> tuple[float, float, str]:
    """Consulta o preço real e o EAN/GTIN com um sistema de retentativas para erros de servidor."""
    async with API_SEMAPHORE:
        variables = {
            "locator": [
                {"key": "id", "value": str(product_id)},
                {"key": "channel", "value": json.dumps({"salesChannel": SALES_CHANNEL_PRICE, "regionId": ""}, separators=(',',':'))},
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
                if res.status_code >= 500:
                    return 0.0, 0.0, 'N/A'
                res.raise_for_status() # Lança exceção para status 4xx
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

                offers = p_data.get('offers') or {}
                if offers:
                    offer_list = offers.get('offers') or []
                    first_offer = offer_list[0] if offer_list else {}
                    list_price = float(first_offer.get('listPrice') or 0.0)
                    price = float(offers.get('lowPrice') or 0.0)
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
        tarefas_precos = [_buscar_preco_calculado(session, e['node']['id']) for e in edges if e.get('node')]
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
                
                ean = ean_detalhado if ean_detalhado not in ['N/A', '', 'None'] else str(p.get('gtin', '')).strip()
                if not ean or ean in ['0', 'None', 'N/A']:
                    ean = str(p.get('ean', 'N/A')).strip()
                if not ean or ean == 'None':
                    ean = 'N/A'
                    
                nome_cru = p['name'].upper().strip()
                
                custom_offers = p.get('customOffers') or {}
                offers_data = p.get('offers') or {}
                
                # Pegamos o p_v preferencialmente da vitrine (customOffers/offers) pois lá ele sempre respeita a fração (ex: 500g).
                # O v_varejo retornado da API detalhada costuma vir como 1KG, o que causava a duplicação na hora de dividir.
                p_v = float(custom_offers.get('listPriceCustom') or offers_data.get('highPrice') or 0.0)
                if p_v <= 0: 
                    p_v = v_varejo
                    
                p_a = v_atacado if v_atacado > 0 else float(custom_offers.get('spotPriceCustom') or offers_data.get('lowPrice') or p_v or 0.0)

                # Produtos a granel (ex: Alho kg, Kiwi kg) têm o preço retornado para a fração (ex: 100g ou 500g)
                # O campo unitMultiplier indica essa fração. 
                # Precisamos dividir o preço retornado pela fração para encontrar o preço por KG.
                unit_multiplier = float(p.get('unitMultiplier') or 1.0)
                if unit_multiplier > 0 and unit_multiplier < 1.0:
                    if p_v == v_varejo and p_v >= (p_a / unit_multiplier) * 0.9:
                        pass # v_varejo já é 1KG
                    else:
                        p_v = p_v / unit_multiplier
                        
                    p_a = p_a / unit_multiplier

                if p_v <= 0 and p_a <= 0: continue
                if p_v <= 0: p_v = p_a
                if p_a > 0 and p_v < p_a: p_v = p_a # Garante que varejo não seja menor que atacado

                condicao = "1 UN"
                tem_desconto_custom = custom_offers.get('hasDiscount')
                
                if p_a < p_v or tem_desconto_custom:
                    condicao = "CLUBE +AMIGO (CPF)"

                # --- TRATAMENTO DE CATEGORIAS (HIERARQUIA) --- #
                cat_tree = p.get('categoryTree', [])
                categorias_extraidas = [get_last_path_part(c).upper() for c in cat_tree]

                cat_site_cru = categorias_extraidas[0] if categorias_extraidas and categorias_extraidas[0] else "OUTROS"
                subcategoria_cru = categorias_extraidas[1] if len(categorias_extraidas) > 1 else "N/A"
                tipo_prod_cru = categorias_extraidas[2] if len(categorias_extraidas) > 2 else "N/A"
                
                
                categoria = cat_site_cru
                subcategoria = subcategoria_cru
                tipo_produto = tipo_prod_cru

                # --- LÓGICA DE MEDIDAS (Baseada no FastStore/VTEX) ---
                nome_limpo, qv, med = nome_cru, "1", "UN"

                unidade_venda = "UN"
                measurement_unit = str(p.get('measurementUnit', '')).lower()
                
                if measurement_unit == 'kg':
                    unidade_venda = "KG"
                    if qv == "1" and med == "UN":
                        qv, med = "1", "KG"
                        
                if nome_cru.endswith(" KG"):
                    unidade_venda = "KG"
                    if qv == "1" and med == "UN":
                        qv, med = "1", "KG"
                        
                nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()

                # Imagem #
                img = p.get('image', [{}])[0].get('url', 'SEM IMAGEM')
                if img.startswith("//"): img = "https:" + img
                
                link_pdp_rel = p.get('slug') or p.get('linkText') or p.get('url') or ''
                if link_pdp_rel:
                    if link_pdp_rel.startswith('http'):
                        link_pdp = link_pdp_rel
                    elif link_pdp_rel.startswith('/'):
                        link_pdp = f"https://www.boasupermercados.com.br{link_pdp_rel}"
                    else:
                        link_pdp = f"https://www.boasupermercados.com.br/{link_pdp_rel}/p"
                else:
                    link_pdp = ""

                lista_final.append({
                    "Mercado": NOME_MERCADO,
                    "EAN": ean,
                    "Categoria": categoria,
                    "subcategoria": subcategoria,
                    "tipo_produto": tipo_produto,
                    "Produto": nome_limpo,
                    "Marca": p.get('brand', {}).get('name', 'OUTROS').upper(),
                    "Preço Varejo": round(p_v, 2),
                    "Preço Atacado": round(p_a, 2),
                    "Qtd_Valor": qv, "Medida": med, "Unidade": unidade_venda, "Condição": condicao, "Data_Hora": agora, "Link_Imagem": img,
                    "Link_PDP": link_pdp
                })
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Erro ao processar um produto na página {pagina_num}: {e}. Produto: {p.get('name', 'N/A')}")
                continue # Continua para o próximo produto na página

        return lista_final
    except Exception as e:
        logger.error(f"Erro inesperado no processamento dos produtos da página {pagina_num}: {e}", exc_info=True)
        return []

async def _extrair_pagina_completa(session: AsyncSession, pagina: int, use_cluster: bool = True):
    """Extrai vitrine e preços de uma página específica"""
    async with PAGE_SEMAPHORE:
        try:
            facets = [{"key": "productClusterIds", "value": CLUSTER_ID}] if use_cluster else []
            
            sort_order = "score_desc" if use_cluster else "discount_desc"

            variables_shelf = {
                "input": {
                    "activeSalesChannel": SALES_CHANNEL_SHELF, 
                    "postalCode": CEP_JUNDIAI, 
                    "page": pagina,
                    "sort": sort_order, 
                    "term": "", 
                    "selectedFacets": facets,
                    "hasChangeOrder": False, 
                    "hasClubWithRegion": True, 
                    "cmsPostalCode": CEP_JUNDIAI, 
                    "clubSc": int(SALES_CHANNEL_PRICE),
                    "regionId": REGION_ID
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
            
            # Extração segura para evitar o erro 'NoneType' se a página exceder o limite da API
            try:
                edges = res_json['data']['getProducts']['data']['products']['edges']
            except (KeyError, TypeError):
                edges = []
                
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
    logger.info(f"🚀 Iniciando extração DUPLA para {NOME_MERCADO} Jundiaí (Cluster + Maiores Descontos)...")
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # Busca 1: Cluster oficial (Garante as ofertas principais)
        tarefas_cluster = [_extrair_pagina_completa(session, p, use_cluster=True) for p in range(0, MAX_PAGES)]
        
        # Busca 2: Varredura de maiores descontos no site todo (Pega os itens ocultos da VTEX)
        tarefas_desconto = [_extrair_pagina_completa(session, p, use_cluster=False) for p in range(0, MAX_PAGES + 4)]
        
        resultados = await asyncio.gather(*(tarefas_cluster + tarefas_desconto))
        
        lista_achatada = [item for sublist in resultados for item in sublist]
    
    # Deduplicação Final
    if not lista_achatada:
        logger.warning(f"Nenhum produto foi capturado para o {NOME_MERCADO}.")
        return []
        
    lista_unica_dict = {}
    for v in lista_achatada:
        ean = str(v.get('EAN', 'N/A')).strip()
        chave = ean if (ean and ean != 'N/A') else f"{v['Produto']}_{v['Marca']}"
        
        # Se o item já existir de outra busca, mantém o que tiver o menor preço de atacado
        if chave in lista_unica_dict:
            preco_atual = parse_preco(lista_unica_dict[chave]['Preço Atacado'])
            preco_novo = parse_preco(v['Preço Atacado'])
            if preco_novo < preco_atual:
                lista_unica_dict[chave] = v
        else:
            lista_unica_dict[chave] = v
        
    lista_unica = list(lista_unica_dict.values())
    logger.info(f"✅ Finalizado! {len(lista_unica)} produtos capturados no Boa Jundiaí.")
    return lista_unica

async def extrair_dados():
    """Interface para o Orquestrador Main"""
    return await motor_extracao_boa()
