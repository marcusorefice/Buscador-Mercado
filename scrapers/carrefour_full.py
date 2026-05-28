import os
import asyncio
import warnings
import json
import re
from datetime import datetime
from curl_cffi import requests
from utils import (
    extrair_medidas_inteligente, setup_logging, 
    read_json_file, formatar_nome_categoria, normalizar_para_cache,
    CATEGORIAS_IGNORADAS
)

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES (SPECS)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'carrefour_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Carrefour")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://mercado.carrefour.com.br/").rstrip('/')

REGIONALIZATION = CONFIG.get("regionalization", {})
REGION_ID = REGIONALIZATION.get("region_id", "InYyLjc5MDlFOEZDNjU2N0M3OTU5NjA4MDFCQTU5RDFFMEQ3Ig==")
CEP_COOKIE_VALUE = REGIONALIZATION.get("cep_cookie_value", "IkhpcGVyIEp1bmRpYcOtIg==")

PAGE_SIZE = 50
CONCURRENCY = 5

def reconstruir_json_remix(dados_flat, index=0):
    if index is None or not (0 <= index < len(dados_flat)): return None
    node = dados_flat[index]
    if isinstance(node, list): return [reconstruir_json_remix(dados_flat, i) for i in node]
    if isinstance(node, dict):
        res = {}
        for k, v in node.items():
            if k.startswith('_'):
                try:
                    key_idx = int(k[1:])
                    chave_real = reconstruir_json_remix(dados_flat, key_idx)
                    res[chave_real] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
                except: continue
            else:
                res[k] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
        return res
    return node

def extrair_ean_pela_foto(url_imagem):
    if not url_imagem or not isinstance(url_imagem, str): return None
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    return match.group(1) if match else None

async def capturar_sessao():
    return {"region-id-food": REGION_ID, "cep": CEP_COOKIE_VALUE}

async def extrair_lote_departamento(session, cat_name, ordem, pagina, sem, agora, indice_reverso):
    # O Carrefour Remix precisa da rota exata. Vamos tentar as duas mais comuns para listagens:
    rotas = [
        "layout%2Fdefault%2Croutes%2F%24department",
        "layout%2Fdefault%2Croutes%2F%24category"
    ]
    
    async with sem:
        for rota in rotas:
            url = f"{BASE_URL_CONFIG}/{cat_name}.data?count={PAGE_SIZE}&page={pagina}&sort={ordem}&_routes={rota}"
            try:
                res = await session.get(url, timeout=30)
                if res.status_code == 200:
                    dados_brutos = res.json()
                    dados = reconstruir_json_remix(dados_brutos, 0)
                    
                    produtos_raw = []
                    # Varredura recursiva para encontrar os produtos onde quer que estejam no JSON
                    def procurar_produtos(d):
                        nonlocal produtos_raw
                        if produtos_raw: return
                        if isinstance(d, dict):
                            if "products" in d and isinstance(d["products"], list) and len(d["products"]) > 0:
                                prod = d["products"][0]
                                if isinstance(prod, dict) and ("name" in prod or "productName" in prod or "node" in prod):
                                    produtos_raw = d["products"]
                                    return
                            for v in d.values(): procurar_produtos(v)
                        elif isinstance(d, list):
                            for v in d: procurar_produtos(v)
                    
                    procurar_produtos(dados)
                    
                    if not produtos_raw:
                        continue # Tenta a próxima rota se essa não tiver produtos
                        
                    lote = []
                    for p in produtos_raw:
                        try:
                            item = p.get('node', p)
                            nome_cru = item.get('name', item.get('productName', '')).upper().strip()
                            if not nome_cru: continue
                            
                            skus = item.get('items', [])
                            if not skus: continue
                            sku_p = skus[0]
                            
                            link_foto = sku_p.get('images', [{}])[0].get('imageUrl', '')
                            ean_oficial = sku_p.get('ean')
                            
                            if not ean_oficial or ean_oficial == "N/A": 
                                ean = extrair_ean_pela_foto(link_foto)
                            else: 
                                ean = ean_oficial
                                
                            if not ean: 
                                ean = indice_reverso.get(normalizar_para_cache(nome_cru), "N/A")

                            off = sku_p.get('sellers', [{}])[0].get('commertialOffer', {})
                            p_v, p_a = float(off.get('ListPrice', 0)), float(off.get('Price', 0))
                            if p_a <= 0: continue
                            if p_v <= 0 or p_v < p_a: p_v = p_a

                            unit_multiplier = float(sku_p.get('unitMultiplier') or 1.0)
                            if unit_multiplier > 0 and unit_multiplier < 1.0:
                                if p_v > (p_a * (1 / unit_multiplier) * 0.5): 
                                    p_a = p_a / unit_multiplier
                                elif p_v < (p_a * 2):
                                    p_v = p_v / unit_multiplier
                                    p_a = p_a / unit_multiplier

                            nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                            
                            # Categoria do site
                            cat_site = cat_name.upper()
                            if cat_site in CATEGORIAS_IGNORADAS: continue

                            link_pdp_rel = item.get('linkText') or item.get('link') or item.get('url') or ''
                            if link_pdp_rel:
                                if link_pdp_rel.startswith('http'): 
                                    link_pdp = link_pdp_rel
                                elif link_pdp_rel.startswith('/'): 
                                    link_pdp = f"{BASE_URL_CONFIG}{link_pdp_rel}"
                                else: 
                                    link_pdp = f"{BASE_URL_CONFIG}/{link_pdp_rel}/p"
                            else: 
                                link_pdp = ""

                            lote.append({
                                "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_site,
                                "Produto": nome_limpo, "Marca": str(item.get('brand', 'OUTROS')).upper(),
                                "Preço Varejo": f"R$ {p_varejo:.2f}".replace('.', ','),
                                "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                                "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                                "Condição": "MEU CARREFOUR (CPF)" if p_a < p_v else "1 UN", 
                                "Data_Hora": agora, "Link_Imagem": link_foto,
                                "Link_PDP": link_pdp
                            })
                        except Exception: continue
                    return lote
            except Exception:
                pass
            
            # --- TENTATIVA 2: FALLBACK PARA API LEGADA ---
            # Se o front-end Remix bloquear, a API Legada VTEX (Search) nos salva de forma invisível.
            _from = (pagina - 1) * PAGE_SIZE
            _to = _from + PAGE_SIZE - 1
            sort_legado = "OrderByPriceASC" if ordem == "price_asc" else "OrderByPriceDESC"
            url_legado = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search/{cat_name}?map=c&O={sort_legado}&_from={_from}&_to={_to}"
            
            try:
                res_leg = await session.get(url_legado, timeout=20)
                if res_leg.status_code in [200, 206]:
                    produtos_raw = res_leg.json()
                    if produtos_raw and isinstance(produtos_raw, list):
                        lote = []
                        for p in produtos_raw:
                            try:
                                nome_cru = str(p.get('productName', '')).upper().strip()
                                if not nome_cru: continue
                                
                                skus = p.get('items', [])
                                if not skus: continue
                                sku_p = skus[0]
                                
                                link_foto = sku_p.get('images', [{}])[0].get('imageUrl', '')
                                ean = sku_p.get('ean')
                                if not ean or ean == "N/A": ean = extrair_ean_pela_foto(link_foto)
                                if not ean: ean = indice_reverso.get(normalizar_para_cache(nome_cru), "N/A")

                                off = sku_p.get('sellers', [{}])[0].get('commertialOffer', {})
                                p_v, p_a = float(off.get('ListPrice', 0)), float(off.get('Price', 0))
                                if p_a <= 0: continue
                                if p_v <= 0 or p_v < p_a: p_v = p_a

                                unit_multiplier = float(sku_p.get('unitMultiplier') or 1.0)
                                if unit_multiplier > 0 and unit_multiplier < 1.0:
                                    if p_v > (p_a * (1 / unit_multiplier) * 0.5): 
                                        p_a = p_a / unit_multiplier
                                    elif p_v < (p_a * 2):
                                        p_v = p_v / unit_multiplier
                                        p_a = p_a / unit_multiplier

                                nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                                cat_site = cat_name.upper()

                                link_pdp_rel = p.get('linkText') or p.get('link') or p.get('url') or ''
                                if link_pdp_rel:
                                    if link_pdp_rel.startswith('http'): link_pdp = link_pdp_rel
                                    elif link_pdp_rel.startswith('/'): link_pdp = f"{BASE_URL_CONFIG}{link_pdp_rel}"
                                    else: link_pdp = f"{BASE_URL_CONFIG}/{link_pdp_rel}/p"
                                else: link_pdp = ""

                                lote.append({
                                    "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_site,
                                    "Produto": nome_limpo, "Marca": str(p.get('brand', 'OUTROS')).upper(),
                                    "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                                    "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                                    "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                                    "Condição": "MEU CARREFOUR (CPF)" if p_a < p_v else "1 UN", 
                                    "Data_Hora": agora, "Link_Imagem": link_foto,
                                    "Link_PDP": link_pdp
                                })
                            except Exception: continue
                        return lote
            except Exception: pass
            
        return []

async def motor_extracao_carrefour_full():
    cookies = await capturar_sessao()
    
    # Carrega biblioteca para fallback de EAN
    bib_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'biblioteca_produtos.json')
    indice_reverso = {}
    if os.path.exists(bib_path):
        biblioteca = read_json_file(bib_path)
        indice_reverso = {normalizar_para_cache(v.get('nome_comum', '')): v.get('ean', 'N/A') for v in biblioteca.values()}

    logger.info(f"🚀 Iniciando extração FULL CATALOG para Carrefour via endpoints '.data' (Padrão)...")
    lista_final, sem, agora = [], asyncio.Semaphore(CONCURRENCY), datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    async with requests.AsyncSession(impersonate="chrome124", cookies=cookies) as session:
        departamentos = [
            "mercearia", "bebidas", "frios-e-laticinios", "carnes-aves-e-peixes",
            "limpeza", "higiene-e-perfumaria", "hortifruti", "padaria",
            "congelados", "pet-shop"
        ]
        logger.info(f"   Foram definidos {len(departamentos)} departamentos principais para varredura.")
            
        async def process_category(cat_name):
            produtos_categoria = []
            logger.info(f"   🔍 Iniciando varredura no departamento: /{cat_name}...")
            
            # Como o limite do Remix na paginação da VTEX é de 2500 itens, pegamos 50 páginas de 50 itens.
            # Para superar isso e pegar todos os milhares de itens, varremos nas duas ordens (asc e desc)
            for ordem in ["OrderByPriceASC", "OrderByPriceDESC"]:
                for pg in range(1, 51):
                    lote = await extrair_lote_departamento(session, cat_name, ordem, pg, sem, agora, indice_reverso)
                    if not lote:
                        break # Se retornou vazio, não tem mais páginas nessa ordem
                    produtos_categoria.extend(lote)
                    await asyncio.sleep(0.3)
                    
            unicos_cat = list({f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v for v in produtos_categoria}.values())
            logger.info(f"   ✅ Departamento /{cat_name}: {len(unicos_cat)} itens capturados.")
            return unicos_cat

        tarefas = [process_category(cat) for cat in departamentos]
        # Roda os departamentos em pedaços para não explodir conexões
        for i in range(0, len(tarefas), 3):
            resultados_chunk = await asyncio.gather(*tarefas[i:i+3])
            for res in resultados_chunk: lista_final.extend(res)
            
        lista_unica = list({f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v for v in lista_final}.values())
        
    logger.info(f"✅ Sucesso! {len(lista_unica)} produtos coletados para o Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_carrefour_full()
