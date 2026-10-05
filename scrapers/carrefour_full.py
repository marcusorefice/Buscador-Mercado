import os
import asyncio
import warnings
import json
import re
from datetime import datetime
from curl_cffi import requests
from utils import ean_eh_valido, setup_logging, read_json_file, normalizar_para_cache, CacheEanPdp

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

PAGE_SIZE = 50
MAX_PAGES = 50

async def capturar_sessao():
    return {
        "region-id-food": REGION_ID,
        "vtex_segment": REGION_ID,
        "cep": CEP_COOKIE_VALUE,
    }


def extrair_ean_pela_foto(url_imagem):
    if not url_imagem or not isinstance(url_imagem, str):
        return None
    match = re.search(r'(789\d{10}|790\d{10})', url_imagem)
    if match and ean_eh_valido(match.group(1)):
        return match.group(1)
    return None

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
                    res[chave_real] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
                except: continue
            else:
                res[k] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
        return res
    return node

async def obter_categorias_menu(session):
    """
    Usa a técnica descoberta no carrefour.py: o endpoint da coleção
    retorna o 'layout/default' que contém toda a árvore de menu do site!
    """
    url = f"{BASE_URL_CONFIG}/colecao/{CLUSTER_ID}.data?_routes=layout%2Fdefault"
    logger.info(f"   📡 Buscando árvore de menu em: {url}")
    try:
        res = await session.get(url, timeout=30)
        if res.status_code == 200:
            json_str = res.text
            paths = re.findall(r'https://mercado\.carrefour\.com\.br/categoria/([^?"\'#]+)', json_str)
            unique_paths = list(set(paths))
            logger.info(f"   🔍 Analisando {len(unique_paths)} links de categorias brutos encontrados...")
            
            folhas = []
            for p in unique_paths:
                is_parent = False
                for other in unique_paths:
                    if other != p and other.startswith(p + '/'):
                        is_parent = True
                        break
                if not is_parent:
                    folhas.append(p)
            
            logger.info(f"   🌳 {len(folhas)} subcategorias finais (folhas) filtradas prontas para varredura.")
            return folhas
        else:
            logger.error(f"   ❌ Falha ao acessar o menu. Status HTTP: {res.status_code}")
    except Exception as e:
        logger.error(f"   ❌ Erro ao extrair categorias do menu: {e}")
    return []

def _parse_produto(item, agora, indice_reverso, cat_path):
    try:
        p = item.get('node', item)
        nome_cru = p.get('name', p.get('productName', '')).upper().strip()
        if not nome_cru: return None

        skus = p.get('items', [])
        if not skus: return None
        sku_p = skus[0]

        link_foto = sku_p.get('images', [{}])[0].get('imageUrl', '')
        ean_oficial = sku_p.get('ean')

        if not ean_oficial or ean_oficial in ("N/A", ""):
            ean = extrair_ean_pela_foto(link_foto)
        else:
            ean = ean_oficial

        if not ean:
            ean = indice_reverso.get(normalizar_para_cache(nome_cru), "N/A")

        off = sku_p.get('sellers', [{}])[0].get('commertialOffer', {})
        p_v, p_a = float(off.get('ListPrice', 0)), float(off.get('Price', 0))
        if p_a <= 0: return None
        if p_v <= 0 or p_v < p_a: p_v = p_a

        unit_multiplier = float(sku_p.get('unitMultiplier') or 1.0)
        if unit_multiplier > 0 and unit_multiplier < 1.0:
            if p_v > (p_a * (1 / unit_multiplier) * 0.5): 
                p_v = p_v * unit_multiplier
            else:
                p_v = p_v * unit_multiplier
                p_a = p_a * unit_multiplier

        nome_limpo, qv, med = nome_cru, "1", "UN"
        
        measurement_unit = str(sku_p.get('measurementUnit', '')).lower()
        
        if measurement_unit == 'kg' or nome_cru.upper().endswith(' KG'):
            unidade_venda = "KG"
            if qv == "1" and med == "UN":
                qv, med = "1", "KG"
        elif measurement_unit == 'g':
            unidade_venda = "UN"
            if qv == "1" and med == "UN":
                qv, med = str(int(unit_multiplier)), "G"
        else:
            unidade_venda = "UN"
                
        if nome_cru.endswith(" KG"):
            unidade_venda = "KG"
            if qv == "1" and med == "UN":
                qv, med = "1", "KG"
                
        nome_limpo = re.sub(r'\s*KG$', '', nome_limpo, flags=re.IGNORECASE).strip()

        partes_cat = cat_path.split('/')
        cat_site = partes_cat[0].upper() if partes_cat else "GERAL"

        link_pdp_rel = p.get('linkText') or p.get('link') or p.get('url') or ''
        if link_pdp_rel:
            if link_pdp_rel.startswith('http'):
                link_pdp = link_pdp_rel
            elif link_pdp_rel.startswith('/'):
                link_pdp = f"{BASE_URL_CONFIG}{link_pdp_rel}"
            else:
                link_pdp = f"{BASE_URL_CONFIG}/{link_pdp_rel}/p"
        else:
            link_pdp = ""

        marca_obj = p.get('brand', 'OUTROS')
        marca_str = marca_obj.get('name', 'OUTROS') if isinstance(marca_obj, dict) else str(marca_obj)

        return {
            "Mercado": NOME_MERCADO,
            "EAN": ean,
            "Categoria": cat_site,
            "Produto": nome_limpo,
            "Marca": marca_str.upper(),
            "Preço Varejo": round(p_v, 2),
            "Preço Atacado": round(p_a, 2),
            "Qtd_Valor": qv,
            "Medida": med,
            "Unidade": unidade_venda,
            "Condição": "MEU CARREFOUR (CPF)" if p_a < p_v else "1 UN",
            "Data_Hora": agora,
            "Link_Imagem": link_foto,
            "Link_PDP": link_pdp,
        }
    except Exception:
        return None

async def extrair_pagina_categoria(session, cat_path, ordem, pagina, sem, agora, indice_reverso):
    _from = pagina * PAGE_SIZE
    _to = _from + PAGE_SIZE - 1
    
    parts = [p for p in cat_path.split('/') if p]
    
    async with sem:
        # By-Pass via SSR Frontend (Remix .data endpoint com a rota category-search nativa)
        try:
            url_data = (
                f"{BASE_URL_CONFIG}/categoria/{cat_path}.data?"
                f"count={PAGE_SIZE}&page={pagina}&sort={ordem}&_routes=layout%2Fdefault%2Croutes%2Fcategory-search"
            )
            
            res_data = await session.get(url_data, timeout=15)
            if res_data.status_code == 200:
                dados_brutos = res_data.json()
                dados = reconstruir_json_remix(dados_brutos, 0)
                
                produtos_raw = []
                def procurar_produtos(d):
                    nonlocal produtos_raw
                    if produtos_raw: return
                    if isinstance(d, dict):
                        if "products" in d and isinstance(d["products"], list) and len(d["products"]) > 0:
                            if isinstance(d["products"][0], dict) and ("productName" in d["products"][0] or "name" in d["products"][0] or "node" in d["products"][0]):
                                produtos_raw = d["products"]
                                return
                        for v in d.values(): procurar_produtos(v)
                    elif isinstance(d, list):
                        for v in d: procurar_produtos(v)
                
                procurar_produtos(dados)
                
                if produtos_raw:
                    lote = []
                    for p in produtos_raw:
                        parsed = _parse_produto(p, agora, indice_reverso, cat_path)
                        if parsed:
                            lote.append(parsed)
                    acabou = len(produtos_raw) < PAGE_SIZE
                    if lote: return lote, acabou
        except Exception as e:
            pass # Ignora erros de timeout

        return [], True

async def varrer_categoria(session, cat_path, sem, agora, indice_reverso):
    coletados = []
    logger.info(f"   🔍 Iniciando varredura na categoria: /{cat_path}")
    for ordem in ["orders_desc", "price_asc"]:
        for pagina in range(0, MAX_PAGES):
            lote, acabou = await extrair_pagina_categoria(
                session, cat_path, ordem, pagina, sem, agora, indice_reverso
            )
            if lote:
                coletados.extend(lote)
                logger.info(f"      📄 [/{cat_path}] - Página {pagina} ({ordem}): +{len(lote)} itens")
            if acabou:
                break
                
    unicos = list({f"{v['Produto']}_{v['Marca']}_{v['Qtd_Valor']}_{v['Medida']}": v for v in coletados}.values())
    if unicos:
        logger.info(f"   📦 [/{cat_path}] {len(unicos)} produtos.")
    else:
        logger.info(f"   ⚠️ [/{cat_path}] Nenhum produto encontrado.")
    return unicos

async def fetch_ean_from_pdp(session, url_pdp, sem_pdp):
    if not url_pdp:
        return "N/A"
    if not url_pdp.startswith('http'):
        url_pdp = f"{BASE_URL_CONFIG}{url_pdp}"

    async with sem_pdp:
        try:
            res = await session.get(url_pdp, timeout=20)
            if res.status_code == 200:
                html = res.text
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

                match = re.search(r'(?:gtin\d*|ean|sku)["\s:]+["\s]*(\d{13})', html, re.IGNORECASE)
                if match:
                    return match.group(1)

                match_any = re.search(r'(789\d{10}|790\d{10})', html)
                if match_any:
                    return match_any.group(1)
        except Exception:
            pass
    return "N/A"


async def enrich_eans_from_pdps(session, lista_produtos):
    sem_pdp = asyncio.Semaphore(15)
    produtos_sem_ean = [p for p in lista_produtos if not p.get('EAN') or p.get('EAN') == 'N/A']
    if not produtos_sem_ean:
        return

    # O EAN de cada produto fica guardado entre coletas: só produtos novos precisam abrir a página
    cache = CacheEanPdp(NOME_MERCADO)
    do_cache = 0
    a_buscar = []
    for p in produtos_sem_ean:
        guardado = cache.buscar(p.get('Link_PDP'))
        if guardado is None:
            a_buscar.append(p)
        else:
            do_cache += 1
            if guardado != 'N/A':
                p['EAN'] = guardado
    produtos_sem_ean = a_buscar

    total_pdps = len(produtos_sem_ean)
    logger.info(f"   🔍 EAN de {do_cache} produtos veio do cache; buscando {total_pdps} páginas de produtos (Turbo Mode)...")

    contador = 0

    async def fetch_and_log(p):
        nonlocal contador
        ean = await fetch_ean_from_pdp(session, p.get('Link_PDP'), sem_pdp)
        contador += 1
        if contador % 50 == 0 or contador == total_pdps:
            logger.info(f"   ⏳ [Carrefour] Progresso PDPs: {contador}/{total_pdps} processados...")
        return ean

    tasks = [fetch_and_log(p) for p in produtos_sem_ean]
    resultados = await asyncio.gather(*tasks)

    for p, ean in zip(produtos_sem_ean, resultados):
        cache.guardar(p.get('Link_PDP'), ean)
        if ean != 'N/A':
            p['EAN'] = ean
    cache.salvar()

async def extrair_dados():
    cookies = await capturar_sessao()

    bib_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'biblioteca_produtos.json')
    biblioteca = read_json_file(bib_path)
    indice_reverso = {
        normalizar_para_cache(v.get('nome_comum', '')): v.get('ean', 'N/A')
        for v in biblioteca.values()
    }

    logger.info("🚀 Iniciando extração COMPLETA Jundiaí (por categorias)...")
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    sem = asyncio.Semaphore(8)  # concorrência de páginas
    lista_final = []

    async with requests.AsyncSession(impersonate="chrome124", cookies=cookies) as session:
        categorias = await obter_categorias_menu(session)
        if not categorias:
            logger.error("   ❌ Nenhuma categoria obtida. Abortando.")
            return []

        logger.info(f"   🚀 Disparando tarefas simultâneas para {len(categorias)} categorias...")

        tarefas = [
            varrer_categoria(session, cat, sem, agora, indice_reverso)
            for cat in categorias
        ]
        resultados = await asyncio.gather(*tarefas)
        for r in resultados:
            if r:
                lista_final.extend(r)

        # Dedup por nome+marca+medida (preserva variações de tamanho)
        lista_unica = list({
            f"{v.get('Produto','')}_{v.get('Marca','')}_{v.get('Qtd_Valor','')}_{v.get('Medida','')}": v
            for v in lista_final
        }.values())

        await enrich_eans_from_pdps(session, lista_unica)

    logger.info(f"✅ Sucesso! {len(lista_unica)} produtos coletados para o GrabIt.")
    return lista_unica
