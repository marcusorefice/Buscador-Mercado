import os
import asyncio
import json
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import (
    padronizar_categoria, 
    extrair_medidas_inteligente, 
    setup_logging, 
    read_json_file,
    MAPA_PARA_APP, CATEGORIAS_IGNORADAS
)

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

                        # Extração de Preços (sellPrice é o final, priceFrom é o antigo)
                        p_venda = float(p.get('price', 0))
                        p_varejo = float(p.get('priceFrom', p_venda))

                        if p_venda <= 0: continue

                        # --- NOVA LÓGICA DE TAXONOMIA ---
                        categorias_api = p.get('categories', []) # Ex: ["/Mercearia/Biscoitos/"]
                        cat_site = ""
                        subcategoria = "N/A"
                        tipo_produto = "N/A"

                        if categorias_api and isinstance(categorias_api, list) and categorias_api[0]:
                            partes_cat = categorias_api[0].strip('/').split('/')
                            if len(partes_cat) > 0: cat_site = partes_cat[0].upper()
                            if len(partes_cat) > 1: subcategoria = partes_cat[1].upper()
                            if len(partes_cat) > 2: tipo_produto = partes_cat[2].upper()

                        if cat_site in CATEGORIAS_IGNORADAS:
                            continue

                        categoria = MAPA_PARA_APP.get(cat_site, padronizar_categoria(nome_bruto, cat_site))

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

                        # 2. Cliente Mais (Se o preço atual for menor que o De/Por)
                        if p_venda < p_varejo:
                            condicoes.append("CLIENTE MAIS")

                        # 3. Fallback: 1un se não houver promo
                        txt_condicao = " | ".join(list(set(condicoes))) if condicoes else "1un"

                        # Imagem (prepend do domínio)
                        img_path = p.get('productImages', [None])[0]
                        img_url = f"{BASE_URL_CONFIG}{img_path.lstrip('/')}" if img_path else ""

                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                        
                        lista_final.append({
                            "Mercado": NOME_MERCADO,
                            "Categoria": categoria,
                            "subcategoria": subcategoria,
                            "tipo_produto": tipo_produto,
                            "Produto": nome_limpo,
                            "Marca": str(p.get('brand', 'PRÓPRIA')).upper(),
                            "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                            "Preço Atacado": f"R$ {p_venda:.2f}".replace('.', ','),
                            "Qtd_Valor": qv,
                            "Medida": med,
                            "Unidade": "UN",
                            "Condição": txt_condicao,
                            "Validade": "VER NO SITE",
                            "Data_Hora": agora,
                            "Link_Imagem": img_url
                        })
                    except: continue

                pagina_atual += 1
                await asyncio.sleep(RATE_LIMIT_DELAY)

    except Exception as e:
        logger.error(f"❌ Erro crítico no motor Pão de Açúcar: {e}")

    lista_unica = list({v['Produto']: v for v in lista_final}.values())
    logger.info(f"🏆 SUCESSO! {len(lista_unica)} ofertas únicas capturadas do {NOME_MERCADO}.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_paodeacucar()