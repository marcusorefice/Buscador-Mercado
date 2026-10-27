"""Extrai do nome do produto quanto ele pesa ou rende, para mostrar o preço por kg ou por litro.

O banco guarda quase tudo como "1 UN"; o volume só existe no nome ("Leite Integral 1l", "Cerveja Heineken
Lata com 12 Un 350ml"). Na dúvida (pack sem quantidade clara, vários pesos diferentes) devolve None: é
melhor não mostrar o preço por kg do que mostrar um valor errado.
"""
import re

# número + unidade de peso/volume ("350ml", "1,5 l", "2 kg", "500 g")
_RE_MEDIDA = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(kg|kgs|g|gr|grs|mg|ml|l|lt|lts|litro|litros)(?![a-z])", re.I)
# "12 x 350ml", "6x80g"
_RE_MULTIPLICADO = re.compile(r"(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|l|lt|litro|litros)(?![a-z])", re.I)
# quantidade de unidades: "com 12 un", "12 und", "c/ 6 unidades", "12 un."
_RE_UNIDADES = re.compile(r"(?<![\w.,])(\d+)\s*(?:un|und|unid|unids|unidade|unidades)\b", re.I)
# Produtos em que "por kg" ou "por litro" não faz sentido (o 50l do saco de lixo é o tamanho do saco, não o conteúdo)
_RE_SEM_PRECO_UNITARIO = re.compile(
    r"(saco|sacos|lixo|caderno|guardanapo|tapete|papel|folhas|bateria|pilha|cola|adesivo|super bonder)", re.I)
# Fora dessa faixa (em kg ou L) o valor é quase certamente erro de leitura do nome
_MIN_QUANTIDADE, _MAX_QUANTIDADE = 0.01, 20
_RE_PACK = re.compile(r"\b(pack|kit|fardo|combo|caixa com|cx com|c/)\b|\bcom \d+\b", re.I)

# unidade -> (fator para kg ou L, unidade de referência)
_FATORES = {
    "kg": (1, "kg"), "kgs": (1, "kg"), "g": (0.001, "kg"), "gr": (0.001, "kg"), "grs": (0.001, "kg"), "mg": (0.000001, "kg"),
    "l": (1, "L"), "lt": (1, "L"), "lts": (1, "L"), "litro": (1, "L"), "litros": (1, "L"), "ml": (0.001, "L"),
}


def _numero(texto):
    return float(texto.replace(",", "."))


def quantidade_base(nome):
    """(quantidade em kg ou L, "kg" ou "L") do produto inteiro, ou None se não der para ter certeza."""
    if not nome:
        return None
    nome = str(nome)

    m = _RE_MULTIPLICADO.search(nome)
    if m:
        fator, ref = _FATORES[m.group(3).lower()]
        return int(m.group(1)) * _numero(m.group(2)) * fator, ref

    medidas = [(_numero(v), u.lower()) for v, u in _RE_MEDIDA.findall(nome)]
    if not medidas:
        return None
    unidades = [int(n) for n in _RE_UNIDADES.findall(nome) if int(n) > 1]
    refs = {_FATORES[u][1] for _, u in medidas}
    if len(refs) != 1:
        return None  # mistura peso e volume (ex: "shampoo 350ml + sabonete 85g")

    if len(medidas) == 1:
        valor, unidade = medidas[0]
        fator, ref = _FATORES[unidade]
        total = valor * fator
        if unidades:
            if len(unidades) > 1:
                return None
            total *= unidades[0]  # "com 12 Un 350ml": cada unidade tem 350ml
        elif _RE_PACK.search(nome):
            return None  # "Pack ... 85g" sem dizer quantas: não dá para saber se 85g é cada um ou o total
        return total, ref

    # Vários pesos: só vale se o maior for exatamente "N unidades x menor" ("6 Un de 80g - 480g")
    totais = sorted({round(v * _FATORES[u][0], 6) for v, u in medidas})
    if len(unidades) == 1 and len(totais) == 2 and abs(totais[0] * unidades[0] - totais[1]) < 1e-6:
        return totais[1], next(iter(refs))
    return None


def preco_por_unidade(preco, nome):
    """(preço por kg ou L, "kg" ou "L") ou None."""
    if not nome or _RE_SEM_PRECO_UNITARIO.search(str(nome)):
        return None
    base = quantidade_base(nome)
    if not base or not preco or preco <= 0:
        return None
    quantidade, ref = base
    if not (_MIN_QUANTIDADE <= quantidade <= _MAX_QUANTIDADE):
        return None
    return round(preco / quantidade, 2), ref
