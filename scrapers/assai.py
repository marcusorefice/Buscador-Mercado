import os
import time
import requests
import urllib3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import hashlib
from utils import setup_logging, webdriver_manager_lock
from motor_ia import MotorIA
import asyncio
from dotenv import load_dotenv

logger = setup_logging()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# CONFIGURAÇÕES DO MÓDULO
# ==========================================
NOME_MERCADO = "Assaí Atacadista"
URL_ASSAI = "https://www.assai.com.br/ofertas/sao-paulo/assai-jundiai"
load_dotenv()

def garantir_pasta(pasta_imagens):
    if not os.path.exists(pasta_imagens):
        os.makedirs(pasta_imagens)

def baixar_imagem(url, nome_arquivo):
    try:
        resposta = requests.get(url, timeout=15, verify=False)
        if resposta.status_code == 200:
            with open(nome_arquivo, 'wb') as f:
                f.write(resposta.content)
            return True
    except:
        pass
    return False

def baixar_encartes(pasta_destino):
    logger.info(f"Iniciando Motor de Captura IA - {NOME_MERCADO}...")
    garantir_pasta(pasta_destino)
    
    options = Options()
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    with webdriver_manager_lock:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    links_imagens = []
    
    try:
        driver.get(URL_ASSAI)
        time.sleep(5)
        
        # Ignora popup de cookies
        try: driver.execute_script("document.getElementById('onetrust-accept-btn-handler')?.click();")
        except: pass

        logger.info("   📖 Localizando folhetos no Assaí...")
        img_elements = driver.find_elements(By.CSS_SELECTOR, ".folheto-img, .ofertas img, img.img-responsive")
        for img in img_elements:
            src = img.get_attribute("src")
            if src and src not in links_imagens and ('oferta' in src.lower() or 'encarte' in src.lower() or 'folheto' in src.lower() or 'jundiai' in src.lower()):
                links_imagens.append(src)
                
    except Exception as e:
        logger.warning(f"   ⚠️ Imagens não detectadas: {e}")
    finally:
        driver.quit()

    imagens_baixadas = []
    if links_imagens:
        logger.info(f"   📥 Baixando {len(links_imagens)} imagens de encarte...")
        for link in sorted(links_imagens):
            url_hash = hashlib.md5(link.encode('utf-8')).hexdigest()
            caminho_local = os.path.join(pasta_destino, f"assai_pag_{url_hash}.jpg")
            if baixar_imagem(link, caminho_local):
                imagens_baixadas.append(caminho_local)
    
    return imagens_baixadas, NOME_MERCADO

async def extrair_dados():
    imagens, nome_mercado = await asyncio.to_thread(baixar_encartes, "temp_imagens")
    
    if not imagens:
        logger.warning(f"Nenhuma imagem encontrada para {nome_mercado}.")
        return []
    
    logger.info(f"Enviando {len(imagens)} encartes de '{nome_mercado}' para o motor de IA...")
    
    chaves_api_str = os.getenv("GEMINI_API_KEYS")
    if not chaves_api_str:
        logger.error("Chaves da API Gemini ausentes.")
        return []
    
    lista_chaves = [k.strip() for k in chaves_api_str.split(',') if k.strip()]
    motor_ia = MotorIA(lista_chaves=lista_chaves)
    
    return await motor_ia.processar_imagens_em_lote_async(imagens, nome_mercado)