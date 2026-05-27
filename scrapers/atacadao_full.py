import os
import json
import warnings
import urllib.parse
import asyncio
from curl_cffi.requests import AsyncSession
import random
from datetime import datetime
from utils import extrair_medidas_inteligente, setup_logging, read_json_file, CATEGORIAS_IGNORADAS, formatar_nome_categoria

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'atacadao_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Atacadão")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://www.atacadao.com.br/").rstrip('/')
URL_LEGACY = f"{BASE_URL_CONFIG}/api/catalog_system/pub/products/search"
URL_CATEGORY_TREE = f"{BASE_URL_CONFIG}/api/catalog_system/pub/category/tree/3"

REGIONALIZATION = CONFIG.get("regionalization", {})
SELLER_ID = REGIONALIZATION.get("seller_id", "atacadaobr633")
REGION_ID = REGIONALIZATION.get("region_id", "U1cjYXRhY2FkYW9icjYzMw==")
CEP_JUNDIAI = REGIONALIZATION.get("cep_jundiai", "13211-772")

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome124")
USER_AGENT = TECHNICAL_DEPS.get("playwright_user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CONCURRENCY = 10 # Menor concorrência para não sobrecarregar em extrações grandes

def extract_category_ids(category_tree):
    """Extrai IDs de categorias folhas recursivamente"""
    ids = []
    for category in category_tree:
        # Se tem filhos, continua descendo
        if category.get('hasChildren') and category.get('children'):
            ids.extend(extract_category_ids(category.get('children')))
        else:
            # É folha
            ids.append((category.get('id'), category.get('name')))
    return ids

async def motor_extracao_atacadao_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO}...")
    lista_final = []
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    cookie_str = f'{{"salesChannel":"1","postalCode":"{CEP_JUNDIAI}","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'
    
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.atacadao.com.br/",
    }

    sem = asyncio.Semaphore(CONCURRENCY)

    async with AsyncSession(impersonate=IMPERSONATE, headers=headers) as session:
        session.cookies.set("regionalization", urllib.parse.quote(cookie_str), domain=urllib.parse.urlparse("https://www.atacadao.com.br").hostname)
        
        # 1. Obter a árvore de categorias
        logger.info("   Obtendo árvore de categorias...")
        try:
            res_tree = await session.get(URL_CATEGORY_TREE, timeout=30)
            if res_tree.status_code != 200:
                logger.error("   Falha ao obter categorias.")
                return []
            categorias_folhas = extract_category_ids(res_tree.json())
            logger.info(f"   Foram encontradas {len(categorias_folhas)} subcategorias para explorar.")
        except Exception as e:
            logger.error(f"   Erro ao acessar categorias: {e}")
            return []

        # 2. Extrair produtos de cada categoria (paginado)
        async def fetch_category_page(cat_id, cat_name, _from, _to, retries=3):
            async with sem:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                url = f"{URL_LEGACY}?fq=C:{cat_id}&_from={_from}&_to={_to}&sc=1"
                
                for attempt in range(retries):
                    try:
                        res = await session.get(url, timeout=40)
                        if res.status_code == 200:
                            if not res.text.strip(): return [] # Vazio
                            return res.json()
                        elif res.status_code == 206:
                            return res.json() # Partial content is OK in VTEX
                        else:
                            await asyncio.sleep(2)
                    except Exception as e:
                        await asyncio.sleep(2)
                return []

        async def process_category(cat_id, cat_name):
            produtos_categoria = []
            _from = 0
            _to = 49
            
            while True:
                dados = await fetch_category_page(cat_id, cat_name, _from, _to)
                if not dados or not isinstance(dados, list):
                    break
                    
                for p in dados:
                    try:
                        nome_cru = str(p.get('productName', '')).upper().strip()
                        if not nome_cru: continue

                        items = p.get('items', [])
                        if not items: continue
                        item_data = items[0]
                        
                        # EAN
                        ean_real = "N/A"
                        ref_ids = item_data.get('referenceId', [])
                        if ref_ids and isinstance(ref_ids, list):
                            ean_real = str(ref_ids[0].get('Value', '')).strip()
                        if not ean_real or len(ean_real) < 12:
                            ean_real = str(item_data.get('ean', '')).strip()
                        if not ean_real or not ean_real.isdigit() or len(ean_real) < 12:
                            ean_real = "N/A"

                        imagens = item_data.get('images', [])
                        imagem_url = imagens[0].get('imageUrl', "SEM IMAGEM") if imagens else "SEM IMAGEM"

                        # Preços
                        sellers = item_data.get('sellers', [])
                        if not sellers: continue
                        co = sellers[0].get('commertialOffer', {})
                        
                        p_var_legado = float(co.get('Price', 0.0))
                        list_pr = float(co.get('ListPrice', p_var_legado))
                        p_ata_legado = p_var_legado
                        cond_legada = "1 UN"
                        
                        if p_ata_legado <= 0: continue
                        
                        if list_pr > p_var_legado:
                            p_var_legado = list_pr
                            p_ata_legado = float(co.get('Price', 0.0))
                            cond_legada = "OFERTA"

                        cat_tree = p.get('categories', [])
                        categoria_str = cat_tree[0] if cat_tree else "GERAL"
                        
                        marca_str = str(p.get('brand', 'OUTROS')).upper()
                        nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                        link_pdp_rel = p.get('linkText', '') or p.get('link', '')
                        if link_pdp_rel:
                            link_pdp = f"https://www.atacadao.com.br/{link_pdp_rel}/p" if not link_pdp_rel.startswith('http') else link_pdp_rel
                        else:
                            link_pdp = ""

                        produtos_categoria.append({
                            "Mercado": NOME_MERCADO, "EAN": ean_real, "Categoria": categoria_str,
                            "Produto": nome_limpo, "Marca": marca_str,
                            "Preço Varejo": f"R$ {p_var_legado:.2f}".replace('.', ','), 
                            "Preço Atacado": f"R$ {p_ata_legado:.2f}".replace('.', ','),
                            "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                            "Condição": cond_legada, "Data_Hora": agora, "Link_Imagem": imagem_url,
                            "Link_PDP": link_pdp
                        })
                    except Exception:
                        continue
                
                if len(dados) < 50:
                    break
                _from += 50
                _to += 50
                if _from >= 2500: # Limite da VTEX
                    break
                    
            logger.info(f"   - Categoria {cat_name} ({cat_id}): {len(produtos_categoria)} itens capturados.")
            return produtos_categoria

        tarefas = [process_category(cat_id, cat_name) for cat_id, cat_name in categorias_folhas]
        
        # Executa em lotes para controlar a memória
        chunk_size = 5
        for i in range(0, len(tarefas), chunk_size):
            chunk = tarefas[i:i+chunk_size]
            resultados_chunk = await asyncio.gather(*chunk)
            for res in resultados_chunk:
                lista_final.extend(res)

    logger.info(f"✅ Extração FULL concluída. {len(lista_final)} itens brutos capturados.")
    # Deduplicar
    lista_unica = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in lista_final}.values())
    logger.info(f"   Total únicos: {len(lista_unica)}")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_atacadao_full()
