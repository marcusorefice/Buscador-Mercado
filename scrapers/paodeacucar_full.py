import os
import asyncio
import json
import re
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import (
    padronizar_categoria, 
    extrair_medidas_inteligente, 
    setup_logging, 
    read_json_file,
    CATEGORIAS_IGNORADAS,
    formatar_nome_categoria
)

logger = setup_logging()

SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'paodeacucar_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Pão de Açúcar")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.paodeacucar.com/").rstrip('/')
TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
CONCURRENCY = 15

async def extract_links_from_home(session):
    headers = {"User-Agent": USER_AGENT}
    try:
        res = await session.get(f"{BASE_URL_CONFIG}/", headers=headers, timeout=20)
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            logger.error("❌ NEXT DATA não encontrado na página inicial.")
            return []
            
        data = json.loads(match.group(1))
        
        def extract_links(node):
            links = []
            if isinstance(node, dict):
                link = node.get('link') or (node.get('attributes') and node.get('attributes').get('link'))
                if link and isinstance(link, str) and ('/secoes/' in link or '/categoria/' in link or '/especial/' in link):
                    links.append(link.split('?')[0]) # Remove query params for clean URLs
                for k, v in node.items():
                    links.extend(extract_links(v))
            elif isinstance(node, list):
                for item in node:
                    links.extend(extract_links(item))
            return links

        links = extract_links(data)
        unique_links = list(set(links))
        return unique_links
    except Exception as e:
        logger.error(f"Erro ao extrair links da home: {e}")
        return []

async def motor_extracao_paodeacucar_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        logger.info("   Obtendo árvore de links da home...")
        links = await extract_links_from_home(session)
        logger.info(f"   Foram encontradas {len(links)} subcategorias/páginas especiais.")

        if not links:
            return []

        # Para cada link, vamos carregar a página e extrair os produtos
        async def process_link(link_path):
            produtos_categoria = []
            url = f"{BASE_URL_CONFIG}{link_path}" if link_path.startswith('/') else link_path
            
            async with sem:
                try:
                    res = await session.get(url, timeout=30)
                    if res.status_code != 200:
                        return []
                        
                    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
                    if not match:
                        return []
                        
                    data = json.loads(match.group(1))
                    props = data.get("props", {}).get("initialState", {})
                    
                    produtos_raw = []
                    # Verifica diferentes possiveis caminhos para os produtos
                    if "category" in props and "products" in props["category"]:
                        produtos_raw = props["category"]["products"]
                    elif "search" in props and "productList" in props["search"]:
                        produtos_raw = props["search"]["productList"]
                    elif "department" in props and "products" in props["department"]:
                        produtos_raw = props["department"]["products"]
                    elif "specialPage" in props and "products" in props["specialPage"]:
                        produtos_raw = props["specialPage"]["products"]
                    
                    if not produtos_raw:
                        return []
                        
                    for p in produtos_raw:
                        try:
                            nome_bruto = str(p.get('name', '')).upper().strip()
                            if not nome_bruto: continue

                            # EAN Logic
                            ean = ""
                            ean = str(p.get('ean', '')).strip()
                            if not ean or len(ean) < 13:
                                ean = str(p.get('gtin', '')).strip()
                            if not ean or len(ean) < 13:
                                sku = str(p.get('sku', '')).strip()
                                if len(sku) == 13 and sku.isdigit():
                                    ean = sku
                            if not ean or ean == '0': ean = 'N/A'

                            # Preços
                            sell_infos = p.get('sellInfos', [{}])
                            sell_info = sell_infos[0] if sell_infos else {}
                            
                            p_varejo_bruto = sell_info.get('sellPrice') or p.get('priceFrom')
                            p_venda_bruto = sell_info.get('currentPrice') or p.get('price')
                            
                            p_varejo = float(p_varejo_bruto) if p_varejo_bruto else 0.0
                            p_venda = float(p_venda_bruto) if p_venda_bruto else 0.0
                            
                            if p_varejo <= 0 and p_venda > 0: p_varejo = p_venda
                            if p_venda <= 0 and p_varejo > 0: p_venda = p_varejo
                            p_atacado = p_venda

                            if p_venda <= 0: continue

                            preco_cliente_mais = p.get('clienteMaisPrice') or p.get('promotionalPrice')
                            if preco_cliente_mais:
                                try:
                                    cm_val = float(preco_cliente_mais)
                                    if 0 < cm_val < p_atacado: p_atacado = cm_val
                                except: pass

                            # Categoria
                            categorias_api = p.get('categories', [])
                            cat_site = "GERAL"
                            subcategoria = "N/A"
                            tipo_produto = "N/A"

                            if categorias_api and isinstance(categorias_api, list) and categorias_api[0]:
                                partes_cat = categorias_api[0].strip('/').split('/')
                                cat_site = partes_cat[0].upper() if len(partes_cat) > 0 else "GERAL"
                                if len(partes_cat) > 1: subcategoria = formatar_nome_categoria(partes_cat[1])
                                if len(partes_cat) > 2: tipo_produto = formatar_nome_categoria(partes_cat[2])
                            else:
                                if p.get('departmentName'):
                                    cat_site = str(p.get('departmentName')).upper()
                                elif p.get('categoryName'):
                                    cat_site = str(p.get('categoryName')).upper()

                            if cat_site in CATEGORIAS_IGNORADAS: continue
                            
                            full_context = f"{nome_bruto} {cat_site} {subcategoria} {tipo_produto}"
                            categoria = padronizar_categoria(full_context, cat_site)
                            
                            # Condições
                            condicoes = []
                            promos = p.get('productPromotions', [])
                            if not promos and p.get('productPromotion'):
                                promos = [p.get('productPromotion')]

                            for pr in promos:
                                buy = pr.get('promotionQuantityBuy')
                                pay = pr.get('promotionQuantityPayFor')
                                if buy and pay and buy > pay:
                                    condicoes.append(f"LEVE {buy} PAGUE {pay}")
                                    preco_com_desconto = (p_varejo * pay) / buy
                                    if preco_com_desconto < p_atacado: p_atacado = preco_com_desconto

                                promo_price = pr.get('unitPrice') or pr.get('promotionPrice') or pr.get('price') or pr.get('discountPrice')
                                if promo_price:
                                    try:
                                        promo_price_val = float(promo_price)
                                        if 0 < promo_price_val < p_atacado: p_atacado = promo_price_val
                                    except: pass
                                        
                                discount_percent = pr.get('promotionPercentOff') or pr.get('discountPercentage') or pr.get('discountValue')
                                if discount_percent and not promo_price:
                                    try:
                                        pct = float(discount_percent)
                                        if pct > 0:
                                            preco_com_desconto = p_varejo * (1 - (pct / 100))
                                            if 0 < preco_com_desconto < p_atacado: p_atacado = preco_com_desconto
                                    except: pass

                            if p_atacado < p_varejo or p_venda < p_varejo:
                                condicoes.append("CLIENTE MAIS (CPF)")

                            txt_condicao = " | ".join(list(set(condicoes))) if condicoes else "1 UN"

                            img_path = p.get('productImages', [None])[0]
                            img_url = f"{BASE_URL_CONFIG}/{img_path.lstrip('/')}" if img_path else ""

                            nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                            
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

                            produtos_categoria.append({
                                "EAN": ean,
                                "Mercado": NOME_MERCADO,
                                "Categoria": categoria,
                                "subcategoria": subcategoria,
                                "tipo_produto": tipo_produto,
                                "Produto": nome_limpo,
                                "Marca": str(p.get('brand', 'PRÓPRIA')).upper(),
                                "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                                "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                                "Qtd_Valor": qv,
                                "Medida": med,
                                "Unidade": unidade_venda,
                                "Condição": txt_condicao, "Data_Hora": agora,
                                "Link_Imagem": img_url,
                                "Link_PDP": link_pdp,
                                "ID_UNICO": p.get('sku') or f"{nome_bruto}_{p.get('brand', 'PROPRIA')}"
                            })
                        except Exception as e:
                            continue
                    return produtos_categoria
                except Exception as e:
                    return []

        # Process batches of links to avoid overwhelming memory/connections
        chunk_size = 50
        for i in range(0, len(links), chunk_size):
            chunk_links = links[i:i+chunk_size]
            logger.info(f"   ⏳ Processando lote {i//chunk_size + 1}/{(len(links)-1)//chunk_size + 1} de {chunk_size} links...")
            tarefas = [process_link(link) for link in chunk_links]
            resultados = await asyncio.gather(*tarefas)
            for res in resultados:
                if res: lista_final.extend(res)
            # await asyncio.sleep(0.5)

    # Deduplication
    produtos_unicos_dict = {v['ID_UNICO']: v for v in lista_final}
    lista_unica = list(produtos_unicos_dict.values())
    for item in lista_unica: item.pop("ID_UNICO", None)
    
    logger.info(f"🏆 SUCESSO! {len(lista_unica)} ofertas únicas capturadas do {NOME_MERCADO} Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_paodeacucar_full()
