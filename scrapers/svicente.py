import os
import asyncio
import warnings
import json
from curl_cffi.requests import AsyncSession
from datetime import datetime
from utils import padronizar_categoria, extrair_medidas_inteligente, setup_logging, read_json_file, MAPA_PARA_APP, CATEGORIAS_IGNORADAS

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
CGID_OFERTAS = CONFIG.get("regionalization", {}).get("cgid", "ofertas-header")
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

async def buscar_pagina_svicente(session, cgid, start):
    params = {"cgid": cgid, "pmid": PMID, "start": start, "sz": TAMANHO_PAGINA}
    try:
        response = await session.get(URL_BASE, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"  [São Vicente] Erro na página {start}: {e}")
    return None

async def processar_categoria(session, cgid, cat_nome, semaforo, agora):
    async with semaforo:
        logger.info(f"📡 [São Vicente] Sincronizando categoria: {cat_nome}")
        
        data_inicial = await buscar_pagina_svicente(session, cgid, 0)
        if not data_inicial: return []

        total_produtos = data_inicial.get('productSearch', {}).get('count', 0)
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

                    # Varre a lista de 'flagtypes' (onde o preço do clube se esconde)
                    flags = p.get('flagtypes', [])
                    for f in flags:
                        if f.get('flagType') == "facil-pra-voce":
                            raw_val = f.get('valueFlagType', "") # Ex: "R$ 18,90"
                            if raw_val:
                                try:
                                    # Limpa o "R$" e converte a vírgula para ponto
                                    p_clube = float(raw_val.replace('R$', '').replace('.', '').replace(',', '.').strip())
                                    valor_varejo = p_venda     # Preço comum vai para Varejo
                                    valor_atacado = p_clube    # Preço Clube vai para Atacado
                                    condicao = "CLUBE SV"
                                except:
                                    condicao = "CLUBE SV"

                    # Se não for clube, checa promoções de quantidade (Leve Mais)
                    if condicao == "1 UN":
                        if promos := p.get('promotions', []):
                            for pr in promos:
                                msg = pr.get('calloutMsg', '').replace('<br/>', ' ').strip().upper()
                                if any(x in msg for x in ["LEVE", "PAGUE", "A PARTIR"]):
                                    condicao = msg
                                    break

                    # --- NOVA LÓGICA DE TAXONOMIA ---
                    # Salesforce Commerce Cloud não costuma mandar a árvore inteira no produto.
                    cat_site = ""
                    subcategoria = "N/A"
                    tipo_produto = "N/A"

                    # Tentativa de extrair de um 'categoryTree' se existir (pouco provável, mas seguro)
                    cat_tree = p.get('categoryTree', [])
                    if isinstance(cat_tree, list) and cat_tree:
                        if len(cat_tree) > 0 and cat_tree[0].get('name'): cat_site = cat_tree[0].get('name').upper()
                        if len(cat_tree) > 1 and cat_tree[1].get('name'): subcategoria = cat_tree[1].get('name').upper()
                        if len(cat_tree) > 2 and cat_tree[2].get('name'): tipo_produto = cat_tree[2].get('name').upper()

                    if cat_site in CATEGORIAS_IGNORADAS:
                        continue
                    
                    categoria = MAPA_PARA_APP.get(cat_site, padronizar_categoria(nome_bruto, p.get('categoryName', cat_nome)))

                    # Metadados e Limpeza
                    img_url = ""
                    imgs = p.get('images', {})
                    for size in ['medium', 'large', 'small']:
                        if size in imgs and imgs[size]:
                            img_url = imgs[size][0].get('url', "")
                            if img_url.startswith('/'): img_url = "https://www.svicente.com.br" + img_url
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
        
        return produtos_categoria

async def motor_extracao_svicente():
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    async with AsyncSession(impersonate=IMPERSONATE) as session:
        # Foca apenas na categoria de ofertas
        return await processar_categoria(session, CGID_OFERTAS, "OFERTAS", asyncio.Semaphore(CONCURRENCY), agora)

async def extrair_dados():
    return await motor_extracao_svicente()