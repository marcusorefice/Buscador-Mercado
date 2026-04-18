import os
import re
import requests
import urllib3
import hashlib

from utils import setup_logging, filtrar_imagens_por_cache, atualizar_cache_downloads
from motor_ia import MotorIA
from dotenv import load_dotenv

logger = setup_logging()
# Desativar avisos de conexão insegura para o download
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# CONFIGURAÇÕES DO MÓDULO
# ==========================================
NOME_MERCADO = "Roldão Atacadista"
URL_ALVO = "https://roldao.com.br/ofertas/"
load_dotenv()

def garantir_pasta(pasta_imagens):
    """Garante que a pasta de destino exista, sem apagar o conteúdo."""
    if not os.path.exists(pasta_imagens):
        os.makedirs(pasta_imagens)

# ==========================================
# FUNÇÃO PRINCIPAL EXPORTADA
# ==========================================
def baixar_encartes(pasta_destino):
    """
    Acessa o site do Roldão, busca links de imagens via Regex e baixa para a pasta destino.
    Retorna uma tupla: (lista_de_caminhos_das_imagens, nome_do_mercado)
    """
    logger.info(f"Iniciando Motor de Captura - {NOME_MERCADO}...")
    garantir_pasta(pasta_destino)

    links_encontrados = set()
    headers = {'User-Agent': 'Mozilla/5.0'}

    logger.info("   🌐 Acessando página de ofertas do Roldão via API/Requests...")
    try:
        res = requests.get(URL_ALVO, headers=headers, verify=False, timeout=15)
        html_limpo = res.text.replace('\\/', '/')
        
        # Expressão regular original mantida para buscar os JPEGs específicos
        matches = re.findall(r'https?://roldao\.com\.br/wp-content/uploads/[^"\']+\-scaled\.jpeg', html_limpo)
        for m in matches:
            if "ROLDAO-" in m.upper() or "ESPECIAL-" in m.upper():
                links_encontrados.add(m)
    except Exception as e:
        logger.error(f"   ❌ Erro ao acessar o site: {e}")
        return [], NOME_MERCADO

    if not links_encontrados:
        logger.warning("   ⚠️ Nenhum encarte encontrado com o padrão esperado.")
        return [], NOME_MERCADO

    imagens_finais = []
    logger.info(f"   📥 Baixando {len(links_encontrados)} imagens de encartes...")
    for link in sorted(list(links_encontrados)): # Sort for consistent processing order
        try:
            url_hash = hashlib.md5(link.encode('utf-8')).hexdigest()
            caminho_local = os.path.join(pasta_destino, f"roldao_img_{url_hash}.jpg")
            img_data = requests.get(link, headers=headers, verify=False, timeout=15).content
            with open(caminho_local, 'wb') as f:
                f.write(img_data)
            imagens_finais.append(caminho_local)
        except Exception as e:
            logger.error(f"      ❌ Falha ao baixar {link}: {e}")

    imagens_finais.sort()
    if not imagens_finais:
        logger.warning("   ⚠️ Nenhuma imagem para processar no Roldão Atacadista.")
    
    return imagens_finais, NOME_MERCADO

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