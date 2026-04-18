import re
import json
import logging
import os
from datetime import datetime

# --- 1. Configuração de logging padrão ---
def setup_logging(log_file=os.path.join('data', 'app.log'), level=logging.INFO):
    """
    Configura um logger padrão para a aplicação.
    Logs serão exibidos no console e salvos em um arquivo.
    """
    # Garante que o logger não adicione handlers duplicados se chamado múltiplas vezes
    if not logging.getLogger('').handlers:
        # Garante que o diretório de log exista
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    # Retorna o logger para uso em outros módulos, se necessário
    return logging.getLogger(__name__)

# Inicializa o logging quando o módulo é importado
logger = setup_logging()

# --- 2. Leitura e escrita segura de arquivos JSON ---
def read_json_file(filepath, default_value=None):
    """
    Lê um arquivo JSON de forma segura.
    Retorna o conteúdo do JSON ou um valor padrão (default_value) em caso de erro.
    """
    if default_value is None:
        default_value = {} # Valor padrão para a maioria dos casos de uso

    if not os.path.exists(filepath):
        logger.warning(f"Arquivo JSON não encontrado: {filepath}. Retornando valor padrão.")
        return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON do arquivo {filepath}: {e}. Retornando valor padrão.")
        return default_value
    except IOError as e:
        logger.error(f"Erro de I/O ao ler o arquivo {filepath}: {e}. Retornando valor padrão.")
        return default_value

def write_json_file(filepath, data):
    """
    Escreve dados em um arquivo JSON de forma segura.
    Retorna True em caso de sucesso, False em caso de erro.
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except TypeError as e:
        logger.error(f"Erro de tipo ao serializar dados para JSON no arquivo {filepath}: {e}.")
        return False
    except IOError as e:
        logger.error(f"Erro de I/O ao escrever no arquivo {filepath}: {e}.")
        return False

# --- 3. Função de limpeza de strings de preços ---
def clean_price_string(price_str):
    """
    Limpa uma string de preço, removendo 'R$', espaços e convertendo vírgula para ponto,
    retornando um float. Retorna 0.0 se a conversão falhar.
    """
    if not isinstance(price_str, (str, int, float)):
        logger.warning(f"Tipo inválido para limpeza de preço: {type(price_str)}. Retornando 0.0.")
        return 0.0
    
    if isinstance(price_str, (int, float)):
        return float(price_str)

    cleaned_str = str(price_str).upper().replace('R$', '').replace(',', '.').strip()
    try:
        return float(cleaned_str)
    except ValueError:
        logger.warning(f"Não foi possível converter '{price_str}' para float após limpeza. Retornando 0.0.")
        return 0.0

def padronizar_categoria(nome, cat_site=""):
    n, c = str(nome).upper(), str(cat_site).upper()
    regras = {
        "Higiene e Perfumaria": ["SABONETE", "DENTAL", "SHAMPOO", "CONDICIONADOR", "DOVE", "REXONA", "COLGATE", "FRALDA", "ABSORVENTE", "PAPEL HIGIÊNICO", "GILLETTE"],
        "Limpeza": ["DETERGENTE", "SABÃO", "OMO", "TIXAN", "VEJA", "YPÊ", "AMACIANTE", "DESINFETANTE", "SBP", "BOMBRIL", "LIXO", "CLORO", "PANO", "PERFEX"],
        "Bebidas": ["ÁGUA", "REFRIGERANTE", "COCA", "GUARANÁ", "CERVEJA", "VINHO", "WHISKY", "SUCO", "TANG", "MONSTER", "RED BULL", "GATORADE", "WHEY"],
        "Laticínios, Ovos e Frios": ["LEITE", "QUEIJO", "IOGURTE", "QUALY", "MARGARINA", "REQUEIJÃO", "PRESUNTO", "MORTADELA", "SALSICHA", "DANONE"],
        "Açougue e Peixaria": ["CARNE", "ACÉM", "BISTECA", "FRANGO", "ASA", "COXA", "LINGUIÇA", "PEIXE", "ATUM", "SARDINHA"],
        "Mercearia": ["ARROZ", "FEIJÃO", "CAFÉ", "AÇÚCAR", "ÓLEO", "AZEITE", "MACARRÃO", "MOLHO", "TOMATE", "BISCOITO", "WAFER", "PASSATEMPO", "BAUDUCCO", "NESCAU", "TODDY", "CHOCOLATE"],
        "Congelados e Pratos Prontos": ["PIZZA", "LASANHA", "NUGGETS", "HAMBÚRGUER", "SORVETE", "AÇAÍ", "DAUCY", "VEGETAIS", "CONGELADO"],
        "Bazar e Utilidades": ["TRAMONTINA", "MARINEX", "ASSADEIRA", "FRIGIDEIRA", "FILME PVC", "PAPEL ALUMÍNIO"]
    }
    for cat, termos in regras.items():
        if any(t in n for t in termos) or any(t in c for t in termos): return cat
    return "Mercearia"

def extrair_medidas_inteligente(nome_produto):
    nome = str(nome_produto).upper()
    match = re.search(r'(\d+(?:[\.,]\d+)?)\s*(G|KG|ML|L|UN)\b', nome)
    if match: return nome.replace(match.group(0), "").strip(), match.group(1).replace(',', '.'), match.group(2)
    return nome, "1", "UN"

# --- 4. Funções de Cache de Download ---
CACHE_DOWNLOADS_FILE = os.path.join('data', 'cache_downloads.json')

def filtrar_imagens_por_cache(imagens, nome_mercado, logger):
    """
    Filtra uma lista de imagens, removendo aquelas que já foram processadas no dia.
    Retorna a lista de imagens a serem processadas e um dicionário com as novas entradas para o cache.
    """
    logger.info(f"Verificando cache de downloads para {len(imagens)} imagens de '{nome_mercado}'...")
    cache_downloads = read_json_file(CACHE_DOWNLOADS_FILE, default_value={})
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    imagens_para_processar = []
    novas_entradas_cache = {}
    
    if nome_mercado not in cache_downloads:
        cache_downloads[nome_mercado] = {}

    for img_path in imagens:
        try:
            nome_arquivo = os.path.basename(img_path)
            tamanho_arquivo = os.path.getsize(img_path)
            
            entrada_cache = cache_downloads[nome_mercado].get(nome_arquivo)
            
            if entrada_cache and entrada_cache.get("size") == tamanho_arquivo and entrada_cache.get("processed_date") == hoje:
                logger.info(f"   CACHE HIT: '{nome_arquivo}' ({tamanho_arquivo} bytes) já processado hoje. Pulando.")
                continue
            else:
                logger.info(f"   CACHE MISS: '{nome_arquivo}' ({tamanho_arquivo} bytes) é novo ou modificado. Será processado.")
                imagens_para_processar.append(img_path)
                novas_entradas_cache[nome_arquivo] = {
                    "size": tamanho_arquivo,
                    "processed_date": hoje
                }
        except FileNotFoundError:
            logger.warning(f"   Arquivo '{img_path}' não encontrado durante verificação de cache. Pulando.")
            continue
            
    return imagens_para_processar, novas_entradas_cache, cache_downloads

def atualizar_cache_downloads(cache_downloads, nome_mercado, novas_entradas_cache, logger):
    """Atualiza e salva o arquivo de cache de downloads."""
    logger.info("Processamento de IA bem-sucedido. Atualizando cache de downloads...")
    if nome_mercado not in cache_downloads:
        cache_downloads[nome_mercado] = {}
    cache_downloads[nome_mercado].update(novas_entradas_cache)
    write_json_file(CACHE_DOWNLOADS_FILE, cache_downloads)