"""
Casamento de produtos pelo nome (sem IA e sem APIs).

Cada mercado escreve o nome do mesmo produto de um jeito diferente, e alguns não mandam EAN.
Este módulo transforma o nome em uma "assinatura" (marca + medida + pack + palavras-chave)
e compara com a biblioteca para descobrir qual produto é.

Resultados possíveis para um item sem EAN:
  - "confirmado": você já disse que esse nome é esse EAN (data/casamentos.json)
  - "auto":       confiança alta e sem empate -> usa o EAN direto
  - "revisao":    parecido, mas não o bastante -> vai para a planilha de revisão
  - None:         nenhum candidato -> o item vira (ou entra) num grupo INT_ com outros
                  mercados que vendem o mesmo produto sem EAN
"""
import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict

# ==========================================
# NORMALIZAÇÃO DE NOMES (também usada pelo passo 4 na higienização do lote)
# ==========================================

def padronizar_multiplicacao(texto):
    # Garante caixa alta, remove espaços extras e mantém ponto decimal limpo
    texto = str(texto).upper().replace("\xa0", " ").replace(",", ".")

    # Padrão Clássico (ex: 10X5.2, 3X90G, 300/190ML)
    padrao_x = r"(\d+)\s*[X/]\s*(\d+\.?\d*)\s*(G|KG|ML|L|UN)?"
    def replacer_x(match):
        qtd = float(match.group(1))
        peso_unitario = float(match.group(2))
        unidade = match.group(3) if match.group(3) else "G"
        if "/" in match.group(0):
            return f"{int(qtd)}{unidade} {int(peso_unitario)}{unidade}"
        peso_total = qtd * peso_unitario
        return f"{int(peso_total) if peso_total.is_integer() else peso_total}{unidade} {int(qtd)}UN"
    texto = re.sub(padrao_x, replacer_x, texto)

    # Padrão Descritivo Comercial (ex: "10 UNIDADES 8G CADA", "10 UN 11G CADA")
    padrao_cada = r"(\d+)\s*(?:UN|UNID|UNIDADES|SACHES|CAPSULA|CAPSULAS)?\s*(?:DE)?\s*(\d+\.?\d*)\s*(G|KG|ML|L)\s*CADA"
    def replacer_cada(match):
        qtd = float(match.group(1))
        peso_unitario = float(match.group(2))
        unidade = match.group(3)
        peso_total = qtd * peso_unitario
        return f"{int(peso_total) if peso_total.is_integer() else peso_total}{unidade} {int(qtd)}UN"
    texto = re.sub(padrao_cada, replacer_cada, texto)

    return texto

def normalizar_sinonimos(texto):
    texto = str(texto).upper()
    substituicoes = {
        r"\bUNIDADES\b": "UN", r"\bUNIDADE\b": "UN", r"\bUNID\b": "UN", r"\bSACHÊS\b": "UN", r"\bSACHES\b": "UN",
        r"\bCÁPSULA\b": "CAPSULA", r"\bCÁPSULAS\b": "CAPSULA", r"\bKIT\b": "PACK", r"\bMUÇARELA\b": "MUSSARELA",
        r"\bMUCSSARELA\b": "MUSSARELA", r"\bMACARRÃO\b": "MASSA", r"\bMASSA ITALIANA\b": "MASSA", r"\bFETTUCINE\b": "FETTUCCINE",
        r"\bLIMÃO\b": "LIMAO", r"\bMAÇÃ\b": "MACA", r"\bAÇÚCAR\b": "ACUCAR", r"\bCAFÉ\b": "CAFE", r"\bCAFÊ\b": "CAFE",
        r"\bCAFA\b": "CAFE", r"\bCHÁ\b": "CHA", r"\bFRALDAS\b": "FRALDA", r"\bPCTS\b": "PCT", r"\bPACOTES\b": "PCT",
        r"\bPACOTE\b": "PCT", r"\bCAIXAS\b": "CX", r"\bCAIXA\b": "CX", r"\bTETRA PAK\b": "CX", r"\bTETRAPAK\b": "CX",
        r"\bLITRO\b": "L", r"\bLITROS\b": "L", r"\bBEBIDA EM CÁPSULAS\b": "CAFE EM CAPSULA",
        r"\bCHOCOLATE QUENTE EM CÁPSULA\b": "CAFE EM CAPSULA", r"\bMOCHACCINO EM CÁPSULA\b": "CAFE EM CAPSULA"
    }
    for padrao, substituto in substituicoes.items():
        texto = re.sub(padrao, substituto, texto)
    return texto

def sem_acentos(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c))

# Marcas que na verdade são setores/categorias (não ajudam a identificar o produto)
MARCAS_GENERICAS = {
    "", "N/A", "NA", "NONE", "OUTROS", "OUTRAS", "PROPRIA", "MARCA PROPRIA", "GERAL", "GENERICO", "GENERICA",
    "HORTIFRUTI", "HORTIFRUTTI", "FEIRA", "ACOUGUE", "PADARIA", "PEIXARIA", "FRIOS", "ROTISSERIE", "SEM MARCA",
}

# Palavras que não ajudam a diferenciar produtos
STOPWORDS = {
    "DE", "DA", "DO", "DAS", "DOS", "E", "EM", "COM", "C", "SEM", "PARA", "P", "A", "O", "AS", "OS", "NA", "NO",
    "AO", "UN", "UND", "UNID", "UNIDADE", "UNIDADES", "PCT", "PACOTE", "CX", "CAIXA", "EMB", "EMBALAGEM",
    "TIPO", "SABOR", "NOVO", "NOVA", "LEVE", "PAGUE", "OFERTA", "PROMOCAO",
    "UNITARIO", "GRANEL", "APROX", "APROXIMADAMENTE", "KG", "G", "ML", "L", "VD", "PET", "FRASCO", "POTE",
    "SACHE", "SACO", "TUBO", "BISNAGA", "VIDRO", "PACK", "MAIS", "MENOS", "MENO", "POR", "LV", "PG", "GRATIS",
    "DESCONTO", "ECONOMICO", "ECONOMICA", "PROMOCIONAL", "ESPECIAL",
}

# Promoções escritas no nome ("LEVE 4 PAGUE 3", "LEVE MAIS PAGUE MENOS", "LV+ PG-")
RE_PROMO = re.compile(r"LEVE\s*\d+\s*PAGUE\s*\d+|LV\s*\d+\s*PG\s*\d+|LEVE\s+MAIS\s+PAGUE\s+MENOS|LV\s*\+\s*PG\s*-|\d+\s*%\s*(?:DE\s+)?(?:DESCONTO|GRATIS|OFF)")

# Abreviações comuns -> forma completa
ABREVIACOES = {
    "BDJ": "BANDEJA", "BJ": "BANDEJA", "REFRIG": "REFRIGERANTE", "REFRI": "REFRIGERANTE", "CERV": "CERVEJA",
    "BISC": "BISCOITO", "CHOC": "CHOCOLATE", "LEIT": "LEITE", "DESN": "DESNATADO", "SEMIDESN": "SEMIDESNATADO",
    "INTEG": "INTEGRAL", "TRAD": "TRADICIONAL", "MUCARELA": "MUSSARELA", "MUZZARELLA": "MUSSARELA",
    "LONGNECK": "LONG_NECK", "LN": "LONG_NECK", "S/LACTOSE": "ZERO_LACTOSE", "LAC": "LACTOSE",
    "DET": "DETERGENTE", "AMAC": "AMACIANTE", "SAB": "SABAO", "LIQ": "LIQUIDO", "PO": "PO",
    "DESCAF": "DESCAFEINADO", "ORG": "ORGANICO", "TEMP": "TEMPERADO", "CONG": "CONGELADO",
}

# Atributos que mudam o produto: se um nome tem e o outro não, NÃO é o mesmo produto
ATRIBUTOS_OBRIGATORIOS = {"ZERO", "DIET", "LIGHT", "ZERO_LACTOSE", "DESCAFEINADO", "ZERO_ALCOOL", "ZERO_ACUCAR", "INTEGRAL"}
# Grupos de atributos que se excluem: se os dois nomes têm um do grupo, tem que ser o mesmo
GRUPOS_EXCLUSIVOS = [
    {"LATA", "GARRAFA", "LONG_NECK"},
    {"INTEGRAL", "DESNATADO", "SEMIDESNATADO"},
    {"PO", "LIQUIDO", "GEL", "BARRA", "CAPSULA"},
    {"REFIL"},
]

UNIDADES_MEDIDA = {
    "ML": ("ml", 1), "L": ("ml", 1000), "LT": ("ml", 1000), "LTS": ("ml", 1000), "LITRO": ("ml", 1000), "LITROS": ("ml", 1000),
    "G": ("g", 1), "GR": ("g", 1), "GRS": ("g", 1), "GRAMA": ("g", 1), "GRAMAS": ("g", 1),
    "KG": ("g", 1000), "KGS": ("g", 1000), "KILO": ("g", 1000), "KILOS": ("g", 1000), "QUILO": ("g", 1000),
    "MG": ("g", 0.001), "M": ("m", 1), "MT": ("m", 1), "MTS": ("m", 1), "METROS": ("m", 1), "CM": ("m", 0.01),
}
RE_MEDIDA = re.compile(r"(?<![A-Z0-9])(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(UNIDADES_MEDIDA, key=len, reverse=True)) + r")(?![A-Z])")
RE_PACK = re.compile(
    r"(?<![A-Z0-9])(?:C/|COM|CX|PCT|PACK|PACOTE|LEVE|FARDO|FD)?\s*(\d+)\s*"
    r"(?:UN|UND|UNID|UNIDADES?|ROLOS?|SACHES?|SACH|CAPSULAS?|CAPS|LATAS?|GARRAFAS?|FRALDAS?|TABLETES?|PCS?|PECAS?|SAQUINHOS?|ENVELOPES?|BARRAS?)(?![A-Z])"
)
RE_PACK_X = re.compile(r"(?<![A-Z0-9])(\d+)\s*X(?![A-Z])|(?<![A-Z0-9])X\s*(\d+)(?![A-Z0-9])")

def eh_obrigatorio(token):
    return token in ATRIBUTOS_OBRIGATORIOS or token.startswith("SEM_")

def normalizar_marca(marca):
    m = re.sub(r"[^A-Z0-9 ]", " ", sem_acentos(str(marca or "")).upper())
    m = re.sub(r"\s+", " ", m).strip()
    return None if m in MARCAS_GENERICAS else m

def _singular(palavra):
    if len(palavra) > 4 and palavra.endswith("S") and not palavra.endswith("SS"):
        if palavra.endswith("OES"): return palavra[:-3] + "AO"
        if palavra.endswith("AES"): return palavra[:-3] + "AO"
        if palavra.endswith("IS") and len(palavra) > 5: return palavra[:-2] + "L"
        return palavra[:-1]
    return palavra

class Assinatura:
    """Representação comparável de um nome de produto."""
    __slots__ = ("marca", "medida", "pack", "tokens", "atributos", "chave", "palavras")

    def __init__(self, nome, marca=None):
        texto = sem_acentos(padronizar_multiplicacao(normalizar_sinonimos(str(nome))))
        texto = texto.upper().replace(",", ".")
        texto = RE_PROMO.sub(" ", texto)
        texto = re.sub(r"S/\s*LACTOSE|SEM\s+LACTOSE|ZERO\s+LACTOSE|0\s*LACTOSE", " ZERO_LACTOSE ", texto)
        texto = re.sub(r"ZERO\s+ALCOOL|SEM\s+ALCOOL|0\.0\b", " ZERO_ALCOOL ", texto)
        texto = re.sub(r"ZERO\s+ACUCAR|SEM\s+ACUCAR|0\s*ACUCAR", " ZERO_ACUCAR ", texto)
        texto = re.sub(r"LONG\s*NECK", " LONG_NECK ", texto)
        # "SEM PIMENTA", "SEM SAL"... viram um atributo único (SEM_PIMENTA), que precisa bater dos dois lados
        texto = re.sub(r"\b(?:SEM|S/)\s+([A-Z]{3,})", r" SEM_\1 ", texto)

        self.marca = normalizar_marca(marca)

        # Medida principal (peso/volume/comprimento), normalizada para g / ml / m
        medidas = []
        for valor, unidade in RE_MEDIDA.findall(texto):
            base, fator = UNIDADES_MEDIDA[unidade]
            medidas.append((base, round(float(valor) * fator, 2)))
        prioridade = {"ml": 0, "g": 1, "m": 2}
        medidas.sort(key=lambda m: prioridade[m[0]])
        self.medida = medidas[0] if medidas else None
        texto = RE_MEDIDA.sub(" ", texto)

        # Quantidade do pack (só conta se > 1)
        packs = [int(n) for n in RE_PACK.findall(texto)]
        packs += [int(a or b) for a, b in RE_PACK_X.findall(texto)]
        packs = [p for p in packs if p > 1]
        self.pack = max(packs) if packs else None
        texto = RE_PACK.sub(" ", texto)
        texto = RE_PACK_X.sub(" ", texto)

        palavras = re.findall(r"[A-Z0-9_]+", re.sub(r"[^A-Z0-9_ ]", " ", texto))
        self.palavras = frozenset(palavras)
        palavras_marca = set(re.findall(r"[A-Z0-9]+", self.marca)) if self.marca else set()
        tokens = set()
        for p in palavras:
            p = ABREVIACOES.get(p, p)
            p = _singular(p)
            # Números soltos ficam (ex: filtro Nº 102 x 103), exceto zeros à esquerda e o '1' de 'TIPO 1'
            if p.isdigit():
                p = p.lstrip('0') or '0'
            if p in STOPWORDS or (len(p) < 2 and not p.isdigit()) or p in palavras_marca:
                continue
            tokens.add(p)
        self.atributos = {t for t in tokens if eh_obrigatorio(t) or any(t in g for g in GRUPOS_EXCLUSIVOS)}
        self.tokens = frozenset(tokens)
        medida_txt = f"{self.medida[1]:g}{self.medida[0]}" if self.medida else "-"
        self.chave = f"{self.marca or '-'}|{' '.join(sorted(self.tokens))}|{medida_txt}|{self.pack or 1}"

def compativel(a: Assinatura, b: Assinatura):
    """Regras rígidas. Retorna (ok, motivo)."""
    if a.marca and b.marca and a.marca != b.marca:
        ma, mb = a.marca.replace(" ", ""), b.marca.replace(" ", "")
        # Aceita marca x fabricante quando a marca de um aparece no nome do outro (OMO x UNILEVER, KIT KAT x NESTLE)
        marca_a_no_b = set(a.marca.split()) <= b.palavras or ma in "".join(sorted(b.palavras))
        marca_b_no_a = set(b.marca.split()) <= a.palavras or mb in "".join(sorted(a.palavras))
        if ma not in mb and mb not in ma and not marca_a_no_b and not marca_b_no_a:
            return False, "marca diferente"
    if (a.medida is None) != (b.medida is None):
        return False, "só um tem medida"
    if a.medida and b.medida:
        if a.medida[0] != b.medida[0]:
            return False, "tipo de medida diferente"
        maior, menor = max(a.medida[1], b.medida[1]), min(a.medida[1], b.medida[1])
        if menor <= 0 or maior / menor > 1.02:
            return False, "medida diferente"
    if (a.pack or 1) != (b.pack or 1):
        return False, "pack diferente"
    if {t for t in a.atributos if eh_obrigatorio(t)} != {t for t in b.atributos if eh_obrigatorio(t)}:
        return False, "atributo (zero/diet/light/integral...) diferente"
    for grupo in GRUPOS_EXCLUSIVOS:
        ga, gb = a.atributos & grupo, b.atributos & grupo
        if ga and gb and ga != gb:
            return False, "embalagem/tipo diferente"
    return True, ""

# ==========================================
# CASADOR
# ==========================================

LIMIAR_AUTO = 0.80        # a partir daqui casa sozinho (se não houver empate)
LIMIAR_REVISAO = 0.55     # entre os dois limiares vai para a planilha de revisão
MARGEM_EMPATE = 0.10      # o 1º precisa ganhar do 2º por pelo menos isso

class CasadorProdutos:
    def __init__(self, biblioteca, casamentos_humanos=None):
        """
        biblioteca: {ean: {"nome_comum", "marca", ...}} (inclui INT_ e variantes)
        casamentos_humanos: {"confirmados": {chave: ean}, "rejeitados": {chave: [ean, ...]}}
        """
        humanos = casamentos_humanos or {}
        self.confirmados = dict(humanos.get("confirmados", {}))
        self.rejeitados = {k: set(v) for k, v in humanos.get("rejeitados", {}).items()}
        self.assinaturas = {}
        self.indice = defaultdict(set)   # token -> eans
        self.df = Counter()              # em quantos produtos cada token aparece
        self.grupos_internos = {}        # chave -> INT_ id (grupos criados nesta rodada)
        for ean, info in biblioteca.items():
            self.adicionar(ean, info.get("nome_comum", ""), info.get("marca"), info.get("assinatura_origem"))

    def adicionar(self, ean, nome, marca, nome_origem=None):
        if ean in self.assinaturas:
            return
        a = Assinatura(nome_origem or nome, marca)
        if not a.tokens:
            return
        self.assinaturas[ean] = a
        for t in a.tokens:
            self.indice[t].add(ean)
            self.df[t] += 1
        if ean.startswith("INT_"):
            self.grupos_internos.setdefault(a.chave, ean)

    def _idf(self, token):
        return math.log((len(self.assinaturas) + 1) / (self.df.get(token, 0) + 1)) + 1

    def pontuar(self, a: Assinatura, b: Assinatura):
        comuns = a.tokens & b.tokens
        if not comuns:
            return 0.0
        peso = lambda ts: sum(self._idf(t) for t in ts)
        p_comum, p_a, p_b = peso(comuns), peso(a.tokens), peso(b.tokens)
        sobreposicao = p_comum / min(p_a, p_b)          # um nome "contido" no outro
        jaccard = p_comum / peso(a.tokens | b.tokens)   # penaliza palavras sobrando
        score = 0.4 * sobreposicao + 0.6 * jaccard
        # Palavra rara que só um dos nomes tem (ex: OREO, NECTARINA, CHURRASCO) indica outra variação
        sobra = a.tokens ^ b.tokens
        if sobra:
            idf_max = max(self._idf(t) for t in sobra)
            score -= 0.3 * max(0.0, idf_max - 6) / 6
        if not (a.marca and b.marca):
            score *= 0.9  # sem marca dos dois lados, exige mais das palavras
        return round(score, 3)

    def candidatos(self, a: Assinatura, incluir_internos=False, limite=5):
        # Busca só produtos que compartilham alguma palavra "rara" com o nome
        tokens_raros = sorted(a.tokens, key=lambda t: self.df.get(t, 0))[:4]
        vistos = set()
        for t in tokens_raros:
            vistos |= self.indice.get(t, set())
        resultado = []
        for ean in vistos:
            if not incluir_internos and ean.startswith("INT_"):
                continue
            b = self.assinaturas[ean]
            ok, _ = compativel(a, b)
            if not ok or ean in self.rejeitados.get(a.chave, ()):
                continue
            score = self.pontuar(a, b)
            if score >= LIMIAR_REVISAO:
                resultado.append((score, ean))
        resultado.sort(key=lambda x: (-x[0], x[1]))
        return resultado[:limite]

    def casar(self, nome, marca):
        """
        Retorna dict {"ean", "tipo": confirmado|auto|revisao, "score", "alternativas"} ou None.
        Só casa com produtos que têm EAN de verdade (INT_ fica para agrupar_interno).
        """
        a = Assinatura(nome, marca)
        if a.chave in self.confirmados:
            return {"ean": self.confirmados[a.chave], "tipo": "confirmado", "score": 1.0, "alternativas": [], "chave": a.chave}
        if not a.tokens:
            return None
        cands = self.candidatos(a)
        if not cands:
            return None
        melhor_score, melhor_ean = cands[0]
        segundo = cands[1][0] if len(cands) > 1 else 0.0
        empate = (melhor_score - segundo) < MARGEM_EMPATE and cands[1][1] != melhor_ean
        tipo = "auto" if melhor_score >= LIMIAR_AUTO and not empate else "revisao"
        return {"ean": melhor_ean, "tipo": tipo, "score": melhor_score, "alternativas": cands[1:], "chave": a.chave}

    def agrupar_interno(self, nome, marca):
        """
        Para itens sem EAN e sem casamento: devolve o ID INT_ do grupo.
        O mesmo produto vindo de mercados diferentes cai no mesmo grupo.
        """
        a = Assinatura(nome, marca)
        if a.chave in self.grupos_internos:
            return self.grupos_internos[a.chave]
        # Tenta um grupo INT_ parecido (ex: "TOMATE ITALIANO BDJ 500G" x "TOMATE ITALIANO 500G BANDEJA")
        for score, ean in self.candidatos(a, incluir_internos=True):
            if ean.startswith("INT_") and score >= LIMIAR_AUTO:
                self.grupos_internos[a.chave] = ean
                return ean
        novo_id = gerar_id_interno(a)
        self.grupos_internos[a.chave] = novo_id
        self.assinaturas[novo_id] = a
        for t in a.tokens:
            self.indice[t].add(novo_id)
            self.df[t] += 1
        return novo_id

LIMIAR_CONFERENCIA = 0.60  # para conferir um EAN vindo de fora (web/cache) contra o nome do item

def nomes_conferem(casador: CasadorProdutos, nome_item, marca_item, nome_ref, marca_ref, limiar=LIMIAR_CONFERENCIA):
    """
    O nome de referência (biblioteca, Open Food Facts, Cosmos) descreve o mesmo produto do item?
    Se a referência não informa medida/pack (comum no Open Food Facts), isso não conta como diferença;
    marca, sabor e atributos (zero, lata, integral...) continuam sendo exigidos.
    """
    a, b = Assinatura(nome_item, marca_item), Assinatura(nome_ref, marca_ref)
    if not a.tokens or not b.tokens:
        return False
    if b.medida is None:
        b.medida = a.medida
    if b.pack is None:
        b.pack = a.pack
    ok, _ = compativel(a, b)
    return ok and casador.pontuar(a, b) >= limiar

def gerar_id_interno(a: Assinatura):
    """ID estável e legível: o mesmo nome gera sempre o mesmo ID em todas as rodadas."""
    medida = f"{a.medida[1]:g}{a.medida[0].upper()}" if a.medida else ""
    partes = [a.marca.replace(" ", "") if a.marca else "GENERICO"] + sorted(a.tokens)[:6] + ([medida] if medida else [])
    if a.pack: partes.append(f"{a.pack}UN")
    legivel = re.sub(r"[^A-Z0-9_]", "", "_".join(partes))[:55]
    sufixo = hashlib.sha1(a.chave.encode("utf-8")).hexdigest()[:6].upper()
    return f"INT_{legivel}_{sufixo}"


# ==========================================
# EQUIVALÊNCIAS: o mesmo produto cadastrado com mais de um EAN
# ==========================================

def _eh_ean_real(ean):
    return not ean.startswith("INT_") and "_" not in ean

def equivalencias_automaticas(casador: CasadorProdutos, nao_equivalentes=()):
    """
    EANs cuja assinatura é IDÊNTICA (mesma marca, palavras, medida e pack) são o mesmo produto.
    Retorna {ean_secundario: ean_principal}. O principal é o menor EAN do grupo (estável entre rodadas).
    """
    bloqueados = {frozenset(par) for par in nao_equivalentes}
    grupos = defaultdict(list)
    for ean, a in casador.assinaturas.items():
        if _eh_ean_real(ean):
            grupos[a.chave].append(ean)
    mapa = {}
    for eans in grupos.values():
        if len(eans) < 2:
            continue
        eans.sort()
        principal = eans[0]
        for outro in eans[1:]:
            if frozenset((principal, outro)) not in bloqueados:
                mapa[outro] = principal
    return mapa

def sugerir_duplicatas(casador: CasadorProdutos, ja_resolvidos=()):
    """Pares de EANs muito parecidos (mas não idênticos) para revisão humana."""
    resolvidos = {frozenset(par) for par in ja_resolvidos}
    sugestoes = {}
    for ean, a in casador.assinaturas.items():
        if not _eh_ean_real(ean):
            continue
        for score, outro in casador.candidatos(a, limite=3):
            if outro == ean or not _eh_ean_real(outro) or score < LIMIAR_AUTO:
                continue
            par = frozenset((ean, outro))
            if par in resolvidos or casador.assinaturas[outro].chave == a.chave:
                continue
            sugestoes[par] = max(score, sugestoes.get(par, 0))
    return sorted(((min(p), max(p), s) for p, s in sugestoes.items()), key=lambda x: -x[2])

def montar_equivalencias(casador: CasadorProdutos, casamentos_humanos):
    """Junta as equivalências automáticas com as decisões humanas (que têm prioridade)."""
    humanos = casamentos_humanos or {}
    mapa = equivalencias_automaticas(casador, humanos.get("nao_equivalentes", []))
    mapa.update(humanos.get("equivalentes", {}))
    # Resolve cadeias (A->B, B->C vira A->C) e evita ciclos
    resolvido = {}
    for ean in mapa:
        atual, vistos = ean, set()
        while atual in mapa and atual not in vistos:
            vistos.add(atual)
            atual = mapa[atual]
        if atual != ean:
            resolvido[ean] = atual
    return resolvido

CASAMENTOS_VAZIO = {"confirmados": {}, "rejeitados": {}, "equivalentes": {}, "nao_equivalentes": []}
