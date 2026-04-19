import json
import asyncio
from curl_cffi import requests

SESSION_FILE = r"D:\Mercado\data\atacadao_session.json"

async def testar_passatempo_jundiai():
    with open(SESSION_FILE, 'r') as f:
        cookies = json.load(f)
    
    # O SEGREDO: Definir o segmento exato de Jundiaí (Seller 633)
    # Esse cookie é o que realmente define a loja na plataforma VTEX
    vtex_segment = "eyJjYW1wYWlnbnMiOm51bGwsImNoYW5uZWwiOiIxIiwicHJpY2VUYWJsZSI6bnVsbCwicmVnaW9uSWQiOm51bGwsInV0bV9jYW1wYWlnbiI6bnVsbCwidXRtX21lZGl1bSI6bnVsbCwidXRtX3NvdXJjZSI6bnVsbCwidXRtaV9jYW1wYWlnbiI6bnVsbCwidXRtaV9wYWdlIjpudWxsLCJ1dG1pX3BhcnQiOm51bGwsImN1cnJlbmN5Q29kZSI6IkJSTCIsImN1cnJlbmN5U3ltYm9sIjoiUiQiLCJjb3VudHJ5Q29kZSI6IkJSQSIsImN1bHR1cmVJbmZvIjoicHQtQlIiLCJhZG1pbkN1bHR1cmVJbmZvIjoicHQtQlIiLCJjaGFubmVsUHJpdmFjeSI6InB1YmxpYyJ9"

    cookies['vtex_segment'] = vtex_segment
    cookies['regionalization'] = "%7B%22salesChannel%22%3A%221%22%2C%22postalCode%22%3A%2213211-772%22%2C%22seller%22%3A%22atacadaobr633%22%7D"

    # Buscando o Passatempo com o parâmetro de Sales Channel (sc=1)
    url = "https://www.atacadao.com.br/api/catalog_system/pub/products/search?ft=passatempo chocolate 130g&sc=1"

    async with requests.AsyncSession(impersonate="chrome124") as session:
        for n, v in cookies.items():
            session.cookies.set(n, v, domain="www.atacadao.com.br")

        headers = {
            "Accept": "application/json",
            "vtex-segment": vtex_segment, # Forçando o cabeçalho de segmento
            "Referer": "https://www.atacadao.com.br/"
        }

        print("🔍 Tentando 'espetar' o Seller 633 de Jundiaí...")
        res = await session.get(url, headers=headers)
        produtos = res.json()

        for p in produtos:
            nome = p['productName'].upper()
            if "CHOCOLATE" in nome and "130G" in nome:
                item = p['items'][0]
                seller_data = item['sellers'][0]
                comm = seller_data['commertialOffer']
                
                print(f"\n🎯 PRODUTO: {p['productName']}")
                print(f"🏪 LOJA (Seller): {seller_data.get('sellerId')}")
                
                # Se o Seller ainda for 1, a VTEX está ignorando nossa regionalização
                if seller_data.get('sellerId') == "1":
                    print("⚠️ Alerta: Ainda no Seller 1. O preço de atacado pode não aparecer.")

                specs = comm.get('PriceSpecifications', [])
                print(f"💰 Preço Base: R$ {comm.get('Price'):.2f}")
                
                if specs:
                    print("--- Tabela de Preços ---")
                    for s in sorted(specs, key=lambda x: x.get('NumberOfInstallments', 1)):
                        qtd = s.get('NumberOfInstallments')
                        valor = s.get('Value')
                        print(f"🔹 {qtd} un. ou + -> R$ {valor:.2f}")
                return

if __name__ == "__main__":
    asyncio.run(testar_passatempo_jundiai())