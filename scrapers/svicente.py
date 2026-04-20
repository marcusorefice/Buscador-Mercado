import os
import asyncio
import warnings
import re
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from datetime import datetime
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file, MAPA_PARA_APP, CATEGORIAS_IGNORADAS, formatar_nome_categoria

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'svicente_spec.json')
CONFIG = read_json_file(SPEC_FILE)

if not CONFIG:
    logger.critical(f"Arquivo de especificação '{SPEC_FILE}' não encontrado ou inválido. Usando valores padrão.")
    CONFIG = {}

# ==========================================
# CONFIGURAÇÕES DO SÃO VICENTE
# ==========================================
NOME_MERCADO = CONFIG.get("market_name", "São Vicente")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.svicente.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "/on/demandware.store/Sites-SaoVicente-Site/pt_BR/Search-UpdateGrid")
URL_BASE = f"{BASE_URL_CONFIG}{API_ENDPOINT}"
TAMANHO_PAGINA = CONFIG.get("pagination", {}).get("page_size", 200)
PMID = CONFIG.get("regionalization", {}).get("pmid", "FPP_030|FPV_030|M_030")

raw_concurrency = CONFIG.get("technical_dependencies", {}).get("concurrency", 5)
try:
    CONCURRENCY = int(raw_concurrency)
except (ValueError, TypeError):
    logger.warning(f"Valor de 'concurrency' inválido ('{raw_concurrency}'). Usando valor padrão 5.")
    CONCURRENCY = 5
IMPERSONATE = CONFIG.get("technical_dependencies", {}).get("impersonation", "chrome120")
USER_AGENT = CONFIG.get("technical_dependencies", {}).get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

headers = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL_CONFIG}/ofertas"
}

async def get_category_links(session):
    """Obtém todas as subcategorias do menu para garantir a taxonomia."""
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
    """Acessa a URL da categoria para extrair o CGID real interno do Demandware."""
    async with semaforo:
        url = f"{BASE_URL_CONFIG}{url_path}" if url_path.startswith('/') else url_path
        try:
            resp = await session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            cgid_match = re.search(r'cgid=([^\"&\']+)', resp.text)
            if cgid_match:
                true_cgid = cgid_match.group(1).split('\\')[0].split("'")[0]
                return true_cgid, cat_name
        except Exception:
            pass
        return None, cat_name

async def buscar_pagina_svicente(session, cgid, start):
    params = {"cgid": cgid, "pmid": PMID, "start": start, "sz": TAMANHO_PAGINA}
    try:
        response = await session.get(URL_BASE, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"  [São Vicente] Erro na página {start} (CGID: {cgid}): {e}")
    return None

async def processar_categoria(session, cgid, cat_nome, semaforo, agora):
    async with semaforo:
        data_inicial = await buscar_pagina_svicente(session, cgid, 0)
        if not data_inicial: return []

        total_produtos = data_inicial.get('productSearch', {}).get('count', 0)
        if total_produtos == 0: return []
        
        tarefas = [buscar_pagina_svicente(session, cgid, start) for start in range(0, total_produtos, TAMANHO_PAGINA)]
        resultados_paginas = await asyncio.gather(*tarefas)
        
        produtos_categoria = []

        for data_pagina in resultados_paginas:
            if not data_pagina: continue
            
            produtos_json = data_pagina.get('productsSearchResult', [])
            for p in produtos_json:
                try:
                    nome_bruto = p.get('productName', p.get('name', '')).upper().strip()
                    if not nome_bruto: continue

                    # --- PREÇOS PADRÃO ---
                    price_data = p.get('price', {})
                    p_venda = float(price_data.get('sales', {}).get('value', 0))
                    p_tabela = float(price_data.get('list', {}).get('value', p_venda)) if price_data.get('list') else p_venda

                    # --- LÓGICA SNIPER: BUSCA PREÇO DO CLUBE NAS FLAGS ---
                    valor_varejo = p_tabela
                    valor_atacado = p_venda
                    condicao = "1 UN"

                    flags = p.get('flagtypes', [])
                    for f in flags:
                        if f.get('flagType') == "facil-pra-voce":
                            raw_val = f.get('valueFlagType', "")
                            if raw_val:
                                try:
                                    p_clube = float(raw_val.replace('R$', '').replace('.', '').replace(',', '.').strip())
                                    valor_varejo = p_venda
                                    valor_atacado = p_clube
                                    condicao = "CLUBE SV"
                                except:
                                    condicao = "CLUBE SV"

                    # Checa promoções de quantidade (Leve Mais)
                    if condicao == "1 UN":
                        if promos := p.get('promotions', []):
                            for pr in promos:
                                msg = pr.get('calloutMsg', '').replace('<br/>', ' ').strip().upper()
                                if any(x in msg for x in ["LEVE", "PAGUE", "A PARTIR"]):
                                    condicao = msg
                                    break
                    
                    # Filtra apenas ofertas
                    if condicao == "1 UN" and p_venda >= p_tabela:
                        continue

                    # --- NOVA LÓGICA DE TAXONOMIA (Garante Bypass da IA) ---
                    subcategoria = formatar_nome_categoria(cat_nome)
                    tipo_produto = "N/A"
                    
                    if cat_nome in CATEGORIAS_IGNORADAS:
                        continue
                    
                    categoria = MAPA_PARA_APP.get(cat_nome, padronizar_categoria(nome_bruto, cat_nome))

                    # Metadados e Limpeza
                    img_url = ""
                    imgs = p.get('images', {})
                    for size in ['medium', 'large', 'small']:
                        if size in imgs and imgs[size]:
                            img_url = imgs[size][0].get('url', "")
                            if img_url.startswith('/'): img_url = f"{BASE_URL_CONFIG}{img_url}"
                            break

                    marca = p.get('brand', 'PRÓPRIA').upper()
                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                    unid_venda = "KG" if " KG" in nome_bruto else "UN"

                    produtos_categoria.append({
                        "Mercado": NOME_MERCADO,
                        "Categoria": categoria,
                        "subcategoria": subcategoria,
                        "tipo_produto": tipo_produto,
                        "Produto": nome_limpo,
                        "Marca": marca,
                        "Preço Varejo": f"R$ {valor_varejo:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {valor_atacado:.2f}".replace('.', ','),
                        "Qtd_Valor": qv,
                        "Medida": med,
                        "Unidade": unid_venda,
                        "Condição": condicao,
                        "Validade": "VER NO SITE",
                        "Data_Hora": agora,
                        "Link_Imagem": img_url if img_url else "SEM IMAGEM"
                    })
                except: continue
        
        if produtos_categoria:
            logger.info(f"   ✓ {cat_nome}: {len(produtos_categoria)} ofertas encontradas.")
            
        return produtos_categoria

async def motor_extracao_svicente():
    logger.info(f"🚀 Iniciando extração com Taxonomia Dinâmica para {NOME_MERCADO}...")
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # 1. Obtém as categorias do site
        logger.info(f"📡 Buscando links de categorias no site...")
        cat_links = await get_category_links(session)
        logger.info(f"   ✓ Encontradas {len(cat_links)} subcategorias no menu.")
        
        if not cat_links:
            logger.warning("Não foi possível carregar as categorias do site.")
            return []
            
        # 2. Descobre o CGID real de cada categoria para buscar os produtos corretos
        logger.info(f"📡 Resolvendo CGIDs internos...")
        semaforo_cgid = asyncio.Semaphore(15) # Mais concorrência para as chamadas HTML
        tasks_cgid = [fetch_true_cgid(session, url_path, cat_name, semaforo_cgid) for cat_name, url_path in cat_links.items()]
        cgid_results = await asyncio.gather(*tasks_cgid)
        
        valid_cgids = [(true_cgid, cat_name) for true_cgid, cat_name in cgid_results if true_cgid]
        logger.info(f"   ✓ Resolvidos {len(valid_cgids)} CGIDs válidos.")

        # 3. Faz a extração paginada de ofertas em cada categoria válida
        logger.info(f"📡 Buscando ofertas em todas as categorias...")
        semaforo_api = asyncio.Semaphore(CONCURRENCY)
        tasks_ofertas = [processar_categoria(session, cgid, cat_name, semaforo_api, agora) for cgid, cat_name in valid_cgids]
        resultados_finais = await asyncio.gather(*tasks_ofertas)
        
        lista_produtos = [p for sublist in resultados_finais for p in sublist]

    if not lista_produtos:
        logger.warning(f"Nenhum produto foi capturado para o {NOME_MERCADO}.")
        return []

    # Remove duplicados por nome de produto mantendo o primeiro encontrado (evita duplicação se o item pertencer a >1 categoria)
    lista_unica = list({v['Produto']: v for v in lista_produtos}.values())
    logger.info(f"✅ Finalizado! {len(lista_unica)} ofertas únicas capturadas no {NOME_MERCADO}.")
    return lista_unica

async def extrair_dados():
    """Interface para o Orquestrador Main"""
    return await motor_extracao_svicente()