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

# NOVO: Mapa de categorias específico para o Covabra
MAPA_DEPARTAMENTOS_COVABRA = {
    'BEBIDAS NÃO ALCOÓLICAS': 'Bebidas',
    'CARNES': 'Açougue e Peixaria',
    'HIGIENE E BELEZA': 'Higiene e Cuidado Pessoal',
    'LIMPEZA': 'Limpeza',
    'MERCEARIA': 'Mercearia e Despensa',
    'HORTIFRUTI': 'Hortifrúti',
    'FRIOS E LATICINIOS': 'Frios e Laticínios',
    'CONGELADOS': 'Congelados e Pratos Prontos'
}

MAPA_DE_PARA_SUBCATEGORIAS = {
    # Agrupando variações de Temperos
    "Temperos": "Temperos e Condimentos",
    "Temperos & Condimentos": "Temperos e Condimentos",
    "Condimentos e Temperos": "Temperos e Condimentos",
    
    # Agrupando variações de Massas
    "Massas Secas & Frescas": "Massas e Molhos",
    
    # Agrupando Iogurtes
    "Iogurtes & Fermentados": "Iogurtes e Lácteos",
    "Iogurtes e Bebidas Lácteas": "Iogurtes e Lácteos",
    "Lácteos": "Iogurtes e Lácteos",
    
    # Agrupando Limpeza
    "Limpeza de Casa": "Limpeza Geral e Banheiro",
    "Limpeza de Cozinha": "Cozinha e Utensílios",
    "Limpeza de Roupas": "Cuidado com as Roupas",

    # Mapeamentos para alinhar com ANCHOR_RULES e consolidar "subcategorias zumbis"
    "Biscoitos": "Biscoitos e Snacks",
    "Biscoitos & Snacks": "Biscoitos e Snacks",
    "Biscoitos e Bolachas": "Biscoitos e Snacks",
    "Salgadinhos e Snacks": "Biscoitos e Snacks",
    "Cafés e Achocolatados": "Cafés, Chás e Achocolatados",
    "Café, Chá e Matinais": "Cafés, Chás e Achocolatados",
    "Frutas Frescas": "Frutas",
    "Arroz, Feijão e Grãos": "Arroz e Grãos",
    "Óleos, Azeites e Vinagres": "Óleos e Azeites",
    "Enlatados e Conservas": "Conservas e Enlatados",
    "Doces e Sobremesas": "Chocolates e Doces",
    "Leites e Cremes": "Leites",
    "Carne Suína e Linguiças": "Suínos",
    "Sucos e Chás Prontos": "Sucos e Refrescos",
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
    
    # REGRA DE NEGÓCIO: A biblioteca só deve ser populada com itens que possuem um EAN válido.
    # Se não houver EAN, não criamos uma entrada. A chave da biblioteca é sempre o EAN.
    if not ean or ean == "N/A" or not ean.isdigit() or len(ean) < 12:
        return None, None

    chave_id = ean
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
# NOVO MOTOR DE TAXONOMIA GRABIT (HIERÁRQUICO)
# =======================================================================

# Categorias Master Válidas (usar um set para performance)
CATEGORIAS_MASTER = {
    "Açougue e Peixaria", "Bebidas", "Bebidas Alcoólicas", "Congelados e Pratos Prontos",
    "Frios e Laticínios", "Higiene e Cuidado Pessoal", "Limpeza", "Mercearia e Despensa",
    "Padaria e Confeitaria", "Hortifrúti", "Pet Shop", "Bebê e Infantil"
}

# NOVO: Âncoras de alta prioridade para resolver ambiguidades e forçar categorias.
# Ex: "MISTURA BOLO" deve ser Mercearia, mesmo que contenha "QUEIJO".
PRIORITY_ANCHOR_RULES = {
    "Mercearia e Despensa": ["MISTURA PARA BOLO", "MISTURA BOLO"],
    "Congelados e Pratos Prontos": ["SORVETE"],
}

# Dicionário de âncoras: palavras-chave que forçam uma categoria.
# Estrutura: { "CategoriaMaster": { "Subcategoria": [Keywords] } }
ANCHOR_RULES = {
    "Mercearia e Despensa": {
        "Arroz, Feijão e Grãos": ["ARROZ", "FEIJÃO", "LENTILHA", "GRÃO DE BICO", "GRÃOS"],
        "Massas e Molhos": ["MACARRÃO", "MASSA INSTANTÂNEA", "MASSA FRESCA", "LASANHA", "NHOQUE", "MOLHO DE TOMATE", "EXTRATO DE TOMATE", "PESTO", "MASSAS E MOLHOS", "MOLHOS"],
        "Óleos, Azeites e Vinagres": ["ÓLEO", "OLEO", "AZEITE", "VINAGRE", "OLEOS E AZEITES E VINAGRES"],
        "Cafés, Chás e Achocolatados": ["CAFÉ", "CAFE", "CHÁ", "CHA", "ACHOCOLATADO", "CAPPUCCINO", "MATINAIS"],
        "Açúcar e Adoçantes": ["AÇÚCAR", "ACUCAR", "ADOÇANTE"],
        "Condimentos e Temperos": ["MAIONESE", "KETCHUP", "MOSTARDA", "TEMPERO", "CONDIMENTO", "CALDO", "SAL"],
        "Farinhas e Misturas": ["FARINHA", "FARINHA DE TRIGO", "FARINHA DE MANDIOCA", "PIPOCA", "AVEIA", "FAROFA", "FERMENTO", "MISTURA PARA BOLO", "MISTURA BOLO", "FARINÁCEOS", "CEREAIS"],
        "Enlatados e Conservas": ["MILHO", "ERVILHA", "ATUM", "SARDINHA", "PALMITO", "AZEITONA", "ENLATADO", "CONSERVA"],
        "Biscoitos e Snacks": ["BISCOITO", "BOLACHA", "COOKIES", "WAFER", "ROSQUINHA", "BISCOITOS DOCES", "BISCOITOS SALGADOS", "SALGADINHO", "SNACK", "AMENDOIM", "CASTANHA", "BATATA PALHA", "APERITIVO"],
        "Doces e Sobremesas": ["CHOCOLATE", "BOMBOM", "BALA", "GOMA", "DOCE DE LEITE", "GOIABADA", "GELATINA", "PUDIM", "SOBREMESA", "BOMBONIERE", "COBERTURA"],
    },
    "Frios e Laticínios": {
        "Leites e Cremes": ["LEITE", "CREME DE LEITE", "LEITE CONDENSADO", "CHANTILY"],
        "Queijos": ["QUEIJO", "MUÇARELA", "MUSSARELA", "PRATO", "QUEIJO MINAS", "PARMESÃO", "RICOTA", "REQUEIJÃO", "CREAM CHEESE", "COTTAGE", "FONDUE"],
        "Iogurtes e Bebidas Lácteas": ["IOGURTE", "PETIT SUISSE", "DANONINHO", "SOBREMESA LÁCTEA", "BEBIDA LÁCTEA", "YOPRO", "FERMENTADO"],
        "Manteigas e Margarinas": ["MANTEIGA", "MARGARINA"],
        "Frios e Embutidos": ["PRESUNTO", "PEITO DE PERU", "SALAME", "MORTADELA", "SALSICHA", "EMBUTIDO", "CHARCUTARIA"],
    },
    "Açougue e Peixaria": {
        "Carne Bovina": ["CONTRA FILÉ", "ALCATRA", "PATINHO", "ACÉM", "CARNE MOÍDA", "ESPETINHO", "CARNE", "BIFE", "BOVINO", "BOVINA"],
        "Aves": ["FRANGO", "FILÉ DE FRANGO", "SOBRECOXA", "ASA", "COXINHA DA ASA"],
        "Carne Suína e Linguiças": ["LINGUIÇA", "BISTECA", "LOMBO", "BACON", "SUÍNO", "SUINA"],
        "Peixes e Frutos do Mar": ["TILÁPIA", "SALMÃO", "BACALHAU", "CAMARÃO", "PEIXE", "FRUTOS DO MAR"],
    },
    "Hortifrúti": {
        "Frutas": ["BANANA", "MAÇÃ", "MACA", "LARANJA", "MAMÃO", "UVA", "MORANGO", "PERA", "ABACAXI", "MELANCIA", "MELAO", "KIWI", "MANGA", "LIMAO"],
        "Legumes e Raízes": ["BATATA", "CEBOLA", "CENOURA", "TOMATE", "ABÓBORA", "ABOBORA", "CHUCHU", "PEPINO", "PIMENTAO", "BERINJELA", "BETERRABA", "MANDIOCA", "ALHO"],
        "Verduras e Folhas": ["ALFACE", "COUVE", "BRÓCOLIS", "BROCOLIS", "ESPINAFRE", "RUCULA", "AGRIÃO", "ACELGA"],
        "Ovos": ["OVO", "OVOS"],
    },
    "Bebidas": {
        "Refrigerantes": ["REFRIGERANTE", "COCA-COLA", "PEPSI", "GUARANÁ", "SPRITE", "FANTA"],
        "Sucos e Chás Prontos": ["SUCO", "NÉCTAR", "REFRESCO", "TODDYNHO", "NESCAU", "ÁGUA DE COCO", "AGUA DE COCO", "CHÁ GELADO", "CHA GELADO", "ICE TEA"],
        "Águas": ["ÁGUA", "AGUA", "AGUA MINERAL"],
        "Energéticos e Isotônicos": ["ENERGÉTICO", "ISOTÔNICO", "RED BULL", "MONSTER"],
    },
    "Bebidas Alcoólicas": {
        "Cervejas": ["CERVEJA", "PILSEN", "PURO MALTE", "HEINEKEN", "BRAHMA", "SKOL", "AMSTEL", "CORONA", "STELLA", "CHOPP", "BEBIDAS ALCOOLICAS"],
        "Vinhos e Espumantes": ["VINHO", "ESPUMANTE"],
        "Destilados e Drinks": ["WHISKY", "VODKA", "GIN", "CACHAÇA", "RUM", "LICOR", "CONHAQUE", "DRINK", "COQUETEL", "AGUARDENTE", "DESTILADOS"],
    },
    "Congelados e Pratos Prontos": {
        "Pratos Prontos Congelados": ["PIZZA CONGELADA", "LASANHA CONGELADA", "HAMBÚRGUER", "NUGGETS", "EMPANADO", "PÃO DE QUEIJO", "PRATO PRONTO"],
        "Sorvetes e Sobremesas Congeladas": ["PICOLÉ", "AÇAÍ", "ACAI", "POLPA DE FRUTA", "SORVETE"],
        "Legumes e Vegetais Congelados": ["BATATA PALITO", "BATATA CONGELADA", "SELETA DE LEGUMES", "MANDIOCA CONGELADA"],
    },
    "Limpeza": {
        "Limpeza de Roupas": ["SABÃO EM PÓ", "SABAO EM PO", "SABÃO LÍQUIDO", "AMACIANTE", "ALVEJANTE", "TIRA-MANCHAS", "OMO", "TIXAN", "ROUPAS"],
        "Limpeza de Cozinha": ["DETERGENTE", "DESENGORDURANTE", "ESPONJA DE AÇO", "ESPONJA DE FIBRA", "CIF", "YPÊ", "LAVA LOUÇA", "COZinha"],
        "Limpeza Geral e Banheiro": ["DESINFETANTE", "LIMPADOR MULTIUSO", "ÁLCOOL", "ALCOOL", "LIMPA-VIDROS", "VEJA", "ÁGUA SANITÁRIA", "AGUA SANITARIA", "BANHEIRO"],
        "Papéis e Descartáveis": ["PAPEL HIGIÊNICO", "PAPEL TOALHA", "GUARDANAPO", "SACO DE LIXO", "PAPÉIS", "EMBALAGENS"],
        "Inseticidas e Repelentes": ["INSETICIDA", "REPELENTE"],
    },
    "Higiene e Cuidado Pessoal": {
        "Cabelos": ["SHAMPOO", "CONDICIONADOR", "MÁSCARA DE TRATAMENTO", "MASCARA CAPILAR", "EUDORA", "CREME DE PENTEAR", "GEL FIXADOR", "CUIDADO COM CABELO"],
        "Corpo e Banho": ["SABONETE", "DESODORANTE", "HIDRATANTE", "FRANCIS", "PROTETOR SOLAR", "ÓLEO CORPORAL", "OLEO CORPORAL", "CORPO"],
        "Higiene Oral": ["CREME DENTAL", "ESCOVA DE DENTE", "ENXAGUANTE BUCAL"],
        "Barba e Depilação": ["APARELHO DE BARBEAR", "ESPUMA DE BARBEAR", "GEL DE BARBEAR", "GILLETTE"],
        "Higiene Íntima": ["ABSORVENTE", "PROTETOR DIÁRIO", "SABONETE ÍNTIMO"],
    },
    "Bebê e Infantil": {
        "Fraldas e Higiene do Bebê": ["FRALDA", "LENÇO UMEDECIDO", "POMADA PARA ASSADURA", "HASTES FLEXÍVEIS", "SHAMPOO INFANTIL", "BEBE E INFANTIL"],
        "Alimentação Infantil": ["FÓRMULA INFANTIL", "PAPINHA", "MINGAU", "CEREAL INFANTIL", "DANONINHO", "BATAVINHO"],
    },
    "Pet Shop": {
        "Alimentos para Pets": ["RAÇÃO", "PEDIGREE", "WHISKAS", "PURINA", "DOG CHOW", "CAT CHOW", "FRISKIES", "SACHÊ GATO", "SACHÊ CÃO", "PETISCO"],
        "Higiene e Cuidados Pet": ["AREIA PARA GATO", "TAPETE HIGIÊNICO", "SHAMPOO PET"],
    },
    "Padaria e Confeitaria": {
        "Pães e Bolos": ["PÃO", "BOLO", "BISNAGUINHA", "PÃO DE ALHO", "PÃES", "TORRADA", "CROSTATA"],
    }
}

# Guardas de Marca: se a marca for X, ela NUNCA pode estar na categoria Y.
BRAND_GUARDS = {
    "FLEISCHMANN": ["Limpeza"], "DR. OETKER": ["Limpeza"], "ROYAL": ["Limpeza"],
    "YOKI": ["Limpeza", "Higiene e Cuidado Pessoal"], "NESTLÉ": ["Limpeza"],
    "GAROTO": ["Limpeza"], "LACTA": ["Limpeza"],
    "SADIA": ["Limpeza", "Higiene e Cuidado Pessoal"],
    "PERDIGÃO": ["Limpeza", "Higiene e Cuidado Pessoal"],
    "SEARA": ["Limpeza", "Higiene e Cuidado Pessoal"],
}

# LISTA DE TERMOS PARA HORTIFRUTI (movido de oba.py para uso geral)
LISTA_HORTIFRUTI = [
    "ABACATE", "ABACAXI", "ABOBORA", "ABOBRINHA", "ACELGA", "AGRIÃO", "ALFACE", 
    "ALHO", "AMEIXA", "AMORA", "BANANA", "BATATA", "BERINJELA", "BETERRABA", 
    "BROCOLIS", "CEBOLA", "CENOURA", "CHUCHU", "COUVE", "ESPINAFRE", "GOIABA", 
    "KIWI", "LARANJA", "LIMAO", "MAÇÃ", "MACA", "MAMÃO", "MAMAO", "MANDIOCA", "MANGA", "MARACUJA", 
    "MELANCIA", "MELAO", "MILHO", "MORANGO", "PEPINO", "PERA", "PIMENTAO", 
    "REPOLHO", "RUCULA", "TOMATE", "UVA"
]

def normalizar_taxonomia_grabit(nome_produto, marca, categoria_mercado, subcategoria_mercado, tipo_produto_mercado, ean, biblioteca, mercado_nome=None):
    """
    Motor de categorização hierárquico para o GrabIt.
    Prioriza a biblioteca, depois regras de negócio (âncoras, guardas) e por último a categoria do site.
    """
    nome_upper = str(nome_produto).upper()
    marca_upper = str(marca).upper()
    nome_completo = f"{nome_upper} {marca_upper} {str(categoria_mercado).upper()} {str(subcategoria_mercado).upper()}"

    # 1. PRIORIDADE MÁXIMA: Biblioteca de Produtos (Fonte da Verdade)
    # Se um item já está na nossa biblioteca, sua categoria é considerada correta e não deve ser alterada.
    if ean and ean != "N/A" and ean in biblioteca:
        entrada_lib = biblioteca[ean]
        if entrada_lib.get("Categoria") in CATEGORIAS_MASTER:
            return entrada_lib.get("Categoria"), entrada_lib.get("subcategoria", "N/A"), entrada_lib.get("tipo_produto", "N/A")

    # --- Lógica de Decisão de Categoria ---
    candidate_category = None
    sub_final = subcategoria_mercado if subcategoria_mercado != "N/A" else "Geral"
    tipo_final = tipo_produto_mercado if tipo_produto_mercado != "N/A" else "Geral"

    # --- REGRAS ESPECÍFICAS DE MERCADO (Ex: Oba) ---
    if mercado_nome == "Oba Hortifruti":
        # Regra de Conservas (DAUCY): Força o tipo de produto e categoria.
        if marca_upper == 'DAUCY':
            candidate_category = 'Mercearia e Despensa'
            sub_final = 'Conservas e Enlatados'
            tipo_final = 'Conservas'
        
        # Regra de Hortifruti (Prioridade para itens sem EAN ou com 'KG')
        is_horti_keyword = any(termo in nome_upper for termo in LISTA_HORTIFRUTI) or any(k in nome_upper for k in ['IMPORTADO', 'NACIONAL', ' KG'])
        if ean == "N/A" and is_horti_keyword:
            candidate_category = 'Hortifrúti'
            if sub_final == "Geral": # Tenta refinar a subcategoria
                if any(termo in nome_upper for termo in ["BATATA", "CEBOLA", "CENOURA", "TOMATE", "ALHO", "PEPINO", "PIMENTAO", "ABOBORA", "BERINJELA"]):
                    sub_final = "Legumes"
                elif any(termo in nome_upper for termo in ["ALFACE", "COUVE", "RUCULA", "ESPINAFRE", "AGRIÃO", "ACELGA"]):
                    sub_final = "Verduras"
                else:
                    sub_final = "Frutas"

    # 2. ÂNCORAS DE ALTA PRIORIDADE: Regras que se sobrepõem a todas as outras.
    if not candidate_category:
        for categoria, keywords in PRIORITY_ANCHOR_RULES.items():
            if any(keyword in nome_upper for keyword in keywords):
                candidate_category = categoria
                break

    # 3. ÂNCORAS GERAIS: Regras de palavras-chave comuns.
    if not candidate_category:
        for categoria, sub_rules in ANCHOR_RULES.items():
            for subcategoria, keywords in sub_rules.items():
                if any(re.search(rf'\b{re.escape(keyword)}\b', nome_completo) for keyword in keywords):
                    candidate_category = categoria
                    sub_final = subcategoria
                    break 
            if candidate_category:
                break

    # 4. FALLBACK PARA CATEGORIA DO MERCADO: Se nenhuma âncora correspondeu.
    if not candidate_category:
        if mercado_nome == "Covabra":
            candidate_category = MAPA_DEPARTAMENTOS_COVABRA.get(str(categoria_mercado).upper(), formatar_nome_categoria(categoria_mercado))
        else:
            candidate_category = MAPA_PARA_APP.get(str(categoria_mercado).upper(), formatar_nome_categoria(categoria_mercado))

    # --- Lógica de Validação e Correção ---

    # 5. GUARDAS DE MARCA (BRAND GUARDS): Valida a categoria candidata contra regras da marca.
    if marca_upper in BRAND_GUARDS:
        if candidate_category in BRAND_GUARDS[marca_upper]:
            candidate_category = "Mercearia e Despensa" # Força para Mercearia se a regra for violada.

    # 6. VALIDAÇÃO FINAL: Garante que a categoria final está na lista de masters.
    if candidate_category not in CATEGORIAS_MASTER:
        candidate_category = "Mercearia e Despensa" # Fallback final para a categoria mais segura.

    # --- REGRAS ESPECÍFICAS DE SUBCATEGORIA E TIPO ---
    # Regra do Café
    if sub_final == 'Matinais' and tipo_final == 'Café':
        sub_final = 'Cafés'

    # Regra da Fralda
    if "FRALDA" in nome_upper:
        tipo_final = "Fraldas Descartáveis"

    # Aplica o mapeamento de subcategorias para padronização final
    sub_padronizada = MAPA_DE_PARA_SUBCATEGORIAS.get(sub_final, sub_final)

    return candidate_category, sub_padronizada, tipo_final

def aplicar_taxonomia_inteligente_legada(nome_produto, cat_site, sub_site, tipo_site):
    n = nome_produto.upper()
 
    # REGRAS DE CORREÇÃO PRIORITÁRIA
    # Higiene Pessoal que cai em Mercearia
    if any(p in n for p in ["SABONETE", "SABONETE LÍQUIDO", "SABONETE LIQUIDO"]) and "DETERGENTE" not in n:
        return "Higiene e Cuidado Pessoal", "Corpo", "Sabonete"
    if any(p in n for p in ["CONDICIONADOR", "SHAMPOO", "MÁSCARA CAPILAR", "MASCARA CAPILAR", "EUDORA"]):
        return "Higiene e Cuidado Pessoal", "Cabelos", "Tratamento Capilar"

    # Itens de Cozinha (Fleischmann) que caem em Limpeza/Frios
    if "FLEISCHMANN" in n and any(p in n for p in ["FERMENTO", "MISTURA"]):
        if "PÃO DE QUEIJO" in n:
            return "Mercearia e Despensa", "Farinhas e Preparos", "Mistura para Pão de Queijo"
        return "Mercearia e Despensa", "Farinhas e Preparos", "Fermentos e Misturas para Bolo"

    # Laticínios e Frios que caem em Mercearia
    if any(p in n for p in ["REQUEIJÃO", "COTTAGE", "CREAM CHEESE", "RICOTA"]):
        return "Frios e Laticínios", "Requeijão e Queijos Cremosos", "Queijo Cremoso"
    if "MARGARINA" in n:
        return "Frios e Laticínios", "Manteigas e Margarinas", "Margarina"
    if "IOGURTE" in n or "BATAVINHO" in n or "DANONINHO" in n:
        return "Frios e Laticínios", "Iogurtes", "Iogurte"
    if "QUEIJO" in n and "PÃO DE QUEIJO" not in n:
        return "Frios e Laticínios", "Queijos", "Queijo"

    # Embutidos e Carnes que caem em Mercearia
    if "LINGUIÇA" in n:
        return "Açougue e Peixaria", "Carnes Suínas e Embutidos", "Linguiça"
    if any(p in n for p in ["PRESUNTO", "MORTADELA", "SALAME", "PEITO DE PERU"]):
        return "Frios e Laticínios", "Frios e Embutidos", "Frios"

    # Sucos, Achocolatados e Energéticos
    if "ACHOCOLATADO" in n or "TODDYNHO" in n or "NESCAU" in n:
        return "Bebidas", "Achocolatados", "Achocolatado Pronto"
    if "SUCO" in n and "REFRESCO" not in n and "SUCRILHOS" not in n:
        return "Bebidas", "Sucos e Chás", "Suco Pronto"
    if "ENERGÉTICO" in n or "RED BULL" in n or "MONSTER" in n:
        return "Bebidas", "Energéticos", "Energético"
    
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
    
    # Encontra todos os possíveis padrões de medida na string
    match_objects = list(re.finditer(r'(\d+(?:[.,]\d+)?)\s*(KG|L|LTS|ML|G|UN|CAPS|FLS|POTS)\b', nome))

    if not match_objects:
        return nome, "1", "UN"

    # Filtra medidas que são provavelmente de conteúdo nutricional (ex: 15g de proteína)
    filtered_matches = []
    for m in match_objects:
        context_after = nome[m.end():m.end() + 15]
        if m.group(2) == 'G' and 'PROT' in context_after:
            continue
        filtered_matches.append(m)

    # Se a filtragem removeu todos, reverte para a lista original para não perder uma medida potencial
    if not filtered_matches:
        filtered_matches = match_objects

    # Define a prioridade das unidades: Volume > Peso > Unidades
    priority = {'L': 6, 'LTS': 6, 'ML': 5, 'KG': 4, 'G': 3}
    
    best_match = None
    best_priority = -1
    
    # Itera para encontrar a melhor correspondência com base na prioridade
    for match in filtered_matches:
        unit = match.group(2)
        current_priority = priority.get(unit, 0) # Unidades como 'UN' terão prioridade 0
        
        # Uma prioridade maior sempre vence.
        # Se a prioridade for a mesma, o que aparecer por último na string é escolhido.
        if current_priority >= best_priority:
            best_priority = current_priority
            best_match = match
    
    if best_match:
        value = best_match.group(1).replace(',', '.')
        unit = best_match.group(2)
        
        # Remove a substring da melhor correspondência do nome do produto e limpa espaços duplos
        cleaned_name = (nome[:best_match.start()] + nome[best_match.end():]).strip()
        cleaned_name = re.sub(r'\s+', ' ', cleaned_name)
        
        return cleaned_name, value, unit

    # Fallback caso algo dê errado
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
    indice_reverso_nome = {normalizar_para_cache(item.get("nome_comum", "")): item for item in biblioteca.values()}
    
    for produto in produtos:
        # Validação básica de preço
        preco_atacado_str = produto.get("Preço Atacado", "")
        if clean_price_string(preco_atacado_str) <= 0:
            continue

        ean = produto.get('EAN', 'N/A')

        # --- POLÍTICA "BIBLIOTECA PRIMEIRO" ---
        if ean and ean != "N/A" and ean in biblioteca:
            entrada_biblioteca = biblioteca[ean]
            
            # Usa dados da biblioteca para identidade e taxonomia, e dados do scraper para preço.
            produto_atualizado = {
                "Mercado": produto.get("Mercado"),
                "EAN": ean,
                "Categoria": entrada_biblioteca.get("Categoria", "OUTROS"),
                "subcategoria": entrada_biblioteca.get("subcategoria", "N/A"),
                "tipo_produto": entrada_biblioteca.get("tipo_produto", "N/A"),
                "Produto": entrada_biblioteca.get("nome_comum", produto.get("Produto")),
                "Marca": entrada_biblioteca.get("marca", produto.get("Marca")),
                "Preço Varejo": produto.get("Preço Varejo"),
                "Preço Atacado": produto.get("Preço Atacado"),
                "Qtd_Valor": produto.get("Qtd_Valor"),
                "Medida": produto.get("Medida"),
                "Unidade": produto.get("Unidade"),
                "Condição": produto.get("Condição"),
                "Data_Hora": produto.get("Data_Hora"),
                "Link_Imagem": entrada_biblioteca.get("imagem", produto.get("Link_Imagem")),
                "PRECISA_DE_IA": False
            }
            produtos_validos.append(produto_atualizado)
            continue # Produto processado, pular para o próximo

        # --- PRODUTO NOVO (NÃO ESTÁ NA BIBLIOTECA) ---
        # ETAPA 1: Otimização e Limpeza do Nome
        nome_bruto = str(produto.get("Produto", "")).strip()
        if not nome_bruto or nome_bruto.lower() in placeholders_comuns:
            continue

        # --- REGRAS DE NEGÓCIO OBA (PESÁVEIS) ---
        # Esta regra é aplicada antes da otimização do nome para usar o nome bruto.
        if produto.get("Mercado") == "Oba Hortifruti":
            # Se o nome original contém KG, força a unidade para KG e quantidade para 1.
            # Isso sobrepõe a extração de `extrair_medidas_inteligente` para garantir o preço por quilo.
            if 'KG' in nome_bruto.upper():
                produto['Unidade'] = 'KG'
                produto['Qtd_Valor'] = '1'
                produto['Medida'] = 'KG' # Garante consistência

        nome_otimizado = remover_frases_duplicadas(otimizar_nome_produto(nome_bruto))
        produto['Produto'] = nome_otimizado

        # ETAPA 2: Normalização da Taxonomia com o motor de regras
        cat_nova, sub_nova, tipo_novo = normalizar_taxonomia_grabit(
            nome_produto=nome_otimizado,
            marca=produto.get("Marca", ""),
            categoria_mercado=produto.get("Categoria", ""),
            subcategoria_mercado=produto.get("subcategoria", "N/A"),
            tipo_produto_mercado=produto.get("tipo_produto", "N/A"),
            ean=ean,
            biblioteca=biblioteca, # Passa a biblioteca para o caso de EAN não estar na chave primária
            mercado_nome=produto.get("Mercado")
        )
        produto["Categoria"], produto["subcategoria"], produto["tipo_produto"] = cat_nova, sub_nova, tipo_novo
        produto["PRECISA_DE_IA"] = False

        # ETAPA 3: Finalização e adição à lista
        produtos_validos.append(produto)

    logger.info(f"✅ Validação GrabIt concluída: {len(produtos_validos)} produtos processados com nova taxonomia.")
    return produtos_validos