import os
import asyncio
import warnings
import json
import re
from datetime import datetime
from curl_cffi import requests
from utils import (
    extrair_medidas_inteligente, setup_logging, 
    read_json_file, formatar_nome_categoria, normalizar_para_cache
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
CLUSTER_ID = REGIONALIZATION.get("cluster_id", "28617")
REGION_ID = REGIONALIZATION.get("region_id", "InYyLjc5MDlFOEZDNjU2N0M3OTU5NjA4MDFCQTU5RDFFMEQ3Ig==")
CEP_COOKIE_VALUE = REGIONALIZATION.get("cep_cookie_value", "IkhpcGVyIEp1bmRpYcOtIg==")

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
                    res[chave_real] = reconstruir_json_remix(dados_flat, v)
                except: continue
            else:
                res[k] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
        return res
    return node

def extrair_ean_pela_foto(url_imagem):
    """
    Técnica de Engenharia Reversa: Captura o EAN-13 embutido no nome do arquivo.
    Como validamos no F12 de Jundiaí, a foto costuma ter o EAN no nome.
    """
    if not url_imagem or not isinstance(url_imagem, str):
        return None
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    return match.group(1) if match else None

async def capturar_sessao():
    return {"region-id-food": REGION_ID, "cep": CEP_COOKIE_VALUE}

async def extrair_lote(session, ordem, pagina, sem, agora, indice_reverso):
    # URL da lista que já traz os produtos e links das imagens
    url = f"{BASE_URL_CONFIG}/colecao/{CLUSTER_ID}.data?map=productClusterIds&count=50&page={pagina}&sort={ordem}&_routes=layout%2Fdefault%2Croutes%2Fcolecao.%24collectionId"
    
    async with sem:
        try:
            res = await session.get(url, timeout=30)
            if res.status_code != 200: return []
            
            dados_brutos = res.json()
            dados = reconstruir_json_remix(dados_brutos, 0)
            colecao = dados.get("routes/colecao.$collectionId", {})
            produtos_raw = colecao.get("products", []) or colecao.get("data", {}).get("products", [])
            
            if not produtos_raw: return []

            lote = []
            for p in produtos_raw:
                try:
                    item = p.get('node', p)
                    nome_cru = item.get('name', item.get('productName', '')).upper().strip()
                    if not nome_cru: continue

                    skus = item.get('items', [])
                    if not skus: continue
                    sku_p = skus[0]
                    
                    # --- O PULO DO GATO: EXTRAÇÃO SEM 503 ---
                    link_foto = sku_p.get('images', [{}])[0].get('imageUrl', '')
                    ean_oficial = sku_p.get('ean')
                    
                    # Se o oficial vier vazio (comum no Carrefour), pega da foto
                    if not ean_oficial or ean_oficial == "N/A":
                        ean = extrair_ean_pela_foto(link_foto)
                    else:
                        ean = ean_oficial
                        
                    # Se ainda assim não tiver, olha no cache da biblioteca
                    if not ean:
                        ean = indice_reverso.get(normalizar_para_cache(nome_cru), "N/A")

                    # Preços
                    off = sku_p.get('sellers', [{}])[0].get('commertialOffer', {})
                    p_v, p_a = float(off.get('ListPrice', 0)), float(off.get('Price', 0))
                    if p_a <= 0: continue
                    if p_v <= 0 or p_v < p_a: p_v = p_a

                    # --- CORREÇÃO DE UNIT MULTIPLIER (HORTIFRUTI VTEX) --- #
                    unit_multiplier = float(sku_p.get('unitMultiplier') or 1.0)
                    if unit_multiplier > 0 and unit_multiplier < 1.0:
                        if p_v > (p_a * (1 / unit_multiplier) * 0.5): 
                            p_a = p_a / unit_multiplier
                        elif p_v < (p_a * 2):
                            p_v = p_v / unit_multiplier
                            p_a = p_a / unit_multiplier

                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                    # Pega o link da página do produto (PDP)
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
                        "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": "GERAL",
                        "Produto": nome_limpo, "Marca": str(item.get('brand', 'OUTROS')).upper(),
                        "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                        "Condição": "MEU CARREFOUR (CPF)" if p_a < p_v else "1 UN", 
                        "Data_Hora": agora, "Link_Imagem": link_foto,
                        "Link_PDP": link_pdp
                    })
                except: continue
            return lote
        except: return []

async def fetch_ean_from_pdp(session, url_pdp, sem_pdp):
    """Busca o EAN no HTML da página de detalhes do produto do Carrefour"""
    if not url_pdp: return "N/A"
    
    if not url_pdp.startswith('http'):
        url_pdp = f"{BASE_URL_CONFIG}{url_pdp}"
        
    async with sem_pdp:
        try:
            res = await session.get(url_pdp, timeout=20)
            if res.status_code == 200:
                html = res.text
                
                # 1. Tenta extrair via ld+json (mais preciso)
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    for script in soup.find_all('script', type='application/ld+json'):
                        data = json.loads(script.string)
                        if isinstance(data, dict) and data.get('@type') == 'Product':
                            ean = data.get('gtin13') or data.get('gtin') or data.get('sku')
                            if ean and len(str(ean)) >= 12:
                                return str(ean)
                except Exception:
                    pass

                # 2. Tenta padrão explícito (gtin, ean, sku com 13 digitos)
                match = re.search(r'(?:gtin\d*|ean|sku)["\s:]+["\s]*(\d{13})', html, re.IGNORECASE)
                if match:
                    return match.group(1)
                
                # 3. Fallback: Qualquer sequência de 13 dígitos começando com 789 ou 790
                match_any = re.search(r'(789\d{10}|790\d{10})', html)
                if match_any:
                    return match_any.group(1)
        except:
            pass
    return "N/A"

async def enrich_eans_from_pdps(session, lista_produtos):
    """Enriquece produtos sem EAN buscando na página do produto (PDP)"""
    sem_pdp = asyncio.Semaphore(15) # Concorrência para PDP
    
    produtos_sem_ean = [p for p in lista_produtos if not p.get('EAN') or p.get('EAN') == 'N/A']
    if not produtos_sem_ean: return
    
    total_pdps = len(produtos_sem_ean)
    logger.info(f"   🔍 Buscando EAN em {total_pdps} páginas de produtos (Turbo Mode)...")
    
    contador = 0
    async def fetch_and_log(p):
        nonlocal contador
        ean = await fetch_ean_from_pdp(session, p.get('Link_PDP'), sem_pdp)
        contador += 1
        if contador % 50 == 0 or contador == total_pdps:
            logger.info(f"   ⏳ [Carrefour] Progresso PDPs: {contador}/{total_pdps} processados...")
        return ean

    # Criar lista de tasks mantendo a referência do produto
    tasks = [fetch_and_log(p) for p in produtos_sem_ean]
        
    resultados = await asyncio.gather(*tasks)
    
    # Atualiza os EANs encontrados
    for p, ean in zip(produtos_sem_ean, resultados):
        if ean != 'N/A':
            p['EAN'] = ean

async def extrair_dados():
    cookies = await capturar_sessao()
    
    # Carrega biblioteca para fallback de EAN
    bib_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'biblioteca_produtos.json')
    biblioteca = read_json_file(bib_path)
    indice_reverso = {normalizar_para_cache(v.get('nome_comum', '')): v.get('ean', 'N/A') for v in biblioteca.values()}

    logger.info(f"🚀 Iniciando extração Turbo Jundiaí (EAN via Imagem)...")
    lista_final, sem, agora = [], asyncio.Semaphore(5), datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    async with requests.AsyncSession(impersonate="chrome124", cookies=cookies) as session:
        tarefas = []
        for ordem in ["price_asc", "price_desc"]:
            for pg in range(1, 35): # Varre 34 páginas de cada lado (1700 produtos por ordem, cobrindo os 2664 totais)
                tarefas.append(extrair_lote(session, ordem, pg, sem, agora, indice_reverso))
        
        resultados = await asyncio.gather(*tarefas)
        for r in resultados:
            if r: lista_final.extend(r)
            
        # Remove duplicados combinando nome, marca e medidas para evitar perda de variações
        lista_unica = list({f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v for v in lista_final}.values())
        
        # Enriquecimento (Fallback final)
        await enrich_eans_from_pdps(session, lista_unica)

    logger.info(f"✅ Sucesso! {len(lista_unica)} produtos coletados para o GrabIt.")
    return lista_unica