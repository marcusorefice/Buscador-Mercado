"""
Coleta do catálogo completo do Pão de Açúcar.

O site deixou de trazer os produtos no HTML das páginas de categoria (os links /secoes/ dão 404 e a
listagem por categoria da própria API também). O que funciona é a BUSCA do site, então:
  1. pega a árvore de categorias do site e usa o nome de cada categoria (todos os níveis) como termo;
  2. pagina a busca de cada termo (21 produtos por página) e junta os produtos pelo SKU;
  3. consulta o preço ao vivo (de/por, promoções, Cliente Mais) em lotes, como o site faz;
  4. converte cada produto com a mesma função do scraper diário (montar_item);
  5. busca o EAN na página do produto, com cache entre coletas.
"""
import asyncio
import json
import re
from datetime import datetime

from curl_cffi.requests import AsyncSession

from utils import setup_logging, CacheEanPdp
from scrapers.paodeacucar import (
    NOME_MERCADO, BASE_URL_CONFIG, STORE_ID, IMPERSONATE, USER_AGENT, montar_item, fetch_ean_from_pdp,
)

logger = setup_logging()

URL_BUSCA = "https://api.vendas.gpa.digital/pa/search/search"
URL_PRECO_AO_VIVO = f"https://api.vendas.gpa.digital/pa/v3/products/ecom/skuLivePrice?storeId={STORE_ID}&sellType=null&sortBy=null&isClienteMais=true"
POR_PAGINA = 21            # a busca ignora valores maiores
LOTE_PRECO = 40            # mesmo tamanho de lote que o site usa
MAX_PAGINAS_POR_TERMO = 50
CONCORRENCIA = 6
IS_TEST_MODE = False       # True: usa só alguns termos (teste rápido)

HEADERS = {
    "User-Agent": USER_AGENT,
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": BASE_URL_CONFIG,
    "referer": f"{BASE_URL_CONFIG}/",
}


async def obter_termos(session):
    """Nomes de todas as categorias do site, cada um com o nome do departamento (vira a Categoria do item)."""
    res = await session.get(f"{BASE_URL_CONFIG}/categoria/bebidas-alcoolicas/vinhos-e-espumantes", timeout=30)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
    if not m:
        return []
    arvore = json.loads(m.group(1)).get("props", {}).get("initialProps", {}).get("layoutProps", {}).get("categories", [])
    termos = {}

    def percorrer(nos, departamento):
        for no in nos or []:
            nome = str(no.get("name", "")).strip()
            dep = departamento or nome
            if nome and nome.lower() not in termos:
                termos[nome.lower()] = (nome, dep.upper())
            percorrer(no.get("subCategory"), dep)

    percorrer(arvore, None)
    return list(termos.values())


async def buscar_termo(session, termo, departamento, sem, produtos):
    """Pagina a busca de um termo e guarda os produtos novos em `produtos` (chave: SKU)."""
    pagina, total_paginas, novos = 1, 1, 0
    while pagina <= min(total_paginas, MAX_PAGINAS_POR_TERMO):
        payload = {"terms": termo, "page": pagina, "sortBy": "relevance", "resultsPerPage": POR_PAGINA,
                   "allowRedirect": True, "storeId": STORE_ID, "department": "ecom", "customerPlus": True, "partner": "fallback"}
        async with sem:
            try:
                res = await session.post(URL_BUSCA, json=payload, headers=HEADERS, timeout=30)
                if res.status_code != 200:
                    break
                dados = res.json()
            except Exception as e:
                logger.warning(f"   [Pão de Açúcar] Falha na busca '{termo}' página {pagina}: {e}")
                break
        total_paginas = dados.get("totalPages") or 1
        lista = dados.get("products") or []
        if not lista:
            break
        for p in lista:
            sku = str(p.get("sku") or "")
            if sku and sku not in produtos:
                produtos[sku] = {"busca": p, "departamento": departamento}
                novos += 1
        pagina += 1
    return novos


async def precos_ao_vivo(session, skus, sem):
    """Preço ao vivo (de/por, promoções, Cliente Mais) dos SKUs, em lotes. Retorna {id_produto: dados}."""
    resultado = {}

    async def lote(parte):
        async with sem:
            for tentativa in range(3):
                try:
                    res = await session.post(URL_PRECO_AO_VIVO, json=parte, headers=HEADERS, timeout=30)
                    if res.status_code == 200:
                        for c in (res.json().get("content") or []):
                            resultado[c.get("id")] = c
                        return
                except Exception:
                    pass
                await asyncio.sleep(1 + tentativa)

    await asyncio.gather(*[lote(skus[i:i + LOTE_PRECO]) for i in range(0, len(skus), LOTE_PRECO)])
    return resultado


async def preencher_eans(session, itens):
    """EAN pela página do produto, com cache entre coletas (o EAN de um produto não muda)."""
    cache = CacheEanPdp(NOME_MERCADO)
    a_buscar = []
    for item in itens:
        guardado = cache.buscar(item.get("Link_PDP"))
        if guardado is None:
            a_buscar.append(item)
        elif guardado != "N/A":
            item["EAN"] = guardado
    logger.info(f"   🔍 EAN de {len(itens) - len(a_buscar)} produtos veio do cache; buscando {len(a_buscar)} páginas de produtos...")
    sem_pdp = asyncio.Semaphore(20)
    feitos = 0

    async def um(item):
        nonlocal feitos
        r = await fetch_ean_from_pdp(session, item.get("Link_PDP"), sem_pdp)
        feitos += 1
        if feitos % 500 == 0:
            logger.info(f"   ⏳ [Pão de Açúcar] Páginas de produto: {feitos}/{len(a_buscar)}")
        return r

    resultados = await asyncio.gather(*[um(i) for i in a_buscar])
    for item, r in zip(a_buscar, resultados):
        ean = r.get("ean", "N/A")
        cache.guardar(item.get("Link_PDP"), ean)
        if ean != "N/A":
            item["EAN"] = ean
    cache.salvar()


async def motor_extracao_paodeacucar_full():
    logger.info(f"🚀 Iniciando extração FULL CATALOG para {NOME_MERCADO} (via busca do site)...")
    agora = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    sem = asyncio.Semaphore(CONCORRENCIA)

    async with AsyncSession(impersonate=IMPERSONATE) as session:
        termos = await obter_termos(session)
        if not termos:
            logger.error("   Não foi possível ler a árvore de categorias do site.")
            return []
        if IS_TEST_MODE:
            termos = termos[:15]
        logger.info(f"   {len(termos)} termos de categoria para buscar...")

        produtos = {}
        novos_por_termo = await asyncio.gather(*[buscar_termo(session, nome, dep, sem, produtos) for nome, dep in termos])
        logger.info(f"   {len(produtos)} produtos únicos encontrados na busca ({sum(1 for n in novos_por_termo if n == 0)} termos sem produto novo).")

        precos = await precos_ao_vivo(session, list(produtos.keys()), sem)
        logger.info(f"   Preço ao vivo obtido para {len(precos)} produtos.")

        itens = {}
        for sku, info in produtos.items():
            base = info["busca"]
            dados = dict(base)
            dados.update(precos.get(base.get("id")) or {})   # preço ao vivo tem de/por e promoções
            dados.setdefault("departmentName", info["departamento"])
            try:
                item = montar_item(dados, agora)
            except Exception as e:
                logger.warning(f"   [Pão de Açúcar] Produto ignorado ({base.get('name')}): {e}")
                continue
            if not item:
                continue
            if not item.get("Categoria") or item["Categoria"] == "GERAL":
                item["Categoria"] = info["departamento"]
            itens[item.pop("ID_UNICO", sku)] = item

        lista = list(itens.values())
        await preencher_eans(session, lista)

    logger.info(f"🏆 SUCESSO! {len(lista)} produtos capturados do {NOME_MERCADO} Full Catalog.")
    return lista


async def extrair_dados():
    return await motor_extracao_paodeacucar_full()
