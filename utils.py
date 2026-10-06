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
class ArquivoCorrompidoError(Exception):
    """O arquivo existe mas não é um JSON válido. Nunca deve ser tratado como 'vazio'."""

def ler_json_seguro(filepath, default_value=None):
    """
    Retorna default_value apenas se o arquivo NÃO existir.
    Se o arquivo existir e estiver corrompido, levanta ArquivoCorrompidoError
    (para o pipeline abortar em vez de sobrescrever dados bons com uma lista vazia).
    """
    if default_value is None: default_value = {}
    if not os.path.exists(filepath): return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ArquivoCorrompidoError(f"Arquivo JSON corrompido: {filepath} ({e})") from e

def read_json_file(filepath, default_value=None):
    if default_value is None: default_value = {}
    try:
        return ler_json_seguro(filepath, default_value)
    except (ArquivoCorrompidoError, OSError) as e:
        logging.getLogger(__name__).error(f"❌ Falha ao ler {filepath}: {e}")
        return default_value

def salvar_json_atomico(filepath, data, indent=4):
    """
    Grava em um arquivo temporário e só depois substitui o original (os.replace é atômico).
    Se o processo cair no meio da gravação, o arquivo original continua intacto.
    """
    pasta = os.path.dirname(filepath)
    if pasta: os.makedirs(pasta, exist_ok=True)
    tmp_path = f"{filepath}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, filepath)

def write_json_file(filepath, data):
    try:
        salvar_json_atomico(filepath, data)
        return True
    except Exception as e:
        logging.getLogger(__name__).error(f"❌ Falha ao gravar {filepath}: {e}")
        return False

# --- 3. Limpeza de Preço ---
def parse_preco(valor):
    """
    Converte qualquer representação de preço para float.
    Aceita: 12.5, "R$ 12,50", "1.234,56", "1234,56", "12.99", "1,234.56".
    Retorna 0.0 se não conseguir interpretar.
    """
    if valor is None or isinstance(valor, bool): return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    s = str(valor).upper().replace('R$', '').replace('\xa0', '').replace(' ', '').strip()
    if s in ("", "N/A", "NONE", "NAN"): return 0.0
    if ',' in s and '.' in s:
        # O separador que aparece por último é o decimal
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')   # 1.234,56
        else:
            s = s.replace(',', '')                     # 1,234.56
    elif ',' in s:
        s = s.replace(',', '.')                        # 12,50
    elif s.count('.') > 1:
        s = s.replace('.', '')                         # 1.234.567
    try: return float(s)
    except ValueError: return 0.0


def normalizar_data_iso(valor):
    """
    Converte 'dd/mm/AAAA HH:MM:SS' (formato dos scrapers) para 'AAAA-MM-DD HH:MM:SS',
    que ordena corretamente como texto no banco. Valores já em ISO passam direto.
    """
    from datetime import datetime
    if not valor: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s = str(valor).strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return s

# --- 4. CATEGORIAS MASTER (necessárias apenas se a IA classificar algo novo) ---
CATEGORIAS_MASTER = [
    "Açougue e Peixaria", "Bebidas", "Bebidas Alcoólicas", "Bebê e Infantil",
    "Congelados e Pratos Prontos", "Frios e Laticínios", "Higiene e Cuidado Pessoal",
    "Hortifrúti", "Limpeza", "Mercearia e Despensa", "Padaria e Confeitaria", "Pet Shop", "Bazar e Utilidades"
]


def normalizar_para_cache(nome):
    if not nome: return ""
    return str(nome).strip()


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

def ean_e_valido(ean_str):
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


# --- Cache do EAN lido na página de cada produto (PDP) ---
class CacheEanPdp:
    """
    O EAN de um produto não muda, então o que foi lido na página dele fica guardado entre coletas
    (um arquivo por mercado, porque os mercados rodam em paralelo). Páginas sem EAN são tentadas
    de novo depois de alguns dias.
    """
    DIAS_PARA_TENTAR_DE_NOVO = 7

    def __init__(self, mercado):
        from datetime import date
        slug = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", mercado).encode("ascii", "ignore").decode().lower()).strip("_")
        self.caminho = os.path.join("data", f"cache_ean_pdp_{slug}.json")
        self.dados = read_json_file(self.caminho, {})
        self.hoje = date.today()

    def buscar(self, link):
        """EAN guardado, 'N/A' se a página foi lida há pouco e não tinha EAN, ou None se precisa ler a página."""
        from datetime import date
        if not link or link not in self.dados:
            return None
        entrada = self.dados[link]
        if entrada.get("ean") not in (None, "", "N/A"):
            return entrada["ean"]
        try:
            idade = (self.hoje - date.fromisoformat(entrada.get("data", ""))).days
        except ValueError:
            return None
        return "N/A" if idade < self.DIAS_PARA_TENTAR_DE_NOVO else None

    def guardar(self, link, ean):
        if link:
            self.dados[link] = {"ean": ean or "N/A", "data": self.hoje.isoformat()}

    def salvar(self):
        write_json_file(self.caminho, self.dados)
