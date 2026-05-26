import asyncio
import re
import urllib.parse
from curl_cffi.requests import AsyncSession
import logging

logger = logging.getLogger(__name__)

async def buscar_ean_open_food_facts(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca o EAN de um produto usando a API do Open Food Facts.
    Retorna um dicionário com o EAN e os dados do produto para comparação, ou None se não encontrar.
    """
    termo_busca = f"{nome_produto} {marca}".strip()
    url = f"https://br.openfoodfacts.org/cgi/search.pl?search_terms={urllib.parse.quote(termo_busca)}&search_simple=1&action=process&json=1"
    
    try:
        response = await session.get(url, timeout=10)
        if response.status_code == 200:
            dados = response.json()
            if dados.get("products") and len(dados["products"]) > 0:
                # Pega o primeiro resultado relevante
                produto_off = dados["products"][0]
                ean = produto_off.get("code")
                if ean and len(str(ean)) >= 12:
                    return {
                        "ean": str(ean),
                        "nome_encontrado": produto_off.get("product_name", ""),
                        "marca_encontrada": produto_off.get("brands", ""),
                        "fonte": "Open Food Facts"
                    }
    except Exception as e:
        logger.debug(f"Erro ao buscar '{termo_busca}' no Open Food Facts: {e}")
    
    return None

async def buscar_ean_google(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Faz uma busca no Google e tenta extrair um EAN brasileiro (789 ou 790 + 10 dígitos)
    dos resultados da página.
    """
    termo_busca = f'"{nome_produto}" {marca} "EAN"'.strip()
    url = f"https://www.google.com/search?q={urllib.parse.quote(termo_busca)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    try:
        response = await session.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            html = response.text
            # Procura por padrões de EAN-13 comuns no Brasil (789 ou 790) no HTML dos resultados
            match = re.search(r'\b(789\d{10}|790\d{10})\b', html)
            if match:
                ean = match.group(1)
                return {
                    "ean": ean,
                    "nome_encontrado": "N/A", # O Google não devolve o nome estruturado facilmente
                    "marca_encontrada": "N/A",
                    "fonte": "Google Search"
                }
    except Exception as e:
        logger.debug(f"Erro ao buscar '{termo_busca}' no Google: {e}")
        
    return None

async def buscar_dados_por_ean_off(session: AsyncSession, ean: str):
    """
    Busca os dados do produto no Open Food Facts pelo EAN para comparação.
    """
    url = f"https://br.openfoodfacts.org/api/v0/product/{ean}.json"
    try:
        response = await session.get(url, timeout=10)
        if response.status_code == 200:
            dados = response.json()
            if dados.get("status") == 1:
                produto_off = dados.get("product", {})
                return {
                    "ean": ean,
                    "nome_encontrado": produto_off.get("product_name", ""),
                    "marca_encontrada": produto_off.get("brands", ""),
                    "categoria_encontrada": produto_off.get("categories", ""),
                    "fonte": "Open Food Facts (EAN)"
                }
    except Exception as e:
        logger.debug(f"Erro ao buscar EAN '{ean}' no Open Food Facts: {e}")
    
    return None

async def tentar_recuperar_ean(nome_produto: str, marca: str = "") -> dict:
    """
    Tenta recuperar o EAN do produto e seus dados de comparação usando o Open Food Facts
    e faz fallback para o Google Search.
    Retorna o dicionário de dados ou None.
    """
    async with AsyncSession(impersonate="chrome120") as session:
        # 1. Tenta Open Food Facts (Melhor para dados estruturados e comparação)
        resultado_off = await buscar_ean_open_food_facts(session, nome_produto, marca)
        if resultado_off:
            return resultado_off
            
        # 2. Fallback: Google Search (Apenas extração bruta de código)
        resultado_google = await buscar_ean_google(session, nome_produto, marca)
        if resultado_google:
            return resultado_google
            
    return None

if __name__ == "__main__":
    # Teste rápido do script
    logging.basicConfig(level=logging.DEBUG)
    
    async def teste():
        print("Buscando 'Coca Cola Lata 350ml'...")
        resultado = await tentar_recuperar_ean("Coca Cola Lata 350ml", "Coca-Cola")
        print(f"Resultado: {resultado}\n")
        
        print("Buscando um produto obscuro (Azeite Gallo Vidro 500ml)...")
        resultado2 = await tentar_recuperar_ean("Azeite Extra Virgem", "Gallo")
        print(f"Resultado: {resultado2}\n")

    asyncio.run(teste())
