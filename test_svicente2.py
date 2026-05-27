import asyncio
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

async def test():
    async with AsyncSession(impersonate='chrome120') as session:
        res = await session.get('https://www.svicente.com.br/', headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        links = soup.find_all('a', href=True)
        unique_links = set([a['href'] for a in links])
        for link in list(unique_links)[:50]:
            print(link)

asyncio.run(test())
