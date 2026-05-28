import os
import asyncio
import json
from datetime import datetime
from curl_cffi.requests import AsyncSession
from utils import (
    padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file,
    CATEGORIAS_IGNORADAS, formatar_nome_categoria
)

logger = setup_logging()

SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'paodeacucar_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Pão de Açúcar")
API_URL = "https://api.vendas.gpa.digital/pa/products/search"
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.paodeacucar.com/").rstrip('/')
URL_CATEGORY_TREE = f"{BASE_URL_CONFIG}/api/catalog_system/pub/category/tree/3" # Pode não funcionar se for SPA puro sem SSR legada

REGIONALIZATION = CONFIG.get("regionalization", {})
STORE_ID = int(REGIONALIZATION.get("store_id", 461))

PAGE_SIZE = CONFIG.get("pagination", {}).get("page_size", 50)
TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome120")
USER_AGENT = TECHNICAL_DEPS.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
RATE_LIMIT_DELAY = TECHNICAL_DEPS.get("rate_limit_delay", 0.3)
CONCURRENCY = 3

# O Pão de Açúcar usa Linx/GPA API, que precisa de departamento para listar tudo.
# Vamos buscar os departamentos via API ou fixar os principais se a API falhar.

DEPARTAMENTOS_PAO = [
    "mercearia", "carnes-e-aves", "peixaria", "frios-e-laticinios", "hortifruti",
    "bebidas", "bebidas-alcoolicas", "limpeza", "higiene-e-perfumaria",
    "padaria-e-confeitaria", "congelados", "pet-shop", "saudaveis", "bebes-e-criancas"
]

async def motor_extracao_paodeacucar_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    headers = {
        "User-Agent": USER_AGENT,
        "accept": "application/json",
        "content-type": "application/json",
        "origin": BASE_URL_CONFIG,
        "referer": f"{BASE_URL_CONFIG}/"
    }

    sem = asyncio.Semaphore(CONCURRENCY)

    async with AsyncSession(impersonate=IMPERSONATE) as session:
        async def process_department(dept_slug):
            produtos_departamento = []
            pagina_atual = 1
            total_paginas = 1
            
            while pagina_atual <= total_paginas:
                async with sem:
                    payload = {
                        "partner": "linx",
                        "page": pagina_atual,
                        "resultsPerPage": PAGE_SIZE,
                        "department": dept_slug,
                        "storeId": STORE_ID,
                        "customerPlus": True,
                        "filters": []
                    }
                    try:
                        res = await session.post(API_URL, json=payload, headers=headers, timeout=30)
                        if res.status_code != 200: break
                        
                        data = res.json()
                        if pagina_atual == 1:
                            total_paginas = min(data.get('totalPages', 1), 50) # Limita a 50 páginas (2500 itens) por depto para não travar
                        
                        produtos = data.get('products', [])
                        if not produtos: break
                        
                        for p in produtos:
                            try:
                                nome_bruto = str(p.get('name', '')).upper().strip()
                                if not nome_bruto: continue
                                
                                categorias_api = p.get('categories', [])
                                cat_site = dept_slug.upper()
                                if categorias_api and isinstance(categorias_api, list) and categorias_api[0]:
                                    partes_cat = categorias_api[0].strip('/').split('/')
                                    cat_site = partes_cat[0].upper() if len(partes_cat) > 0 else dept_slug.upper()

                                if cat_site in CATEGORIAS_IGNORADAS: continue

                                ean = str(p.get('ean', '')).strip()
                                if not ean or len(ean) < 13: ean = str(p.get('gtin', '')).strip()
                                if not ean or len(ean) < 13:
                                    sku = str(p.get('sku', '')).strip()
                                    if len(sku) == 13 and sku.isdigit(): ean = sku
                                if not ean or ean == '0': ean = 'N/A'

                                sell_infos = p.get('sellInfos', [{}])
                                sell_info = sell_infos[0] if sell_infos else {}
                                
                                p_varejo = float(sell_info.get('sellPrice') or p.get('priceFrom') or 0.0)
                                p_venda = float(sell_info.get('currentPrice') or p.get('price') or 0.0)
                                
                                if p_varejo <= 0 and p_venda > 0: p_varejo = p_venda
                                if p_venda <= 0 and p_varejo > 0: p_venda = p_varejo
                                if p_venda <= 0: continue
                                
                                p_atacado = p_venda
                                preco_cliente_mais = p.get('clienteMaisPrice') or p.get('promotionalPrice')
                                if preco_cliente_mais:
                                    try:
                                        cm_val = float(preco_cliente_mais)
                                        if 0 < cm_val < p_atacado: p_atacado = cm_val
                                    except: pass

                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                                
                                img_path = p.get('productImages', [None])[0]
                                img_url = f"{BASE_URL_CONFIG}/{img_path.lstrip('/')}" if img_path else ""

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

                                produtos_departamento.append({
                                    "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_site,
                                    "Produto": nome_limpo, "Marca": str(p.get('brand', 'PRÓPRIA')).upper(),
                                    "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                                    "Preço Atacado": f"R$ {p_atacado:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv, "Medida": med, "Unidade": "UN", "Condição": "1 UN",
                                    "Data_Hora": agora, "Link_Imagem": img_url,
                                    "Link_PDP": link_pdp
                                })
                            except: continue
                        pagina_atual += 1
                        await asyncio.sleep(RATE_LIMIT_DELAY)
                    except: break
            logger.info(f"   - Departamento {dept_slug}: {len(produtos_departamento)} itens capturados.")
            return produtos_departamento

        tarefas = [process_department(dept) for dept in DEPARTAMENTOS_PAO]
        for i in range(0, len(tarefas), 5):
            resultados_chunk = await asyncio.gather(*tarefas[i:i+5])
            for res in resultados_chunk: lista_final.extend(res)

    lista_unica = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())
    logger.info(f"✅ {len(lista_unica)} produtos totais capturados no {NOME_MERCADO} Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_paodeacucar_full()
