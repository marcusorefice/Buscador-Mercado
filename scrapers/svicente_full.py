import os
import asyncio
import warnings
import re
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from datetime import datetime
from utils import extrair_medidas_inteligente, setup_logging, read_json_file, CATEGORIAS_IGNORADAS

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'svicente_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "São Vicente")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.svicente.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/on/demandware.store/Sites-SaoVicente-Site/pt_BR/Search-UpdateGrid")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"
TAMANHO_PAGINA = CONFIG.get("pagination", {}).get("page_size", 200)
PMID = CONFIG.get("regionalization", {}).get("pmid", "FPP_030|FPV_030|M_030")

CONCURRENCY = 5
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")
USER_AGENT = CONFIG.get("technical_dependencies", {}).get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

headers = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

def extrair_ean_pela_foto(url_imagem):
    if not url_imagem or not isinstance(url_imagem, str): return None
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    return match.group(1) if match else None

async def get_category_links(session):
    try:
        res = await session.get(f"{BASE_URL_CONFIG}/", headers={"User-Agent": USER_AGENT}, timeout=30)
        soup = BeautifulSoup(res.text, 'html.parser')
        links = soup.find_all('a', href=True)
        cats = {}
        for a in links:
            t = a.get_text(strip=True)
            h = a['href']
            if t.startswith('Ver Tudo em '):
                cat_name = t.replace('Ver Tudo em ', '').strip().upper()
                if h not in cats.values():
                     cats[cat_name] = h
        return cats
    except Exception as e:
        logger.error(f"Erro ao buscar categorias do menu principal: {e}")
        return {}

async def fetch_true_cgid(session, url_path, cat_name, semaforo):
    async with semaforo:
        url = f"{BASE_URL_CONFIG}{url_path}" if url_path.startswith('/') else url_path
        try:
            resp = await session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            cgid_match = re.search(r'cgid=([^\"&\']+)', resp.text)
            if cgid_match:
                true_cgid = cgid_match.group(1).split('\\')[0].split("'")[0]
                return true_cgid, cat_name
        except Exception: pass
        return None, cat_name

async def buscar_pagina_svicente(session, cgid, start):
    params = {"cgid": cgid, "start": start, "sz": TAMANHO_PAGINA}
    try:
        response = await session.get(URL_BASE, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"  [São Vicente] Erro na página {start} (CGID: {cgid}): {e}")
    return None

async def motor_extracao_svicente_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    sem = asyncio.Semaphore(CONCURRENCY)

    async with AsyncSession(impersonate=IMPERSONATE) as session:
        links_categorias = await get_category_links(session)
        if not links_categorias: return []

        tarefas_cgid = [fetch_true_cgid(session, url, name, sem) for name, url in links_categorias.items()]
        resultados_cgid = await asyncio.gather(*tarefas_cgid)
        cgids_validos = [(cgid, name) for cgid, name in resultados_cgid if cgid and name not in CATEGORIAS_IGNORADAS]

        logger.info(f"   Iniciando varredura em {len(cgids_validos)} categorias...")

        async def process_category(cgid, cat_nome):
            produtos_categoria = []
            start = 0
            while True:
                async with sem:
                    data = await buscar_pagina_svicente(session, cgid, start)
                    if not data or not data.get('productSearch'): break
                    
                    produtos_json = data.get('productsSearchResult', [])
                    if not produtos_json: break
                    
                    for p in produtos_json:
                        nome_bruto = p.get('productName', p.get('name', '')).upper().strip()
                        if not nome_bruto: continue
                        
                        img_url = ""
                        imgs = p.get('images', {})
                        for size in ['medium', 'large', 'small']:
                            if size in imgs and imgs[size]:
                                img_url = imgs[size][0].get('url', "")
                                if img_url.startswith('/'): img_url = f"{BASE_URL_CONFIG}{img_url}"
                                break

                        ean = str(p.get('gtin', '')).strip()
                        if not ean or len(ean) < 12: ean = str(p.get('ean', '')).strip()
                        if not ean or len(ean) < 12:
                            sku = str(p.get('id', '')).strip()
                            if len(sku) == 13 and sku.isdigit(): ean = sku
                        if (not ean or len(ean) < 12) and img_url:
                            ean_from_img = extrair_ean_pela_foto(img_url)
                            if ean_from_img: ean = ean_from_img
                        if not ean or ean == 'None': ean = 'N/A'

                        try:
                            price_info = p.get('price', {})
                            if not price_info: continue
                            
                            p_v = float(price_info.get('list', {}).get('value', 0.0) or price_info.get('sales', {}).get('value', 0.0))
                            p_a = float(price_info.get('sales', {}).get('value', 0.0))
                            
                            if p_a <= 0: continue
                            if p_v <= 0 or p_v < p_a: p_v = p_a

                            nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                            marca = str(p.get('brand', 'OUTROS')).upper()
                            
                            link_pdp = p.get('url', '')
                            if link_pdp and not link_pdp.startswith('http'):
                                link_pdp = f"https://www.svicente.com.br{link_pdp}"

                            produtos_categoria.append({
                                "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_nome,
                                "Produto": nome_limpo, "Marca": marca,
                                "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                                "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                                "Qtd_Valor": qv, "Medida": med, "Unidade": "UN", "Condição": "1 UN",
                                "Data_Hora": agora, "Link_Imagem": img_url if img_url else "SEM IMAGEM",
                                "Link_PDP": link_pdp
                            })
                        except: continue
                    
                    if len(produtos_json) < TAMANHO_PAGINA: break
                    start += TAMANHO_PAGINA
            
            logger.info(f"   - Categoria {cat_nome}: {len(produtos_categoria)} itens capturados.")
            return produtos_categoria

        tarefas_cat = [process_category(cgid, cat_nome) for cgid, cat_nome in cgids_validos]
        chunk_size = 3
        for i in range(0, len(tarefas_cat), chunk_size):
            chunk = tarefas_cat[i:i+chunk_size]
            resultados_chunk = await asyncio.gather(*chunk)
            for res in resultados_chunk:
                lista_final.extend(res)

    lista_unica = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())
    logger.info(f"✅ {len(lista_unica)} produtos capturados no {NOME_MERCADO} Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_svicente_full()
