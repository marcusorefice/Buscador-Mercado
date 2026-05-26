import re
import json
import logging
import os
import threading
import unicodedata

# --- Global Lock for WebDriverManager ---
webdriver_manager_lock = threading.Lock()

# --- 1. Configuração de logging padrão ---
def setup_logging(log_file=os.path.join('data', 'app.log'), level=logging.INFO):
    if not logging.getLogger('').handlers:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
        )
    return logging.getLogger(__name__)

logger = setup_logging()

# --- 2. Leitura e escrita segura de arquivos JSON ---
def read_json_file(filepath, default_value=None):
    if default_value is None: default_value = {}
    if not os.path.exists(filepath): return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except: return default_value

def write_json_file(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except: return False

# --- 3. Limpeza de Preço ---
def clean_price_string(price_str):
    if not isinstance(price_str, (str, int, float)): return 0.0
    if isinstance(price_str, (int, float)): return float(price_str)
    cleaned = str(price_str).upper().replace('R$', '').replace(',', '.').strip()
    try: return float(cleaned)
    except: return 0.0

# --- 4. CATEGORIAS MASTER (necessárias apenas se a IA classificar algo novo) ---
CATEGORIAS_MASTER = [
    "Açougue e Peixaria", "Bebidas", "Bebidas Alcoólicas", "Bebê e Infantil",
    "Congelados e Pratos Prontos", "Frios e Laticínios", "Higiene e Cuidado Pessoal",
    "Hortifrúti", "Limpeza", "Mercearia e Despensa", "Padaria e Confeitaria", "Pet Shop", "Bazar e Utilidades"
]

# --- 5. Funções de Padronização e Filtros Desativadas (Pass-through) ---
CATEGORIAS_IGNORADAS = set() # Nenhuma categoria é ignorada mais
MAPA_PARA_APP = {} # Desativado
MAPA_DE_PARA_SUBCATEGORIAS = {} # Desativado

def normalizar_para_cache(nome):
    if not nome: return ""
    return str(nome).strip()

def normalizar_taxonomia_grabit(nome_produto, marca, categoria_mercado, subcategoria_mercado, tipo_produto_mercado, ean, biblioteca, mercado_nome=None):
    return categoria_mercado, subcategoria_mercado, tipo_produto_mercado

def aplicar_taxonomia_inteligente_legada(nome_produto, cat_site, sub_site, tipo_site):
    return cat_site, sub_site, tipo_site

def padronizar_categoria(nome, cat_site=""):
    return cat_site

def formatar_nome_categoria(texto: str) -> str:
    return texto

def extrair_medidas_inteligente(nome_produto):
    return nome_produto, "1", "UN"

def limpar_ruido_produto(nome):
    return nome

def otimizar_nome_produto(nome: str) -> str:
    return nome

def remover_frases_duplicadas(texto: str) -> str:
    return texto

def aplicar_title_case(texto):
    return texto

def normalizar_marca(marca: str) -> str:
    return marca if marca else "N/A"

def formatar_produto_para_db(prod):
    return prod

# --- 6. Geração de Tags Inteligentes ---
STOP_WORDS = {"com", "sem", "para", "de", "do", "da", "e", "em", "um", "uma", "o", "a", "os", "as", "no", "na", "ao", "aos", "à", "às"}
TERMOS_GENERICOS = {"cuidado", "pessoal", "higiene", "geral", "itens", "despensa", "mercearia", "frios", "laticinios", "uso", "hortifruti", "hortifrúti", "bazar", "padaria", "bebidas", "congelados", "pratos", "prontos", "utilidades", "limpeza", "casa"}

def extrair_tags_inteligentes(produto):
    """Gera tags de busca inteligentes a partir dos dados de um produto."""
    nome = str(produto.get("nome_comum", produto.get("Produto", ""))).lower()
    marca = str(produto.get("marca", produto.get("Marca", ""))).lower()
    tipo = str(produto.get("tipo_produto", "")).lower()
    categoria = str(produto.get("Categoria", "")).lower()
    
    tags_set = set()
    
    if marca and marca != "n/a": tags_set.add(marca)
    if tipo and tipo != "n/a": tags_set.add(tipo)
        
    atributos_compostos = [
        "com abas", "sem abas", "zero lactose", "sem lactose", "sem açúcar", 
        "zero açúcar", "puro malte", "zero álcool", "longa vida", "extra virgem",
        "integral", "diet", "light", "noturno"
    ]
    
    for attr in atributos_compostos:
        if attr in nome:
            tags_set.add(attr)
            
    palavras_nome = re.findall(r'\b[a-z0-9áéíóúâêîôûãõç]+\b', nome)
    for palavra in palavras_nome:
        if palavra not in STOP_WORDS and len(palavra) > 2 and not palavra.isdigit():
            if not re.match(r'^\d+(kg|g|ml|l|un|m|pots|gr|cm|mm)$', palavra):
                tags_set.add(palavra)
            
    tags_limpas = [tag for tag in tags_set if tag not in TERMOS_GENERICOS]
    
    if "pet shop" in categoria:
        tags_limpas = [t for t in tags_limpas if t not in ["açougue", "acougue", "peixaria", "carne", "peixe"]]
            
    return sorted(list(set(tags_limpas)))

def is_valid_check_digit(ean_str):
    if not str(ean_str).isdigit() or len(str(ean_str)) != 13:
        return False
    digits = [int(x) for x in str(ean_str)]
    check_digit = digits.pop()
    digits.reverse()
    total = sum(d * 3 if i % 2 == 0 else d for i, d in enumerate(digits))
    return (10 - (total % 10)) % 10 == check_digit

def criar_entrada_biblioteca(p_info):
    """Cria uma entrada padronizada para a biblioteca de produtos."""
    nome_produto = str(p_info.get("Produto", ""))
    ean_original = p_info.get("EAN", "N/A")
    ean = ean_original

    is_valid_ean_format = (ean and ean != "N/A" and is_valid_check_digit(ean))

    if not is_valid_ean_format:
        logger.warning(f"EAN inválido ou ausente '{ean_original}' para o produto '{nome_produto}'. O item não será adicionado à biblioteca.")
        return None, None

    chave_id = str(ean)

    if str(chave_id).startswith("2") and len(str(chave_id)) == 13 and str(chave_id).isdigit():
        return None, None

    marca = normalizar_marca(p_info.get("Marca", ""))
    categoria = p_info.get("Categoria", "OUTROS")
    
    entrada = {
        "id": chave_id, 
        "nome_comum": nome_produto, 
        "marca": marca, 
        "ean": ean,
        "Categoria": categoria, 
        "subcategoria": p_info.get("subcategoria", "N/A"),
        "tipo_produto": p_info.get("tipo_produto", "N/A"),
        "imagem": p_info.get("Link_Imagem", "SEM IMAGEM"), 
        "tags": []
    }

    entrada["tags"] = extrair_tags_inteligentes(entrada)

    return chave_id, entrada

def validar_e_limpar_produtos(produtos, logger, biblioteca):
    if not produtos: return []
    produtos_validos = []
    placeholders_comuns = ['produto indisponível', 'item não encontrado', 'carregando...']
    
    for produto in produtos:
        preco_atacado_str = produto.get("Preço Atacado", "")
        if clean_price_string(preco_atacado_str) <= 0:
            continue

        ean = produto.get('EAN', 'N/A')
        
        if ean and ean != "N/A":
            if not is_valid_check_digit(ean) or (str(ean).startswith("2") and len(str(ean)) == 13):
                ean = "N/A"
                produto['EAN'] = "N/A"

        nome_bruto = str(produto.get("Produto", "")).strip()
        if not nome_bruto or nome_bruto.lower() in placeholders_comuns:
            continue
            
        produto["Produto"] = nome_bruto
        produto["Categoria"] = produto.get("Categoria", "N/A")
        produto["subcategoria"] = produto.get("subcategoria", "N/A")
        produto["tipo_produto"] = produto.get("tipo_produto", "N/A")
        produto["Marca"] = produto.get("Marca", "N/A")
        
        produto["PRECISA_DE_IA"] = False
        produto["VERIFICADO"] = False
        
        # Coloca as tags em cada item para pesquisa no app (nova funcionalidade pedida)
        produto["tags"] = extrair_tags_inteligentes(produto)
        
        # --- CHECAGEM NA BIBLIOTECA E RESOLUÇÃO DE CONFLITO ---
        if ean and ean != "N/A" and ean in biblioteca:
            entrada_bib = biblioteca[ean]
            
            nome_scraper = nome_bruto.upper()
            nome_bib = str(entrada_bib.get("nome_comum", "")).strip().upper()
            
            # Se os dados que vieram forem diferentes dos da biblioteca (conflito de EAN entre mercados),
            # marca para IA resolver o conflito
            if nome_scraper != nome_bib or str(produto["Categoria"]).upper() != str(entrada_bib.get("Categoria", "")).upper():
                 produto["PRECISA_DE_IA"] = True
                 produto["CONFLITO_DADOS"] = {
                     "dados_novos": {
                         "nome_comum": nome_bruto, 
                         "marca": produto.get("Marca"), 
                         "Categoria": produto.get("Categoria"),
                         "subcategoria": produto.get("subcategoria"),
                         "tipo_produto": produto.get("tipo_produto")
                     },
                     "dados_biblioteca": {
                         "nome_comum": entrada_bib.get("nome_comum"), 
                         "marca": entrada_bib.get("marca"), 
                         "Categoria": entrada_bib.get("Categoria"),
                         "subcategoria": entrada_bib.get("subcategoria"),
                         "tipo_produto": entrada_bib.get("tipo_produto"),
                         "tags": entrada_bib.get("tags")
                     }
                 }
            else:
                 # Confia nos dados combinados/verificados da biblioteca
                 produto["VERIFICADO"] = True
                 produto["Produto"] = entrada_bib.get("nome_comum", produto["Produto"])
                 produto["Marca"] = entrada_bib.get("marca", produto["Marca"])
                 produto["Categoria"] = entrada_bib.get("Categoria", produto["Categoria"])
                 produto["subcategoria"] = entrada_bib.get("subcategoria", produto["subcategoria"])
                 produto["tipo_produto"] = entrada_bib.get("tipo_produto", produto["tipo_produto"])
                 produto["tags"] = entrada_bib.get("tags", produto["tags"])
        else:
             # Produto Novo: Confia nos dados originais do mercado
             produto["VERIFICADO"] = True 

        produtos_validos.append(produto)

    logger.info(f"✅ Limpeza concluída: {len(produtos_validos)} produtos (categorias e nomes originais do mercado). Tags adicionadas!")
    return produtos_validos

import asyncio
from buscador_ean import tentar_recuperar_ean, buscar_dados_por_ean_off

async def enriquecer_ean_produtos_async(produtos_validados, logger):
    async def buscar_para_produto(p):
        if p.get("EAN", "N/A") == "N/A":
            nome = p.get("Produto", "")
            marca = p.get("Marca", "")
            resultado = await tentar_recuperar_ean(nome, marca)
            if resultado and resultado.get("ean"):
                p["EAN"] = str(resultado["ean"])
                p["Fonte_EAN"] = resultado["fonte"]
                logger.info(f"🔍 EAN recuperado via {resultado['fonte']}: {p['EAN']} para '{nome}'")
        return p

    semaforo = asyncio.Semaphore(10)
    
    async def buscar_com_semaforo(p):
        async with semaforo:
            return await buscar_para_produto(p)

    tarefas = [buscar_com_semaforo(p) for p in produtos_validados]
    return await asyncio.gather(*tarefas)

async def comparar_dados_produto_off(ean: str):
    from curl_cffi.requests import AsyncSession
    async with AsyncSession(impersonate="chrome120") as session:
         return await buscar_dados_por_ean_off(session, str(ean))
