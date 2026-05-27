import os
import asyncio
import warnings
from datetime import datetime
from curl_cffi import requests
from utils import extrair_medidas_inteligente, setup_logging, read_json_file

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES (SPECS)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'boa_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Boa Supermercados")
BASE_URL_CONFIG = CONFIG.get("base_url", "https://sitemercado.com.br/").rstrip('/')
API_ENDPOINT = CONFIG.get("api_endpoint", "api/b2c/v1/products/store/2679")

TECHNICAL_DEPS = CONFIG.get("technical_dependencies", {})
IMPERSONATE = TECHNICAL_DEPS.get("impersonation", "chrome124")

async def obter_departamentos(session):
    """Busca a lista completa de departamentos da loja"""
    url_deptos = f"{BASE_URL_CONFIG}/api/b2c/v1/departments/store/2679"
    try:
        res = await session.get(url_deptos, timeout=20)
        if res.status_code == 200:
            return res.json().get('departments', [])
        return []
    except Exception as e:
        logger.warning(f"Erro ao buscar departamentos Boa: {e}")
        return []

async def extrair_pagina_categoria(session, depto_slug, pagina, sem, agora):
    # Endpoint de busca com slug do departamento e paginação
    url = f"{BASE_URL_CONFIG}/{API_ENDPOINT}?department={depto_slug}&limit=50&page={pagina}&sort=price"
    
    async with sem:
        try:
            res = await session.get(url, timeout=30)
            if res.status_code != 200: return []
            
            dados = res.json()
            produtos_raw = dados.get('products', [])
            if not produtos_raw: return []

            lote = []
            for item in produtos_raw:
                try:
                    nome_cru = item.get('name', '').upper().strip()
                    if not nome_cru: continue
                    
                    ean_real = item.get('gtin', item.get('barcode', 'N/A'))
                    if ean_real: ean_real = str(ean_real).lstrip('0') or 'N/A'

                    p_v, p_a = float(item.get('price', 0)), float(item.get('promotional_price') or item.get('price', 0))
                    if p_a <= 0: continue
                    if p_v <= 0 or p_v < p_a: p_v = p_a

                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                    marca = str(item.get('brand', 'OUTROS')).upper()
                    img = item.get('image', {}).get('url', 'SEM IMAGEM') if isinstance(item.get('image'), dict) else 'SEM IMAGEM'
                    condicao = "CLIENTE BOA" if p_a < p_v else "1 UN"
                    link_pdp = item.get('url', '')

                    lote.append({
                        "Mercado": NOME_MERCADO, "EAN": ean_real, "Categoria": "GERAL",
                        "Produto": nome_limpo, "Marca": marca,
                        "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, "Medida": med, "Unidade": "UN", "Condição": condicao, "Data_Hora": agora, "Link_Imagem": img,
                        "Link_PDP": link_pdp
                    })
                except Exception:
                    continue
            return lote
        except Exception:
            return []

async def motor_extracao_boa_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para Boa...")
    lista_final, sem, agora = [], asyncio.Semaphore(5), datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    async with requests.AsyncSession(impersonate=IMPERSONATE) as session:
        # Obtém todos os departamentos da loja
        departamentos = await obter_departamentos(session)
        logger.info(f"   Foram encontrados {len(departamentos)} departamentos.")

        tarefas = []
        for depto in departamentos:
            slug = depto.get('slug')
            if not slug: continue
            
            logger.info(f"   Preparando extração de departamento: {slug}...")
            # Como a sitemercado limita a API, vamos varrer até um limite razoável (ex: 20 páginas = 1000 itens/depto)
            for pg in range(1, 21):
                tarefas.append(extrair_pagina_categoria(session, slug, pg, sem, agora))
        
        # Executa em lotes para controle
        chunk_size = 20
        for i in range(0, len(tarefas), chunk_size):
            chunk = tarefas[i:i+chunk_size]
            resultados = await asyncio.gather(*chunk)
            for r in resultados:
                if r: lista_final.extend(r)
            
        lista_unica = list({f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v for v in lista_final}.values())
        
    logger.info(f"✅ Sucesso! {len(lista_unica)} produtos coletados para o Full Catalog.")
    return lista_unica

async def extrair_dados():
    return await motor_extracao_boa_full()
