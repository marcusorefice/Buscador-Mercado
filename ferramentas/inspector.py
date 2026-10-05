import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import asyncio
import json
import re
import os
import sys
from collections import Counter
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError
from bs4 import BeautifulSoup, Tag

# --- Heurísticas e Configurações ---
PRICE_REGEX = re.compile(r'R\$\s*\d+([,.]\d{2})?')
COMMON_PRODUCT_TAGS = ['h1', 'h2', 'h3', 'h4', 'strong', 'a', 'p', 'div']
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']

def reconstruir_json_remix(dados_flat, index=0):
    """Traduz o formato de índices do Remix (usado pelo Carrefour) para um JSON legível."""
    if index is None or not (0 <= index < len(dados_flat)):
        return None
    
    node = dados_flat[index]
    
    if isinstance(node, list):
        return [reconstruir_json_remix(dados_flat, i) for i in node]
    
    if isinstance(node, dict):
        res = {}
        for k, v in node.items():
            if k.startswith('_'):
                try:
                    key_idx = int(k[1:])
                    chave_real = reconstruir_json_remix(dados_flat, key_idx)
                    res[chave_real] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
                except: continue
            else:
                res[k] = reconstruir_json_remix(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
        return res
    return node

def get_simple_selector(tag: Tag) -> str:
    """Gera um seletor CSS simples e legível para um elemento, priorizando ID e classes."""
    if tag.get('id'):
        return f"#{tag.get('id')}"
    
    classes = tag.get('class', [])
    if classes:
        # Usa apenas as classes mais prováveis de serem únicas, evitando classes de estado (ex: 'active')
        stable_classes = [c for c in classes if not any(x in c for x in ['active', 'hover', 'focus', 'disabled'])]
        if stable_classes:
            return f"{tag.name}.{'.'.join(stable_classes)}"
        
    return tag.name # Fallback

async def test_image_patterns(soup, url):
    """Testa padrões de sites baseados em encartes de imagem."""
    print("\n[+] Testando Padrões de Encarte de Imagem (IA)...")

    # Padrão 1: FlipSnack (Ex: Tauste)
    if 'flipsnack.com' in url:
        print("   ✅ SUCESSO! Detectado portal FlipSnack. A extração será por screenshots (Selenium).")
        return "FLIPSNACK_IA", "tauste.py"

    # Padrão 2: Galeria de Imagens/PDFs (Ex: Assaí, Roldão, Fort)
    image_links = soup.find_all('a', href=re.compile(r'\.(jpg|jpeg|png|pdf)$', re.IGNORECASE))
    if len(image_links) > 4:  # Heurística: mais de 4 links sugere um encarte
        print(f"   ✅ SUCESSO! Detectada galeria com {len(image_links)} imagens/PDFs. A extração será por download e processamento de IA.")
        
        common_attrs = Counter()
        for a in image_links:
            for attr in a.attrs:
                if attr in ['data-fancybox', 'rel', 'data-gallery']:
                    common_attrs[f"a[{attr}='{a[attr]}']"] += 1
        
        if common_attrs:
            best_selector, _ = common_attrs.most_common(1)[0]
            print(f"     - Seletor de agrupamento sugerido: '{best_selector}'")
        
        return "IMAGE_GALLERY_IA", "assai.py / roldao.py / fort.py"

    # Padrão 3: Carrossel de Imagens dentro de um container (Ex: Tenda)
    next_buttons = soup.select('span[class*="next"], button[class*="next"], a[class*="next"]')
    if next_buttons and any(btn.find_parent() and btn.find_parent().find('img') for btn in next_buttons):
        print("   ✅ SUCESSO! Detectado possível carrossel de imagens com botões de navegação. A extração será por Selenium e processamento de IA.")
        return "IMAGE_CAROUSEL_IA", "tenda.py"

    print("   - Nenhum padrão de encarte de imagem óbvio foi detectado.")
    return None, None

async def test_known_patterns(api_candidates):
    """Testa padrões de scraping conhecidos contra os endpoints de API encontrados."""
    print("\n[+] Testando Padrões de Scraping Conhecidos...")
    if not api_candidates:
        print("   - Nenhum candidato de API para testar.")
        return None, None

    matched_pattern = None
    matched_scraper_example = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        for candidate in api_candidates:
            if matched_pattern: break
            url = candidate['url']
            
            # Padrão 1: VTEX API (Covabra, Oba)
            if '/api/catalog_system/pub/products/search' in url:
                print(f"   - Testando padrão VTEX API em: {url[:80]}...")
                try:
                    api_request = await context.request.get(url)
                    data = await api_request.json()
                    if isinstance(data, list) and data and 'productName' in data[0] and 'items' in data[0]:
                        print("     ✅ SUCESSO! Padrão VTEX API compatível.")
                        matched_pattern, matched_scraper_example = "VTEX_API", "covabra.py / oba.py"
                except Exception: pass

            # Padrão 2: VTEX Remix Stream (Carrefour)
            elif '.data?' in url:
                print(f"   - Testando padrão VTEX Remix Stream em: {url[:80]}...")
                try:
                    api_request = await context.request.get(url)
                    data_flat = await api_request.json()
                    data_reconstructed = reconstruir_json_remix(data_flat, 0)
                    if 'products' in json.dumps(data_reconstructed):
                         print("     ✅ SUCESSO! Padrão VTEX Remix Stream compatível.")
                         matched_pattern, matched_scraper_example = "VTEX_REMIX", "carrefour.py"
                except Exception: pass

            # Padrão 3: GPA/Linx API (Pão de Açúcar)
            elif 'api.vendas.gpa.digital' in url:
                 print("     ⚠️  Detectado padrão GPA/Linx API. Requer uma requisição POST. Scraper será similar ao 'paodeacucar.py'.")
                 matched_pattern, matched_scraper_example = "GPA_LINX", "paodeacucar.py"

            # Padrão 4: GraphQL (Atacadão, Boa)
            elif '/api/graphql' in url:
                print("     ⚠️  Detectado padrão GraphQL. Requer uma query específica. Scraper será similar ao 'atacadao.py' ou 'boa.py'.")
                matched_pattern, matched_scraper_example = "GRAPHQL", "atacadao.py / boa.py"

            # Padrão 5: Salesforce Demandware (São Vicente)
            elif 'Search-UpdateGrid' in url:
                print(f"   - Testando padrão Salesforce Demandware em: {url[:80]}...")
                try:
                    api_request = await context.request.get(url)
                    data = await api_request.json()
                    if 'productsSearchResult' in data or 'productSearch' in data:
                        print("     ✅ SUCESSO! Padrão Salesforce Demandware compatível.")
                        matched_pattern, matched_scraper_example = "SALESFORCE_DW", "svicente.py"
                except Exception: pass

        await browser.close()

    if not matched_pattern:
        print("   - Nenhum padrão conhecido correspondeu aos endpoints da API encontrados.")
    
    return matched_pattern, matched_scraper_example

async def inspect_website(url: str):
    """
    Motor de inspeção que analisa uma URL em busca de APIs de dados e estrutura HTML
    para acelerar a criação de novos scrapers.
    """
    print(f"🚀 Iniciando inspeção para: {url}")
    
    api_candidates = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # --- Interceptador de Rede para encontrar APIs ---
        async def handle_response(response):
            if response.request.resource_type in ["fetch", "xhr"]:
                try:
                    data = await response.json()
                    json_str = json.dumps(data)
                    # Heurística: se o JSON tiver chaves comuns de e-commerce, é um bom candidato
                    if any(key in json_str.lower() for key in ['products', 'items', 'offers', 'price', 'productname']):
                        api_candidates.append({
                            "url": response.url,
                            "method": response.request.method,
                            "data_preview": json.dumps(data, indent=2, ensure_ascii=False)[:500]
                        })
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            print("   - Navegando e aguardando a página carregar (pode levar até 1 minuto)...")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(5)
            html_content = await page.content()
        except TimeoutError:
            print("   - Timeout! A página demorou muito para carregar. Analisando o que foi possível...")
            html_content = await page.content()
        except Exception as e:
            print(f"   - Erro crítico na navegação: {e}")
            await browser.close()
            return

        await browser.close()

    print("\n" + "="*50)
    print("📊 RELATÓRIO DE INSPEÇÃO")
    print("="*50)

    # --- Relatório de API ---
    if api_candidates:
        print("\n[+] API Endpoints Encontrados (Melhor Opção!):")
        for i, candidate in enumerate(api_candidates):
            print(f"\n--- Candidato API #{i+1} ---")
            print(f"  URL: {candidate['url']}")
            print(f"  Método: {candidate['method']}")
            print(f"  Preview dos Dados:\n{candidate['data_preview']}")
    else:
        print("\n[-] Nenhuma API de dados óbvia foi detectada. Verificando padrões de imagem e HTML.")

    # --- Análise de Padrões e HTML ---
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Teste de Padrões de API Conhecidos
    matched_pattern, matched_scraper_example = await test_known_patterns(api_candidates)

    # 2. Teste de Padrões de Imagem (IA) se nenhum padrão de API foi encontrado
    if not matched_pattern:
        img_pattern, img_scraper_example = await test_image_patterns(soup, url)
        if img_pattern:
            matched_pattern = img_pattern
            matched_scraper_example = img_scraper_example

    if matched_scraper_example:
        print(f"\n💡 Dica de Ouro: A estrutura da API é similar à do '{matched_scraper_example}'. Use-o como referência principal!")


    # 3. Análise da Estrutura HTML (Fallback)
    print("\n[+] Análise da Estrutura HTML (Fallback para extração direta):")
    class_counter = Counter(tuple(sorted(tag.get('class', []))) for tag in soup.find_all(True) if tag.get('class'))
    product_container_selector = None
    if class_counter:
        most_common_class_tuple, count = class_counter.most_common(1)[0]
        if most_common_class_tuple and count > 4:
            product_container_selector = "." + ".".join(most_common_class_tuple)
            print(f"\n  - Possível Seletor do Container de Produto: '{product_container_selector}' (encontrado {count} vezes)")
            
            first_container = soup.select_one(product_container_selector)
            if first_container:
                price_tags = first_container.find_all(string=PRICE_REGEX)
                if price_tags:
                    price_tag = price_tags[0].parent
                    print(f"  - Possível Seletor de Preço: '{get_simple_selector(price_tag)}' (Texto: '{price_tag.get_text(strip=True)}')")

                name_candidates = []
                for tag in first_container.find_all(COMMON_PRODUCT_TAGS):
                    text = tag.get_text(strip=True)
                    if 5 < len(text) < 100 and not PRICE_REGEX.search(text) and not any(c in text for c in ['<', '>']):
                        name_candidates.append((len(text), tag))
                
                if name_candidates:
                    name_candidates.sort(key=lambda x: x[0], reverse=True)
                    best_name_tag = name_candidates[0][1]
                    print(f"  - Possível Seletor de Nome: '{get_simple_selector(best_name_tag)}' (Texto: '{best_name_tag.get_text(strip=True)}')")

                for img in first_container.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src and any(src.endswith(ext) for ext in IMAGE_EXTENSIONS):
                        print(f"  - Possível Seletor de Imagem: '{get_simple_selector(img)}' (Atributo: 'src' ou 'data-src')")
                        break
    else:
        print("\n  - Não foi possível identificar um container de produto repetitivo. A análise HTML pode ser imprecisa.")

    print("\n" + "="*50)
    print("PASSO 2: GERAÇÃO DE ARQUIVOS TEMPLATE")
    print("="*50)

    market_name = input("Digite o nome do novo mercado (ex: 'Meu Mercado'): ").strip()
    if market_name:
        safe_name = market_name.lower().replace(' ', '_').replace('-', '_')
        spec_filename = f"{safe_name}_spec.json"
        scraper_filename = f"{safe_name}.py"
        
        data_origin_str = "API" if api_candidates else "HTML Scraping"
        if matched_pattern:
            if "IA" in matched_pattern:
                data_origin_str = f"Image Scraping ({matched_pattern})"
            else:
                data_origin_str = f"API ({matched_pattern})"

        spec_data = {
            "market_name": market_name,
            "base_url": url,
            "data_origin": data_origin_str,
            "scraping_method": f"Similar to {matched_scraper_example}" if matched_scraper_example else "TODO: Definir método",
            "selectors_mapping": { # Mantido para o caso de fallback para HTML
                "product_container": product_container_selector or "TODO: .classe-do-produto",
                "product_name": "TODO: seletor-do-nome",
                "price": "TODO: seletor-do-preço",
                "image_url": "TODO: seletor-da-imagem"
            },
            "pagination": { "method": "TODO: 'scroll', 'click_next', ou 'url_param'" }
        }
        
        spec_path = os.path.join('specs', spec_filename)
        with open(spec_path, 'w', encoding='utf-8') as f: json.dump(spec_data, f, indent=2, ensure_ascii=False)
        print(f"✅ Arquivo de especificação gerado: '{spec_path}'")

        scraper_template_base = f'''
import os
import asyncio
from utils import setup_logging, read_json_file
# Adicione aqui os imports necessários (ex: playwright, curl_cffi)

logger = setup_logging()

SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', '{spec_filename}')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name")
URL_ALVO = CONFIG.get("base_url")

async def extrair_dados():
    """Motor de extração para {market_name}."""
    logger.info(f"🚀 Iniciando extração para {{NOME_MERCADO}}...")
    lista_final = []
    # TODO: Implementar a lógica de scraping com base no relatório do inspetor.
    logger.info(f"✅ Finalizado! {{len(lista_final)}} produtos únicos do {{NOME_MERCADO}} processados.")
    return lista_final
'''
        
        scraper_template = scraper_template_base
        if matched_pattern:
            hint = f"""
# Dica: Este scraper parece ser do tipo '{matched_pattern}'.
# Use o arquivo '{matched_scraper_example}' como referência para a lógica de extração.
"""
            scraper_template = hint + scraper_template_base

        scraper_path = os.path.join('scrapers', scraper_filename)
        with open(scraper_path, 'w', encoding='utf-8') as f: f.write(scraper_template.strip())
        print(f"✅ Arquivo de scraper gerado: '{scraper_path}'")
        print("\n💡 Dica: Edite os arquivos gerados com os seletores corretos e implemente a lógica de paginação.")

    else:
        print("Nome do mercado não fornecido. Geração de arquivos pulada.")

if __name__ == "__main__":
    target_url = input("Por favor, insira a URL da página de ofertas do mercado: ").strip()
    if target_url:
        asyncio.run(inspect_website(target_url))
    else:
        print("Nenhuma URL fornecida. Encerrando.")