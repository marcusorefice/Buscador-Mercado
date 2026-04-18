import os
import asyncio
import warnings
import json
from datetime import datetime
from curl_cffi import requests
from playwright.async_api import async_playwright
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'carrefour_spec.json')
CONFIG = read_json_file(SPEC_FILE)

# ==========================================
# CONFIGURAÇÕES DO CARREFOUR
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "Carrefour")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://mercado.carrefour.com.br/").rstrip('/')

REGIONALIZATION = CONFIG.get("regionalization", {})
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "28617")
REGION_ID = REGIONALIZATION.get("region_id", "InYyLjc5MDlFOEZDNjU2N0M3OTU5NjA4MDFCQTU5RDFFMEQ3Ig==")
SESSION_FILE = REGIONALIZATION.get("session_file", "carrefour_session.json")
CEP_COOKIE_VALUE = REGIONALIZATION.get("cep_cookie_value", "IkhpcGVyIEp1bmRpYcOtIg==")

PAGINATION = CONFIG.get("pagination", {})
PAGE_SIZE = PAGINATION.get("page_size", 50)
MAX_PAGES_PER_SORT = PAGINATION.get("max_pages_per_sort", 25)

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
CONCURRENCY = TECHNICAL_DEPS.get("concurrency", 8)
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome124")
PLAYWRIGHT_USER_AGENT = TECHNICAL_DEPS.get("playwright_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ==========================================
# 1. TRADUTOR DE STREAM REMIX/VTEX
# ==========================================
def reconstruir_json_remix(dados_flat, index=0):
    """Traduz o formato de índices do Remix para um JSON legível"""
    if index is None or not (0 <= index < len(dados_flat)):
        return None
    
    node = dados_flat[index]
    
    if isinstance(node, list):
        return [reconstruir_json_remix(dados_flat, i) for i in node]
    
    if isinstance(node, dict):
        res = {}
        for k, v in node.items():
            # Se a chave começa com _, ela é uma referência a um índice
            if k.startswith('_'):
                try:
                    key_idx = int(k[1:])
                    chave_real = reconstruir_json_remix(dados_flat, key_idx)
                    res[chave_real] = reconstruir_json_remix(dados_flat, v)
                except: continue
            else:
                res[k] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
        return res
    
    return node

# ==========================================
# 2. CAPTURA DE SESSÃO (PLAYWRIGHT)
# ==========================================
async def _salvar_sessao_json(cookies):
    """Salva os cookies da sessão em um arquivo JSON."""
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump(cookies, f)
    except Exception as e:
        logger.warning(f"Não foi possível salvar o arquivo de sessão: {e}")

async def _carregar_sessao_json():
    """Carrega os cookies de um arquivo de sessão, se existir."""
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, 'r') as f:
            return json.load(f)
    except:
        return None

async def _testar_sessao(cookies):
    """Testa se os cookies de uma sessão cacheada ainda são válidos."""
    if not cookies:
        return False
    logger.info(f"🧪 [{NOME_MERCADO}] Testando sessão cacheada...")
    test_url = f"{BASE_URL_CONFIG}/colecao/{CLUSTER_ID}.data?count=1"
    try:
        async with requests.AsyncSession(impersonate=IMPERSONATE, cookies=cookies) as s:
            res = await s.head(test_url, timeout=15)
            if res.status_code == 200:
                logger.info(f"✅ Sessão cacheada do {NOME_MERCADO} é válida.")
                return True
            logger.warning(f"Sessão cacheada inválida (Status: {res.status_code}). Renovando...")
            return False
    except Exception:
        logger.warning("Erro ao testar sessão cacheada. Renovando...")
        return False

async def _capturar_nova_sessao_playwright():
    """Usa o Playwright para iniciar uma nova sessão e obter cookies válidos."""
    logger.info(f"🔑 [{NOME_MERCADO}] Capturando nova sessão com Playwright (isso pode levar um minuto)...")
    cookies_dict = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=PLAYWRIGHT_USER_AGENT)
        page = await context.new_page()
        try:
            await page.goto(f"{BASE_URL_CONFIG}/colecao/{CLUSTER_ID}", wait_until="domcontentloaded", timeout=60000)
            pw_cookies = await context.cookies()
            cookies_dict = {c['name']: c['value'] for c in pw_cookies}
            cookies_dict["region-id-food"] = REGION_ID
            cookies_dict["cep"] = CEP_COOKIE_VALUE
            logger.info("✅ Nova sessão regional do Carrefour ativada.")
        except Exception as e:
            logger.error(f"Erro crítico na captura com Playwright: {e}")
        finally:
            await browser.close()
    return cookies_dict

async def capturar_sessao():
    """Orquestrador de sessão: tenta usar cache, se falhar, cria uma nova."""
    cookies = await _carregar_sessao_json()
    if await _testar_sessao(cookies):
        return cookies
    
    novos_cookies = await _capturar_nova_sessao_playwright()
    if novos_cookies:
        await _salvar_sessao_json(novos_cookies)
    return novos_cookies

# ==========================================
# 3. EXTRAÇÃO TURBO
# ==========================================
async def extrair_lote(session, ordem, pagina, sem, agora):
    # URL exata detectada no seu Sniffer de Elite
    url = f"{BASE_URL_CONFIG}/colecao/{CLUSTER_ID}.data?map=productClusterIds&count={PAGE_SIZE}&page={pagina}&sort={ordem}&_routes=layout%2Fdefault%2Croutes%2Fcolecao.%24collectionId"
    
    async with sem:
        try:
            res = await session.get(url, timeout=30)
            if res.status_code != 200: return []

            # Tradução do Stream
            dados_brutos = res.json()
            # O índice 0 costuma ser a raiz do mapa de dados
            dados_limpos = reconstruir_json_remix(dados_brutos, 0)
            
            # Navega até a lista de produtos (padrão detectado no console)
            colecao = dados_limpos.get("routes/colecao.$collectionId", {})
            produtos_raw = colecao.get("products", []) or colecao.get("data", {}).get("products", [])

            if not produtos_raw: return []

            lote = []

            for p in produtos_raw:
                try:
                    item = p.get('node', p)
                    nome_cru = item.get('name', item.get('productName', '')).upper().strip()
                    if not nome_cru: continue

                    # Preços, Validade e Imagem (Varejo e Atacado/CPF)
                    validade_iso = "Consulte no site"
                    link_imagem = "SEM IMAGEM"
                    
                    off = item.get('offers', {}).get('offers', [{}])[0]
                    p_a = float(off.get('price', off.get('Price', 0)))
                    p_v = float(off.get('listPrice', off.get('ListPrice', 0)))
                    
                    if off.get('priceValidUntil'):
                        validade_iso = off.get('priceValidUntil')
                    elif off.get('PriceValidUntil'):
                        validade_iso = off.get('PriceValidUntil')
                        
                    if 'image' in item and isinstance(item['image'], list) and len(item['image']) > 0:
                        link_imagem = item['image'][0].get('url', 'SEM IMAGEM')

                    if p_a <= 0 and 'items' in item and isinstance(item['items'], list) and len(item['items']) > 0:
                        comm = item['items'][0].get('sellers', [{}])[0].get('commertialOffer', {})
                        p_a = float(comm.get('Price', 0))
                        p_v = float(comm.get('ListPrice', 0))
                        
                        if comm.get('PriceValidUntil'):
                            validade_iso = comm.get('PriceValidUntil')
                        elif comm.get('priceValidUntil'):
                            validade_iso = comm.get('priceValidUntil')
                            
                        if link_imagem == "SEM IMAGEM":
                            imagens = item['items'][0].get('images', [])
                            if imagens and isinstance(imagens, list) and len(imagens) > 0:
                                link_imagem = imagens[0].get('imageUrl', imagens[0].get('imageurl', 'SEM IMAGEM'))

                    if p_a <= 0: continue
                    if p_v <= 0 or p_v < p_a: p_v = p_a

                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                    marca = item.get('brand', 'OUTROS')
                    if isinstance(marca, dict): marca = marca.get('name', 'OUTROS')
                    
                    validade = "Consulte no site"
                    if validade_iso != "Consulte no site" and isinstance(validade_iso, str) and 'T' in validade_iso:
                        try:
                            data_part = validade_iso.split('T')[0]
                            ano, mes, dia = data_part.split('-')
                            validade = f"{dia}/{mes}/{ano}"
                        except:
                            validade = validade_iso

                    lote.append({
                        "Mercado": NOME_MERCADO, "Categoria": padronizar_categoria(nome_cru),
                        "Produto": nome_limpo, "Marca": str(marca).upper(),
                        "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                        "Condição": "MEU CARREFOUR (CPF)" if p_a < p_v else "1 UN",
                        "Validade": validade, "Data_Hora": agora,
                        "Link_Imagem": link_imagem
                    })
                except: continue
            return lote
        except: return []

async def motor_principal():
    cookies = await capturar_sessao()
    if not cookies: return []

    logger.info(f"🚀 Iniciando extração para {NOME_MERCADO}...")
    lista_final = []
    sem = asyncio.Semaphore(CONCURRENCY)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    async with requests.AsyncSession(impersonate=IMPERSONATE, cookies=cookies) as session:
        tarefas = []
        # Cercamos a lista: 25 páginas de cada ponta de preço
        for ordem in ["price_asc", "price_desc"]:
            logger.info(f"📡 Preparando varredura do {NOME_MERCADO}: {ordem}")
            for pg in range(1, MAX_PAGES_PER_SORT + 1):
                tarefas.append(extrair_lote(session, ordem, pg, sem, agora))
        
        resultados = await asyncio.gather(*tarefas)
        for r in resultados:
            if r: lista_final.extend(r)

    lista_unica = list({v['Produto']: v for v in lista_final}.values())
    logger.info(f"✅ Finalizado! {len(lista_unica)} produtos únicos do {NOME_MERCADO} processados.")
    return lista_unica

def extrair_dados():
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(motor_principal())