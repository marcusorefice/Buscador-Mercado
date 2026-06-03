import os
import time
import hashlib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from utils import setup_logging, webdriver_manager_lock
from motor_ia import MotorIA
import asyncio
from dotenv import load_dotenv

# ==========================================
# CONFIGURAÇÕES DO MÓDULO
# ==========================================
NOME_MERCADO = "Tauste Supermercado"
URL_PORTAL = "https://www.flipsnack.com/taustesupermercado/"

logger = setup_logging()
load_dotenv()

def garantir_pasta(pasta_imagens):
    """Garante que a pasta de destino exista, sem apagar o conteúdo."""
    if not os.path.exists(pasta_imagens):
        os.makedirs(pasta_imagens)

def calcular_hash_imagem(caminho_imagem):
    with open(caminho_imagem, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

# ==========================================
# FUNÇÃO PRINCIPAL EXPORTADA
# ==========================================
def baixar_encartes(pasta_destino):
    """
    Navega pelo portal FlipSnack, localiza encartes de Jundiaí e tira prints 
    de cada página até o fim do folheto.
    Retorna uma tupla: (lista_de_caminhos_das_imagens, nome_do_mercado)
    """
    logger.info(f"Iniciando Motor Fotógrafo - {NOME_MERCADO}...")
    garantir_pasta(pasta_destino)
    
    options = Options()
    options.add_argument('--headless=new') 
    options.add_argument('--mute-audio')
    options.add_argument('--window-size=1920,1080')
    with webdriver_manager_lock:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    imagens_geradas = []
    
    try:
        logger.info("   📡 Acessando portal FlipSnack...")
        driver.get(URL_PORTAL)
        
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.flip-card")))
        cards = driver.find_elements(By.CSS_SELECTOR, "a.flip-card")
        links_jundiai = []
        
        for card in cards:
            try:
                titulo = card.find_element(By.TAG_NAME, "strong").text.lower()
                if "jundia" in titulo:
                    href = card.get_attribute("href")
                    links_jundiai.append((titulo, href))
            except NoSuchElementException:
                continue
                
        if not links_jundiai:
            logger.warning("   ⚠️ Nenhum folheto ativo para Jundiaí encontrado no Tauste.")
            driver.quit()
            return [], NOME_MERCADO
            
        logger.info(f"   🎯 Encontrados {len(links_jundiai)} encartes. Iniciando sessões de fotos...")
        
        # Use a hash do link para um identificador estável do encarte
        for link_idx, (titulo, link) in enumerate(sorted(links_jundiai, key=lambda x: x[1])): # Sort by link for consistency
            logger.info(f"   📸 Abrindo encarte: {titulo.title()}")
            driver.get(link)
            
            try:
                WebDriverWait(driver, 15).until(EC.frame_to_be_available_and_switch_to_it((By.ID, "player-iframe")))
            except TimeoutException:
                logger.error("      ❌ Iframe do player não carregou.")
                continue
                
            time.sleep(5) # Tempo para o player renderizar a primeira página
            pagina = 1
            hash_anterior = ""
            
            while True:
                nome_arq = os.path.join(pasta_destino, f"tauste_{hashlib.md5(link.encode('utf-8')).hexdigest()}_pag_{pagina:02d}.png")
                driver.save_screenshot(nome_arq)
                
                hash_atual = calcular_hash_imagem(nome_arq)
                
                # Se a foto for igual à anterior, chegamos ao fim do folheto
                if hash_atual == hash_anterior:
                    os.remove(nome_arq)
                    break
                    
                hash_anterior = hash_atual
                imagens_geradas.append(nome_arq)
                
                try:
                    btn_next = driver.find_element(By.ID, "btn-next")
                    if btn_next.is_displayed():
                        driver.execute_script("arguments[0].click();", btn_next)
                        pagina += 1
                        time.sleep(2) # Espera a animação de virada de página
                    else:
                        break
                except NoSuchElementException:
                    break
            
            driver.switch_to.default_content()

    except Exception as e:
        logger.error(f"   ❌ Erro crítico no Tauste: {e}")
    finally:
        driver.quit()

    imagens_geradas.sort()
    return imagens_geradas, NOME_MERCADO

# ==========================================
# FUNÇÃO DE EXTRAÇÃO (PADRÃO DO PROJETO)
# ==========================================
async def extrair_dados():
    """
    Orquestra o download dos encartes e o processamento pela IA.
    Esta função segue o padrão do `main.py`, retornando uma lista de produtos.
    """
    imagens, nome_mercado = await asyncio.to_thread(baixar_encartes, "temp_imagens")
    
    if not imagens:
        logger.warning(f"Nenhuma imagem de encarte encontrada para {nome_mercado}. O scraper será encerrado.")
        return []
    
    logger.info(f"Encontradas {len(imagens)} imagens de '{nome_mercado}'. Enviando para o motor de IA (usará cache se aplicável).")
    
    # --- Bloco de integração com o motor de IA ---
    chaves_api_str = os.getenv("GEMINI_API_KEYS")
    if not chaves_api_str:
        logger.error("Chaves da API Gemini não encontradas no arquivo .env. A extração de dados das imagens será pulada.")
        return []
    
    lista_chaves = [k.strip() for k in chaves_api_str.split(',') if k.strip()]
    motor_ia = MotorIA(lista_chaves=lista_chaves)
    produtos_extraidos = await motor_ia.processar_imagens_em_lote_async(imagens, nome_mercado)
    
    # A lógica de cache agora é gerenciada inteiramente pelo MotorIA, que cria arquivos .json
    # em temp_json_cache para cada imagem processada, evitando reprocessamento desnecessário.
    if not produtos_extraidos:
        logger.warning(f"Processamento de IA não retornou produtos para {nome_mercado}.")
    
    return produtos_extraidos