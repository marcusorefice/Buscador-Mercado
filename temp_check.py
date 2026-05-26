import asyncio
import re
import json
from curl_cffi.requests import AsyncSession

async def main():
    headers = {"User-Agent": "Mozilla/5.0"}
    async with AsyncSession(impersonate="chrome120") as s:
        res = await s.get("https://www.paodeacucar.com/produto/9112/cava-espanhola-freixenet-carta-nevada-demi-sec-750ml", headers=headers)
        if res.status_code == 200:
            html = res.text
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
            if match:
                data = json.loads(match.group(1))
                product = data.get('props', {}).get('pageProps', {}).get('product', {})
                print("shelfList:", product.get('shelfList'))
            else:
                print("No __NEXT_DATA__")
        else:
            print("Status:", res.status_code)

if __name__ == "__main__":
    asyncio.run(main())