import os
from datetime import datetime
from curl_cffi.requests import AsyncSession
import asyncio
from utils import extrair_medidas_inteligente, setup_logging, read_json_file, formatar_nome_categoria, CATEGORIAS_IGNORADAS

logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'covabra_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Covabra")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.covabra.com.br/").rstrip('/')
URL_LEGACY = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search"
URL_CATEGORY_TREE = f"{BASE_URL_CONFIG}/api/catalog_system/pub/category/tree/3"

PAGE_SIZE = CONFIG.get("pagination", {}).get("page_size", 50)
TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome110")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
CONCURRENCY = 5

def extract_category_paths(category_tree, current_path=""):
    """Extrai caminhos completos de categorias folhas recursivamente"""
    paths = []
    for category in category_tree:
        cat_id = str(category.get('id'))
        new_path = f"{current_path}{cat_id}/" if current_path else f"{cat_id}/"
        if category.get('hasChildren') and category.get('children'):
            paths.extend(extract_category_paths(category.get('children'), new_path))
        else:
            paths.append((new_path, category.get('name')))
    return paths

async def motor_extracao_covabra_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }

    sem = asyncio.Semaphore(CONCURRENCY)

    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        # 1. Obter a árvore de categorias
        logger.info("   Obtendo árvore de categorias...")
        try:
            res_tree = await session.get(URL_CATEGORY_TREE, timeout=30)
            if res_tree.status_code != 200:
                logger.error("   Falha ao obter categorias.")
                return []
            categorias_folhas = extract_category_paths(res_tree.json())
            logger.info(f"   Foram encontradas {len(categorias_folhas)} subcategorias para explorar.")
        except Exception as e:
            logger.error(f"   Erro ao acessar categorias: {e}")
            return []

        # 2. Extrair produtos de cada categoria
        async def process_category(cat_path, cat_name):
            produtos_categoria = []
            _from = 0
            
            while True:
                async with sem:
                    _to = _from + PAGE_SIZE - 1
                    url_final = f"{URL_LEGACY}?fq=C:{cat_path}&_from={_from}&_to={_to}"
                    try:
                        response = await session.get(url_final, timeout=30)
                        
                        if response.status_code not in [200, 206]:
                            break

                        produtos_raw = response.json()
                        if not produtos_raw or not isinstance(produtos_raw, list):
                            break

                        for p in produtos_raw:
                            try:
                                nome_original = str(p.get('productName', '')).upper().strip()
                                if not nome_original: continue

                                categorias_vtex = p.get('categories', [])
                                cat_site_cru = ""
                                subcategoria_cru = "N/A"
                                tipo_produto_cru = "N/A"

                                if categorias_vtex and isinstance(categorias_vtex, list) and categorias_vtex[0]:
                                    partes_cat = categorias_vtex[0].strip('/').split('/')
                                    if len(partes_cat) > 0: cat_site_cru = partes_cat[0].upper()
                                    if len(partes_cat) > 1: subcategoria_cru = formatar_nome_categoria(partes_cat[1])
                                    if len(partes_cat) > 2: tipo_produto_cru = formatar_nome_categoria(partes_cat[2])
                                
                                if cat_site_cru in CATEGORIAS_IGNORADAS: continue
                                
                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_original)

                                item = p.get('items', [{}])[0]
                                ean = str(item.get('ean', 'N/A')).strip()
                                offer = item.get('sellers', [{}])[0].get('commertialOffer', {})
                                
                                p_venda = float(offer.get('Price', 0.0))
                                p_varejo = float(offer.get('ListPrice', p_venda))

                                if p_venda <= 0: continue

                                # --- CORREÇÃO DE UNIT MULTIPLIER (HORTIFRUTI VTEX) --- #
                                unit_multiplier = float(item.get('unitMultiplier') or 1.0)
                                if unit_multiplier > 0 and unit_multiplier < 1.0:
                                    if p_varejo > (p_venda * (1 / unit_multiplier) * 0.5): 
                                        p_varejo = p_varejo * unit_multiplier
                                    else:
                                        p_varejo = p_varejo * unit_multiplier
                                        p_venda = p_venda * unit_multiplier

                                condicao = "1 UN"
                                marca = str(p.get('brand', 'OUTROS')).upper()
                                img_url = item.get('images', [{}])[0].get('imageUrl', '')
                                
                                link_pdp_rel = p.get('linkText') or p.get('link') or p.get('url') or ''
                                if link_pdp_rel:
                                    if link_pdp_rel.startswith('http'):
                                        link_pdp = link_pdp_rel
                                    elif link_pdp_rel.startswith('/'):
                                        link_pdp = f"https://www.covabra.com.br{link_pdp_rel}"
                                    else:
                                        link_pdp = f"https://www.covabra.com.br/{link_pdp_rel}/p"
                                else:
                                    link_pdp = ""
                                
                                produtos_categoria.append({
                                    "Mercado": NOME_MERCADO,
                                    "EAN": ean,
                                    "Categoria": cat_site_cru,
                                    "subcategoria": subcategoria_cru,
                                    "tipo_produto": tipo_produto_cru,
                                    "Produto": nome_limpo,
                                    "Marca": marca,
                                    "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                                    "Preço Atacado": f"R$ {p_venda:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv,
                                    "Medida": med,
                                    "Unidade": "UN", "Condição": condicao,
                                    "Data_Hora": agora,
                                    "Link_Imagem": img_url,
                                    "Link_PDP": link_pdp
                                })
                            except:
                                continue
                        
                        if len(produtos_raw) < PAGE_SIZE:
                            break
                        _from += PAGE_SIZE
                        if _from >= 2500: break # Limite VTEX
                    except Exception as e:
                        logger.error(f"Erro na categoria {cat_path} pag {_from}: {e}")
                        break
            
            logger.info(f"   - Categoria {cat_name} ({cat_path.strip('/')}): {len(produtos_categoria)} itens capturados.")
            return produtos_categoria

        tarefas = [process_category(cat_path, cat_name) for cat_path, cat_name in categorias_folhas]
        
        # Executa em lotes
        chunk_size = 5
        for i in range(0, len(tarefas), chunk_size):
            chunk = tarefas[i:i+chunk_size]
            resultados_chunk = await asyncio.gather(*chunk)
            for res in resultados_chunk:
                lista_final.extend(res)

    lista_deduplicada = list({f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v for v in lista_final}.values())
    
    logger.info(f"✅ {len(lista_deduplicada)} produtos totais capturados no {NOME_MERCADO} Full Catalog.")
    return lista_deduplicada

async def extrair_dados():
    return await motor_extracao_covabra_full()
