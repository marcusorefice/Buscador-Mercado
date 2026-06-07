import os
import asyncio
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import (
    padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file,
    re,
    CATEGORIAS_IGNORADAS, formatar_nome_categoria
)

logger = setup_logging()

SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'oba_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Oba Hortifruti")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.obahortifruti.com.br/").rstrip('/')
URL_LEGACY = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search"
URL_CATEGORY_TREE = f"{BASE_URL_CONFIG}/api/catalog_system/pub/category/tree/3"

PAGE_SIZE = CONFIG.get("pagination", {}).get("page_size", 50)
TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
CONCURRENCY = 15

def extract_category_ids(category_tree, path=""):
    ids = []
    for category in category_tree:
        c_id = category.get('id')
        current_path = f"{path}/{c_id}" if path else str(c_id)
        if category.get('hasChildren') and category.get('children'):
            ids.extend(extract_category_ids(category.get('children'), current_path))
        else:
            ids.append((current_path, category.get('name')))
    return ids

async def motor_extracao_oba_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        logger.info("   Obtendo árvore de categorias...")
        try:
            res_tree = await session.get(URL_CATEGORY_TREE, timeout=30)
            if res_tree.status_code != 200:
                logger.error("   Falha ao obter categorias.")
                return []
            categorias_folhas = extract_category_ids(res_tree.json())
            logger.info(f"   Foram encontradas {len(categorias_folhas)} subcategorias.")
        except Exception as e:
            logger.error(f"   Erro: {e}")
            return []

        async def process_category(cat_id, cat_name):
            produtos_categoria = []
            _from = 0
            while True:
                async with sem:
                    _to = _from + PAGE_SIZE - 1
                    url_final = f"{URL_LEGACY}?fq=C:{cat_id}&_from={_from}&_to={_to}"
                    try:
                        res = await session.get(url_final, timeout=30)
                        if res.status_code not in [200, 206]: break
                        produtos_raw = res.json()
                        if not produtos_raw or not isinstance(produtos_raw, list): break

                        for p in produtos_raw:
                            try:
                                nome_bruto = str(p.get('productName', '')).upper().strip()
                                if not nome_bruto: continue
                                
                                categorias_vtex = p.get('categories', [])
                                cat_site = ""
                                if categorias_vtex and isinstance(categorias_vtex, list) and categorias_vtex[0]:
                                    partes_cat = categorias_vtex[0].strip('/').split('/')
                                    if len(partes_cat) > 0: cat_site = partes_cat[0].upper()
                                if cat_site in CATEGORIAS_IGNORADAS: continue

                                items = p.get('items', [])
                                if not items: continue
                                sku = items[0]
                                
                                codigo_bruto = str(sku.get('gtin', '')).strip() or str(sku.get('ean', '')).strip()
                                ean = codigo_bruto if codigo_bruto.isdigit() and len(codigo_bruto) in [12, 13] else "N/A"

                                oferta = sku.get('sellers', [{}])[0].get('commertialOffer', {})
                                p_venda = float(oferta.get('Price', 0.0))
                                p_varejo = float(oferta.get('ListPrice', p_venda))

                                if p_venda <= 0: continue

                                # --- CORREÇÃO DE UNIT MULTIPLIER (HORTIFRUTI VTEX) --- #
                                unit_multiplier = float(sku.get('unitMultiplier') or 1.0)
                                if unit_multiplier > 0 and unit_multiplier < 1.0:
                                    if p_varejo > (p_venda * (1 / unit_multiplier) * 0.5): 
                                        p_varejo = p_varejo * unit_multiplier
                                    else:
                                        p_varejo = p_varejo * unit_multiplier
                                        p_venda = p_venda * unit_multiplier

                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                                
                                measurement_unit = str(sku.get('measurementUnit', '')).lower()
                                
                                if measurement_unit == 'kg' or nome_bruto.upper().endswith(' KG'):
                                    unidade_venda = "KG"
                                else:
                                    unidade_venda = "UN"
                                        
                                if nome_bruto.endswith(" KG"):
                                    unidade_venda = "KG"
                                    if qv == "1" and med == "UN":
                                        qv, med = "1", "KG"
                                        
                                nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()
                                
                                img_url = sku.get('images', [{}])[0].get('imageUrl', '')
                                marca = p.get('brand', 'PRÓPRIA').upper()
                                
                                link_pdp_rel = p.get('linkText') or p.get('link') or p.get('url') or ''
                                if link_pdp_rel:
                                    if link_pdp_rel.startswith('http'):
                                        link_pdp = link_pdp_rel
                                    elif link_pdp_rel.startswith('/'):
                                        link_pdp = f"https://www.obahortifruti.com.br{link_pdp_rel}"
                                    else:
                                        link_pdp = f"https://www.obahortifruti.com.br/{link_pdp_rel}/p"
                                else:
                                    link_pdp = ""

                                produtos_categoria.append({
                                    "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_site,
                                    "Produto": nome_limpo, "Marca": marca,
                                    "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','), "Preço Atacado": f"R$ {p_venda:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv, "Medida": med, "Unidade": unidade_venda,
                                    "Condição": "1 UN", "Data_Hora": agora, "Link_Imagem": img_url,
                                    "Link_PDP": link_pdp
                                })
                            except: continue

                        if len(produtos_raw) < PAGE_SIZE: break
                        _from += PAGE_SIZE
                        if _from >= 2500: break
                    except: break
            logger.info(f"   - Categoria {cat_name}: {len(produtos_categoria)} itens")
            return produtos_categoria

        tarefas = [process_category(cat_id, cat_name) for cat_id, cat_name in categorias_folhas]
        resultados = await asyncio.gather(*tarefas)
        for res in resultados: 
            if res: lista_final.extend(res)

    lista_unica = list({f"{v['Produto']}_{v['Marca']}": v for v in lista_final}.values())
    logger.info(f"✅ {len(lista_unica)} produtos totais capturados no {NOME_MERCADO} Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_oba_full()
