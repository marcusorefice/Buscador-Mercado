import asyncio
import urllib.parse
from curl_cffi.requests import AsyncSession

CEP_JUNDIAI = '13211-772'
SELLER_ID = 'atacadaobr633'
REGION_ID = 'U1cjYXRhY2FkYW9icjYzMw=='
CLUSTER_OFERTAS = '312'

async def test_graphql():
    cookie_str = f'{{"salesChannel":"1","postalCode":"{CEP_JUNDIAI}","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'
    
    headers_with_ua = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.atacadao.com.br/catalogo",
        "Origin": "https://www.atacadao.com.br",
        "Content-Type": "application/json"
    }
    
    headers_without_ua = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.atacadao.com.br/catalogo",
        "Origin": "https://www.atacadao.com.br",
        "Content-Type": "application/json"
    }

    variables = {
        "first": 5, 
        "after": "0", 
        "sort": "score_desc", 
        "term": "",
        "selectedFacets": [
            {"key": "productClusterIds", "value": CLUSTER_OFERTAS},
            {"key": "region-id", "value": REGION_ID},
            {"key": "channel", "value": f'{{"salesChannel":"1","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'},
            {"key": "locale", "value": "pt-BR"}
        ]
    }
    
    query_graphql = """
    query ProductsQuery($term: String, $selectedFacets: [SelectedFacetInput], $first: Int, $after: String, $sort: String) {
      search(term: $term, selectedFacets: $selectedFacets, first: $first, after: $after, sort: $sort) {
        products {
          pageInfo { totalCount }
        }
      }
    }
    """
    
    payload = {
        "operationName": "ProductsQuery",
        "variables": variables,
        "query": query_graphql
    }

    print("Testing WITH User-Agent override...")
    async with AsyncSession(impersonate='chrome120', headers=headers_with_ua) as session:
        session.cookies.set("regionalization", urllib.parse.quote(cookie_str), domain="www.atacadao.com.br")
        resp = await session.post('https://www.atacadao.com.br/api/graphql', json=payload)
        print("  Status:", resp.status_code)
        
    print("Testing WITHOUT User-Agent override...")
    async with AsyncSession(impersonate='chrome120', headers=headers_without_ua) as session:
        session.cookies.set("regionalization", urllib.parse.quote(cookie_str), domain="www.atacadao.com.br")
        resp = await session.post('https://www.atacadao.com.br/api/graphql', json=payload)
        print("  Status:", resp.status_code)

asyncio.run(test_graphql())
