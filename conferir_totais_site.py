import asyncio
import os
import json
import re
import urllib.parse
from curl_cffi.requests import AsyncSession

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

async def check_vtex_legacy(session, url, nome):
    """O Pulo do Gato para a VTEX: O cabeçalho 'resources' revela o total exato."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        res = await session.get(f"{url}/api/catalog_system/pub/products/search?_from=0&_to=0&sc=1", headers=headers, timeout=15)
        resources = res.headers.get("resources", "")
        if "/" in resources:
            total = int(resources.split("/")[-1])
            return nome, total
    except Exception:
        pass
    return nome, "Não revelado pela API"

async def check_atacadao(session):
    """Atacadão usa GraphQL, podemos extrair a chave totalCount na raiz."""
    query = """
    query ProductsQuery($term: String, $selectedFacets: [SelectedFacetInput], $first: Int) {
      search(term: $term, selectedFacets: $selectedFacets, first: $first) {
        products { pageInfo { totalCount } }
      }
    }
    """
    payload = {
        "operationName": "ProductsQuery",
        "variables": {
            "first": 1, "term": "",
            "selectedFacets": [
                {"key": "region-id", "value": "U1cjYXRhY2FkYW9icjYzMw=="},
                {"key": "channel", "value": '{"salesChannel":"1","seller":"atacadaobr633","regionId":"U1cjYXRhY2FkYW9icjYzMw=="}'},
                {"key": "locale", "value": "pt-BR"}
            ]
        },
        "query": query
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://www.atacadao.com.br",
        "Referer": "https://www.atacadao.com.br/catalogo",
    }
    try:
        res = await session.post("https://www.atacadao.com.br/api/graphql", json=payload, headers=headers, timeout=15)
        total = res.json().get('data', {}).get('search', {}).get('products', {}).get('pageInfo', {}).get('totalCount', 0)
        if total > 0: return "Atacadão", total
    except:
        pass
    return "Atacadão", "Não revelado pela API"

async def check_paodeacucar(session):
    """O Pão de Açúcar usa a API da Linx. Somamos o total de cada departamento base."""
    deps = [
        "mercearia", "carnes-e-aves", "peixaria", "frios-e-laticinios", "hortifruti",
        "bebidas", "bebidas-alcoolicas", "limpeza", "higiene-e-perfumaria",
        "padaria-e-confeitaria", "congelados", "pet-shop", "saudaveis", "bebes-e-criancas"
    ]
    url = "https://api.vendas.gpa.digital/pa/products/search"
    total = 0
    headers = {
        "User-Agent": USER_AGENT,
        "origin": "https://www.paodeacucar.com",
        "referer": "https://www.paodeacucar.com/"
    }
    for d in deps:
        try:
            payload = {"partner": "linx", "page": 1, "resultsPerPage": 1, "department": d, "storeId": 461, "filters": []}
            res = await session.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                total += res.json().get('totalProducts', 0)
        except: pass
    return "Pão de Açúcar", total if total > 0 else "Não revelado pela API"

async def check_dom_olivio(session):
    """Dom Olívio usa VTEX FastStore via GraphQL Hash"""
    params = {
        "operationName": "GetProductsQuery",
        "operationHash": "ae50c5a735b1464f0ba48be4f2b32f7289ce6284",
        "variables": json.dumps({"input":{"activeSalesChannel":"1","postalCode":"13211-745","page":0,"sort":"score_desc","term":"","selectedFacets":[]}}, separators=(',', ':'))
    }
    url = f"https://www.domolivio.com.br/api/graphql?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        res = await session.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            total = res.json().get('data', {}).get('getProducts', {}).get('data', {}).get('products', {}).get('pageInfo', {}).get('totalCount', 0)
            if total > 0: return "Dom Olívio", total
    except: pass
    return "Dom Olívio", "Não revelado pela API"

async def check_carrefour(session):
    """Extração cirúrgica pelo JSON do SSR Remix do Carrefour (Cluster de Jundiaí)"""
    url = "https://mercado.carrefour.com.br/colecao/28617.data?map=productClusterIds&count=1&page=0&sort=orders_desc&_routes=layout%2Fdefault%2Croutes%2Fcolecao.%24collectionId"
    headers = {
        "User-Agent": USER_AGENT,
        "cookie": "region-id-food=InYyLjc5MDlFOEZDNjU2N0M3OTU5NjA4MDFCQTU5RDFFMEQ3Ig%3D%3D; cep=IkhpcGVyIEp1bmRpYcOtIg%3D%3D"
    }
    try:
        res = await session.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            match = re.search(r'"recordsFiltered"\s*:\s*(\d+)|"totalCount"\s*:\s*(\d+)', res.text)
            if match:
                total = match.group(1) or match.group(2)
                if total: return "Carrefour", int(total)
    except: pass
    return "Carrefour", "Não revelado pela API"

async def check_boa(session):
    """Boa Supermercados usa Sitemercado, que retorna o total no cabeçalho X-Total-Count em cada depto."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        res = await session.get("https://sitemercado.com.br/api/b2c/v1/departments/store/2679", headers=headers, timeout=15)
        deps = res.json().get('departments', [])
        total = 0
        for d in deps:
            slug = d.get('slug')
            if slug:
                try:
                    r = await session.get(f"https://sitemercado.com.br/api/b2c/v1/products/store/2679?department={slug}&limit=1&page=1", headers=headers, timeout=10)
                    if r.status_code == 200:
                        count = int(r.headers.get("x-total-count", 0))
                        total += count
                except: pass
        return "Boa Supermercados", total if total > 0 else "Não revelado pela API"
    except:
        return "Boa Supermercados", "Não revelado pela API"

async def main():
    print("\n" + "="*60)
    print("🔎 CONSULTANDO O TOTAL BRUTO DE PRODUTOS DIRETAMENTE NOS SITES")
    print("="*60)
    print("Aguarde, conectando de forma invisível às APIs dos mercados...\n")

    async with AsyncSession(impersonate="chrome124") as session:
        tarefas = [
            check_atacadao(session),
            check_paodeacucar(session),
            check_vtex_legacy(session, "https://www.covabra.com.br", "Covabra"),
            check_vtex_legacy(session, "https://www.obahortifruti.com.br", "Oba Hortifruti"),
            check_dom_olivio(session),
            check_carrefour(session),
            check_boa(session)
        ]
        
        resultados = await asyncio.gather(*tarefas)
        
        for mercado, total in resultados:
            total_formatado = f"{total:,}".replace(',', '.') if isinstance(total, int) else total
            print(f"🏪 {mercado.ljust(20)} {total_formatado} produtos cadastrados")

    print("\n" + "="*60)
    print("💡 DICA: Compare esses números com o seu 'check_db.py'.")
    print("Lembre-se: o seu script filtra itens sem foto, sem EAN, lixo de balança")
    print("e pneus de carro. Portanto, ter 70% ou 80% do número acima significa sucesso absoluto!")
    print("="*60 + "\n")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())