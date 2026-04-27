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

                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)

                    lote.append({
                        "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": "GERAL",
                        "Produto": nome_limpo, "Marca": str(item.get('brand', 'OUTROS')).upper(),
                        "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                        "Condição": "MEU CARREFOUR (CPF)" if p_a < p_v else "1 UN", 
                        "Data_Hora": agora, "Link_Imagem": link_foto
                    })
                except: continue
            return lote
        except: return []

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
            for pg in range(1, 11): # Varre 10 páginas de cada lado (1000 produtos)
                tarefas.append(extrair_lote(session, ordem, pg, sem, agora, indice_reverso))
        
        resultados = await asyncio.gather(*tarefas)
        for r in resultados:
            if r: lista_final.extend(r)

    # Remove duplicados por nome para a planilha final
    lista_unica = list({v['Produto']: v for v in lista_final}.values())
    logger.info(f"✅ Sucesso! {len(lista_unica)} produtos coletados para o GrabIt.")
    return lista_unica