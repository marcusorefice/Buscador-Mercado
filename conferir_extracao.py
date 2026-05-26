import asyncio
from curl_cffi import requests
from utils import setup_logging
import scrapers.atacadao as atacadao
from scrapers.atacadao import URL_BASE, CLUSTER_OFERTAS, REGION_ID, SELLER_ID

logger = setup_logging()

async def buscar_total_site():
    query = """
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
        "variables": {
            "first": 1,
            "after": "0",
            "sort": "score_desc",
            "term": "",
            "selectedFacets": [
                {"key": "productClusterIds", "value": CLUSTER_OFERTAS},
                {"key": "region-id", "value": REGION_ID},
                {"key": "channel", "value": f'{{"salesChannel":"1","seller":"{SELLER_ID}","regionId":"{REGION_ID}"}}'},
                {"key": "locale", "value": "pt-BR"}
            ]
        },
        "query": query
    }
    
    async with requests.AsyncSession(impersonate="chrome") as session:
        try:
            response = await session.post(URL_BASE, json=payload, timeout=20)
            data = response.json()
            total = data.get('data', {}).get('search', {}).get('products', {}).get('pageInfo', {}).get('totalCount', 0)
            return total
        except Exception as e:
            logger.error(f"Erro ao buscar total no site: {e}")
            return 0

async def verificar_atacadao():
    print("=" * 50)
    print("🔍 VERIFICAÇÃO DE EXTRAÇÃO - ATACADÃO")
    print("=" * 50)
    
    print("1. Buscando total de itens informados pela API do site...")
    total_site = await buscar_total_site()
    print(f"Total informado no site (GraphQL totalCount): {total_site}")
    
    print("\n2. Executando o scraper oficial do Atacadão...")
    produtos_finais = await atacadao.extrair_dados()
    
    print("\n" + "=" * 50)
    print("📊 RESULTADO DA VERIFICAÇÃO")
    print("=" * 50)
    print(f"Total de produtos encontrados no site: {total_site}")
    print(f"Total de produtos retornados e salvos pelo Scraper: {len(produtos_finais)}")
    print(f"Diferença: {total_site - len(produtos_finais)} produtos")
    
    print("\n📝 POR QUE HÁ DIFERENÇA?")
    print("1. Deduplicação: Produtos idênticos (mesmo nome limpo e preço) são combinados em um só para evitar poluição visual.")
    print("2. Categorias Ignoradas: O scraper descarta categorias que não são relevantes para o App (ex: Automotivo, Jardinagem, etc.).")
    print("3. Produtos Inválidos/Incompletos: Itens sem imagem válida, com erro no preço (ex: preço = 0), ou sem descrição são ignorados pelo processo de validação.")

if __name__ == "__main__":
    asyncio.run(verificar_atacadao())
