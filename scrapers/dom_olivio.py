import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import urllib.parse
import warnings
import re
import base64
from datetime import datetime
import curl_cffi
from curl_cffi.requests import AsyncSession
from utils import (
    extrair_medidas_inteligente, 
    setup_logging, 
    read_json_file, 
    CATEGORIAS_IGNORADAS,
    formatar_nome_categoria
) 

# Silencia avisos para um log mais limpo
warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES TÉCNICAS (NÃO ALTERAR)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'dom_olivio_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Dom Olivio")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.domolivio.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
REGION_ID = REGIONALIZATION.get("region_id", "v2.C263836B4901B1A5F7E3F7DDE018919B")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13209-000")
SALES_CHANNEL_SHELF = REGIONALIZATION.get("channel", "1")
SALES_CHANNEL_PRICE = REGIONALIZATION.get("price_channel", "2") 
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "2085")

MAX_PAGES = 25

API_HASHES = CONFIG.get("api_hashes", {})
GET_PRODUCTS_HASH = API_HASHES.get("get_products", "ae50c5a735b1464f0ba48be4f2b32f7289ce6284")
CLIENT_PRODUCT_HASH = API_HASHES.get("client_product", "47aa22eb750cb2c529e5eeafb921bfeadb67db71")

# Otimização de concorrência para evitar Erro 500 por sobrecarga (Rate Limit)
PAGE_SEMAPHORE = asyncio.Semaphore(2)
API_SEMAPHORE = asyncio.Semaphore(3)
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")

def _gerar_headers_vtex(region_id):
    segment_data = {
        "campaigns": None, "channel": "1", "priceTables": None, "regionId": region_id,
        "utm_campaign": None, "utm_source": None, "utmi_campaign": None,
        "currencyCode": "BRL", "currencySymbol": "R$", "countryCode": "BRA",
        "cultureInfo": "pt-BR", "admin_cultureInfo": "pt-BR", "channelPrivacy": "public"
    }
    segment_b64 = base64.b64encode(json.dumps(segment_data).encode('utf-8')).decode('utf-8')
    return {
        "accept": "*/*",
        "accept-language": "pt-BR,pt;q=0.9",
        "cookie": f"vtex_segment={segment_b64};",
        "referer": "https://www.domolivio.com.br/"
    }

async def _buscar_preco_calculado(session: AsyncSession, product_id: str, retries=3, delay=1.5) -> tuple[float, float, str]:
    """Consulta o preço real e o EAN/GTIN com um sistema de retentativas e recuo exponencial."""
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
                res = await session.get(url, timeout=12)
                if res.status_code >= 500:
                    # Falha na VTEX FastStore (Item inválido no canal 2 ou indisponível para simulação)
                    return 0.0, 0.0, 'N/A'
                res.raise_for_status()
                data = res.json()
                if not isinstance(data, dict):
                    logger.warning(f"Resposta inesperada (não é um dict) para o produto ID {product_id}.")
                    return 0.0, 0.0, 'N/A'
                
                p_data = (data.get('data') or {}).get('product') or {}
                
                ean = str(p_data.get('gtin', '')).strip()
                if not ean or ean == '0' or ean == 'None':
                    ean = str(p_data.get('ean', 'N/A')).strip()
                if not ean or ean == '0' or ean == 'None':
                    ean = 'N/A'

                offers = p_data.get('offers') or {}
                if offers:
                    offer_list = offers.get('offers') or []
                    first_offer = offer_list[0] if offer_list else {}
                    list_price = float(first_offer.get('listPrice') or 0.0)
                    price = float(offers.get('lowPrice') or 0.0)
                    return list_price, price, ean
                
                return 0.0, 0.0, ean

            except (asyncio.TimeoutError, curl_cffi.requests.errors.RequestsError, Exception) as e:
                if tentativa < retries - 1:
                    # Aplica recuo exponencial (espera mais a cada falha: 1.5s, 3.0s...)
                    tempo_espera = delay * (tentativa + 1)
                    await asyncio.sleep(tempo_espera)
                else:
                    logger.error(f"Erro final ao buscar preço para ID {product_id} após {retries} tentativas: {e}")

        return 0.0, 0.0, 'N/A'

async def _processar_edges(session: AsyncSession, edges: list, pagina_num: int):
    """Processa uma lista de 'edges' da API, busca preços e retorna produtos formatados."""
    if not edges:
        return []
    
    try:
        tarefas_precos = [_buscar_preco_calculado(session, e.get('node', {}).get('id')) for e in edges if e.get('node')]
        precos_finais = await asyncio.gather(*tarefas_precos)

        lista_final = []
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        def get_last_path_part(path_str: str) -> str:
            if not isinstance(path_str, str): return ""
            parts = [part for part in path_str.split('/') if part]
            return parts[-1] if parts else ""

        for edge, (v_varejo, v_atacado, ean_detalhado) in zip(edges, precos_finais):
            try:
                p = edge.get('node')
                if not p or not isinstance(p, dict):
                    continue
                
                ean = ean_detalhado if ean_detalhado not in ['N/A', '', 'None'] else str(p.get('gtin', '')).strip()
                if not ean or ean in ['0', 'None', 'N/A']:
                    ean = str(p.get('ean', 'N/A')).strip()
                if not ean or ean == 'None':
                    ean = 'N/A'
                
                nome_cru = str(p.get('name', '')).upper().strip()
                if not nome_cru:
                    continue
                
                custom_offers = p.get('customOffers') or {}
                offers_data = p.get('offers') or {}
                
                # Pegamos o p_v preferencialmente da vitrine (customOffers/offers) pois lá ele sempre respeita a fração (ex: 500g).
                # O v_varejo retornado da API detalhada costuma vir como 1KG, o que causava a duplicação na hora de dividir.
                p_v = float(custom_offers.get('listPriceCustom') or offers_data.get('highPrice') or 0.0)
                if p_v <= 0: 
                    p_v = v_varejo

                p_a = v_atacado if v_atacado > 0 else float(custom_offers.get('spotPriceCustom') or offers_data.get('lowPrice') or p_v or 0.0)

                # FIX: spotPriceCustom is sometimes incorrectly multiplied by unitMultiplier on VTEX's backend
                if p_a > p_v * 1.5:
                    p_a = float(offers_data.get('lowPrice') or p_v or 0.0)

                unit_multiplier = float(p.get('unitMultiplier') or 1.0)
                if unit_multiplier > 0 and unit_multiplier != 1.0:
                    # Se p_v veio como 1KG do v_varejo (fallback), não dividimos. Mas da vitrine é seguro dividir.
                    if p_v == v_varejo and p_v >= (p_a / unit_multiplier) * 0.9:
                        pass # v_varejo já é 1KG
                    else:
                        p_v = p_v / unit_multiplier

                    p_a = p_a / unit_multiplier

                if p_v <= 0 and p_a <= 0: continue
                if p_v <= 0: p_v = p_a
                if p_a > 0 and p_v < p_a: p_v = p_a

                condicao = "1 UN"
                tem_desconto_custom = custom_offers.get('hasDiscount')

                if p_a < p_v or tem_desconto_custom:
                    condicao = "CLUBE +AMIGO (CPF)"

                cat_tree = p.get('categoryTree', [])
                categorias_extraidas = []
                if isinstance(cat_tree, list) and cat_tree:
                    if isinstance(cat_tree[0], dict):
                        categorias_extraidas = [c.get('name', '').upper() for c in cat_tree]
                    elif isinstance(cat_tree[0], str):
                        categorias_extraidas = [get_last_path_part(c).upper() for c in cat_tree]

                categoria = categorias_extraidas[0] if categorias_extraidas and categorias_extraidas[0] else "OUTROS"
                subcategoria = formatar_nome_categoria(categorias_extraidas[1]) if len(categorias_extraidas) > 1 else "N/A"
                tipo_produto = formatar_nome_categoria(categorias_extraidas[2]) if len(categorias_extraidas) > 2 else "N/A"
                
                if categoria in CATEGORIAS_IGNORADAS: continue
                
                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

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

                img_list = p.get('image') or [{}]
                img = img_list[0].get('url', 'SEM IMAGEM') if isinstance(img_list, list) and img_list and isinstance(img_list[0], dict) else 'SEM IMAGEM'
                if img.startswith("//"): img = "https:" + img

                link_pdp_rel = p.get('slug') or p.get('linkText') or p.get('url') or ''
                if link_pdp_rel:
                    if link_pdp_rel.startswith('http'): link_pdp = link_pdp_rel
                    elif link_pdp_rel.startswith('/'): link_pdp = f"https://www.domolivio.com.br{link_pdp_rel}"
                    else: link_pdp = f"https://www.domolivio.com.br/{link_pdp_rel}/p"
                else: link_pdp = ""

                lista_final.append({
                    "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": categoria, "subcategoria": subcategoria,
                    "tipo_produto": tipo_produto, "Produto": nome_limpo, "Marca": (p.get('brand') or {}).get('name', 'OUTROS').upper(),
                    "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','), "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                    "Qtd_Valor": qv, "Medida": med, "Unidade": unidade_venda, "Condição": condicao, "Data_Hora": agora, 
                    "Link_Imagem": img, "Link_PDP": link_pdp
                })
            except Exception as e:
                nome_err = p.get('name', 'N/A') if isinstance(p, dict) else 'N/A'
                logger.warning(f"Erro ao processar um produto na página {pagina_num}: {e}. Produto: {nome_err}")
                continue

        return lista_final
    except Exception as e:
        logger.error(f"Erro inesperado no processamento dos produtos da página {pagina_num}: {e}", exc_info=True)
        return []

async def _extrair_pagina_completa(session: AsyncSession, pagina: int, use_cluster: bool = True):
    async with PAGE_SEMAPHORE:
        try:
            facets = [{"key": "productclusterids", "value": CLUSTER_ID}] if use_cluster else []
            facets.extend([
                {"key": "fuzzy", "value": "0"},
                {"key": "operator", "value": "and"}
            ])
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

async def motor_extracao_dom_olivio():
    logger.info(f"🚀 Iniciando extração DUPLA para {NOME_MERCADO} (Cluster + Maiores Descontos)...")
    headers = _gerar_headers_vtex(REGION_ID)
    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        # Executa as páginas do cluster primeiro
        logger.info(f"⏳ Coletando produtos por Cluster id: {CLUSTER_ID}...")
        tarefas_cluster = [_extrair_pagina_completa(session, p, use_cluster=True) for p in range(0, MAX_PAGES)]
        resultados_cluster = await asyncio.gather(*tarefas_cluster)
        
        # Intervalo estratégico para esvaziar a fila do servidor antes da próxima leva
        await asyncio.sleep(3.5)
        
        # Executa as páginas de maiores descontos na sequência
        logger.info("⏳ Coletando produtos por Maiores Descontos...")
        tarefas_desconto = [_extrair_pagina_completa(session, p, use_cluster=False) for p in range(0, MAX_PAGES + 4)]
        resultados_desconto = await asyncio.gather(*tarefas_desconto)
        
        resultados = resultados_cluster + resultados_desconto
        lista_achatada = [item for sublist in resultados for item in sublist]
    
    if not lista_achatada:
        logger.warning(f"Nenhum produto foi capturado para o {NOME_MERCADO}.")
        return []

    lista_unica_dict = {}
    for v in lista_achatada:
        ean = str(v.get('EAN', 'N/A')).strip()
        chave = ean if (ean and ean != 'N/A') else f"{v['Produto']}_{v['Marca']}"
        if chave in lista_unica_dict:
            preco_atual = float(str(lista_unica_dict[chave]['Preço Atacado']).replace('R$ ', '').replace(',', '.'))
            preco_novo = float(str(v['Preço Atacado']).replace('R$ ', '').replace(',', '.'))
            if preco_novo < preco_atual: lista_unica_dict[chave] = v
        else: lista_unica_dict[chave] = v
            
    lista_unica = list(lista_unica_dict.values())
    logger.info(f"✅ Finalizado! {len(lista_unica)} produtos capturados no {NOME_MERCADO}.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_dom_olivio()