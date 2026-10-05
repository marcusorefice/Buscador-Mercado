import os
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
REGION_ID = REGIONALIZATION.get("region_id") # Pode ser null
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-745")
SALES_CHANNEL_SHELF = REGIONALIZATION.get("channel", "1")
SALES_CHANNEL_PRICE = REGIONALIZATION.get("price_channel", "2")

API_HASHES = CONFIG.get("api_hashes", {})
GET_PRODUCTS_HASH = API_HASHES.get("get_products", "ae50c5a735b1464f0ba48be4f2b32f7289ce6284")
CLIENT_PRODUCT_HASH = API_HASHES.get("client_product", "47aa22eb750cb2c529e5eeafb921bfeadb67db71")

API_SEMAPHORE = asyncio.Semaphore(40)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
CONCURRENCY = 10

DEPARTAMENTOS_FALLBACK = [
    "bebidas", "carnes-e-aves", "frios-e-laticinios", 
    "hortifruti", "limpeza", "higiene-e-beleza", "padaria", 
    "congelados", "pet-shop", "saudaveis", "bebes"
]

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

async def _buscar_preco_calculado(session: AsyncSession, product_id: str, retries=2, delay=0.5) -> tuple[float, float, str]:
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
                # ⏱️ Reduzido de 10s para 5s para não prender o scraper se a rede oscilar
                res = await session.get(url, timeout=5)
                res.raise_for_status()
                data = res.json()
                if not isinstance(data, dict):
                    return 0.0, 0.0, 'N/A'
                
                p_data = data.get('data', {}).get('product', {})
                
                ean = str(p_data.get('gtin', '')).strip()
                if not ean or ean == '0' or ean == 'None':
                    ean = str(p_data.get('ean', '')).strip()
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

            except (asyncio.TimeoutError, curl_cffi.requests.errors.RequestsError) as e:
                if tentativa < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    break
            except Exception as e:
                break

        return 0.0, 0.0, 'N/A'

async def fetch_ean_from_pdp(session: AsyncSession, url_pdp: str, sem_pdp: asyncio.Semaphore) -> str:
    if not url_pdp: return "N/A"
    async with sem_pdp:
        try:
            res = await session.get(url_pdp, timeout=15)
            if res.status_code == 200:
                todos_eans = re.findall(r'\b(789\d{10}|790\d{10})\b', res.text)
                if todos_eans: return todos_eans[0]
        except Exception: pass
    return "N/A"

async def enrich_eans_from_pdps(session: AsyncSession, lista_produtos: list):
    sem_pdp = asyncio.Semaphore(15)
    produtos_sem_ean = [p for p in lista_produtos if str(p.get('EAN', '')).startswith('INT_') or p.get('EAN') == 'N/A']
    if not produtos_sem_ean: return
    logger.info(f"   🔍 Buscando EAN em {len(produtos_sem_ean)} páginas de produtos (Arrastão HTML)...")
    tasks = [fetch_ean_from_pdp(session, p.get('Link_PDP'), sem_pdp) for p in produtos_sem_ean]
    resultados = await asyncio.gather(*tasks)
    for p, ean in zip(produtos_sem_ean, resultados):
        if ean != 'N/A': p['EAN'] = ean

async def motor_extracao_dom_olivio_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    sem = asyncio.Semaphore(CONCURRENCY)

    headers = _gerar_headers_vtex(REGION_ID)
    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        # 1. Obter os sub-departamentos via Facets GraphQL (Varredura Profunda)
        logger.info("   Mapeando sub-departamentos via Facets GraphQL (Varredura Profunda)...")
        departamentos_ativos = []
        try:
            novos_deptos = set()
            termos_estrategicos = [
                "arroz", "feijao", "oleo", "macarrao", "cafe", "acucar", "leite",
                "carne", "frango", "linguica", "peixe", "hamburguer",
                "queijo", "presunto", "manteiga", "iogurte", "requeijao",
                "refrigerante", "cerveja", "suco", "agua", "vinho",
                "maca", "banana", "batata", "tomate", "cebola", "alface",
                "pao", "bolo", "biscoito", "chocolate", "sorvete",
                "detergente", "sabao", "amaciante", "desinfetante", "papel",
                "shampoo", "sabonete", "creme", "desodorante", "fralda",
                "racao", "petisco", ""
            ]
            async def buscar_facets(termo):
                try:
                    selected_facets_shelf = [{"key": "fuzzy", "value": "0"}, {"key": "operator", "value": "and"}]
                    variables_shelf = {
                        "input": {
                            "activeSalesChannel": SALES_CHANNEL_SHELF, 
                            "postalCode": CEP_JUNDIAI, 
                            "page": 0, "sort": "score_desc", "term": termo, 
                            "selectedFacets": selected_facets_shelf,
                            "hasChangeOrder": False, 
                            "hasClubWithRegion": True, 
                            "cmsPostalCode": CEP_JUNDIAI, 
                            "clubSc": int(SALES_CHANNEL_PRICE)
                        }
                    }
                    if REGION_ID:
                        variables_shelf["input"]["regionId"] = REGION_ID
                    params_shelf = {
                        "operationName": "GetProductsQuery",
                        "operationHash": GET_PRODUCTS_HASH,
                        "variables": json.dumps(variables_shelf, separators=(',', ':'))
                    }
                    res_facets = await session.get(f"{URL_BASE}?" + urllib.parse.urlencode(params_shelf), timeout=15)
                    if res_facets.status_code == 200:
                        return res_facets.json()
                except:
                    pass
                return None

            tarefas_buscas = [buscar_facets(t) for t in termos_estrategicos]
            resultados_buscas = await asyncio.gather(*tarefas_buscas)

            for data_facets in resultados_buscas:
                if data_facets:
                    facets_array = data_facets.get('data', {}).get('getProducts', {}).get('data', {}).get('facets', [])
                    for f in facets_array:
                        key_str = str(f.get('key', '')).lower()
                        if key_str in ['category-1', 'category-2', 'category-3', 'department', 'c']:
                            k = f.get('key')
                            for v in f.get('values', []):
                                val = v.get('value')
                                if val:
                                    novos_deptos.add((k, val))
                                
            if novos_deptos:
                departamentos_ativos = list(novos_deptos)
                logger.info(f"   Mapeados {len(departamentos_ativos)} blocos de categorias (Níveis 1, 2 e 3) para varredura massiva.")
            else:
                logger.warning("   Nenhum departamento retornado nas Facets. Usando Fallback.")
                departamentos_ativos = [("c", d) for d in DEPARTAMENTOS_FALLBACK]
        except Exception as e:
            logger.warning(f"   Falha ao obter Facets Dinâmicas: {e}. Usando Fallback.")
            departamentos_ativos = [("c", d) for d in DEPARTAMENTOS_FALLBACK]

        produtos_vistos = set()

        async def process_category(chave_dept, dept_slug):
            produtos_categoria = []
            pagina = 0
            
            logger.info(f"   📂 Iniciando varredura no departamento: {dept_slug.upper()}")
            
            while True:
                async with sem:
                    try:
                        selected_facets_cat = [
                            {"key": chave_dept, "value": dept_slug},
                            {"key": "fuzzy", "value": "0"},
                            {"key": "operator", "value": "and"}
                        ]
                        variables_shelf = {
                            "input": {
                                "activeSalesChannel": SALES_CHANNEL_SHELF, 
                                "postalCode": CEP_JUNDIAI, 
                                "page": pagina,
                                "sort": "score_desc", 
                                "term": "", 
                                "selectedFacets": selected_facets_cat,
                                "hasChangeOrder": False, 
                                "hasClubWithRegion": True, 
                                "cmsPostalCode": CEP_JUNDIAI, 
                                "clubSc": int(SALES_CHANNEL_PRICE)
                            }
                        }
                        if REGION_ID:
                            variables_shelf["input"]["regionId"] = REGION_ID
                        params_shelf = {
                            "operationName": "GetProductsQuery",
                            "operationHash": GET_PRODUCTS_HASH,
                            "variables": json.dumps(variables_shelf, separators=(',', ':'))
                        }
                        url_shelf = f"{URL_BASE}?" + urllib.parse.urlencode(params_shelf)
                        
                        res = await session.get(url_shelf, timeout=20)
                        if res.status_code != 200:
                            logger.error(f"   ❌ Erro HTTP {res.status_code} na categoria '{dept_slug}' (Página {pagina})")
                            break
                        
                        res_json = res.json()
                        edges = []
                        try:
                            edges = res_json['data']['getProducts']['data']['products']['edges']
                        except (KeyError, TypeError):
                            pass
                            
                        if not edges:
                            break

                        if pagina % 3 == 0:
                            logger.info(f"   ⏳ [{dept_slug.upper()}] Lendo página {pagina} (Total parcial: {len(produtos_categoria)} itens)...")

                        novos_edges = []
                        for e in edges:
                            pid = e['node']['id']
                            if pid not in produtos_vistos:
                                produtos_vistos.add(pid)
                                novos_edges.append(e)

                        tarefas_precos = [_buscar_preco_calculado(session, e['node']['id']) for e in novos_edges]
                        precos_finais = await asyncio.gather(*tarefas_precos)

                        def get_last_path_part(path_str: str) -> str:
                            if not isinstance(path_str, str): return ""
                            parts = [path_str.split('/')[-1]] if '/' not in path_str else [part for part in path_str.split('/') if part]
                            return parts[-1] if parts else ""

                        for edge, (v_varejo, v_atacado, ean_detalhado) in zip(novos_edges, precos_finais):
                            try:
                                p = edge['node']
                                items = p.get('items', [])
                                ean_from_items = ''
                                if items and isinstance(items, list):
                                    ean_from_items = str(items[0].get('ean', '')).strip()
                                    if (not ean_from_items or ean_from_items == '0' or ean_from_items == 'None' or len(ean_from_items) < 8) and items[0].get('referenceId'):
                                        for ref in items[0].get('referenceId', []):
                                            if ref.get('Key') == 'RefId':
                                                ean_from_items = str(ref.get('Value', '')).strip()
                                
                                if ean_from_items and ean_from_items not in ['0', 'None', 'N/A'] and len(ean_from_items) >= 8:
                                    ean = ean_from_items
                                else:
                                    ean = ean_detalhado if ean_detalhado not in ['N/A', '', 'None'] and len(ean_detalhado) >= 8 else str(p.get('gtin', '')).strip()
                                    if not ean or ean in ['0', 'None', 'N/A'] or len(ean) < 8:
                                        ean = str(p.get('ean', 'N/A')).strip()
                                    if not ean or ean == 'None':
                                        ean = 'N/A'
                                
                                nome_cru = p['name'].upper().strip()
                                
                                custom_offers = p.get('customOffers') or {}
                                offers_data = p.get('offers') or {}
                                
                                p_v = float(custom_offers.get('listPriceCustom') or offers_data.get('highPrice') or 0.0)
                                if p_v <= 0: 
                                    p_v = v_varejo
                                    
                                p_a = v_atacado if v_atacado > 0 else float(custom_offers.get('spotPriceCustom') or offers_data.get('lowPrice') or p_v or 0.0)

                                if p_a > p_v * 1.5:
                                    p_a = float(offers_data.get('lowPrice') or p_v or 0.0)

                                unit_multiplier = float(p.get('unitMultiplier') or 1.0)
                                measurement_unit = str(p.get('measurementUnit') or 'UN').upper()
                                
                                # Em vez de dividir o preco (o que causa bugs como 149.75 o kg), 
                                # vamos preservar o preco da oferta original e registrar a Qtd_Valor.
                                qv_from_vtex = "1"
                                med_from_vtex = "UN"
                                if unit_multiplier > 0 and unit_multiplier != 1.0:
                                    qv_from_vtex = str(unit_multiplier)
                                    med_from_vtex = measurement_unit

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

                                cat_site_cru = categorias_extraidas[0] if categorias_extraidas and categorias_extraidas[0] else "OUTROS"
                                subcategoria_cru = formatar_nome_categoria(categorias_extraidas[1]) if len(categorias_extraidas) > 1 else "N/A"
                                tipo_prod_cru = formatar_nome_categoria(categorias_extraidas[2]) if len(categorias_extraidas) > 2 else "N/A"
                                
                                if cat_site_cru in CATEGORIAS_IGNORADAS: continue
                                
                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                                # Se a VTEX enviou um unitMultiplier (ex: 5.0 kg), usamos ele em vez da extração de texto
                                if qv_from_vtex != "1":
                                    qv = qv_from_vtex
                                    med = med_from_vtex

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

                                img = p.get('image', [{}])[0].get('url', 'SEM IMAGEM')
                                if img.startswith("//"): img = "https:" + img
                                
                                link_pdp_rel = p.get('slug') or p.get('linkText') or p.get('url') or ''
                                if link_pdp_rel:
                                    if link_pdp_rel.startswith('http'):
                                        link_pdp = link_pdp_rel
                                    elif link_pdp_rel.startswith('/'):
                                        link_pdp = f"https://www.domolivio.com.br{link_pdp_rel}"
                                    else:
                                        link_pdp = f"https://www.domolivio.com.br/{link_pdp_rel}/p"
                                else:
                                    link_pdp = ""

                                produtos_categoria.append({
                                    "Mercado": NOME_MERCADO,
                                    "EAN": ean,
                                    "Categoria": cat_site_cru,
                                    "subcategoria": subcategoria_cru,
                                    "tipo_produto": tipo_prod_cru,
                                    "Produto": nome_limpo,
                                    "Marca": p.get('brand', {}).get('name', 'OUTROS').upper(),
                                    "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                                    "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv, "Medida": med, "Unidade": unidade_venda, "Condição": condicao, "Data_Hora": agora, "Link_Imagem": img,
                                    "Link_PDP": link_pdp
                                })
                            except Exception as e:
                                continue

                        page_info = res_json.get('data', {}).get('getProducts', {}).get('data', {}).get('products', {}).get('pageInfo', {})
                        if page_info and page_info.get('hasNextPage') is False:
                            break
                            
                        pagina += 1
                        
                        if pagina > 100:
                            logger.warning(f"   ⚠️ Limite de segurança de 100 páginas atingido em '{dept_slug}'.")
                            break
                    except Exception as e:
                        logger.error(f"Erro no departamento {dept_slug}: {e}")
                        break
                        
            logger.info(f"   - Departamento {dept_slug}: {len(produtos_categoria)} itens capturados.")
            return produtos_categoria

        tarefas = [process_category(chave, dept) for chave, dept in departamentos_ativos]
        
        chunk_size = 5
        for i in range(0, len(tarefas), chunk_size):
            chunk = tarefas[i:i+chunk_size]
            resultados_chunk = await asyncio.gather(*chunk)
            for res in resultados_chunk:
                lista_final.extend(res)

        lista_unica = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())
        
        await enrich_eans_from_pdps(session, lista_unica)

    logger.info(f"✅ Extração FULL concluída. {len(lista_unica)} produtos únicos capturados no {NOME_MERCADO}.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_dom_olivio_full()
