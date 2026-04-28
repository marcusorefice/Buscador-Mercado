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

def extrair_ean_pela_foto(url_imagem):
    """Técnica para capturar o EAN-13 embutido no nome do arquivo de imagem."""
    if not url_imagem or not isinstance(url_imagem, str):
        return None
    # Padrão para EAN-13 (iniciando com 789 ou 790, comum no Brasil)
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    return match.group(1) if match else None

async def fetch_ean_from_product_page(session, product_id):
    """
    Tenta buscar o EAN na página de detalhes do produto como último recurso.
    Isso é um fallback para o caso de a API de busca não retornar o EAN.
    """
    if not product_id:
        return None
    
    # A URL do produto no S. Vicente é previsível com o ID (pid)
    url = f"https://www.svicente.com.br/on/demandware.store/Sites-SaoVicente-Site/pt_BR/Product-Show?pid={product_id}"
    try:
        resp = await session.get(url, timeout=15)
        if resp.status_code == 200:
            # 1. Busca na tabela de código
            match = re.search(r'<td>C&oacute;digo</td>\s*<td>(\d{13,14})</td>', resp.text, re.IGNORECASE)
            if match:
                return match.group(1)

            # 2. Busca padrão explícito JSON
            match2 = re.search(r'(?:gtin\d*|ean|sku)["\s:]+["\s]*(\d{13})', resp.text, re.IGNORECASE)
            if match2:
                return match2.group(1)

            # 3. Fallback: Qualquer EAN brasileiro (789/790) no HTML (ex: urls de imagens)
            match_any = re.search(r'(789\d{10}|790\d{10})', resp.text)
            if match_any:
                return match_any.group(1)
    except Exception as e:
        logger.warning(f"  [S. Vicente] Falha ao buscar EAN extra na página do produto ID {product_id}: {e}")
    
    return None

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
        if not data_inicial or not data_inicial.get('productSearch'):
            return []

        total_produtos = data_inicial.get('productSearch', {}).get('count', 0)
        if total_produtos == 0: return []
        
        # Otimização: Processa a primeira página já buscada e cria tarefas apenas para as restantes.
        paginas_a_processar = [data_inicial]
        if total_produtos > TAMANHO_PAGINA:
            tarefas = [buscar_pagina_svicente(session, cgid, start) for start in range(TAMANHO_PAGINA, total_produtos, TAMANHO_PAGINA)]
            resultados_restantes = await asyncio.gather(*tarefas)
            paginas_a_processar.extend(resultados_restantes)
        
        produtos_categoria = []

        # Itera sobre os resultados já coletados
        for data_pagina in paginas_a_processar:
            if not data_pagina: continue
            
            produtos_json = data_pagina.get('productsSearchResult', [])
            
            # 1. Identificar todos os produtos que precisam de busca extra na PDP para o EAN
            pdp_tasks = []
            produtos_para_processar = []
            
            for p in produtos_json:
                nome_bruto = p.get('productName', p.get('name', '')).upper().strip()
                if not nome_bruto: continue
                
                # --- Metadados e Limpeza (IMG URL PRIMEIRO PARA EAN) ---
                img_url = ""
                imgs = p.get('images', {})
                for size in ['medium', 'large', 'small']:
                    if size in imgs and imgs[size]:
                        img_url = imgs[size][0].get('url', "")
                        if img_url.startswith('/'): img_url = f"{BASE_URL_CONFIG}{img_url}"
                        break

                # Lógica de EAN/GTIN aprimorada para buscar em múltiplos campos
                ean = ""
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
                
                # Se ainda não temos EAN, vamos precisar da PDP
                precisa_pdp = not ean or len(ean) < 12
                if precisa_pdp:
                    # Registra a tarefa para buscar na PDP
                    pdp_tasks.append(fetch_ean_from_product_page(session, p.get('id')))
                
                produtos_para_processar.append({
                    "raw_data": p,
                    "nome_bruto": nome_bruto,
                    "img_url": img_url,
                    "ean_preliminar": ean,
                    "precisa_pdp": precisa_pdp
                })
            
            # 2. Executa as buscas na PDP em paralelo
            resultados_pdp = []
            if pdp_tasks:
                logger.info(f"   ⚡ [S. Vicente] Buscando EAN na PDP para {len(pdp_tasks)} produtos em paralelo...")
                resultados_pdp = await asyncio.gather(*pdp_tasks)
            
            # 3. Processa e finaliza os dados
            pdp_index = 0
            for item in produtos_para_processar:
                p = item["raw_data"]
                nome_bruto = item["nome_bruto"]
                img_url = item["img_url"]
                ean = item["ean_preliminar"]
                
                if item["precisa_pdp"]:
                    ean_from_page = resultados_pdp[pdp_index]
                    pdp_index += 1
                    if ean_from_page:
                        ean = ean_from_page
                
                if not ean or len(ean) < 12:
                    ean = "N/A"

                try:
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
                                except:
                                    condicao = nome_condicao
                            else:
                                condicao = nome_condicao

                    # Checa promoções de quantidade (Leve Mais)
                    if condicao == "1 UN":
                        if promos := p.get('promotions', []):
                            for pr in promos:
                                msg = pr.get('calloutMsg', '').replace('<br/>', ' ').strip().upper()
                                if any(x in msg for x in ["LEVE", "PAGUE", "A PARTIR"]):
                                    condicao = msg
                                    break

                    # --- LÓGICA DE TAXONOMIA ---
                    if cat_nome in CATEGORIAS_IGNORADAS:
                        continue
                    
                    # A 'cat_nome' (ex: 'CERVEJAS') é a nossa subcategoria mais provável.
                    # A 'padronizar_categoria' encontra a categoria principal (ex: 'BEBIDAS').
                    categoria_principal = padronizar_categoria(cat_nome, cat_nome)
                    subcategoria_base = formatar_nome_categoria(cat_nome)

                    # A categorização final será feita pelo 'validar_e_limpar_produtos' no orquestrador.
                    # Aqui, usamos a taxonomia base vinda do site para passar ao próximo passo.
                    categoria = categoria_principal
                    subcategoria = subcategoria_base
                    tipo_produto = "N/A" # Será refinado depois

                    marca = p.get('brand', 'PRÓPRIA').upper()
                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_bruto)
                    unid_venda = "KG" if " KG" in nome_bruto else "UN"

                    produtos_categoria.append({
                        "Mercado": NOME_MERCADO,
                        "EAN": ean,
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
                        "Condição": condicao, "Data_Hora": agora,
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