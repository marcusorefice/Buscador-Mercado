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
# Limite rígido da Demandware por grade. Respeitar isso evita saltos cegos na paginação
TAMANHO_PAGINA_REAL = 48 
IS_TEST_MODE = False # Define como True para baixar uma amostra menor

CONCURRENCY = 15
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")
USER_AGENT = CONFIG.get("technical_dependencies", {}).get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

headers = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest"
}

def ean_eh_valido(ean_str):
    if not ean_str or not ean_str.isdigit(): return False
    padded = ean_str.zfill(14)
    total = sum(int(padded[i]) * (3 if i % 2 == 0 else 1) for i in range(13))
    return str((10 - (total % 10)) % 10) == padded[13]

def extrair_ean_pela_foto(url_imagem):
    if not url_imagem or not isinstance(url_imagem, str): return None
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    if match and ean_eh_valido(match.group(1)):
        return match.group(1)
    return None

async def fetch_ean_from_product_page(session, product_id, semaforo_pdp):
    """Busca o EAN na página de detalhes como último recurso (Alta Precisão)."""
    async with semaforo_pdp:
        if not product_id:
            return None
        url = f"https://www.svicente.com.br/on/demandware.store/Sites-SaoVicente-Site/pt_BR/Product-Show?pid={product_id}"
        try:
            resp = await session.get(url, timeout=15)
            if resp.status_code == 200:
                match = re.search(r'<td>C&oacute;digo</td>\s*<td>(\d{13,14})</td>', resp.text, re.IGNORECASE)
                if match: return match.group(1)

                match2 = re.search(r'(?:gtin\d*|ean|sku)["\s:]+["\s]*(\d{13})', resp.text, re.IGNORECASE)
                if match2: return match2.group(1)

                match_any = re.search(r'(789\d{10}|790\d{10})', resp.text)
                if match_any: return match_any.group(1)
        except Exception:
            pass
        return None

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

async def buscar_pagina_svicente(session, cgid, start, retries=3):
    # SEM PMID! Isso garante que a API retorne o catálogo completo, não apenas o que está em promoção.
    params = {"cgid": cgid, "start": start, "sz": TAMANHO_PAGINA_REAL}
    for tentativa in range(retries):
        try:
            response = await session.get(URL_BASE, params=params, headers=headers, timeout=20)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            if tentativa == retries - 1:
                logger.error(f"  [São Vicente] Erro na página {start} (CGID: {cgid}): {e}")
            await asyncio.sleep(1)
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

        if IS_TEST_MODE:
            cgids_validos = cgids_validos[:2] # Processa apenas 2 categorias para teste
            logger.info(f"⚠️ MODO DE TESTE ATIVADO: Processando apenas {len(cgids_validos)} categorias.")

        logger.info(f"   Iniciando varredura em {len(cgids_validos)} categorias...")

        async def process_category(session, cgid, cat_nome, semaforo_api):
            async with semaforo_api:
                data_inicial = await buscar_pagina_svicente(session, cgid, 0)
                if not data_inicial or not data_inicial.get('productSearch'):
                    return []
                    
                total_produtos = data_inicial.get('productSearch', {}).get('count', 0)
                if total_produtos == 0: return []
                
                paginas_a_processar = [data_inicial]
                
                # Dispara o restante das páginas da categoria em paralelo!
                if total_produtos > TAMANHO_PAGINA_REAL:
                    max_produtos = total_produtos
                    if IS_TEST_MODE:
                        max_produtos = min(total_produtos, TAMANHO_PAGINA_REAL * 2) # Limita a 2 páginas por categoria no teste
                        logger.info(f"⚠️ MODO DE TESTE: {cat_nome} limitado a {max_produtos} produtos (de {total_produtos}).")
                    
                    tarefas = [buscar_pagina_svicente(session, cgid, start) for start in range(TAMANHO_PAGINA_REAL, max_produtos, TAMANHO_PAGINA_REAL)]
                    # Processa blocos de 5 páginas para não gerar engarrafamento
                    for i in range(0, len(tarefas), 5):
                        lote = tarefas[i:i+5]
                        resultados_restantes = await asyncio.gather(*lote)
                        paginas_a_processar.extend(resultados_restantes)
                
                produtos_categoria = []
                produtos_para_processar = []
                pdp_tasks = []
                semaforo_pdp = asyncio.Semaphore(15)

                for data_pagina in paginas_a_processar:
                    if not data_pagina: continue
                    produtos_json = data_pagina.get('productsSearchResult', [])
                    
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
                        if not ean or len(ean) < 12:
                            custom_attrs = p.get('customAttributes', {})
                            if isinstance(custom_attrs, dict):
                                ean_from_attr = custom_attrs.get('ean', '') or custom_attrs.get('gtin', '')
                                if ean_from_attr: ean = str(ean_from_attr).strip()
                        if (not ean or len(ean) < 12) and img_url:
                            ean_from_img = extrair_ean_pela_foto(img_url)
                            if ean_from_img: ean = ean_from_img
                            
                        precisa_pdp = not ean or len(ean) < 12
                        if precisa_pdp:
                            pdp_tasks.append(fetch_ean_from_product_page(session, p.get('id'), semaforo_pdp))
                            
                        produtos_para_processar.append({
                            "raw_data": p, "nome_bruto": nome_bruto, "img_url": img_url,
                            "ean_preliminar": ean, "precisa_pdp": precisa_pdp
                        })

                resultados_pdp = []
                if pdp_tasks:
                    resultados_pdp = await asyncio.gather(*pdp_tasks)
                    
                pdp_index = 0
                for item in produtos_para_processar:
                    p = item["raw_data"]
                    nome_bruto = item["nome_bruto"]
                    img_url = item["img_url"]
                    ean = item["ean_preliminar"]
                    
                    if item["precisa_pdp"]:
                        ean_from_page = resultados_pdp[pdp_index]
                        pdp_index += 1
                        if ean_from_page: ean = ean_from_page
                    
                    if not ean or len(ean) < 12: ean = "N/A"

                    try:
                        price_data = p.get('price', {})
                        p_venda = float(price_data.get('sales', {}).get('value', 0))
                        p_tabela = float(price_data.get('list', {}).get('value', p_venda)) if price_data.get('list') else p_venda

                        valor_varejo = p_tabela
                        valor_atacado = p_venda
                        condicao = "1 UN"

                        flags = p.get('flagtypes', [])
                        for f in flags:
                            flag_type = f.get('flagType')
                            if flag_type in ["facil-pra-voce", "facil-pra-pagar"]:
                                raw_val = f.get('valueFlagType', "")
                                nome_condicao = "CARTÃO FÁCIL" if flag_type == "facil-pra-pagar" else "CLUBE SV"
                                if raw_val:
                                    try:
                                        p_clube = float(raw_val.replace('R$', '').replace('.', '').replace(',', '.').strip())
                                        valor_varejo = p_venda
                                        valor_atacado = p_clube
                                        condicao = nome_condicao
                                    except: condicao = nome_condicao
                                else: condicao = nome_condicao

                        if condicao == "1 UN":
                            if promos := p.get('promotions', []):
                                for pr in promos:
                                    msg = pr.get('calloutMsg', '').replace('<br/>', ' ').strip().upper()
                                    if any(x in msg for x in ["LEVE", "PAGUE", "A PARTIR"]):
                                        condicao = msg
                                        break

                        # Segurança para não descartar indevidamente itens sem promoção
                        if valor_atacado <= 0: continue
                        if valor_varejo <= 0 or valor_varejo < valor_atacado: valor_varejo = valor_atacado

                        marca = str(p.get('brand', 'OUTROS')).upper()
                        
                        link_pdp_rel = p.get('url', '')
                        pid = p.get('id')
                        if link_pdp_rel:
                            if link_pdp_rel.startswith('http'): link_pdp = link_pdp_rel
                            else: link_pdp = f"https://www.svicente.com.br{link_pdp_rel if link_pdp_rel.startswith('/') else '/' + link_pdp_rel}"
                        elif pid:
                            link_pdp = f"https://www.svicente.com.br/on/demandware.store/Sites-SaoVicente-Site/pt_BR/Product-Show?pid={pid}"
                        else:
                            link_pdp = ""

                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                        measurement_unit = str(p.get('measurementUnit', '')).lower()
                        if measurement_unit == 'kg' or nome_bruto.upper().endswith(' KG'):
                            unid_venda = "KG"
                        else:
                            unid_venda = "UN"

                        if unid_venda == "KG" and qv == "1" and med == "UN":
                            qv, med = "1", "KG"
                            
                        nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()

                        produtos_categoria.append({
                            "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": cat_nome,
                            "Produto": nome_limpo, "Marca": marca,
                            "Preço Varejo": f"R$ {valor_varejo:.2f}".replace('.', ','),
                            "Preço Atacado": f"R$ {valor_atacado:.2f}".replace('.', ','),
                            "Qtd_Valor": qv, "Medida": med, "Unidade": unid_venda, "Condição": condicao,
                            "Data_Hora": agora, "Link_Imagem": img_url if img_url else "SEM IMAGEM",
                            "Link_PDP": link_pdp
                        })
                    except: continue
            
                logger.info(f"   ✓ {cat_nome}: {len(produtos_categoria)} itens capturados.")
                return produtos_categoria

        tarefas_ofertas = [process_category(session, cgid, cat_nome, sem) for cgid, cat_nome in cgids_validos]
        resultados_finais = await asyncio.gather(*tarefas_ofertas)
        
        for res in resultados_finais:
            lista_final.extend(res)

    lista_unica = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())
    logger.info(f"✅ {len(lista_unica)} produtos capturados no {NOME_MERCADO} Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_svicente_full()
