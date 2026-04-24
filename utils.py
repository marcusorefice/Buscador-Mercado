import re
import json
import logging
import os
from datetime import datetime
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

# --- 4. MAPA DE CATEGORIAS DA VTEX PARA O APP ---
MAPA_PARA_APP = {
    "MERCEARIA": "Mercearia e Despensa", "ALIMENTOS": "Mercearia e Despensa",
    "PADARIA E MATINAIS": "Laticínios, Ovos e Matinais", "LATICÍNIOS": "Laticínios, Ovos e Matinais",
    "CONGELADOS": "Congelados e Pratos Prontos", "AÇOUGUE": "Açougue e Peixaria",
    "HORTIFRÚTI": "Hortifrúti", "BEBIDAS": "Bebidas", "LIMPEZA": "Limpeza",
    "HIGIENE E PERFUMARIA": "Higiene e Cuidado Pessoal", "PET SHOP": "Pet Shop",
    "N/A": "Mercearia e Despensa"
}

CATEGORIAS_IGNORADAS = {"AUTOMOTIVO", "JARDINAGEM", "ESPORTE E LAZER", "VESTUÁRIO", "CAFETERIA"}

def normalizar_para_cache(nome):
    """Função movida do classificador_ia para evitar dependência circular."""
    if not nome: return ""
    nfkd = unicodedata.normalize('NFKD', str(nome).lower()).encode('ascii', 'ignore').decode('ascii')
    texto = re.sub(r'\d+(?:[.,]\d+)?\s*(KG|G|ML|L|UN|M|POTS|GR)', '', nfkd, flags=re.IGNORECASE)
    return " ".join(re.sub(r'[^a-z0-9\s]', '', texto).split())

def criar_entrada_biblioteca(p_info):
    """Cria uma entrada padronizada para a biblioteca de produtos a partir de um dicionário de produto validado."""
    nome_produto = p_info.get("Produto", "")
    ean = p_info.get("EAN", "N/A")
    
    chave_id = ean if ean and ean != "N/A" else normalizar_para_cache(nome_produto)
    if not chave_id: return None, None # Não pode criar entrada sem chave

    marca = p_info.get("Marca", "")
    categoria = p_info.get("Categoria", "OUTROS")
    
    full_text = f"{nome_produto} {categoria} {marca}".lower()
    tags_text = unicodedata.normalize('NFKD', full_text).encode('ascii', 'ignore').decode('ascii')
    tags = sorted(list(set(re.findall(r'\b[a-z0-9]{3,}\b', tags_text))))
    
    entrada = {
        "id": chave_id, 
        "nome_comum": nome_produto, 
        "marca": marca, 
        "ean": ean,
        "Categoria": categoria, 
        "subcategoria": p_info.get("subcategoria", "N/A"),
        "tipo_produto": p_info.get("tipo_produto", "N/A"),
        "imagem": p_info.get("Link_Imagem", "SEM IMAGEM"), 
        "tags": tags
    }
    return chave_id, entrada

# =======================================================================
# AUDITOR DE ANOMALIAS (Identifica bizarrices para mandar pra IA)
# =======================================================================
def auditar_anomalias_categoria(nome, categoria, subcategoria):
    n, c, s = str(nome).upper(), str(categoria).upper(), str(subcategoria).upper()
    
    # Lista de bizarrices que disparam a necessidade de IA
    if "LÁCTEOS" in s and c == "CONGELADOS E PRATOS PRONTOS": return True
    if any(x in n for x in ["WHEY", "YOPRO", "BEBIDA LÁCTEA"]) and c == "CONGELADOS E PRATOS PRONTOS": return True
    if "BEBIDA" in s and c == "MERCEARIA E DESPENSA": return True
    if "LIMPEZA" in c and any(x in n for x in ["ARROZ", "FEIJÃO", "CARNE", "LEITE"]): return True
    if "AÇOUGUE" in c and any(x in n for x in ["SHAMPOO", "SABÃO", "DETERGENTE"]): return True
    
    return False

# =======================================================================
# TAXONOMIA INTELIGENTE 2.0 (Filtros Atacadão)
# =======================================================================
def aplicar_taxonomia_inteligente(nome_produto, cat_site, sub_site, tipo_site):
    n = nome_produto.upper()
    
    # 1. CORREÇÃO DE BEBIDAS 
    if any(re.search(rf'\b{p}\b', n) for p in ["COCA-COLA", "COCA", "PEPSI", "GUARANÁ", "SPRITE", "FANTA", "ITUBAÍNA", "SCHIN", "SCHWEPPES"]):
        tipo_refri = "Refrigerante Sem Açúcar" if "ZERO" in n or "SEM AÇÚCAR" in n else "Refrigerante Cola"
        return "Bebidas", "Refrigerantes", tipo_refri
        
    if "ÁGUA MINERAL" in n or "ÁGUA COM GÁS" in n or "ÁGUA SEM GÁS" in n:
        return "Bebidas", "Água", "Água Mineral"

    # 2. CORREÇÃO DE ÁLCOOL 
    if any(re.search(rf'\b{p}\b', n) for p in ["HEINEKEN", "AMSTEL", "BRAHMA", "SKOL", "CERVEJA", "CORONA", "STELLA"]):
        return "Bebidas Alcoólicas", "Cervejas", "Cerveja Pilsen/Lager"
        
    if "VINHO" in n and "VINAGRE" not in n:
        return "Bebidas Alcoólicas", "Vinhos", "Vinho"

    # 3. ENLATADOS NA PEIXARIA
    if cat_site == "Açougue e Peixaria":
        if any(p in n for p in ["ATUM", "SARDINHA"]) and any(p in n for p in ["RALADO", "SÓLIDO", "NATURAL", "ÓLEO", "TOMATE"]):
            return "Mercearia e Despensa", "Enlatados e Conservas", "Peixes em Conserva"

    # 4. FALSOS HORTIFRÚTIS 
    if cat_site == "Hortifrúti":
        if any(p in n for p in ["BATATA PALHA", "SOPA", "BARRA", "BISCOITO", "CHOCOLATE", "GELATINA"]):
            return "Mercearia e Despensa", "Snacks e Doces", "Industrializados"
        if any(p in n for p in ["BEBIDA", "CHÁ", "SUCO", "REFRESCO", "ADES", "MUPY", "ICE TEA"]):
            return "Bebidas", "Sucos e Chás", "Prontos para Beber"

    # 5. CORREÇÃO DE PET SHOP
    termos_pet = ["WHISKAS", "PEDIGREE", "FRISKIES", "PURINA", "DOG CHOW", "CAT CHOW"]
    if any(p in n for p in termos_pet) or ("RAÇÃO" in n) or ("SACHÊ" in n and ("GATO" in n or "CÃO" in n)):
        return "Pet Shop", "Cães e Gatos", "Alimento para Pets"

    # 6. CORREÇÃO OMO E SABÃO
    if "OMO" in n or "TIXAN" in n or "SABÃO EM PÓ" in n or "SABAO EM PO" in n:
        return "Limpeza", "Roupas", "Sabão em Pó"

    # =======================================================================
    # NOVAS REGRAS: DESCARTÁVEIS E ORGANIZAÇÃO (Tira da Mercearia)
    # =======================================================================
    
    # 7. SACO DE LIXO -> Limpeza
    if "SACO" in n and "LIXO" in n:
        return "Limpeza", "Organização e Limpeza", "Saco de Lixo"

    # 8. SACOS DE FREEZER / FILME PVC / ALUMÍNIO -> Bazar e Utilidades
    if any(p in n for p in ["SACO PLÁSTICO", "FREEZER", "FILME PVC", "PAPEL ALUMÍNIO", "ASSADEIRA DESCARTÁVEL"]):
        if "LIXO" not in n: # Garante que não confunda com o lixo da regra acima
            return "Bazar e utilidades", "Descartáveis", "Embalagens e Utilidades"

    return cat_site, sub_site, tipo_site

# =======================================================================
# FUNÇÃO LEGADA (Para outros scrapers: Boa, Pão de Açúcar, etc)
# =======================================================================
def padronizar_categoria(nome, cat_site=""):
    n, c = str(nome).upper(), str(cat_site).upper()
    regras = {
        "Pet Shop": ["RAÇÃO", "GATO", "CACHORRO", "PET"],
        "Bebidas": ["ÁGUA", "REFRIGERANTE", "COCA", "GUARANÁ", "CERVEJA", "VINHO", "SUCO"],
        "Mercearia e Despensa": ["ARROZ", "FEIJÃO", "CAFÉ", "AÇÚCAR", "ÓLEO", "AZEITE", "MACARRÃO"],
        "Limpeza": ["DETERGENTE", "SABÃO", "OMO", "TIXAN", "VEJA", "YPÊ", "AMACIANTE"]
    }
    for cat, termos in regras.items():
        if any(t in n for t in termos) or any(t in c for t in termos): return cat
    return "Mercearia e Despensa"

def formatar_nome_categoria(texto: str) -> str:
    if not isinstance(texto, str) or not texto or texto.upper() == "N/A": return "N/A"
    texto_limpo = texto.replace('-', ' ').replace('_', ' ').strip()
    palavras = texto_limpo.lower().split()
    palavras_a_ignorar = ['e', 'de', 'da', 'do', 'dos', 'das', 'a', 'o', 'as', 'os']
    return " ".join([p if p in palavras_a_ignorar else p.capitalize() for p in palavras])

def extrair_medidas_inteligente(nome_produto):
    nome = str(nome_produto).upper()
    match = re.search(r'(\d+(?:[\.,]\d+)?)\s*(G|KG|ML|L|LTS|UN|CAPS|FLS|POTS)\b', nome)
    if match: return nome.replace(match.group(0), "").strip(), match.group(1).replace(',', '.'), match.group(2)
    return nome, "1", "UN"

def otimizar_nome_produto(nome: str) -> str:
    if not isinstance(nome, str): return nome
    n = re.sub(r'[®©™\xae\u2122\u00a9]', '', nome.upper())
    termos_pet = ["RAÇÃO", "ÚMID", "SACHÊ", "SACHE", "GATO", "CÃO", "CÃES", "CACHORRO", "FRISKIES", "PURINA", "WHISKAS"]
    if any(t in n for t in termos_pet):
        replaces = [("RAÇÃO ÚMIDA PARA", ""), ("RAÇÃO ÚMIDA", ""), ("NESTLÉ PURINA", ""), ("NESTLÉ", ""), ("PURINA", ""), (" PARA ", " "), (" COM ", " ")]
        for velho, novo in replaces: n = n.replace(velho, novo)
        n = n.replace("CACHORROS", "CÃES").replace("CACHORRO", "CÃES")
        if "SACHÊ" not in n and "SACHE" not in n: n = "SACHÊ " + n
        palavras, vistos, unicas = n.split(), set(), []
        for p in palavras:
            if p not in vistos or len(p) <= 2:
                vistos.add(p); unicas.append(p)
        n = " ".join(unicas)
    return re.sub(r'\s+', ' ', n).strip()

def remover_frases_duplicadas(texto: str) -> str:
    if not isinstance(texto, str) or not texto: return ""
    palavras = texto.split()
    if len(palavras) < 2: return texto
    for tamanho_bloco in range(len(palavras) // 2, 0, -1):
        for i in range(len(palavras) - (2 * tamanho_bloco) + 1):
            if palavras[i : i + tamanho_bloco] == palavras[i + tamanho_bloco : i + (2 * tamanho_bloco)]:
                del palavras[i + tamanho_bloco : i + (2 * tamanho_bloco)]
                return remover_frases_duplicadas(" ".join(palavras))
    return " ".join(palavras)

def validar_e_limpar_produtos(produtos, logger, biblioteca):
    if not produtos: return []
    produtos_validos = []
    placeholders_comuns = ['produto indisponível', 'item não encontrado', 'carregando...']
    
    for produto in produtos:
        # --- ETAPA DE ENRIQUECIMENTO PELA BIBLIOTECA ---
        # Antes de qualquer validação, tentamos enriquecer o produto com dados da biblioteca.
        chave_ean = produto.get('EAN')
        chave_nome = normalizar_para_cache(produto.get('Produto'))
        
        entrada_biblioteca = None
        if chave_ean and chave_ean != "N/A" and chave_ean in biblioteca:
            entrada_biblioteca = biblioteca[chave_ean]
        elif chave_nome in biblioteca:
            entrada_biblioteca = biblioteca[chave_nome]

        if entrada_biblioteca:
            # Preenche a imagem se estiver faltando no scraper atual
            if not produto.get('Link_Imagem') or produto.get('Link_Imagem') == 'SEM IMAGEM':
                produto['Link_Imagem'] = entrada_biblioteca.get('imagem', 'SEM IMAGEM')

            # Preenche a marca se estiver faltando ou for genérica
            if not produto.get('Marca') or produto.get('Marca') == 'OUTROS':
                produto['Marca'] = entrada_biblioteca.get('marca', 'OUTROS')
            
            # Pré-aplica a taxonomia da biblioteca, que é a fonte mais confiável
            produto['Categoria'] = entrada_biblioteca.get('Categoria', produto.get('Categoria'))
            produto['subcategoria'] = entrada_biblioteca.get('subcategoria', produto.get('subcategoria'))
            produto['tipo_produto'] = entrada_biblioteca.get('tipo_produto', produto.get('tipo_produto'))

        nome_produto = str(produto.get("Produto", "")).strip()
        nome_produto = remover_frases_duplicadas(otimizar_nome_produto(nome_produto))
        marca = str(produto.get("Marca", "")).strip()
        
        # Proteção para nomes como "Água de Coco Quadrado"
        if marca and marca.upper() != 'PRÓPRIA' and nome_produto.upper().endswith(marca.upper()):
            nome_teste = nome_produto[:-len(marca)].strip(' -')
            if not nome_teste.upper().endswith((' DE', ' COM', ' SEM', ' EM', ' E', ' PARA')) and len(nome_teste) > 3:
                nome_produto = nome_teste

        cat_site_crua = str(produto.get("Categoria", "")).upper()
        if not cat_site_crua: cat_site_crua = "MERCEARIA"

        cat_site = MAPA_PARA_APP.get(cat_site_crua, formatar_nome_categoria(cat_site_crua))
        sub_site = formatar_nome_categoria(produto.get("subcategoria", ""))
        tipo_site = formatar_nome_categoria(produto.get("tipo_produto", ""))

        cat_nova, sub_nova, tipo_novo = aplicar_taxonomia_inteligente(nome_produto, cat_site, sub_site, tipo_site)

        produto["Categoria"], produto["subcategoria"], produto["tipo_produto"] = cat_nova, sub_nova, tipo_novo
        
        # Auditoria Automática
        produto["PRECISA_DE_IA"] = auditar_anomalias_categoria(nome_produto, cat_nova, sub_nova)

        preco_atacado_str = produto.get("Preço Atacado", "")
        if not nome_produto or nome_produto.lower() in placeholders_comuns or clean_price_string(preco_atacado_str) <= 0:
            continue
            
        produto['Produto'] = nome_produto
        produtos_validos.append(produto)

    logger.info(f"✅ Validação concluída: {len(produtos_validos)} produtos processados.")
    return produtos_validos