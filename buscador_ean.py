import asyncio
import re
import urllib.parse
from curl_cffi.requests import AsyncSession
import logging
import os
import httpx
import random

logger = logging.getLogger(__name__)

# Só usamos fontes que devolvem o NOME do produto junto com o EAN, para o passo 4 conferir se é
# mesmo o produto procurado. Yahoo/Bing/DuckDuckGo/Google foram removidos: eles pegavam qualquer
# número de 8-14 dígitos da página de resultados (IDs, rastreadores...) e geraram EANs falsos
# (um único número chegou a ser atribuído a 3.152 produtos diferentes).
cosmos_esgotado = False
off_semaphore = asyncio.Semaphore(2)
cosmos_semaphore = asyncio.Semaphore(1)

def is_valid_ean(ean_str):
    if not ean_str or not ean_str.isdigit(): return False
    if len(ean_str) not in (8, 12, 13, 14): return False
    if len(set(ean_str)) == 1: return False
    padded = ean_str.zfill(14)
    total = sum(int(padded[i]) * (3 if i % 2 == 0 else 1) for i in range(13))
    return str((10 - (total % 10)) % 10) == padded[13]

def simplificar_termo(nome: str, marca: str) -> str:
    """Limpa o nome do produto para evitar pesquisas gigantes que os buscadores não acham."""
    # Remove pesos e medidas grudados (ex: 250G, 1L, 500ML)
    nome_limpo = re.sub(r'\b\d+[,.]?\d*(kg|g|ml|l|un|m|cm|mm|mg)\b', '', str(nome), flags=re.IGNORECASE)
    # Remove caracteres especiais
    nome_limpo = re.sub(r'[^\w\s]', ' ', nome_limpo)
    palavras = [p for p in nome_limpo.split() if len(p) > 2]
    # Pega apenas as 4 primeiras palavras cruciais do produto
    termo = " ".join(palavras[:4])
    # Garante que a marca esteja presente na busca
    marca_limpa = str(marca).upper().strip()
    if marca_limpa and marca_limpa not in termo.upper() and marca_limpa not in ["OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "NONE"]:
        termo += f" {marca_limpa}"
    return termo.strip()

async def buscar_ean_cosmos_web(session: AsyncSession, termo_busca: str):
    """Web Scraping direto no portal Cosmos (Bypass da API de 25 req/dia, é ilimitado!)."""
    url = f"https://cosmos.bluesoft.com.br/pesquisar?q={urllib.parse.quote(termo_busca)}"
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://cosmos.bluesoft.com.br/",
    }
    try:
        response = await session.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            matches = re.findall(r'href="/produtos/(\d{8,14})-([^"/?]+)"', response.text)
            for ean, slug in matches:
                if is_valid_ean(ean):
                    # ex: /produtos/7891000100103-leite-integral-italac-1l -> "LEITE INTEGRAL ITALAC 1L"
                    nome = urllib.parse.unquote(slug).replace("-", " ").upper()
                    return {"ean": ean, "nome_encontrado": nome, "marca_encontrada": "", "fonte": "Cosmos Web (Scraper)"}
    except Exception: pass
    return None

async def buscar_ean_open_food_facts(session: AsyncSession, termo_busca: str):
    """
    Busca o EAN de um produto usando a API do Open Food Facts.
    Retorna um dicionário com o EAN e os dados do produto para comparação, ou None se não encontrar.
    """
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
                        "fonte": "Open Food Facts",
                        "Link_Imagem": produto_off.get("image_url", "")
                    }
    except Exception as e:
        logger.debug(f"Erro ao buscar '{termo_busca}' no Open Food Facts: {e}")
    
    return None


async def buscar_ean_cosmos_api(nome_produto: str, marca: str = ""):
    """
    Busca o EAN de um produto usando a Cosmos API (Bluesoft).
    """
    global cosmos_esgotado
    token_cosmos = os.getenv("COSMOS_API_TOKEN")
    
    if not token_cosmos or cosmos_esgotado:
        return None
        
    query_cosmos = f"{nome_produto} {marca}".strip()
    url_cosmos = f"https://api.cosmos.bluesoft.com.br/products?description={urllib.parse.quote(query_cosmos)}"
    
    try:
        async with httpx.AsyncClient() as client_http:
            res_cosmos = await client_http.get(
                url_cosmos, 
                headers={"X-Cosmos-Token": token_cosmos, "User-Agent": "ComparadorApp/1.0"},
                timeout=5.0
            )
            if res_cosmos.status_code == 200:
                data_cosmos = res_cosmos.json()
                lista = data_cosmos if isinstance(data_cosmos, list) else data_cosmos.get("data", [])
                if lista and isinstance(lista, list) and len(lista) > 0:
                    ean_cosmos = str(lista[0].get("gtin", ""))
                    if ean_cosmos.isdigit():
                        marca_cosmos = lista[0].get("brand") or {}
                        return {
                            "ean": ean_cosmos,
                            "nome_encontrado": lista[0].get("description", ""),
                            "marca_encontrada": marca_cosmos.get("name", "") if isinstance(marca_cosmos, dict) else str(marca_cosmos),
                            "fonte": "Cosmos API"
                        }
            elif res_cosmos.status_code == 429:
                logger.warning("⚠️ Limite diário de 25 requisições da API Cosmos esgotado.")
                cosmos_esgotado = True
    except Exception as e:
        logger.debug(f"Erro na API Cosmos: {e}")
        
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
    Procura o EAN do produto em fontes que devolvem o nome junto (Open Food Facts e Cosmos).
    O resultado ainda precisa ser conferido pelo passo 4 (o nome encontrado tem que bater com o item).
    """
    termo_simples = simplificar_termo(nome_produto, marca)
    navegadores = ["chrome100", "chrome110", "chrome120", "edge99", "edge101", "safari15_3", "safari15_5", "safari17_0"]

    try:
        async with AsyncSession(impersonate=random.choice(navegadores)) as session:
            async with off_semaphore:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                resultado = await buscar_ean_open_food_facts(session, termo_simples)
            if resultado:
                return resultado

            async with cosmos_semaphore:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                resultado = await buscar_ean_cosmos_web(session, termo_simples)
            if resultado:
                return resultado

            return await buscar_ean_cosmos_api(termo_simples, "")
    except Exception as e:
        logger.debug(f"Erro na busca de EAN para '{termo_simples}': {e}")
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
