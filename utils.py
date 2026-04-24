import re
import json
import logging
import os
from datetime import datetime
import threading

# --- Global Lock for WebDriverManager ---
# This lock prevents a race condition when multiple scrapers running in parallel
# (especially synchronous ones in threads) try to access or install the
# chromedriver simultaneously via webdriver-manager.
webdriver_manager_lock = threading.Lock()

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

# --- 4. Mapeamento e Padronização de Categorias ---

# Mapeamento das categorias do site para as categorias do App
MAPA_PARA_APP = {
    # Itens de Mercado
    "MERCEARIA": "Mercearia e Despensa",
    "ALIMENTOS": "Mercearia e Despensa",
    "ALIMENTOS BÁSICOS": "Mercearia e Despensa",
    "PADARIA E MATINAIS": "Laticínios, Ovos e Matinais",
    "PADARIA": "Laticínios, Ovos e Matinais",
    "LATICÍNIOS": "Laticínios, Ovos e Matinais",
    "FRIOS E LATICÍNIOS": "Laticínios, Ovos e Matinais",
    "FRIOS E CONGELADOS": "Congelados e Pratos Prontos",
    "CONGELADOS": "Congelados e Pratos Prontos",
    "CARNES, AVES E PEIXES": "Açougue e Peixaria",
    "AÇOUGUE": "Açougue e Peixaria",
    "PEIXARIA": "Açougue e Peixaria",
    "HORTIFRÚTI": "Hortifrúti",
    "HORTIFRUTI": "Hortifrúti",
    "BEBIDAS": "Bebidas",
    "LIMPEZA": "Limpeza",
    "PRODUTOS DE LIMPEZA": "Limpeza",
    "HIGIENE E PERFUMARIA": "Higiene e Cuidado Pessoal",
    "HIGIENE E BELEZA": "Higiene e Cuidado Pessoal",
    "CUIDADOS PESSOAIS": "Higiene e Cuidado Pessoal",
    "BEBÊ": "Higiene e Cuidado Pessoal",
    
    # Bazar e Utilidades
    "UTILIDADES DOMÉSTICAS": "Bazar e utilidades",
    "ELETRÔNICOS E ELETROPORTÁTEIS": "Bazar e utilidades",
    "DESCARTÁVEIS E EMBALAGENS": "Bazar e utilidades",
    "PAPELARIA": "Bazar e utilidades",
    "CASA E LAZER": "Bazar e utilidades",
    "BAZAR": "Bazar e utilidades",
    "PET SHOP": "Pet Shop",
    "PET": "Pet Shop"
}

CATEGORIAS_IGNORADAS = {"AUTOMOTIVO", "JARDINAGEM", "ESPORTE E LAZER", "VESTUÁRIO", "CAFETERIA"}

def padronizar_categoria(nome, cat_site=""):
    n, c = str(nome).upper(), str(cat_site).upper()
    regras = {
        "Pet Shop": ["RAÇÃO", "GATO", "CACHORRO", "PET", "AREIA", "WHISKAS", "PEDIGREE", "FRISKIES", "PURINA"],
        "Mercearia e Despensa": ["ARROZ", "FEIJÃO", "CAFÉ", "AÇÚCAR", "ÓLEO", "AZEITE", "MACARRÃO", "MOLHO", "BISCOITO", "WAFER", "PASSATEMPO", "BAUDUCCO", "NESCAU", "TODDY", "CHOCOLATE"],
        "Laticínios, Ovos e Matinais": ["LEITE", "QUEIJO", "IOGURTE", "QUALY", "MARGARINA", "REQUEIJÃO", "PRESUNTO", "MORTADELA", "SALSICHA", "DANONE", "OVOS"],
        "Congelados e Pratos Prontos": ["PIZZA", "LASANHA", "NUGGETS", "HAMBÚRGUER", "SORVETE", "AÇAÍ", "DAUCY", "VEGETAIS", "CONGELADO"],
        "Açougue e Peixaria": ["CARNE", "ACÉM", "BISTECA", "FRANGO", "ASA", "COXA", "LINGUIÇA", "PEIXE", "ATUM", "SARDINHA"],
        "Hortifrúti": ["FRUTAS", "LEGUMES", "VERDURAS", "CEBOLA", "BATATA", "TOMATE", "ALFACE", "CENOURA", "UVA", "MORANGO", "BANANA", "MACA", "LARANJA"],
        "Bebidas": ["ÁGUA", "REFRIGERANTE", "COCA", "GUARANÁ", "CERVEJA", "VINHO", "WHISKY", "SUCO", "TANG", "MONSTER", "RED BULL", "GATORADE", "WHEY"],
        "Limpeza": ["DETERGENTE", "SABÃO", "OMO", "TIXAN", "VEJA", "YPÊ", "AMACIANTE", "DESINFETANTE", "SBP", "BOMBRIL", "LIXO", "CLORO", "PANO", "PERFEX"],
        "Higiene e Cuidado Pessoal": ["SABONETE", "DENTAL", "SHAMPOO", "CONDICIONADOR", "DOVE", "REXONA", "COLGATE", "FRALDA", "ABSORVENTE", "PAPEL HIGIÊNICO", "GILLETTE"],
        "Bazar e utilidades": ["TRAMONTINA", "MARINEX", "ASSADEIRA", "FRIGIDEIRA", "FILME PVC", "PAPEL ALUMÍNIO"]
    }
    for cat, termos in regras.items():
        if any(t in n for t in termos) or any(t in c for t in termos): return cat
    return "Mercearia e Despensa"

def formatar_nome_categoria(texto: str) -> str:
    """
    Formata um nome de categoria/subcategoria para um formato mais legível.
    Ex: 'LEITE-E-DERIVADOS' -> 'Leite e Derivados'
    Ex: 'BEBIDAS-ALCOOLICAS' -> 'Bebidas Alcoolicas'
    """
    if not isinstance(texto, str) or not texto or texto.upper() == "N/A":
        return "N/A"
    
    # Substitui hífens e underscores por espaços e remove espaços extras
    texto_limpo = texto.replace('-', ' ').replace('_', ' ').strip()
    
    # Aplica capitalização de título (Title Case) e lida com palavras pequenas
    palavras = texto_limpo.lower().split()
    palavras_capitalizadas = []
    palavras_a_ignorar = ['e', 'de', 'da', 'do', 'dos', 'das', 'a', 'o', 'as', 'os']
    for p in palavras:
        if p in palavras_a_ignorar:
            palavras_capitalizadas.append(p)
        else:
            palavras_capitalizadas.append(p.capitalize())

    return " ".join(palavras_capitalizadas)

def extrair_medidas_inteligente(nome_produto):
    nome = str(nome_produto).upper()
    # Adicionamos: CAPS (Cápsulas), FLS (Folhas), POTS (Potes), LTS (Litros)
    match = re.search(r'(\d+(?:[\.,]\d+)?)\s*(G|KG|ML|L|LTS|UN|CAPS|FLS|POTS)\b', nome)
    if match: return nome.replace(match.group(0), "").strip(), match.group(1).replace(',', '.'), match.group(2)
    return nome, "1", "UN"

def otimizar_nome_produto(nome: str) -> str:
    """Simplifica nomes de produtos muito longos, focando em Marca + Formato + Sabor."""
    if not isinstance(nome, str): return nome
    n = nome.upper()
    
    # Remove símbolos de marca registrada que poluem o nome (ex: NESTLÉ®)
    n = re.sub(r'[®©™\xae\u2122\u00a9]', '', n)

    # --- Regras para Ração Úmida / Pet Shop ---
    termos_pet = ["RAÇÃO", "ÚMID", "SACHÊ", "SACHE", "GATO", "CÃO", "CÃES", "CACHORRO", "FRISKIES", "PURINA", "WHISKAS", "DOG CHOW", "CAT CHOW"]
    if any(t in n for t in termos_pet):
        # Substituições de palavras desnecessárias e jargões comerciais
        replaces = [
            ("RAÇÃO ÚMIDA PARA", ""), ("RAÇÃO ÚMIDA", ""), 
            ("ALIMENTO ÚMIDO PARA", ""), ("ALIMENTO ÚMIDO", ""),
            ("NESTLÉ PURINA", ""), ("NESTLE PURINA", ""), 
            ("NESTLÉ", ""), ("NESTLE", ""), ("PURINA", ""),
            ("EXTRALIFE", ""), ("DE TODOS OS TAMANHOS", ""), ("TODOS OS TAMANHOS", ""),
            ("100% COMPLETO E BALANCEADO", ""), ("COMPLETO E BALANCEADO", ""),
            ("SABOR", ""), ("AO MOLHO", ""), ("EM GELEIA", ""), 
            (" PARA ", " "), (" COM ", " ")
        ]
        for velho, novo in replaces:
            n = n.replace(velho, novo)
            
        n = n.replace("CACHORROS", "CÃES").replace("CACHORRO", "CÃES")
        n = n.replace("CÃES CÃES", "CÃES").replace("GATOS GATOS", "GATOS")
        
        # Adiciona "SACHÊ" no início se não existir
        if "SACHÊ" not in n and "SACHE" not in n:
            marcas_sache = ["FRISKIES", "WHISKAS", "PEDIGREE", "FANCY FEAST", "DOG CHOW", "CAT CHOW"]
            if any(m in n for m in marcas_sache) and any(a in n for a in ["GATO", "CÃO"]):
                n = "SACHÊ " + n
                
        # Deduplicação agressiva de palavras (ex: FRANGO ADULTOS FRANGO -> FRANGO ADULTOS)
        palavras = n.split()
        vistos = set()
        palavras_unicas = []
        for p in palavras:
            if p not in vistos or len(p) <= 2: # Permite conectivos como E/DE repetirem
                vistos.add(p)
                palavras_unicas.append(p)
        n = " ".join(palavras_unicas)
    
    # Limpa espaços extras deixados pelos replaces
    return re.sub(r'\s+', ' ', n).strip()

def remover_frases_duplicadas(texto: str) -> str:
    """
    Remove blocos de palavras adjacentes que se repetem em uma string.
    Funciona de forma recursiva para limpar múltiplas repetições.
    Ex: 'BISCOITO OBA BEM QUERER OBA BEM QUERER' -> 'BISCOITO OBA BEM QUERER'
    Ex: 'PNEU PNEU ARO 13 ARO 13' -> 'PNEU ARO 13'
    """
    if not isinstance(texto, str) or not texto:
        return ""

    palavras = texto.split()
    # Se for muito curto, não há o que fazer.
    if len(palavras) < 2:
        return texto

    # Itera de blocos de palavras maiores para os menores (até 1 palavra)
    for tamanho_bloco in range(len(palavras) // 2, 0, -1):
        # Itera pela lista de palavras para encontrar blocos adjacentes
        for i in range(len(palavras) - (2 * tamanho_bloco) + 1):
            bloco1 = palavras[i : i + tamanho_bloco]
            bloco2 = palavras[i + tamanho_bloco : i + (2 * tamanho_bloco)]
            
            if bloco1 == bloco2:
                del palavras[i + tamanho_bloco : i + (2 * tamanho_bloco)]
                return remover_frases_duplicadas(" ".join(palavras))
    
    return " ".join(palavras)

def validar_e_limpar_produtos(produtos, logger):
    """
    Valida uma lista de produtos, removendo itens inválidos e limpando dados.
    Um produto é considerado inválido se não tiver nome ou um preço de atacado válido.
    Esta função é um utilitário geral e não depende de pandas.
    """
    if not produtos:
        return []

    produtos_validos = []
    # Placeholders em minúsculas para comparação case-insensitive
    placeholders_comuns = ['produto indisponível', 'item não encontrado', 'carregando...']

    logger.info(f"\n🛡️  Iniciando validação e limpeza de {len(produtos)} produtos coletados...")
    
    for produto in produtos:
        nome_produto = produto.get("Produto")
        if isinstance(nome_produto, str):
            nome_produto = nome_produto.strip()
        
        # Otimização de nomes muito longos (ex: Ração Úmida -> Sachê)
        nome_produto = otimizar_nome_produto(nome_produto)
        
        # Limpeza de frases duplicadas no nome do produto
        nome_produto = remover_frases_duplicadas(nome_produto)
        
        # Padronização de Categoria
        categoria_original = produto.get("Categoria", "")
        produto["Categoria"] = padronizar_categoria(nome_produto, categoria_original)
        
        # Padronização de Subcategoria
        subcategoria_original = produto.get("subcategoria", "")
        produto["subcategoria"] = formatar_nome_categoria(subcategoria_original)
        
        # Remove a marca do final do nome do produto, se houver repetição.
        marca = produto.get("Marca")
        if isinstance(nome_produto, str) and isinstance(marca, str) and marca and marca.upper() != 'PRÓPRIA':
            if nome_produto.upper().endswith(marca.upper()):
                nome_produto = nome_produto[:-len(marca)].strip(' -')

        # Proteção Blindada: Corrige itens de Pet Shop classificados erroneamente como Açougue
        if isinstance(nome_produto, str):
            is_pet = False
            marcas_pet = ["FRISKIES", "WHISKAS", "PEDIGREE", "PURINA", "DOG CHOW", "CAT CHOW", "FANCY FEAST"]
            if any(m in nome_produto for m in marcas_pet):
                is_pet = True
            elif "RAÇÃO" in nome_produto or ("SACHÊ" in nome_produto and any(x in nome_produto for x in ["GATO", "CÃO", "CACHORRO"])):
                is_pet = True
                
            if is_pet:
                produto["Categoria"] = "Pet Shop"
                sub_atual = str(produto.get("subcategoria", "")).upper()
                tipo_atual = str(produto.get("tipo_produto", "")).upper()
                if sub_atual in ["CARNES", "AVES", "PEIXARIA", "AÇOUGUE", "N/A", "OUTROS"]:
                    produto["subcategoria"] = "CÃES E GATOS"
                if tipo_atual in ["CARNE BOVINA", "FRANGO", "PEIXE", "N/A", "OUTROS", "CARNES"]:
                    produto["tipo_produto"] = "ALIMENTO ÚMIDO" if "SACHÊ" in nome_produto else "RAÇÃO"

        # Proteção Anti-Sprite Fantasma: Corrige bebidas alcoólicas categorizadas como refrigerante
        if isinstance(nome_produto, str):
            is_alcoholic = False
            # Lista expandida para maior cobertura
            termos_alcoolicos = ["ALCOÓLICA", "VODKA", "GIN", "WHISKY", "CACHAÇA", "TEQUILA", "LICOR", "SKYY", "ABSOLUT", "SMIRNOFF", "ICE"]
            
            # Verifica nome e marca
            nome_upper = nome_produto.upper()
            marca_upper = str(marca).upper() if marca else ""

            if any(termo in nome_upper or termo in marca_upper for termo in termos_alcoolicos):
                is_alcoholic = True

            if is_alcoholic:
                # Se for alcoólico, garante que a taxonomia não seja de refrigerante
                sub_atual = str(produto.get("subcategoria", "")).upper()
                tipo_atual = str(produto.get("tipo_produto", "")).upper()
                
                # Palavras-chave que indicam erro de categoria
                termos_errados = ["REFRIGERANTE", "SPRITE", "COCA-COLA", "FANTA", "GUARANÁ"]

                if any(termo in sub_atual for termo in termos_errados):
                    logger.warning(f"Correção de taxonomia: '{nome_produto}' é alcoólico mas estava como subcategoria '{produto.get('subcategoria')}'. Resetando.")
                    produto["subcategoria"] = "Bebidas Alcoólicas"
                
                if any(termo in tipo_atual for termo in termos_errados):
                    logger.warning(f"Correção de taxonomia: '{nome_produto}' é alcoólico mas estava como tipo de produto '{produto.get('tipo_produto')}'. Resetando.")
                    produto["tipo_produto"] = "Prontas para Beber"

        # Proteção Anti-Pet Shop Falso: Corrige itens comuns categorizados como Pet Shop
        if produto.get("Categoria") == "Pet Shop" and isinstance(nome_produto, str):
            termos_nao_pet = ["REFRIGERANTE", "CERVEJA", "SUCO", "ÁGUA", "LEITE", "ARROZ", "FEIJÃO", "MACARRÃO", "SABÃO", "DETERGENTE", "SHAMPOO"]
            if any(termo in nome_produto.upper() for termo in termos_nao_pet) and not any(pet_term in nome_produto.upper() for pet_term in ["CÃES", "GATO", "PET"]):
                logger.warning(f"Correção de categoria: '{nome_produto}' estava como 'Pet Shop'. Reclassificando.")
                produto["Categoria"] = padronizar_categoria(nome_produto, "")

        preco_atacado_str = produto.get("Preço Atacado", "")
        
        # Validação do Nome e Preço (campos essenciais para a chave do DB)
        if not nome_produto or nome_produto.lower() in placeholders_comuns or clean_price_string(preco_atacado_str) <= 0:
            logger.debug(f"Descartando item inválido: Mercado='{produto.get('Mercado', 'N/A')}', Produto='{nome_produto}', Preço='{preco_atacado_str}'")
            continue
            
        produto['Produto'] = nome_produto # Garante que a versão limpa do nome seja usada
        produtos_validos.append(produto)

    logger.info(f"✅ Validação concluída: {len(produtos_validos)} de {len(produtos)} produtos são válidos e seguirão para o salvamento.")
    return produtos_validos