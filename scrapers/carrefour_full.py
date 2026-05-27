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
    if not url_imagem or not isinstance(url_imagem, str): return None
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    return match.group(1) if match else None

async def capturar_sessao():
    return {"region-id-food": REGION_ID, "cep": CEP_COOKIE_VALUE}

async def extrair_lote_categoria(session, category_url, pagina, sem, agora, indice_reverso):
    url = f"{BASE_URL_CONFIG}{category_url}?page={pagina}&sort=price_asc"
    
    async with sem:
        try:
            res = await session.get(url, timeout=30)
            if res.status_code != 200: return []
            
            # O Carrefour usa Remix, então a estrutura do JSON é um pouco diferente quando navega por categoria
            # Vamos tentar procurar o padrão 'products' no JSON
            dados_brutos = res.json()
            dados = reconstruir_json_remix(dados_brutos, 0)
            
            # Procurar array de produtos recursivamente
            produtos_raw = []
            def find_products(d):
                nonlocal produtos_raw
                if isinstance(d, dict):
                    if 'products' in d and isinstance(d['products'], list):
                        produtos_raw.extend(d['products'])
                    for v in d.values():
                        find_products(v)
                elif isinstance(d, list):
                    for item in d:
                        find_products(item)
            
            find_products(dados)
            
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
                    
                    link_foto = sku_p.get('images', [{}])[0].get('imageUrl', '')
                    ean_oficial = sku_p.get('ean')
                    
                    if not ean_oficial or ean_oficial == "N/A": ean = extrair_ean_pela_foto(link_foto)
                    else: ean = ean_oficial
                        
                    if not ean: ean = indice_reverso.get(normalizar_para_cache(nome_cru), "N/A")

                    off = sku_p.get('sellers', [{}])[0].get('commertialOffer', {})
                    p_v, p_a = float(off.get('ListPrice', 0)), float(off.get('Price', 0))
                    if p_a <= 0: continue
                    if p_v <= 0 or p_v < p_a: p_v = p_a

                    nome_limpo, qv, med = extrair_medidas_inteligente(nome_cru)
                    link_pdp = item.get('link', '')

                    lote.append({
                        "Mercado": NOME_MERCADO, "EAN": ean, "Categoria": "GERAL",
                        "Produto": nome_limpo, "Marca": str(item.get('brand', 'OUTROS')).upper(),
                        "Preço Varejo": f"R$ {p_v:.2f}".replace('.', ','),
                        "Preço Atacado": f"R$ {p_a:.2f}".replace('.', ','),
                        "Qtd_Valor": qv, "Medida": med, "Unidade": "UN",
                        "Condição": "1 UN", 
                        "Data_Hora": agora, "Link_Imagem": link_foto,
                        "Link_PDP": link_pdp
                    })
                except: continue
            return lote
        except: return []

async def motor_extracao_carrefour_full():
    cookies = await capturar_sessao()
    
    # Carrega biblioteca para fallback de EAN
    bib_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'biblioteca_produtos.json')
    indice_reverso = {}
    if os.path.exists(bib_path):
        biblioteca = read_json_file(bib_path)
        indice_reverso = {normalizar_para_cache(v.get('nome_comum', '')): v.get('ean', 'N/A') for v in biblioteca.values()}

    logger.info(f"🚀 Iniciando extração FULL CATALOG para Carrefour...")
    lista_final, sem, agora = [], asyncio.Semaphore(5), datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Lista de departamentos principais do Carrefour para varrer
    departamentos = [
        "/mercearia", "/bebidas", "/frios-e-laticinios", "/carnes-aves-e-peixes",
        "/limpeza", "/higiene-e-perfumaria", "/hortifruti", "/padaria",
        "/congelados", "/pet-shop"
    ]

    async with requests.AsyncSession(impersonate="chrome124", cookies=cookies) as session:
        tarefas = []
        for depto in departamentos:
            logger.info(f"   Preparando extração de {depto}...")
            # Paginando até um limite razoável por departamento (ex: 50 páginas de 50 = 2500 itens)
            for pg in range(1, 51):
                tarefas.append(extrair_lote_categoria(session, depto, pg, sem, agora, indice_reverso))
        
        # Executa em lotes
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
    return await motor_extracao_carrefour_full()
