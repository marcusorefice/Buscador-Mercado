import os
import asyncio
import json
import urllib.parse
import warnings
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import extrair_medidas_inteligente, setup_logging, read_json_file

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES (SPECS)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'dom_olivio_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Dom Olívio")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.domolivio.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/api/graphql")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"

REGIONALIZATION = CONFIG.get("regionalization", {})
REGION_ID = REGIONALIZATION.get("region_id")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-745")
SALES_CHANNEL_SHELF = REGIONALIZATION.get("channel", "1")

API_HASHES = CONFIG.get("api_hashes", {})
GET_PRODUCTS_HASH = API_HASHES.get("get_products", "ae50c5a735b1464f0ba48be4f2b32f7289ce6284")

IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")

# O Dom Olívio usa FastStore GraphQL, vamos pegar a árvore de categorias via API Legacy se possível
URL_CATEGORY_TREE = f"{BASE_URL_CONFIG}/api/catalog_system/pub/category/tree/3"

def extract_category_ids(category_tree):
    ids = []
    for category in category_tree:
        if category.get('hasChildren') and category.get('children'):
            ids.extend(extract_category_ids(category.get('children')))
        else:
            ids.append((category.get('id'), category.get('name')))
    return ids

async def motor_extracao_dom_olivio_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    sem = asyncio.Semaphore(5)

    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # Tenta obter categorias via legacy (costuma funcionar em FastStore)
        try:
            res_tree = await session.get(URL_CATEGORY_TREE, timeout=20)
            categorias_folhas = []
            if res_tree.status_code == 200:
                categorias_folhas = extract_category_ids(res_tree.json())
        except:
            categorias_folhas = []

        if not categorias_folhas:
            logger.warning("Falha ao obter categorias via legacy. O Dom Olívio Full Catalog precisa de um mapeamento manual ou GraphQL complexo para varrer tudo. Usando fallback de ClusterID se configurado, mas isso não é o catálogo completo.")
            return []
            
        # 2. Extrair produtos de cada categoria (usando Legacy Search para varrer, pois GraphQL pagina pior)
        URL_LEGACY = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search"
        
        async def process_category(cat_id, cat_name):
            produtos_categoria = []
            _from = 0
            
            while True:
                async with sem:
                    _to = _from + 49
                    url_final = f"{URL_LEGACY}?fq=C:{cat_id}&_from={_from}&_to={_to}"
                    try:
                        response = await session.get(url_final, timeout=30)
                        if response.status_code not in [200, 206]: break
                        
                        produtos_raw = response.json()
                        if not produtos_raw or not isinstance(produtos_raw, list): break
                        
                        for p in produtos_raw:
                            try:
                                nome_cru = str(p.get('productName', '')).upper().strip()
                                if not nome_cru: continue
                                
                                item = p.get('items', [{}])[0]
                                ean = str(item.get('ean', 'N/A')).strip()
                                offer = item.get('sellers', [{}])[0].get('commertialOffer', {})
                                
                                p_venda = float(offer.get('Price', 0.0))
                                p_varejo = float(offer.get('ListPrice', p_venda))
                                
                                # Correção VTEX: Produtos a granel e Heurística de Preço
                                unit_multiplier = float(item.get('unitMultiplier') or 1.0)
                                if unit_multiplier > 0 and unit_multiplier < 1.0:
                                    if p_varejo > (p_venda * (1 / unit_multiplier) * 0.5): 
                                        p_venda = p_venda / unit_multiplier
                                    elif p_varejo < (p_venda * 2):
                                        p_varejo = p_varejo / unit_multiplier
                                        p_venda = p_venda / unit_multiplier
                                        
                                if p_venda <= 0: continue
                                
                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                                img_url = item.get('images', [{}])[0].get('imageUrl', '')
                                marca = str(p.get('brand', 'OUTROS')).upper()
                                
                                cat_site_cru = "GERAL"
                                cats = p.get('categories', [])
                                if cats: cat_site_cru = cats[0].strip('/').split('/')[0].upper()
                                
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
                                    "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_site_cru,
                                    "Produto": nome_limpo, "Marca": marca,
                                    "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                                    "Preço Atacado": f"R$ {p_venda:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv, "Medida": med, "Unidade": "UN", "Condição": "1 UN",
                                    "Data_Hora": agora, "Link_Imagem": img_url,
                                    "Link_PDP": link_pdp
                                })
                            except: continue
                            
                        if len(produtos_raw) < 50: break
                        _from += 50
                        if _from >= 2500: break
                    except: break
            logger.info(f"   - Categoria {cat_name}: {len(produtos_categoria)} itens")
            return produtos_categoria

        tarefas = [process_category(cat_id, cat_name) for cat_id, cat_name in categorias_folhas]
        chunk_size = 5
        for i in range(0, len(tarefas), chunk_size):
            resultados_chunk = await asyncio.gather(*tarefas[i:i+chunk_size])
            for res in resultados_chunk: lista_final.extend(res)

    lista_unica = list({f"{v['Produto']}_{v['Marca']}": v for v in lista_final}.values())
    logger.info(f"✅ {len(lista_unica)} produtos coletados para {NOME_MERCADO} Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_dom_olivio_full()
