import asyncio
import re
import urllib.parse
from curl_cffi.requests import AsyncSession
import logging
import os
import httpx

logger = logging.getLogger(__name__)

cosmos_esgotado = False
google_esgotado = False

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://cosmos.bluesoft.com.br/",
    }
    try:
        response = await session.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            matches = re.findall(r'href="/produtos/(\d{8,14})-[^"]+"', response.text)
            for ean in matches:
                if is_valid_ean(ean):
                    return {"ean": ean, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "Cosmos Web (Scraper)"}
    except Exception: pass
    return None

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
                        "fonte": "Open Food Facts",
                        "Link_Imagem": produto_off.get("image_url", "")
                    }
    except Exception as e:
        logger.debug(f"Erro ao buscar '{termo_busca}' no Open Food Facts: {e}")
    
    return None

async def buscar_ean_google_api(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca usando a API oficial do Google Custom Search (100 requisições/dia grátis).
    """
    global google_esgotado
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_CX")
    
    if not api_key or not cx or google_esgotado:
        return None
        
    # Pesquisa flexível: sem aspas! Deixa o Google cruzar as palavras do nome da melhor forma.
    termo_busca = f'{nome_produto} {marca} EAN'.strip()
    url = f"https://www.googleapis.com/customsearch/v1?q={urllib.parse.quote(termo_busca)}&key={api_key}&cx={cx}"
    
    try:
        response = await session.get(url, timeout=10)
        if response.status_code == 200:
            dados = response.json()
            items = dados.get("items", [])
            
            # Concatena os snippets (resumos) e títulos dos resultados para caçar o EAN
            texto_resultados = " ".join([item.get("snippet", "") + " " + item.get("title", "") for item in items])
            
            # Procura por qualquer sequência de 8, 12, 13 ou 14 dígitos numéricos e valida matematicamente
            matches = re.findall(r'\b(\d{8}|\d{12,14})\b', texto_resultados)
            for ean_candidato in matches:
                if is_valid_ean(ean_candidato):
                    return {
                        "ean": ean_candidato,
                        "nome_encontrado": "N/A",
                        "marca_encontrada": "N/A",
                        "fonte": "Google Custom Search API"
                    }
        elif response.status_code in [403, 429]:
            logger.warning("⚠️ Limite diário de 100 requisições do Google Search API esgotado (403/429).")
            google_esgotado = True
    except Exception as e:
        logger.debug(f"Erro na API do Google Search: {e}")
        
    return None

async def buscar_ean_duckduckgo(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca o EAN usando a versão HTML (Lite) do DuckDuckGo. Grátis e sem limites de API.
    """
    termo_busca = f'{nome_produto} {marca} EAN'.strip()
    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        response = await session.post(url, data={"q": termo_busca}, headers=headers, timeout=10)
        if response.status_code == 200:
            matches = re.findall(r'\b(\d{8}|\d{12,14})\b', response.text)
            for ean_candidato in matches:
                if is_valid_ean(ean_candidato):
                    return {
                        "ean": ean_candidato, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "DuckDuckGo HTML"
                    }
    except Exception as e:
        pass
    return None

async def buscar_ean_yahoo(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca o EAN usando o Yahoo Search, que é muito mais permissivo com raspagem.
    """
    termo_busca = f'{nome_produto} {marca} EAN'.strip()
    url = f"https://br.search.yahoo.com/search?p={urllib.parse.quote(termo_busca)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        response = await session.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            texto_limpo = re.sub(r'<[^>]+>', ' ', response.text)
            matches = re.findall(r'\b(\d{8}|\d{12,14})\b', texto_limpo)
            for ean_candidato in matches:
                if is_valid_ean(ean_candidato):
                    return {
                        "ean": ean_candidato, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "Yahoo Search"
                    }
    except Exception:
        pass
    return None

async def buscar_ean_bing(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca o EAN usando o Bing Search.
    """
    termo_busca = f'{nome_produto} {marca} EAN'.strip()
    url = f"https://www.bing.com/search?q={urllib.parse.quote(termo_busca)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    try:
        response = await session.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            texto_limpo = re.sub(r'<[^>]+>', ' ', response.text)
            matches = re.findall(r'\b(\d{8}|\d{12,14})\b', texto_limpo)
            for ean_candidato in matches:
                if is_valid_ean(ean_candidato):
                    return {
                        "ean": ean_candidato, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "Bing Search"
                    }
    except Exception:
        pass
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
                        return {
                            "ean": ean_cosmos,
                            "nome_encontrado": "N/A",
                            "marca_encontrada": "N/A",
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
    Tenta recuperar o EAN do produto e seus dados de comparação usando o Open Food Facts
    e faz fallback para o Google Search.
    Retorna o dicionário de dados ou None.
    """
    termo_simples = simplificar_termo(nome_produto, marca)
    
    try:
        async with AsyncSession(impersonate="chrome120") as session:
            # 1. Busca Interna Estruturada: Open Food Facts
            resultado_off = await buscar_ean_open_food_facts(session, nome_produto, marca)
            if resultado_off:
                return resultado_off
                
            # 2. Busca Web Primária: Yahoo Search
            resultado_yahoo = await buscar_ean_yahoo(session, termo_simples, "")
            if resultado_yahoo:
                return resultado_yahoo
                
            # 3. Busca Web Secundária: DuckDuckGo
            resultado_ddg = await buscar_ean_duckduckgo(session, termo_simples, "")
            if resultado_ddg:
                return resultado_ddg
                
            # 4. Busca Web Extra: Bing Search
            resultado_bing = await buscar_ean_bing(session, termo_simples, "")
            if resultado_bing:
                return resultado_bing
                
            # 5. Fallback de Precisão: Cosmos WEB
            resultado_cosmos_web = await buscar_ean_cosmos_web(session, termo_simples)
            if resultado_cosmos_web:
                return resultado_cosmos_web
                
            # 6. Último Recurso Web: Google Custom Search API
            resultado_google = await buscar_ean_google_api(session, termo_simples, "")
            if resultado_google:
                return resultado_google
    except Exception as e:
        logger.debug(f"Erro na criação da sessão de busca: {e}")
            
    # 7. Fallback Final: Cosmos API (Com termo simplificado)
    resultado_cosmos = await buscar_ean_cosmos_api(termo_simples, "")
    if resultado_cosmos:
        return resultado_cosmos
        
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
