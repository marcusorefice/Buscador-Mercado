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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils import setup_logging, filtrar_imagens_por_cache, atualizar_cache_downloads
from motor_ia import MotorIA
from dotenv import load_dotenv

logger = setup_logging()
# Desativar avisos de conexão insegura
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# CONFIGURAÇÕES DO MÓDULO
# ==========================================
NOME_MERCADO = "Tenda Atacado"
URL_TENDA = "https://www.tendaatacado.com.br/institucional/nossas-lojas/jundiai"
load_dotenv()

def garantir_pasta(pasta_imagens):
    """Garante que a pasta de destino exista, sem apagar o conteúdo."""
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

# ==========================================
# FUNÇÃO PRINCIPAL QUE O MAIN.PY PROCURA
# ==========================================
def baixar_encartes(pasta_destino):
    logger.info(f"Iniciando Motor de Captura - {NOME_MERCADO}...")
    garantir_pasta(pasta_destino)
    
    options = Options()
    options.add_argument('--headless=new') 
    options.add_argument('--window-size=1920,1080')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    links_imagens = []
    
    try:
        driver.get(URL_TENDA)
        time.sleep(5)
        
        try: driver.execute_script("document.getElementById('onetrust-accept-btn-handler')?.click();")
        except: pass

        logger.info("   📖 Localizando e abrindo o folheto digital...")
        try:
            capa = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "img.folder")))
            driver.execute_script("arguments[0].click();", capa)
            time.sleep(4)
        except:
            logger.warning("   ⚠️ Capa do folheto não detectada.")
            driver.quit()
            return [], NOME_MERCADO

        for i in range(30):
            try:
                img_element = driver.find_element(By.CSS_SELECTOR, "img#image")
                src_atual = img_element.get_attribute("src")
                
                if src_atual and src_atual not in links_imagens:
                    links_imagens.append(src_atual)
                
                clicou = driver.execute_script("""
                    let nextBtn = document.querySelector('span.next-icon') || document.querySelector('.slick-next');
                    if (nextBtn) { nextBtn.click(); return true; }
                    return false;
                """)
                
                if not clicou or (i > 0 and src_atual == links_imagens[0]):
                    break
                    
                time.sleep(2)
            except:
                break
                
    finally:
        driver.quit()

    imagens_baixadas = []
    if links_imagens:
        logger.info(f"   📥 Baixando {len(links_imagens)} páginas (com hash para cache)...")
        for link in sorted(links_imagens): # Sort for consistent processing order
            url_hash = hashlib.md5(link.encode('utf-8')).hexdigest()
            caminho_local = os.path.join(pasta_destino, f"tenda_pag_{url_hash}.jpg")
            if baixar_imagem(link, caminho_local):
                imagens_baixadas.append(caminho_local)
    
    return imagens_baixadas, NOME_MERCADO

# ==========================================
# FUNÇÃO DE EXTRAÇÃO (PADRÃO DO PROJETO)
# ==========================================
def extrair_dados():
    """
    Orquestra o download dos encartes e o processamento pela IA.
    Esta função segue o padrão do `main.py`, retornando uma lista de produtos.
    """
    imagens, nome_mercado = baixar_encartes(pasta_destino="temp_imagens")
    
    if not imagens:
        logger.warning(f"Nenhuma imagem de encarte encontrada para {nome_mercado}. O scraper será encerrado.")
        return []
        
    # --- Bloco de Cache ---
    imagens_para_processar, novas_entradas, cache_existente = filtrar_imagens_por_cache(imagens, nome_mercado, logger)
    if not imagens_para_processar:
        logger.info(f"Todas as imagens para '{nome_mercado}' já estavam em cache. Nenhum processamento de IA necessário.")
        return []

    logger.info(f"Encontradas {len(imagens_para_processar)} imagens novas de '{nome_mercado}' para serem processadas pela IA.")
    
    # --- Bloco de integração com o motor de IA ---
    chaves_api_str = os.getenv("GEMINI_API_KEYS")
    if not chaves_api_str:
        logger.error("Chaves da API Gemini não encontradas no arquivo .env. A extração de dados das imagens será pulada.")
        return []

    lista_chaves = [k.strip() for k in chaves_api_str.split(',') if k.strip()]
    motor_ia = MotorIA(lista_chaves=lista_chaves)
    produtos_extraidos = motor_ia.processar_imagens_em_lote(imagens_para_processar, nome_mercado)

    # --- Atualização do Cache ---
    if produtos_extraidos:
        atualizar_cache_downloads(cache_existente, nome_mercado, novas_entradas, logger)
    else:
        logger.warning("Processamento de IA não retornou produtos. O cache de downloads não será atualizado para permitir nova tentativa.")

    return produtos_extraidos