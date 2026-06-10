import asyncio
import re
import urllib.parse
from curl_cffi.requests import AsyncSession
import logging
import os
import httpx
import random

logger = logging.getLogger(__name__)

cosmos_esgotado = False
google_esgotado = False
duckduckgo_semaphore = asyncio.Semaphore(1)
yahoo_semaphore = asyncio.Semaphore(1)
bing_semaphore = asyncio.Semaphore(1)
off_semaphore = asyncio.Semaphore(2)

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
            matches = re.findall(r'href="/produtos/(\d{8,14})-[^"]+"', response.text)
            for ean in matches:
                if is_valid_ean(ean):
                    return {"ean": ean, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "Cosmos Web (Scraper)"}
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
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(termo_busca)}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://duckduckgo.com/",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    for tentativa in range(2): # Tenta até 2 vezes
        try:
            response = await session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                matches = re.findall(r'\b(\d{8}|\d{12,14})\b', response.text)
                for ean_candidato in matches:
                    if is_valid_ean(ean_candidato):
                        return { "ean": ean_candidato, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "DuckDuckGo HTML" }
                return None # Se achou a página mas não o EAN, não adianta tentar de novo.
            
            logger.warning(f"⚠️ DuckDuckGo bloqueou a requisição (Status: {response.status_code}) para '{termo_busca}'")
            if tentativa == 0: # Se for a primeira tentativa, espera um tempo bem mais longo
                await asyncio.sleep(random.uniform(5.0, 10.0))
        except Exception as e:
            logger.debug(f"Erro no DuckDuckGo: {e}")
            if tentativa == 0:
                await asyncio.sleep(random.uniform(5.0, 10.0))
    return None

async def buscar_ean_yahoo(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca o EAN usando o Yahoo Search, que é muito mais permissivo com raspagem.
    """
    termo_busca = f'{nome_produto} {marca} EAN'.strip()
    url = f"https://br.search.yahoo.com/search?p={urllib.parse.quote(termo_busca)}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for tentativa in range(2):
        try:
            response = await session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                matches = re.findall(r'\b(\d{8}|\d{12,14})\b', response.text)
                for ean_candidato in matches:
                    if is_valid_ean(ean_candidato):
                        return {
                            "ean": ean_candidato, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "Yahoo Search"
                        }
                return None # Achou a página mas não o EAN, não tenta de novo
        
            logger.warning(f"⚠️ Yahoo bloqueou a requisição (Status: {response.status_code}) para '{termo_busca}'")
            if tentativa == 0:
                await asyncio.sleep(random.uniform(4.0, 7.0))

        except Exception as e:
            logger.debug(f"Erro no Yahoo: {e}")
            if tentativa == 0:
                await asyncio.sleep(random.uniform(4.0, 7.0))
    return None

async def buscar_ean_bing(session: AsyncSession, nome_produto: str, marca: str = ""):
    """
    Busca o EAN usando o Bing Search.
    """
    termo_busca = f'{nome_produto} {marca} EAN'.strip()
    url = f"https://www.bing.com/search?q={urllib.parse.quote(termo_busca)}"
    headers = {
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for tentativa in range(2):
        try:
            response = await session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                matches = re.findall(r'\b(\d{8}|\d{12,14})\b', response.text)
                for ean_candidato in matches:
                    if is_valid_ean(ean_candidato):
                        return {
                            "ean": ean_candidato, "nome_encontrado": "N/A", "marca_encontrada": "N/A", "fonte": "Bing Search"
                        }
                return None # Achou a página mas não o EAN, não tenta de novo

            logger.warning(f"⚠️ Bing bloqueou a requisição (Status: {response.status_code}) para '{termo_busca}'")
            if tentativa == 0:
                await asyncio.sleep(random.uniform(6.0, 10.0))
        except Exception as e:
            logger.debug(f"Erro no Bing: {e}")
            if tentativa == 0:
                await asyncio.sleep(random.uniform(6.0, 10.0))
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
    Tenta recuperar o EAN do produto seguindo a ordem solicitada:
    Open Food Facts -> Yahoo -> Bing -> DuckDuckGo -> Cosmos -> Google.
    Faz 2 tentativas completas (se necessário) antes de desistir.
    """
    termo_simples = simplificar_termo(nome_produto, marca)
    
    navegadores = ["chrome100", "chrome110", "chrome120", "edge99", "edge101", "safari15_3", "safari15_5", "safari17_0"]
    
    for rodada in range(2):
        browser_escolhido = random.choice(navegadores)
        
        try:
            async with AsyncSession(impersonate=browser_escolhido) as session:
                # --- BUSCA SEQUENCIAL DISTRIBUÍDA (Carga Balanceada) ---
                async def tent_off():
                    async with off_semaphore:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        return await buscar_ean_open_food_facts(session, termo_simples)
                async def tent_yahoo():
                    async with yahoo_semaphore:
                        await asyncio.sleep(random.uniform(1.5, 3.0))
                        return await buscar_ean_yahoo(session, termo_simples, "")
                async def tent_bing():
                    async with bing_semaphore:
                        await asyncio.sleep(random.uniform(2.0, 4.0))
                        return await buscar_ean_bing(session, termo_simples, "")
                async def tent_ddg():
                    async with duckduckgo_semaphore:
                        await asyncio.sleep(random.uniform(1.5, 3.0))
                        return await buscar_ean_duckduckgo(session, termo_simples, "")

                # Embaralha os motores. Cada item vai começar por um buscador diferente!
                motores = [tent_off, tent_yahoo, tent_bing, tent_ddg]
                random.shuffle(motores)

                # Executa sequencialmente a fila embaralhada do item
                for motor in motores:
                    resultado = await motor()
                    if resultado and resultado.get("ean"):
                        return resultado

                # --- BUSCA SEQUENCIAL DE FALLBACK (Cosmos e Google) ---
                resultado = await buscar_ean_cosmos_web(session, termo_simples)
                if resultado: return resultado
                
                resultado = await buscar_ean_cosmos_api(termo_simples, "")
                if resultado: return resultado
                
                # 6. Google API
                resultado = await buscar_ean_google_api(session, termo_simples, "")
                if resultado: return resultado

        except Exception as e:
            logger.debug(f"Erro na criação da sessão de busca (Rodada {rodada+1}): {e}")
            
        if rodada == 0:
            logger.warning(f"🔁 Nenhuma EAN encontrada na 1ª tentativa para '{termo_simples}'. Tentando novamente...")
            await asyncio.sleep(random.uniform(5.0, 8.0))

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
