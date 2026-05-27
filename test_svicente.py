import asyncio
from curl_cffi.requests import AsyncSession

async def test():
    async with AsyncSession(impersonate='chrome120') as session:
        cgid = '012'
        url = 'https://www.svicente.com.br/on/demandware.store/Sites-SaoVicente-Site/pt_BR/Search-UpdateGrid'
        
        # Without PMID
        params1 = {'cgid': cgid, 'start': 0, 'sz': 1}
        headers = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}
        res1 = await session.get(url, params=params1, headers=headers)
        if res1.status_code == 200:
            data = res1.json()
            prods = data.get('productsSearchResult', [])
            if prods:
                print('Price info without pmid:', prods[0].get('price'))

asyncio.run(test())
