import os
import time
import re
import asyncio
import warnings
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
import hashlib
from curl_cffi import requests as curl_requests
from pdf2image import convert_from_path

from utils import (
    setup_logging, 
    read_json_file,
    webdriver_manager_lock
)
from motor_ia import MotorIA
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=DeprecationWarning)
logger = setup_logging()
load_dotenv()

# ==========================================
# CARREGAMENTO DAS CONFIGURAÇÕES (SPEC)
# ==========================================
SPEC_FILE = os.path.join(os.path.dirname(__file__), '..', 'specs', 'assai_spec.json')
CONFIG = read_json_file(SPEC_FILE)

NOME_MERCADO = CONFIG.get("market_name", "Assaí Atacadista")
URL_ALVO = CONFIG.get("base_url", "https://www.assai.com.br/ofertas/sao-paulo/assai-jundiai")
SELECTORS = CONFIG.get("selectors_mapping", {})

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_POPPLER = os.path.join(BASE_DIR, 'poppler-25.12.0', 'Library', 'bin')

def garantir_pasta(pasta_destino):
    """Garante que a pasta de destino exista."""
    if not os.path.exists(pasta_destino):
        os.makedirs(pasta_destino)

def converter_pdf_em_imagens(caminho_pdf):
    logger.info(f"   📄 [Conversor] PDF -> JPG: {os.path.basename(caminho_pdf)}")
    try:
        paginas = convert_from_path(caminho_pdf, dpi=150, poppler_path=CAMINHO_POPPLER)
        caminhos = []
        for i, pg in enumerate(paginas):
            caminho_img = caminho_pdf.replace(".pdf", f"_pg{i+1}.jpg")
            pg.save(caminho_img, "JPEG")
            caminhos.append(caminho_img)
        return caminhos
    except Exception as e:
        logger.error(f"Erro Poppler: {e}")
        return []

def _parse_selector(selector_str):
    if not selector_str: return None, None
    match = re.match(r"(.+?)\s*\(\s*Value\s*:\s*(\S+)\s*\)", selector_str)
    if match: return match.group(1).strip(), match.group(2).strip()
    return selector_str, None

def baixar_encartes(pasta_destino="temp_imagens"):
    logger.info(f"Iniciando Motor de Captura - {NOME_MERCADO}...")
    garantir_pasta(pasta_destino)
    
    options = Options()
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

    with webdriver_manager_lock:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    links_finais = []
    
    try:
        driver.get(URL_ALVO)
        logger.info("⏳ Aguardando carregamento inicial...")
        time.sleep(10) # Tempo para o carrossel renderizar

        # 1. Ajuste de Loja (Apenas se a URL mudar ou falhar)
        if "jundiai" not in driver.current_url.lower():
            logger.warning("   ⚠️ URL desviada. Forçando localização Jundiaí...")
            try:
                sel_gatilho, _ = _parse_selector(SELECTORS.get("location_trigger"))
                clicar = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel_gatilho)))
                driver.execute_script("arguments[0].click();", clicar)
                time.sleep(3)
                # Adicione aqui os Selects se o URL direto falhar
            except: pass

        # 2. Rolar para garantir que o carrossel carregue (Lazy Loading)
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(2)

        # 3. DETECÇÃO ROBUSTA DE ENCARTES
        sel_media, _ = _parse_selector(SELECTORS.get("media_links", 'a[data-fancybox="ofertas"]'))
        
        # Espera até 15 segundos pelos LINKS. Se eles aparecerem, ignoramos avisos de erro.
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel_media)))
            logger.info("   ✅ Encartes detectados com sucesso!")
        except:
            # Se não achou links, aí sim verificamos se a mensagem de "sem encarte" é real
            sel_vazio, _ = _parse_selector(SELECTORS.get("empty_status_check"))
            avisos = driver.find_elements(By.CSS_SELECTOR, sel_vazio)
            if avisos and avisos[0].is_displayed() and "não temos encarte" in avisos[0].text.lower():
                logger.info(f"   ℹ️ STATUS CONFIRMADO: {avisos[0].text.strip()}")
                return [], NOME_MERCADO

        # 4. Processar as Abas (Jornal 1, Jornal 2, etc.)
        sel_tabs, _ = _parse_selector(SELECTORS.get("insert_tabs"))
        tabs = driver.find_elements(By.CSS_SELECTOR, sel_tabs)
        
        # Itera sobre todas as abas encontradas. Se não houver abas, o range(1) garante que o bloco rode uma vez para a página principal.
        for i in range(len(tabs) if tabs else 1):
            if tabs:
                logger.info(f"   📑 Processando Aba {i+1}/{len(tabs)}...")
                try:
                    driver.execute_script("arguments[0].click();", tabs[i])
                    time.sleep(3) # Aguarda a troca de conteúdo da aba
                except Exception as e:
                    logger.warning(f"      Não foi possível clicar na aba {i+1}. Pulando. Erro: {e}")
                    continue

            # Captura todas as páginas do carrossel visível (da aba atual)
            while True:
                links_atuais = driver.execute_script("""
                    let urls = [];
                    document.querySelectorAll(arguments[0]).forEach(a => {
                        if(a.href) urls.push(a.href);
                    });
                    return urls;
                """, sel_media)
                
                for l in links_atuais:
                    if l not in links_finais: links_finais.append(l)

                # Clica no "Próximo" do carrossel para ver se tem mais páginas
                try:
                    sel_next, _ = _parse_selector(SELECTORS.get("next_button"))
                    btn_next = driver.find_element(By.CSS_SELECTOR, sel_next)
                    if "slick-disabled" in btn_next.get_attribute("class"): break
                    driver.execute_script("arguments[0].click();", btn_next)
                    time.sleep(1)
                except: break

    finally:
        driver.quit()

    # 5. Download Final
    imagens_finais = []
    if links_finais:
        logger.info(f"   📥 Baixando {len(links_finais)} páginas encontradas...")
        for link in sorted(links_finais): # Sort for consistent processing order
            try:
                res = curl_requests.get(link, impersonate="chrome", timeout=20)
                if res.status_code == 200:
                    url_hash = hashlib.md5(link.encode('utf-8')).hexdigest()
                    ext = ".pdf" if ".pdf" in link.lower() else ".jpg"
                    nome = os.path.join(pasta_destino, f"assai_raw_{url_hash}{ext}")
                    with open(nome, 'wb') as f: f.write(res.content)
                    
                    if ext == ".pdf":
                        imagens_convertidas = converter_pdf_em_imagens(nome)
                        imagens_finais.extend(imagens_convertidas)
                        os.remove(nome)
                    else:
                        imagens_finais.append(nome)
            except Exception as e:
                logger.error(f"Erro no download de {link}: {e}")

    imagens_finais.sort()
    return imagens_finais, NOME_MERCADO

async def extrair_dados():
    """
    Orquestra o download dos encartes e o processamento pela IA.
    Esta função segue o padrão do `main.py`, retornando uma lista de produtos.
    O cache de processamento da IA é gerenciado pelo MotorIA.
    """
    # A função de scraping (com Selenium) é bloqueante, então a executamos em uma thread.
    imagens, nome_mercado = await asyncio.to_thread(baixar_encartes)
    
    if not imagens:
        logger.warning(f"Nenhuma imagem de encarte encontrada para {nome_mercado}. O scraper será encerrado.")
        return []
        
    logger.info(f"Encontradas {len(imagens)} imagens de '{nome_mercado}'. Enviando para o motor de IA (usará cache se aplicável).")
    
    chaves_api_str = os.getenv("GEMINI_API_KEYS")
    if not chaves_api_str:
        logger.error("Chaves da API Gemini não encontradas no arquivo .env. A extração de dados das imagens será pulada.")
        return []
    
    lista_chaves = [k.strip() for k in chaves_api_str.split(',') if k.strip()]
    motor_ia = MotorIA(lista_chaves=lista_chaves)
    produtos_extraidos = await motor_ia.processar_imagens_em_lote_async(imagens, nome_mercado)
    
    if not produtos_extraidos:
        logger.warning(f"Processamento de IA não retornou produtos para {nome_mercado}.")
    
    return produtos_extraidos