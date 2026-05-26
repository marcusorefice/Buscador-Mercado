import os
import asyncio
import json
import urllib.parse
import warnings
import re
from datetime import datetime
import curl_cffi
from curl_cffi.requests import AsyncSession
from utils import (
    padronizar_categoria, 
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
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'dom_olivio_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Dom Olívio")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.domolivio.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
REGION_ID = REGIONALIZATION.get("region_id") # Pode ser null
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-745")
SALES_CHANNEL_SHELF = REGIONALIZATION.get("channel", "1")
SALES_CHANNEL_PRICE = REGIONALIZATION.get("price_channel", "2")
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "2085")

MAX_PAGES = CONFIG.get("pagination", {}).get("max_pages", 25)

# Hashes da API GraphQL
API_HASHES = CONFIG.get("api_hashes", {})
GET_PRODUCTS_HASH = API_HASHES.get("get_products", "ae50c5a735b1464f0ba48be4f2b32f7289ce6284")
CLIENT_PRODUCT_HASH = API_HASHES.get("client_product", "47aa22eb750cb2c529e5eeafb921bfeadb67db71")

# Semáforos preventivos para evitar Bloqueio/404
PAGE_SEMAPHORE = asyncio.Semaphore(10)
API_SEMAPHORE = asyncio.Semaphore(30)
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")

async def _buscar_preco_calculado(session: AsyncSession, product_id: str) -> tuple[float, float, str]:
    """Consulta o preço real (incluindo descontos de cartão/clube) e GTIN/EAN via Hash"""
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
        
        try:
            res = await session.get(url, timeout=10)
            res.raise_for_status()
            data = res.json()
            if not isinstance(data, dict):
                logger.warning(f"Resposta inesperada (não é um dict) para o produto ID {product_id}.")
                return 0.0, 0.0, 'N/A'
            
            p_data = data.get('data', {}).get('product', {})
            
            # Extração do GTIN/EAN, que só está disponível na chamada detalhada na VTEX FastStore
            ean = str(p_data.get('gtin', '')).strip()
            if not ean or ean == '0' or ean == 'None':
                ean = str(p_data.get('ean', '')).strip()
            if not ean or ean == '0' or ean == 'None':
                ean = 'N/A'
                
            offers = p_data.get('offers', {})
            if offers:
                list_price = float(offers.get('offers', [{}])[0].get('listPrice', 0.0))
                price = float(offers.get('lowPrice', 0.0))
                return list_price, price, ean
                
            return 0.0, 0.0, ean
        except (asyncio.TimeoutError, json.JSONDecodeError, curl_cffi.requests.errors.RequestsError) as e:
            logger.error(f"Erro ao buscar preço detalhado para ID {product_id}: {e}")
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar preço detalhado para ID {product_id}: {e}", exc_info=True)

        return 0.0, 0.0, 'N/A'

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
                logger.info(f"Página {pagina} do {NOME_MERCADO} não retornou produtos. Fim da lista?")
                return []

            tarefas_precos = [_buscar_preco_calculado(session, e['node']['id']) for e in edges]
            precos_finais = await asyncio.gather(*tarefas_precos)

            lista_final = []
            agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

            def get_last_path_part(path_str: str) -> str:
                if not isinstance(path_str, str): return ""
                parts = [part for part in path_str.split('/') if part]
                return parts[-1] if parts else ""

            for edge, (v_varejo, v_atacado, ean_detalhado) in zip(edges, precos_finais):
                try:
                    p = edge['node']
                    nome_cru = p['name'].upper().strip()
                    
                    # Prioriza o EAN/GTIN da chamada detalhada, pois é mais confiável na VTEX FastStore.
                    if ean_detalhado and ean_detalhado not in ['N/A', '', 'None']:
                        ean = ean_detalhado
                    else:
                        ean = str(p.get('gtin', '')).strip()
                        if not ean or ean == 'None':
                            ean = str(p.get('ean', '')).strip()
                        if not ean or ean == 'None':
                            ean = str(p.get('sku', '')).strip()
                        if not ean or ean == 'None':
                            ean = str(p.get('id', '')).strip()
                        if not ean or ean == 'None':
                            ean = 'N/A'
                    
                    p_v = v_varejo if v_varejo > 0 else float(p.get('offers', {}).get('highPrice', 0.0))
                    p_a = v_atacado if v_atacado > 0 else float(p.get('offers', {}).get('lowPrice', p_v))
                    
                    if p_v <= 0 and p_a <= 0: continue
                    if p_v <= 0: p_v = p_a
                    if p_v < p_a: p_v = p_a

                    # Lógica de Condição corrigida para refletir o padrão do Boa.
                    # Se há diferença de preço, é uma oferta do clube.
                    condicao = "1 UN"
                    if p_a < p_v:
                        condicao = "EXCLUSIVO CLUBE DOM (CPF)"

                    # --- LÓGICA DE TAXONOMIA (ROBUSTA) ---
                    cat_tree = p.get('categoryTree', [])
                    cat_site = "OUTROS"
                    subcategoria = "N/A"
                    tipo_prod = "N/A"

                    # Tenta o formato de lista de dicionários (como Carrefour)
                    if isinstance(cat_tree, list) and cat_tree and isinstance(cat_tree[0], dict):
                        if len(cat_tree) > 0: cat_site = cat_tree[0].get('name', 'OUTROS').upper()
                        if len(cat_tree) > 1: subcategoria = formatar_nome_categoria(cat_tree[1].get('name', 'N/A'))
                        if len(cat_tree) > 2: tipo_prod = formatar_nome_categoria(cat_tree[2].get('name', 'N/A'))
                    # Tenta o formato de lista de strings (como Boa)
                    elif isinstance(cat_tree, list) and cat_tree and isinstance(cat_tree[0], str):
                        categorias_extraidas = [get_last_path_part(c).upper() for c in cat_tree]
                        if len(categorias_extraidas) > 0: cat_site = categorias_extraidas[0] if categorias_extraidas[0] else "OUTROS"
                        if len(categorias_extraidas) > 1: subcategoria = formatar_nome_categoria(categorias_extraidas[1])
                        if len(categorias_extraidas) > 2: tipo_prod = formatar_nome_categoria(categorias_extraidas[2])
                    
                    if cat_site in CATEGORIAS_IGNORADAS: continue
                    
                    # Usa o contexto completo para uma categorização mais precisa, evitando erros da API de origem.
                    full_context = f"{nome_cru} {cat_site} {subcategoria} {tipo_prod}"
                    categoria_final = padronizar_categoria(full_context, cat_site)
                    
                    # --- LÓGICA DE MEDIDAS CORRIGIDA ---
                    nome_limpo = nome_cru
                    qv = "1"
                    med = "UN"
                    unidade_venda = "UN" # A maioria dos itens é vendida por unidade (pacote, bandeja, etc.)

                    # 1. Tenta extrair a medida de campos estruturados da API (padrão VTEX/Dom Olívio)
                    medida_extraida_api = False
                    try:
                        # CORREÇÃO: Os campos estão na raiz do produto 'p', não dentro de 'items'.
                        if 'unitMultiplier' in p and 'measurementUnit' in p:
                            unit_multiplier = float(p['unitMultiplier'])
                            measurement_unit = p['measurementUnit'].lower()

                            if measurement_unit == 'kg':
                                if unit_multiplier < 1.0:
                                    qv, med = str(int(unit_multiplier * 1000)), 'G'
                                else:
                                    qv, med = (str(int(unit_multiplier)), 'KG') if unit_multiplier.is_integer() else (str(unit_multiplier), 'KG')
                            elif measurement_unit == 'g':
                                qv, med = str(int(unit_multiplier)), 'G'
                            
                            medida_extraida_api = True
                    except (ValueError, TypeError, IndexError, KeyError):
                        pass
                    
                    # 2. Se a API não forneceu a medida, usa a extração do nome
                    if not medida_extraida_api:
                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                    # 3. Lógica de Unidade de Venda (KG vs UN), especialmente para itens pesáveis
                    if nome_cru.endswith(" KG"):
                        unidade_venda = "KG"
                        if qv == "1" and med == "UN":
                            qv, med = "1", "KG"
                    
                    # 4. Limpeza final do nome
                    nome_limpo = re.sub(r'\s*\d+[\.,]?\d*\s*(G|KG|L|ML|UN)\b', '', nome_limpo, flags=re.IGNORECASE).strip()
                    if nome_limpo.endswith(" KG"):
                        nome_limpo = nome_limpo[:-3].strip()

                    img = p.get('image', [{}])[0].get('url', 'SEM IMAGEM')
                    if img.startswith("//"): img = "https:" + img

                    lista_final.append({
                        "Mercado": NOME_MERCADO,
                        "EAN": ean,
                        "Categoria": categoria_final,
                        "subcategoria": subcategoria,
                        "tipo_produto": tipo_prod,
                        "Produto": nome_limpo,
                        "Marca": p.get('brand', {}).get('name', 'OUTROS').upper(),
                        "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, "Medida": med, "Unidade": unidade_venda, "Condição": condicao, "Data_Hora": agora, "Link_Imagem": img
                    })
                except (KeyError, TypeError, ValueError) as e:
                    logger.warning(f"Erro ao processar um produto na página {pagina}: {e}. Produto: {p.get('name', 'N/A')}")
                    continue

            return lista_final
        except (asyncio.TimeoutError, json.JSONDecodeError, curl_cffi.requests.errors.RequestsError) as e:
            logger.error(f"Erro ao extrair página completa {pagina} do {NOME_MERCADO}: {e}")
            return []
        except Exception as e:
            logger.error(f"Erro inesperado ao extrair página completa {pagina} do {NOME_MERCADO}: {e}", exc_info=True)
            return []

async def motor_extracao_dom_olivio():
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO}...")
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        tarefas = [_extrair_pagina_completa(session, p) for p in range(1, MAX_PAGES + 1)]
        resultados = await asyncio.gather(*tarefas)
        
        lista_achatada = [item for sublist in resultados for item in sublist]
    
    if not lista_achatada:
        logger.warning(f"Nenhum produto foi capturado para o {NOME_MERCADO}.")
        return []

    # Deduplicação por uma chave mais robusta (Produto + Marca) para evitar que
    # produtos diferentes com nomes similares (após a limpeza) se sobreponham.
    lista_unica = list({f"{v['Produto']}_{v['Marca']}": v for v in lista_achatada}.values())
    logger.info(f"✅ Finalizado! {len(lista_achatada)} produtos brutos coletados, resultando em {len(lista_unica)} produtos únicos.")
    return lista_unica

async def extrair_dados():
    """Interface para o Orquestrador Main"""
    return await motor_extracao_dom_olivio()