import os
import json
import warnings
import urllib.parse
import asyncio
from curl_cffi.requests import AsyncSession
import random
import re
from datetime import datetime
from utils import extrair_medidas_inteligente, setup_logging, read_json_file, CATEGORIAS_IGNORADAS, formatar_nome_categoria

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'atacadao_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Atacadão")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.atacadao.com.br/").rstrip('/')
URL_GRAPHQL = f"{BASE_URL_CONFIG}/api/graphql"
URL_LEGACY = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search"
URL_CATEGORY_TREE = f"{BASE_URL_CONFIG}/api/catalog_system/pub/category/tree/3"

REGIONALIZATION = CONFIG.get("regionalization", {})
SELLER_ID = REGIONALIZATION.get("seller_id", "atacadaobr633")
REGION_ID = REGIONALIZATION.get("region_id", "U1cjYXRhY2FkYW9icjYzMw==")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-772")

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome124")
USER_AGENT = TECHNICAL_DEPS.get("playwright_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CONCURRENCY = 20
PAGE_SIZE = 50

def extract_category_facets(category_tree):
    """Extrai facets GraphQL de categorias folhas recursivamente"""
    facets_list = []
    for category in category_tree:
        if category.get('hasChildren') and category.get('children'):
            facets_list.extend(extract_category_facets(category.get('children')))
        else:
            url = category.get('url', '')
            path = urllib.parse.urlparse(url).path.strip('/')
            if path:
                parts = path.split('/')
                c_facets = [{"key": "c", "value": p} for p in parts]
                facets_list.append((category.get('name'), c_facets))
    return facets_list

async def motor_extracao_atacadao_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    cookie_str = f'{{"salesChannel":"1","postalCode":"{CEP_JUNDIAI}","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'
    
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.atacadao.com.br/catalogo",
        "Origin": "https://www.atacadao.com.br",
        "Cookie": f"regionalization={urllib.parse.quote(cookie_str)}"
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
            categorias_folhas = extract_category_facets(res_tree.json())
            logger.info(f"   Foram encontradas {len(categorias_folhas)} subcategorias para explorar via GraphQL.")
        except Exception as e:
            logger.error(f"   Erro ao acessar categorias: {e}")
            return []

        async def process_category(cat_name, cat_facets):
            produtos_categoria = []
            offset = 0
            
            while True:
                async with sem:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    
                    variables = {
                        "first": PAGE_SIZE, 
                        "after": str(offset), 
                        "sort": "score_desc", 
                        "term": "",
                        "selectedFacets": cat_facets + [
                            {"key": "region-id", "value": REGION_ID},
                            {"key": "channel", "value": f'{{"salesChannel":"1","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'},
                            {"key": "locale", "value": "pt-BR"}
                        ]
                    }
                    
                    query_graphql = """
                    query ProductsQuery($term: String, $selectedFacets: [SelectedFacetInput], $first: Int, $after: String, $sort: String) {
                      search(term: $term, selectedFacets: $selectedFacets, first: $first, after: $after, sort: $sort) {
                        products {
                          pageInfo { totalCount }
                          edges {
                            node {
                              id
                              gtin
                              name
                              slug
                              linkText
                              link
                              image { url }
                              offers {
                                offers { price listPrice minQuantity }
                              }
                              brand { name }
                              breadcrumbList {
                                itemListElement { name }
                              }
                            }
                          }
                        }
                      }
                    }
                    """
                    
                    payload = {
                        "operationName": "ProductsQuery",
                        "variables": variables,
                        "query": query_graphql
                    }

                    try:
                        res = await session.post(URL_GRAPHQL, json=payload, timeout=45)
                        if res.status_code in [429, 503, 500, 502, 504]:
                            await asyncio.sleep(random.uniform(2.0, 4.0))
                            continue
                            
                        response_json = res.json()
                        search_data = (response_json.get('data') or {}).get('search')
                        products_data = (search_data or {}).get('products')
                        
                        if not products_data:
                            break

                        bloco_produtos = products_data.get('edges', [])
                        if not bloco_produtos:
                            break

                        # Cruza EAN e Preço de Atacado com API Legada
                        ids_produtos = [str(p.get('node', {}).get('id')) for p in bloco_produtos if p.get('node', {}).get('id')]
                        mapa_dados = {}
                        
                        if ids_produtos:
                            query_ids = "&".join([f"fq=productId:{pid}" for pid in ids_produtos])
                            url_legado = f"{URL_LEGACY}?{query_ids}&sc=1"
                            
                            try:
                                resp_legado = await session.get(url_legado, timeout=30)
                                if resp_legado.status_code in [200, 206]:
                                    legacy_data = resp_legado.json()
                                    
                                    for lp in legacy_data:
                                        pid = str(lp.get('productId', ''))
                                        items = lp.get('items', [])
                                        
                                        ean_real = "N/A"
                                        if items and isinstance(items, list):
                                            item_data = items[0]
                                            ref_ids = item_data.get('referenceId', [])
                                            if ref_ids and isinstance(ref_ids, list):
                                                ean_real = str(ref_ids[0].get('Value', '')).strip()
                                            if not ean_real or len(ean_real) < 12:
                                                ean_real = str(item_data.get('ean', '')).strip()
                                            if not ean_real or not ean_real.isdigit() or len(ean_real) < 12:
                                                ean_real = "N/A"
                                                
                                        sellers = items[0].get('sellers', []) if items else []
                                        co = sellers[0].get('commertialOffer', {}) if sellers else {}
                                        
                                        p_var_legado = float(co.get('Price', 0.0))
                                        list_pr = float(co.get('ListPrice', p_var_legado))
                                        p_ata_legado = p_var_legado
                                        cond_legada = "1 UN"
                                        
                                        if list_pr > p_var_legado:
                                            p_var_legado = list_pr
                                            p_ata_legado = float(co.get('Price', 0.0))
                                            cond_legada = "OFERTA"
                                            
                                        teasers = co.get('Teasers', [])
                                        promos = co.get('DiscountHighLight', [])
                                        todas_tags = teasers + promos
                                        
                                        for tag in todas_tags:
                                            nome_tag = str(tag.get('<Name>', tag.get('name', ''))).lower()
                                            match = re.search(r'(\d+)\s*(?:un|unid|unidade|unidades|cx|caixa|pct|pacote)s?[^\d]*(\d+[.,]\d{2})', nome_tag)
                                            if match:
                                                qtd = match.group(1)
                                                valor_str = match.group(2).replace(',', '.')
                                                try:
                                                    v_atacado = float(valor_str)
                                                    if v_atacado > 0 and v_atacado <= p_var_legado:
                                                        p_ata_legado = v_atacado
                                                        cond_legada = f"A PARTIR DE {qtd} UN"
                                                        break
                                                except: pass
                                                
                                        mapa_dados[pid] = {
                                            'ean': ean_real,
                                            'p_varejo': p_var_legado,
                                            'p_atacado': p_ata_legado,
                                            'condicao': cond_legada
                                        }
                            except Exception as e_legado:
                                pass

                        for edge in bloco_produtos:
                            p = edge.get('node', {})
                            if not p: continue

                            try:
                                nome_cru = str(p.get('name', '')).upper().strip()
                                if not nome_cru: continue

                                pid = str(p.get('id', ''))
                                dados_legados = mapa_dados.get(pid, {})
                                
                                ean = dados_legados.get('ean') if dados_legados.get('ean') else str(p.get('gtin', 'N/A')).strip()

                                imagens = p.get('image', [])
                                imagem_url = imagens[0].get('url', "SEM IMAGEM") if imagens else "SEM IMAGEM"

                                ofertas_container = p.get('offers', {})
                                lista_ofertas = ofertas_container.get('offers', [{}])
                                offer_base = lista_ofertas[0] if lista_ofertas else {}
                                
                                p_varejo = float(offer_base.get('listPrice') if offer_base.get('listPrice') else offer_base.get('price', 0.0))
                                p_atacado = float(offer_base.get('price', 0.0))
                                condicao = "OFERTA" if p_atacado < p_varejo else "1 UN"
                                
                                if dados_legados:
                                    c_leg = dados_legados.get('condicao', '1 UN')
                                    p_ata_leg = dados_legados.get('p_atacado', 0.0)
                                    p_var_leg = dados_legados.get('p_varejo', 0.0)
                                    
                                    if c_leg not in ["1 UN", "OFERTA"]:
                                        condicao = c_leg
                                        if p_ata_leg > 0: p_atacado = p_ata_leg
                                        if p_var_leg > p_varejo: p_varejo = p_var_leg
                                    elif condicao == "1 UN" and c_leg == "OFERTA":
                                        condicao = "OFERTA"
                                        if p_ata_leg > 0: p_atacado = p_ata_leg
                                        if p_var_leg > 0: p_varejo = p_var_leg
                                        
                                if len(lista_ofertas) > 1 and condicao == "1 UN":
                                    offer_atacado = lista_ofertas[-1]
                                    p_ata_fs = float(offer_atacado.get('price', p_atacado))
                                    min_qty = offer_atacado.get('minQuantity', 1)
                                    if min_qty > 1 and p_ata_fs < p_varejo:
                                        p_atacado = p_ata_fs
                                        condicao = f"A PARTIR DE {min_qty} UN"

                                cat_tree = p.get('breadcrumbList', {}).get('itemListElement', [])
                                cat_site_cru = ""
                                if cat_tree and isinstance(cat_tree, list) and len(cat_tree) > 0:
                                    cat_site_cru = cat_tree[0].get('name', '').upper()

                                if cat_site_cru in CATEGORIAS_IGNORADAS: continue
                                
                                marca_obj = p.get('brand', {})
                                marca_str = marca_obj.get('name', 'OUTROS').upper() if isinstance(marca_obj, dict) else str(marca_obj or 'OUTROS').upper()

                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                                
                                measurement_unit = str(p.get('measurementUnit', '')).lower()
                                
                                if measurement_unit == 'kg' or nome_cru.upper().endswith(' KG'):
                                    unidade_venda = "KG"
                                else:
                                    unidade_venda = "UN"
                                        
                                if nome_cru.endswith(" KG"):
                                    unidade_venda = "KG"
                                    if qv == "1" and med == "UN":
                                        qv, med = "1", "KG"
                                        
                                nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()

                                if p_atacado <= 0: continue
                                if p_varejo <= 0 or p_varejo < p_atacado: p_varejo = p_atacado

                                link_pdp_rel = p.get('slug') or p.get('linkText') or p.get('link') or ''
                                if link_pdp_rel:
                                    if link_pdp_rel.startswith('http'):
                                        link_pdp = link_pdp_rel
                                    elif link_pdp_rel.startswith('/'):
                                        link_pdp = f"https://www.atacadao.com.br{link_pdp_rel}"
                                    else:
                                        link_pdp = f"https://www.atacadao.com.br/{link_pdp_rel}/p"
                                else:
                                    link_pdp = ""

                                produtos_categoria.append({
                                    "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_site_cru,
                                    "Produto": nome_limpo, "Marca": marca_str,
                                    "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','), "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv, "Medida": med, "Unidade": unidade_venda,
                                    "Condição": condicao, "Data_Hora": agora, "Link_Imagem": imagem_url,
                                    "Link_PDP": link_pdp
                                })
                            except Exception:
                                continue
                        
                        if len(bloco_produtos) < PAGE_SIZE:
                            break
                        offset += PAGE_SIZE
                        if offset >= 2500: # Limite VTEX
                            logger.warning(f"   ⚠️ Categoria {cat_name} atingiu o limite de 2500 itens da VTEX: produtos além disso não foram coletados.")
                            break
                    except Exception as e:
                        logger.error(f"Erro na categoria {cat_name}: {e}")
                        break
            
            logger.info(f"   - Categoria {cat_name}: {len(produtos_categoria)} itens capturados.")
            return produtos_categoria

        tarefas = [process_category(cat_name, cat_facets) for cat_name, cat_facets in categorias_folhas]
        
        # Executa em lotes para controlar a memória
        chunk_size = 5
        for i in range(0, len(tarefas), chunk_size):
            chunk = tarefas[i:i+chunk_size]
            resultados_chunk = await asyncio.gather(*chunk)
            for res in resultados_chunk:
                lista_final.extend(res)

    logger.info(f"✅ Extração FULL concluída. {len(lista_final)} itens brutos capturados.")
    # Deduplicar
    lista_unica = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())
    logger.info(f"   Total únicos: {len(lista_unica)}")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_atacadao_full()
