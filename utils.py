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
    import re
    if not nome: return ""
    nome = str(nome).upper()
    # Remove lixo promocional e termos redundantes
    ruidos = [
        r'\bLEVE\s+\d+\s*PAGUE\s+\d+\b', r'\bLV\s*\d+\s*PG\s*\d+\b', 
        r'\bOFERTA\b', r'\bIMPERD[ÍI]VEL\b', r'\bPROMO[CÇ][AÃ]O\b', 
        r'\bEXCLUSIVO\b', r'\bNOVA EMBALAGEM\b', r'\bGR[ÁA]TIS\b', r'\bBRINDE\b',
        r'-\s*$', r'^\s*-'
    ]
    for r in ruidos:
        nome = re.sub(r, '', nome)
    return re.sub(r'\s+', ' ', nome).strip()

def otimizar_nome_produto(nome: str) -> str:
    return limpar_ruido_produto(nome)

def remover_frases_duplicadas(texto: str) -> str:
    # Apenas retorna o texto, mas pode ser implementado no futuro se necessário
    return texto

def aplicar_title_case(texto):
    import re
    if not texto: return ""
    texto = str(texto).lower()
    excecoes = {"de", "do", "da", "dos", "das", "e", "em", "com", "sem", "para", "a", "o", "as", "os"}
    palavras = texto.split()
    resultado = []
    for i, p in enumerate(palavras):
        # Manter unidades de medida combinadas com número em minúsculo (ex: 1kg, 500ml)
        if re.match(r'^\d+([.,]\d+)?(kg|g|mg|ml|l|cm|mm|m)$', p):
            resultado.append(p)
        # Exceções (preposições) em minúsculo
        elif p in excecoes and i > 0:
            resultado.append(p)
        else:
            # Coloca a primeira letra em maiúsculo (ex: Maçã, Sabão)
            resultado.append(p.capitalize())
    return " ".join(resultado)

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

import re

def ean_eh_valido(ean_str):
    """
    Função centralizada para validação rigorosa de EAN.
    Bloqueia EANs falsos, códigos internos de supermercado e valida o dígito verificador.
    """
    if ean_str is None: return False
    ean_str = str(ean_str).strip()
    
    if ean_str == "N/A" or not ean_str: return False
    
    # IDs internos gerados pelo nosso sistema são sempre válidos para o nosso banco
    if ean_str.startswith('INT_'): return True
    
    # Se contém letras (exceto INT_) não é EAN válido
    if not ean_str.isdigit(): return False
    
    # Tamanhos aceitos para GTIN/EAN: 8, 12, 13, 14
    if len(ean_str) not in (8, 12, 13, 14): return False
    
    # Bloqueia lixo como '0000000000000' ou '1111111111111'
    if len(set(ean_str)) == 1: return False
    
    # Bloqueia EANs de pesagem/balança (geralmente começam com 2, 02, 20-29 no Brasil)
    # Esses não são universais e causam agrupamento errado de hortifruti/açougue.
    if len(ean_str) >= 12:
        prefixo = ean_str[:2]
        if prefixo.startswith('2') or prefixo == '02' or (prefixo.isdigit() and 20 <= int(prefixo) <= 29):
            return False
            
    # Validação do Dígito Verificador (Mod 10)
    padded = ean_str.zfill(14)
    total = sum(int(padded[i]) * (3 if i % 2 == 0 else 1) for i in range(13))
    check_digit_calculado = str((10 - (total % 10)) % 10)
    return check_digit_calculado == padded[13]

def is_valid_check_digit(ean_str):
    """Alias para manter compatibilidade com código legado até ser totalmente refatorado."""
    return ean_eh_valido(ean_str)

def gerar_id_interno(nome_produto: str, marca: str) -> str:
    """
    Gera um ID interno (INT_...) seguro para produtos sem EAN.
    Usa informações de peso, medida e apresentação extraídas do nome para evitar 
    que produtos inteiros e fracionados sejam mesclados.
    """
    from utils import otimizar_nome_produto, normalizar_marca # evita erro circular se já estiver no topo
    import re
    
    nome_base = str(nome_produto).lower()
    marca_base = str(marca).lower()
    
    # Extrair medidas e apresentações importantes ANTES de limpar o nome
    apresentacao = []
    
    # Busca por peso ou volume (ex: 500g, 1kg, 2l, 300ml)
    medida_match = re.search(r'(\d+[,.]?\d*\s*(kg|g|mg|ml|l|litro|litros|gramas|kilo|kilos))\b', nome_base)
    if medida_match:
        apresentacao.append(medida_match.group(1).replace(" ", "").replace(",", "."))
        
    # Busca por formato de venda (bandeja, peca, pedaco, cortado, fatiado)
    formatos = ["bandeja", "peca", "peça", "pedaco", "pedaço", "cortado", "fatiado", "inteira", "inteiro", "metade", "kg", "granel", "pacote", "pct"]
    for formato in formatos:
        if re.search(rf'\b{formato}\b', nome_base):
            # Normalizar para evitar variação (ex: peça -> peca)
            f_norm = formato.replace("ç", "c").replace("pedaço", "pedaco")
            apresentacao.append(f_norm)
            
    # Gera uma base limpa (letras e numeros apenas)
    nome_limpo = re.sub(r'[^a-z0-9]', '', nome_base)
    marca_limpa = re.sub(r'[^a-z0-9]', '', marca_base)
    
    if not marca_limpa or marca_limpa == "na":
        marca_limpa = "generico"
        
    # Monta o sufixo de apresentação
    sufixo_apresentacao = "_".join(sorted(set(apresentacao)))
    if sufixo_apresentacao:
         id_final = f"INT_{marca_limpa}_{nome_limpo}_{sufixo_apresentacao}"
    else:
         id_final = f"INT_{marca_limpa}_{nome_limpo}"
         
    return id_final[:70].upper() # Limita tamanho e padroniza para maiúsculo


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

def exibir_resumo_coleta(resumo_geral, logger_instance):
    """
    Exibe o relatório final de coleta formatando o tempo em minutos e segundos.
    Espera um dicionário resumo_geral onde as chaves são os nomes dos mercados
    e os valores são dicionários {"qtd": X, "tempo": Y_segundos}.
    """
    logger_instance.info("📊 RESUMO FINAL DA COLETA:")
    total_time_seconds = 0
    total_items = 0
    
    for mercado, info in resumo_geral.items():
        if isinstance(info, dict):
            qtd = info.get("qtd", 0)
            tempo_s = info.get("tempo", 0.0)
        else:
            qtd = info
            tempo_s = 0.0
            
        total_time_seconds += tempo_s
        total_items += qtd
        
        minutos = int(tempo_s // 60)
        segundos = int(tempo_s % 60)
        
        if minutos > 0:
            tempo_formatado = f"{minutos}m {segundos}s"
        else:
            tempo_formatado = f"{segundos}s"
            
        logger_instance.info(f"  - {mercado}: {qtd} produtos coletados em {tempo_formatado}")
        
    minutos_totais = int(total_time_seconds // 60)
    segundos_totais = int(total_time_seconds % 60)
    
    if minutos_totais > 0:
        tempo_total_formatado = f"{minutos_totais}m {segundos_totais}s"
    else:
        tempo_total_formatado = f"{segundos_totais}s"
        
    logger_instance.info(f"  > TOTAL GERAL: {total_items} produtos em ~{tempo_total_formatado} (tempo corrido pode ser menor devido ao paralelismo)")
