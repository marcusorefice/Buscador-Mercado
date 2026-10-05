import os
import asyncio
import json
import re
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import setup_logging, read_json_file


logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'paodeacucar_spec.json')
CONFIG = read_json_file(SPEC_FILE)

# ==========================================
# CONFIGURAÇÕES DO PÃO DE AÇÚCAR
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "Pão de Açúcar")
API_URL = CONFIG.get("api_endpoint", "https://api.vendas.gpa.digital/pa/special-page")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.paodeacucar.com/").rstrip('/')

REGIONALIZATION = CONFIG.get("regionalization", {})
STORE_ID = int(REGIONALIZATION.get("store_id", 461))
# O 'terms' aqui é o slug da página de ofertas. Ele pode mudar com o tempo.
TERMS = REGIONALIZATION.get("terms", "ofertasdodia-pao2023")

PAGE_SIZE = CONFIG.get("pagination", {}).get("page_size", 50)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
RATE_LIMIT_DELAY = TECHNICAL_DEPS.get("rate_limit_delay", 0.3)

async def motor_extracao_paodeacucar():
    """
    Motor Sniper Linx - Bate na API de alta performance do Pão de Açúcar.
    Captura 1.200+ ofertas paginando de 50 em 50.
    """
    logger.info(f"🚀 Iniciando Varredura Total - {NOME_MERCADO} Jundiaí")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    headers = {
        "User-Agent": USER_AGENT,
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": BASE_URL_CONFIG,
        "referer": f"{BASE_URL_CONFIG}/"
    }

    try:
        async with AsyncSession(impersonate=IMPERSONATE) as s:
            pagina_atual = 1
            total_paginas = 1 # Será atualizado na primeira chamada

            while pagina_atual <= total_paginas:
                # Payload idêntico ao seu log de sucesso
                payload = {
                    "partner": "linx",
                    "page": pagina_atual,
                    "resultsPerPage": PAGE_SIZE,
                    "terms": TERMS,
                    "sortBy": "relevance",
                    "department": "ecom",
                    "storeId": STORE_ID,
                    "customerPlus": True,
                    "filters": []
                }

                logger.info(f"    📡 Coletando página {pagina_atual} de {total_paginas}...")
                res = await s.post(API_URL, json=payload, headers=headers, timeout=30)
                
                if res.status_code != 200:
                    logger.error(f"    ❌ Falha na página {pagina_atual}: Status {res.status_code}")
                    break

                data = res.json()
                
                # Atualiza o total de páginas na primeira rodada
                if pagina_atual == 1:
                    total_paginas = data.get('totalPages', 1)
                    total_produtos = data.get('totalProducts', 0)
                    logger.info(f"    📊 Total detectado: {total_produtos} produtos em {total_paginas} páginas.")

                produtos = data.get('products', [])
                if not produtos:
                    break

                for p in produtos:
                    try:
                        nome_bruto = str(p.get('name', '')).upper().strip()
                        if not nome_bruto: continue
                        ean = str(p.get('ean', 'N/A')).strip()

                        # --- LÓGICA DE EXTRAÇÃO DE EAN (MELHOR ESFORÇO) ---
                        # A API de ofertas raramente fornece o EAN. Esta lógica tenta encontrá-lo em vários campos.
                        ean = ""
                        # 1. Tenta o campo 'ean'
                        ean = str(p.get('ean', '')).strip()
                        # 2. Tenta o campo 'gtin' se o 'ean' falhar
                        if not ean or len(ean) < 13:
                            ean = str(p.get('gtin', '')).strip()
                        # 3. Tenta o campo 'sku', mas apenas se tiver 13 dígitos (formato EAN-13)
                        if not ean or len(ean) < 13:
                            sku = str(p.get('sku', '')).strip()
                            if len(sku) == 13 and sku.isdigit():
                                ean = sku
                        # 4. Define o valor final como 'N/A' se nada for encontrado
                        if not ean or ean == '0': ean = 'N/A'

                        # Extração da URL da página de detalhes do produto (PDP)
                        link_pdp_rel = p.get('urlDetails', '') or p.get('url', '')
                        if link_pdp_rel:
                            if link_pdp_rel.startswith('http'):
                                link_pdp = link_pdp_rel
                            elif link_pdp_rel.startswith('/'):
                                link_pdp = f"{BASE_URL_CONFIG}{link_pdp_rel}"
                            else:
                                link_pdp = f"{BASE_URL_CONFIG}/{link_pdp_rel}"
                        else:
                            link_pdp = ""

                        # Extração de Preços via sellInfos
                        sell_infos = p.get('sellInfos', [{}])
                        sell_info = sell_infos[0] if sell_infos else {}
                        
                        # Fallback para os campos antigos caso a API omita o sellInfos em algum item
                        p_varejo_bruto = sell_info.get('sellPrice') or p.get('priceFrom')
                        p_venda_bruto = sell_info.get('currentPrice') or p.get('price')
                        
                        p_varejo = float(p_varejo_bruto) if p_varejo_bruto else 0.0
                        p_venda = float(p_venda_bruto) if p_venda_bruto else 0.0
                        
                        if p_varejo <= 0 and p_venda > 0: p_varejo = p_venda
                        if p_venda <= 0 and p_varejo > 0: p_venda = p_varejo

                        p_atacado = p_venda

                        if p_venda <= 0: continue

                        # Resgate de preços especiais (Cliente Mais) ocultos na raiz do item
                        preco_cliente_mais = p.get('clienteMaisPrice') or p.get('promotionalPrice')
                        if preco_cliente_mais:
                            try:
                                cm_val = float(preco_cliente_mais)
                                if 0 < cm_val < p_atacado:
                                    p_atacado = cm_val
                            except: pass

                        # Captura as categorias da API
                        categorias_api = p.get('categories', [])
                        cat_site = "GERAL"
                        subcategoria = "N/A"
                        tipo_produto = "N/A"

                        if categorias_api and isinstance(categorias_api, list) and categorias_api[0]:
                            partes_cat = categorias_api[0].strip('/').split('/')
                            cat_site = partes_cat[0].upper() if len(partes_cat) > 0 else "GERAL"
                            if len(partes_cat) > 1: subcategoria = partes_cat[1]
                            if len(partes_cat) > 2: tipo_produto = partes_cat[2]
                        else:
                            if p.get('departmentName'):
                                cat_site = str(p.get('departmentName')).upper()
                            elif p.get('categoryName'):
                                cat_site = str(p.get('categoryName')).upper()

                        # VERIFICAÇÃO DE CATEGORIA (Adicione um log aqui para saber o que está sendo pulado)

                        # Usa o contexto completo para uma categorização mais precisa, evitando erros da API de origem.
                        full_context = f"{nome_bruto} {cat_site} {subcategoria} {tipo_produto}"
                        categoria = cat_site
                        
                        # --- LÓGICA DE CONDIÇÕES ---
                        condicoes = []
                        
                        # 1. Promoções de Quantidade (Leve 4 Pague 2)
                        # O campo pode estar em productPromotion (singular) ou productPromotions (lista)
                        promos = p.get('productPromotions', [])
                        if not promos and p.get('productPromotion'):
                            promos = [p.get('productPromotion')]

                        for pr in promos:
                            buy = pr.get('promotionQuantityBuy')
                            pay = pr.get('promotionQuantityPayFor')
                            if buy and pay and buy > pay:
                                condicoes.append(f"LEVE {buy} PAGUE {pay}")
                                # Calcula o preço unitário aplicando o desconto sobre o preço cheio
                                preco_com_desconto = (p_varejo * pay) / buy
                                if preco_com_desconto < p_atacado:
                                    p_atacado = preco_com_desconto

                            # Busca preços de desconto direto na promoção (Ex: unitPrice do Cliente Mais)
                            promo_price = pr.get('unitPrice') or pr.get('promotionPrice') or pr.get('price') or pr.get('discountPrice')
                            if promo_price:
                                try:
                                    promo_price_val = float(promo_price)
                                    if 0 < promo_price_val < p_atacado:
                                        p_atacado = promo_price_val
                                except: pass
                                    
                            # Busca descontos percentuais explícitos
                            discount_percent = pr.get('promotionPercentOff') or pr.get('discountPercentage') or pr.get('discountValue')
                            if discount_percent and not promo_price:
                                try:
                                    pct = float(discount_percent)
                                    if pct > 0:
                                        preco_com_desconto = p_varejo * (1 - (pct / 100))
                                        if 0 < preco_com_desconto < p_atacado:
                                            p_atacado = preco_com_desconto
                                except: pass

                        # 2. Cliente Mais (Se o preço no atacado ficou menor que o De/Por original)
                        if p_atacado < p_varejo or p_venda < p_varejo:
                            condicoes.append("CLIENTE MAIS (CPF)")

                        # 3. Fallback: 1un se não houver promo
                        txt_condicao = " | ".join(list(set(condicoes))) if condicoes else "1 UN"

                        # Imagem (prepend do domínio)
                        img_path = p.get('productImages', [None])[0]
                        # Adicionamos a barra / manualmente entre as chaves
                        img_url = f"{BASE_URL_CONFIG}/{img_path.lstrip('/')}" if img_path else ""

                        nome_limpo, qv, med = nome_bruto, "1", "UN"
                        
                        unidade_venda = "UN"
                        if str(p.get('unit', '')).lower() == 'kg' or str(p.get('measurementUnit', '')).lower() == 'kg':
                            unidade_venda = "KG"
                            if qv == "1" and med == "UN":
                                qv, med = "1", "KG"
                                
                        if nome_bruto.endswith(" KG"):
                            unidade_venda = "KG"
                            if qv == "1" and med == "UN":
                                qv, med = "1", "KG"
                                
                        nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()
                        
                        # USAMOS O SKU OU NOME+MARCA PARA EVITAR APAGAR ITENS REPETIDOS
                        # O SKU, se disponível, é um identificador único mais confiável para evitar colisões
                        # e garantir a integridade dos dados durante a deduplicação.
                        sku = p.get('sku')
                        if sku:
                            id_unico = str(sku)
                        else:
                            id_unico = f"{nome_bruto}_{p.get('brand', 'PROPRIA')}"
                        lista_final.append({
                            "ID_UNICO": id_unico, # Campo temporário para não perder dados
                            "EAN": ean,
                            "Mercado": NOME_MERCADO,
                            "Categoria": categoria,
                            "subcategoria": subcategoria,
                            "tipo_produto": tipo_produto,
                            "Produto": nome_limpo,
                            "Marca": str(p.get('brand', 'PRÓPRIA')).upper(),
                            "Preço Varejo": round(p_varejo, 2),
                            "Preço Atacado": round(p_atacado, 2),
                            "Qtd_Valor": qv,
                            "Medida": med,
                            "Unidade": unidade_venda,
                            "Condição": txt_condicao, "Data_Hora": agora,
                            "Link_Imagem": img_url,
                            "Link_PDP": link_pdp
                        })
                    except Exception as e:
                        # Agora você sabe por que o item foi ignorado
                        logger.warning(f"⚠️ Item ignorado por erro técnico: {nome_bruto} | Erro: {e}")
                        continue

                pagina_atual += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)

    except Exception as e:
        logger.error(f"❌ Erro crítico no motor Pão de Açúcar: {e}")

    # --- ETAPA DE DEDUPLICAÇÃO ---
    # A API pode retornar o mesmo produto várias vezes se ele estiver em múltiplas categorias promocionais.
    # Usamos um dicionário com a chave 'ID_UNICO' (SKU ou Nome+Marca) para garantir que cada produto apareça apenas uma vez.
    # O dicionário por si só já garante a unicidade pela chave.
    produtos_unicos_dict = {v['ID_UNICO']: v for v in lista_final}
    lista_unica = list(produtos_unicos_dict.values())

    # Realiza a busca de EAN por página dos produtos
    async with AsyncSession(impersonate=IMPERSONATE) as s:
        await enrich_eans_from_pdps(s, lista_unica)

    # Limpa a chave temporária 'ID_UNICO' de cada item na lista final para garantir
    # a compatibilidade com o banco de dados, que não possui essa coluna.
    for item in lista_unica: item.pop("ID_UNICO", None)
    
    logger.info(f"🏆 SUCESSO! {len(lista_unica)} ofertas únicas capturadas do {NOME_MERCADO}.")
    return lista_unica

async def fetch_ean_from_pdp(session, url_pdp, sem_pdp):
    """Busca o EAN e Categorias no HTML da página de detalhes do produto do Pão de Açúcar"""
    result = {"ean": "N/A", "cat": "", "subcat": "N/A", "tipo": "N/A"}
    if not url_pdp: return result
    
    headers = {
        "User-Agent": USER_AGENT,
    }
    
    async with sem_pdp:
        try:
            res = await session.get(url_pdp, headers=headers, timeout=20)
            if res.status_code == 200:
                html = res.text
                # 1. Tenta padrão explícito (gtin, ean com 13 dígitos)
                match = re.search(r'(?:gtin\d*|ean)["\s:]+["\s]*(\d{13})', html, re.IGNORECASE)
                if match:
                    result["ean"] = match.group(1)
                else:
                    # 2. Fallback: Qualquer sequência de 13 dígitos começando com 789 ou 790 ou 871
                    match_any = re.search(r'(789\d{10}|790\d{10}|871\d{10})', html)
                    if match_any:
                        result["ean"] = match_any.group(1)
                
                # Extração de categorias
                match_next = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
                if match_next:
                    data = json.loads(match_next.group(1))
                    product_data = data.get('props', {}).get('pageProps', {}).get('product', {})
                    shelf_list = product_data.get('shelfList', [])
                    if shelf_list:
                        cats = [s.get('name', '').upper() for s in shelf_list if s.get('name')]
                        if len(cats) > 0: result["cat"] = cats[0]
                        if len(cats) > 1: result["subcat"] = cats[1]
                        if len(cats) > 2: result["tipo"] = cats[2]
                
                # Tenta extração via LD+JSON se o formato anterior falhou
                if not result["cat"]:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        for script in soup.find_all('script', type='application/ld+json'):
                            try:
                                data = json.loads(script.string)
                                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                                    items = data.get('itemListElement', [])
                                    if items:
                                        cats = [i.get('item', {}).get('name', '').upper() for i in items if i.get('item', {}).get('name')]
                                        if len(cats) > 0 and cats[0] == 'HOME': cats = cats[1:]
                                        if len(cats) > 0: result["cat"] = cats[0]
                                        if len(cats) > 1: result["subcat"] = cats[1]
                                        if len(cats) > 2: result["tipo"] = cats[2]
                            except: pass
                    except: pass
        except:
            pass
            
    return result

async def enrich_eans_from_pdps(session, lista_produtos):
    """Enriquece produtos sem EAN ou Categoria buscando na página do produto (PDP)"""
    sem_pdp = asyncio.Semaphore(50) # Concorrência Aumentada
    
    produtos_pendentes = [p for p in lista_produtos if not p.get('EAN') or p.get('EAN') == 'N/A' or not p.get('Categoria') or p.get('Categoria') == 'GERAL']
    if not produtos_pendentes: return
    
    total_pdps = len(produtos_pendentes)
    logger.info(f"   🔍 Buscando EAN e Categorias em {total_pdps} páginas de produtos (Turbo Mode)...")
    
    contador = 0
    async def fetch_and_log(p):
        nonlocal contador
        res = await fetch_ean_from_pdp(session, p.get('Link_PDP'), sem_pdp)
        contador += 1
        if contador % 50 == 0 or contador == total_pdps:
            logger.info(f"   ⏳ [Pão de Açúcar] Progresso PDPs: {contador}/{total_pdps} processados...")
        return res

    # Criar lista de tasks mantendo a referência do produto
    tasks = [fetch_and_log(p) for p in produtos_pendentes]
        
    resultados = await asyncio.gather(*tasks)
    
    # Atualiza os dados encontrados
    for p, res in zip(produtos_pendentes, resultados):
        if res['ean'] != 'N/A' and (not p.get('EAN') or p.get('EAN') == 'N/A'):
            p['EAN'] = res['ean']
        if res['cat']:
            cat_site = res['cat']
            subcat = res['subcat']
            tipo = res['tipo']
            
            p['Categoria'] = cat_site
            p['subcategoria'] = subcat
            p['tipo_produto'] = tipo
            
async def extrair_dados():
    # ...
    # Essa chamada agora será gerida dentro do motor_extracao_paodeacucar, então no final dessa função vamos só chamar o motor
    return await motor_extracao_paodeacucar()