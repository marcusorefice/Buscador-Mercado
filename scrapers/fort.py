import os
import time
import requests
import urllib3
import hashlib
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from pdf2image import convert_from_path

from utils import setup_logging, webdriver_manager_lock
from motor_ia import MotorIA
from dotenv import load_dotenv
import logging

# Desativar avisos de conexão insegura para o download
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Desativar logs verbosos do webdriver_manager
logging.getLogger('WDM').setLevel(logging.ERROR)
os.environ['WDM_LOG'] = '0'
os.environ['WDM_LOG_LEVEL'] = '0'

# ==========================================
# CONFIGURAÇÕES DO MÓDULO
# ==========================================
NOME_MERCADO = "Fort Atacadista"

# Ajuste do caminho do Poppler para a arquitetura modular 
logger = setup_logging()
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_POPPLER = os.path.join(BASE_DIR, 'poppler-25.12.0', 'Library', 'bin')

def garantir_pasta(pasta_imagens):
    """Garante que a pasta de destino exista, sem apagar o conteúdo."""
    if not os.path.exists(pasta_imagens):
        os.makedirs(pasta_imagens)

# ==========================================
# CONVERSOR LOCAL (PDF -> JPG)
# ==========================================
def converter_pdf_em_imagens(caminho_pdf):
    logger.info(f"   📄 [Conversor] PDF -> JPG: {os.path.basename(caminho_pdf)}")
    try:
        paginas = convert_from_path(caminho_pdf, dpi=150, poppler_path=CAMINHO_POPPLER)
        caminhos_imagens = []
        for i, pagina in enumerate(paginas):
            caminho_img = caminho_pdf.replace(".pdf", f"_pg{i+1}.jpg")
            pagina.save(caminho_img, "JPEG")
            caminhos_imagens.append(caminho_img)
        return caminhos_imagens
    except Exception as e:
        logger.error(f"Erro no Poppler ao converter PDF {os.path.basename(caminho_pdf)}: {e}")
        return []
# ==========================================
# FUNÇÃO PRINCIPAL EXPORTADA
# ==========================================
def baixar_encartes(pasta_destino):
    """
    Navega no site do Fort, foca na loja selecionada, baixa PDFs/Imagens, converte e salva.
    Retorna uma tupla: (lista_de_caminhos_das_imagens, nome_do_mercado)
    """
    logger.info(f"Iniciando Motor de Captura - {NOME_MERCADO}...")
    garantir_pasta(pasta_destino)
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    with webdriver_manager_lock:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    arquivos_baixados = []
    try:
        driver.get("https://www.fortatacadista.com.br/ofertas/")
        wait = WebDriverWait(driver, 25)
        
        # Mantendo sua lógica de foco cirúrgico na loja específica
        Select(wait.until(EC.presence_of_element_located((By.ID, "tabloide-estados")))).select_by_visible_text("SP")
        time.sleep(2)
        Select(wait.until(EC.presence_of_element_located((By.ID, "tabloide-cidades")))).select_by_visible_text("Jundiaí")
        time.sleep(2)
        Select(wait.until(EC.presence_of_element_located((By.ID, "tabloide-lojas")))).select_by_visible_text("Jundiaí | SP | Fort Atacadista 635")
        time.sleep(8)
        
        # Coleta os links e garante uma ordem consistente (opcional, mas bom para depuração)
        links = sorted(list(set(driver.execute_script("return Array.from(document.querySelectorAll('.tabloid-link')).map(a => a.href);"))))
        
        logger.info(f"Encontrados {len(links)} encartes para download.")
        for url in links:
            ext = "pdf" if ".pdf" in url.lower() else "jpg"
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
            caminho = os.path.join(pasta_destino, f"fort_raw_{url_hash}.{ext}")
            res = requests.get(url, verify=False)
            with open(caminho, 'wb') as f: 
                f.write(res.content)
            arquivos_baixados.append(caminho)
            
    finally: 
        driver.quit()

    logger.info("Iniciando processamento de PDFs e limpeza de arquivos temporários.")
    imagens_finais = []
    for caminho in arquivos_baixados:
        if caminho.lower().endswith(".pdf"):
            imagens_convertidas = converter_pdf_em_imagens(caminho)
            imagens_finais.extend(imagens_convertidas)
            try:
                os.remove(caminho)
            except Exception as e:
                logger.warning(f"Não foi possível excluir o PDF {os.path.basename(caminho)}: {e}")
        elif caminho.lower().endswith(('.jpg', '.jpeg', '.png')):
            imagens_finais.append(caminho)

    imagens_finais.sort()

    if not imagens_finais:
        logger.warning("Nenhuma imagem para processar no Fort Atacadista.")
    
    return imagens_finais, NOME_MERCADO

# ==========================================
# FUNÇÃO DE EXTRAÇÃO (PADRÃO DO PROJETO)
# ==========================================
def extrair_dados():
    """
    Orquestra o download dos encartes e o processamento pela IA.
    Esta função segue o padrão do `main.py`, retornando uma lista de produtos.
    O cache de processamento da IA é gerenciado pelo MotorIA.
    """
    imagens, nome_mercado = baixar_encartes(pasta_destino="temp_imagens")
    
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
    # Processa TODAS as imagens. O motor de IA tem seu próprio cache interno para evitar reprocessamento.
    produtos_extraidos = motor_ia.processar_imagens_em_lote(imagens, nome_mercado)
    
    # A lógica de cache foi movida para dentro do MotorIA, tornando o cache aqui desnecessário.
    if not produtos_extraidos:
        logger.warning(f"Processamento de IA não retornou produtos para {nome_mercado}.")
    
    return produtos_extraidos