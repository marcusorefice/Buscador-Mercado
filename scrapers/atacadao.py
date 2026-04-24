import os
import json
import warnings
import urllib.parse
import asyncio
import re
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

# AGORA USAMOS AS DUAS APIS SIMULTANEAMENTE:
URL_GRAPHQL = f"{BASE_URL_CONFIG}/api/graphql"
URL_LEGACY = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search"

REGIONALIZATION = CONFIG.get("regionalization", {})
SELLER_ID = REGIONALIZATION.get("seller_id", "atacadaobr633")
REGION_ID = REGIONALIZATION.get("region_id", "U1cjYXRhY2FkYW9icjYzMw==")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-772")
CLUSTER_OFERTAS = REGIONALIZATION.get("cluster_ofertas", "312")

PAGINATION = CONFIG.get("pagination", {})
PAGE_SIZE = PAGINATION.get("page_size", 50)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("playwright_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CONCURRENCY = TECHNICAL_DEPS.get("concurrency", 5)

async def motor_extracao_atacadao():
    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO} (Estratégia: Híbrida + Radar de Atacado)...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    cookie_str = f'{{"salesChannel":"1","postalCode":"{CEP_JUNDIAI}","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'
    
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.atacadao.com.br/catalogo",
        "Origin": "https://www.atacadao.com.br"
    }

    sem = asyncio.Semaphore(CONCURRENCY) 

    async def extrair_pagina_hibrida(session, offset, is_first=False, retries=3):
        async with sem:
            if not is_first:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                
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
            url_get = f"{URL_GRAPHQL}?{urllib.parse.urlencode(params)}"

            for tentativa in range(retries):
                try:
                    response = await session.get(url_get, timeout=45)
                    if response.status_code in [429, 503, 500, 502, 504]:
                        await asyncio.sleep(random.uniform(2.0, 4.0))
                        continue

                    response_json = response.json()
                    search_data = (response_json.get('data') or {}).get('search')
                    products_data = (search_data or {}).get('products')
                    
                    if not products_data:
                        return [], 0

                    bloco_produtos = products_data.get('edges', [])
                    total_items = products_data.get('pageInfo', {}).get('totalCount', 0) if is_first else 0
                    
                    # =========================================================
                    # PASSO MÁGICO: Cruzar EAN e Caçar Preços de Atacado
                    # =========================================================
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
                                    
                                    # EAN
                                    ean_real = "N/A"
                                    if items:
                                        ean_real = str(items[0].get('ean', '')).strip()
                                        if not ean_real or ean_real.lower() == "none" or len(ean_real) < 12:
                                            ean_real = "N/A"
                                            
                                    # Preços Legados Base
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
                                        
                                    # O CAÇADOR DE ATACADO (Regex nas Promos/Teasers)
                                    teasers = co.get('Teasers', [])
                                    promos = co.get('DiscountHighLight', [])
                                    todas_tags = teasers + promos
                                    
                                    for tag in todas_tags:
                                        nome_tag = str(tag.get('<Name>', tag.get('name', ''))).lower()
                                        # Regex busca: (Quantidade) + (UN/CX) + (Preço Decimal)
                                        # Ex: "A partir de 6 un. R$ 10,99"
                                        match = re.search(r'(\d+)\s*(?:un|unid|unidade|unidades|cx|caixa|pct|pacote)s?[^\d]*(\d+[.,]\d{2})', nome_tag)
                                        if match:
                                            qtd = match.group(1)
                                            valor_str = match.group(2).replace(',', '.')
                                            try:
                                                v_atacado = float(valor_str)
                                                if v_atacado > 0 and v_atacado <= p_var_legado:
                                                    p_ata_legado = v_atacado
                                                    cond_legada = f"A PARTIR DE {qtd} UN"
                                                    break # Achou a regra, pode parar
                                            except:
                                                pass
                                                
                                    mapa_dados[pid] = {
                                        'ean': ean_real,
                                        'p_varejo': p_var_legado,
                                        'p_atacado': p_ata_legado,
                                        'condicao': cond_legada
                                    }
                        except Exception as e_legado:
                            logger.warning(f"   - Omissão tolerada ao cruzar API Legada: {e_legado}")

                    # =========================================================
                    # MONTAGEM FINAL DOS PRODUTOS
                    # =========================================================
                    produtos_extraidos = []
                    for edge in bloco_produtos:
                        p = edge.get('node', {})
                        if not p: continue

                        try:
                            nome_cru = str(p.get('name', '')).upper().strip()
                            if not nome_cru: continue

                            pid = str(p.get('id', ''))
                            dados_legados = mapa_dados.get(pid, {})
                            
                            # EAN (Prioridade absoluta para o legado cruzado)
                            ean = dados_legados.get('ean') if dados_legados.get('ean') else str(p.get('gtin', 'N/A')).strip()

                            imagens = p.get('image', [])
                            imagem_url = imagens[0].get('url', "SEM IMAGEM") if imagens else "SEM IMAGEM"

                            # Puxa o preço básico da FastStore
                            ofertas_container = p.get('offers', {})
                            lista_ofertas = ofertas_container.get('offers', [{}])
                            offer_base = lista_ofertas[0] if lista_ofertas else {}
                            
                            p_varejo = float(offer_base.get('listPrice') if offer_base.get('listPrice') else offer_base.get('price', 0.0))
                            p_atacado = float(offer_base.get('price', 0.0))
                            condicao = "OFERTA" if p_atacado < p_varejo else "1 UN"
                            
                            # TENTA SOBRESCREVER COM AS REGRAS DE ATACADO DO NOSSO CAÇADOR
                            if dados_legados:
                                c_leg = dados_legados.get('condicao', '1 UN')
                                p_ata_leg = dados_legados.get('p_atacado', 0.0)
                                p_var_leg = dados_legados.get('p_varejo', 0.0)
                                
                                # Se o caçador encontrou uma regra de quantidade (ex: 3 UN)
                                if c_leg not in ["1 UN", "OFERTA"]:
                                    condicao = c_leg
                                    if p_ata_leg > 0: p_atacado = p_ata_leg
                                    if p_var_leg > p_varejo: p_varejo = p_var_leg
                                        
                                # Se o FastStore não deu oferta, mas o legado deu o De/Por
                                elif condicao == "1 UN" and c_leg == "OFERTA":
                                    condicao = "OFERTA"
                                    if p_ata_leg > 0: p_atacado = p_ata_leg
                                    if p_var_leg > 0: p_varejo = p_var_leg
                                    
                            # Tenta sobrescrever se o FastStore tiver a tabela embutida (raro, mas seguro)
                            if len(lista_ofertas) > 1 and condicao == "1 UN":
                                offer_atacado = lista_ofertas[-1]
                                p_ata_fs = float(offer_atacado.get('price', p_atacado))
                                min_qty = offer_atacado.get('minQuantity', 1)
                                if min_qty > 1 and p_ata_fs < p_varejo:
                                    p_atacado = p_ata_fs
                                    condicao = f"A PARTIR DE {min_qty} UN"

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

                            if p_atacado <= 0: continue
                            if p_varejo <= 0 or p_varejo < p_atacado: p_varejo = p_atacado

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
                    logger.warning(f"   [{NOME_MERCADO}] Falha no offset {offset} (Tentativa {tentativa+1}): {e}")
                    await asyncio.sleep(1.0)
            
            return [], 0

    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        session.cookies.set("regionalization", urllib.parse.quote(cookie_str), domain=urllib.parse.urlparse("https://www.atacadao.com.br").hostname)
        
        produtos_iniciais, total_items = await extrair_pagina_hibrida(session, 0, is_first=True)
        lista_final.extend(produtos_iniciais)
        
        if total_items > PAGE_SIZE:
            logger.info(f"   - API Nova informou {total_items} produtos. Mesclando condições de Atacado em paralelo...")
            
            offsets = [offset for offset in range(PAGE_SIZE, total_items, PAGE_SIZE)]
            tarefas = [extrair_pagina_hibrida(session, off) for off in offsets]
            resultados = await asyncio.gather(*tarefas)
            
            for res, _ in resultados:
                lista_final.extend(res)

    logger.info(f"✅ Extração Híbrida concluída. {len(lista_final)} itens brutos capturados.")
    return list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())

async def extrair_dados():
    return await motor_extracao_atacadao()