"""
Revisão humana dos casamentos de nomes (a sua "base confiável").

  python revisar_casamentos.py              -> importa as decisões (S/N) das planilhas para data/casamentos.json
  python revisar_casamentos.py duplicatas   -> gera data/revisao_duplicatas.xlsx com EANs que parecem o mesmo produto

Fluxo:
  1. O passo 4 gera data/revisao_casamentos.xlsx com os casamentos duvidosos.
  2. Você preenche a coluna DECISÃO com S (é o mesmo produto) ou N (não é).
  3. Na próxima vez que rodar o passo 4 (ou este script), as decisões vão para data/casamentos.json
     e passam a valer para sempre, em todos os mercados.
"""
import os
import sys
import logging

from utils import ler_json_seguro, salvar_json_atomico, read_json_file
from casamento_produtos import CasadorProdutos, sugerir_duplicatas, CASAMENTOS_VAZIO

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ARQUIVO_CASAMENTOS = os.path.join(DATA_DIR, "casamentos.json")
ARQUIVO_BIBLIOTECA = os.path.join(DATA_DIR, "biblioteca_produtos.json")
ARQUIVO_REVISAO = os.path.join(DATA_DIR, "revisao_casamentos.xlsx")
ARQUIVO_DUPLICATAS = os.path.join(DATA_DIR, "revisao_duplicatas.xlsx")

COLUNA_DECISAO = "DECISÃO (S/N)"
COLUNA_CHAVE = "chave (não alterar)"
MAX_DUPLICATAS = 3000

def carregar_casamentos():
    dados = ler_json_seguro(ARQUIVO_CASAMENTOS, {})
    for chave, vazio in CASAMENTOS_VAZIO.items():
        dados.setdefault(chave, type(vazio)())
    return dados

def _ler_planilha(caminho):
    import pandas as pd
    if not os.path.exists(caminho):
        return None
    return pd.read_excel(caminho, dtype=str).fillna("")

def _salvar_planilha(linhas, caminho, colunas):
    import pandas as pd
    if not linhas:
        if os.path.exists(caminho):
            os.remove(caminho)
        return
    df = pd.DataFrame(linhas, columns=colunas)
    tmp = caminho + ".tmp.xlsx"
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Revisão")
        planilha = writer.sheets["Revisão"]
        for i, col in enumerate(colunas, 1):
            largura = 14 if col in (COLUNA_DECISAO, "Pontuação") else 45
            planilha.column_dimensions[planilha.cell(1, i).column_letter].width = largura
        planilha.freeze_panes = "A2"
    os.replace(tmp, caminho)

def _decisao(valor):
    v = str(valor).strip().upper()
    if v in ("S", "SIM", "Y", "1", "X"): return "S"
    if v in ("N", "NAO", "NÃO", "0"): return "N"
    return ""

def importar_decisoes():
    """Lê as planilhas, grava as decisões em data/casamentos.json e deixa nas planilhas só o que falta decidir."""
    casamentos = carregar_casamentos()
    total = 0

    df = _ler_planilha(ARQUIVO_REVISAO)
    if df is not None and COLUNA_DECISAO in df.columns:
        pendentes = []
        for linha in df.to_dict("records"):
            decisao, chave, ean = _decisao(linha.get(COLUNA_DECISAO)), linha.get(COLUNA_CHAVE), str(linha.get("EAN sugerido", "")).strip()
            if not decisao or not chave or not ean:
                pendentes.append(linha)
                continue
            if decisao == "S":
                casamentos["confirmados"][chave] = ean
            else:
                rejeitados = casamentos["rejeitados"].setdefault(chave, [])
                if ean not in rejeitados:
                    rejeitados.append(ean)
            total += 1
        _salvar_planilha(pendentes, ARQUIVO_REVISAO, list(df.columns))

    df = _ler_planilha(ARQUIVO_DUPLICATAS)
    if df is not None and COLUNA_DECISAO in df.columns:
        pendentes = []
        for linha in df.to_dict("records"):
            decisao, a, b = _decisao(linha.get(COLUNA_DECISAO)), str(linha.get("EAN A", "")).strip(), str(linha.get("EAN B", "")).strip()
            if not decisao or not a or not b:
                pendentes.append(linha)
                continue
            if decisao == "S":
                casamentos["equivalentes"][b] = a
            elif [a, b] not in casamentos["nao_equivalentes"]:
                casamentos["nao_equivalentes"].append([a, b])
            total += 1
        _salvar_planilha(pendentes, ARQUIVO_DUPLICATAS, list(df.columns))

    if total:
        salvar_json_atomico(ARQUIVO_CASAMENTOS, casamentos)
        logger.info(f"📝 {total} decisões de revisão importadas para '{ARQUIVO_CASAMENTOS}'.")
    return total

def exportar_sugestoes(sugestoes):
    """sugestoes: lista de dicts com Mercado, Nome no mercado, Marca, EAN sugerido, Nome na biblioteca, Pontuação, chave."""
    colunas = ["Mercado", "Nome no mercado", "Marca", "EAN sugerido", "Nome na biblioteca", "Pontuação", COLUNA_DECISAO, COLUNA_CHAVE]
    linhas = []
    for s in sorted(sugestoes, key=lambda x: -x["Pontuação"]):
        linhas.append({**{c: s.get(c, "") for c in colunas}, COLUNA_DECISAO: "", COLUNA_CHAVE: s["chave"]})
    _salvar_planilha(linhas, ARQUIVO_REVISAO, colunas)
    return len(linhas)

def gerar_planilha_duplicatas():
    biblioteca = read_json_file(ARQUIVO_BIBLIOTECA, {})
    casamentos = carregar_casamentos()
    resolvidos = [list(p) for p in casamentos["nao_equivalentes"]] + [[b, a] for b, a in casamentos["equivalentes"].items()]
    logger.info(f"🔎 Procurando produtos repetidos entre {len(biblioteca)} itens da biblioteca (pode levar 1-2 minutos)...")
    casador = CasadorProdutos(biblioteca, casamentos)
    pares = sugerir_duplicatas(casador, resolvidos)[:MAX_DUPLICATAS]
    colunas = ["EAN A", "Nome A", "EAN B", "Nome B", "Pontuação", COLUNA_DECISAO]
    linhas = [{
        "EAN A": a, "Nome A": biblioteca[a].get("nome_comum", ""),
        "EAN B": b, "Nome B": biblioteca[b].get("nome_comum", ""),
        "Pontuação": score, COLUNA_DECISAO: "",
    } for a, b, score in pares]
    _salvar_planilha(linhas, ARQUIVO_DUPLICATAS, colunas)
    logger.info(f"✅ {len(linhas)} pares para revisar em '{ARQUIVO_DUPLICATAS}'. Marque S/N e rode 'python revisar_casamentos.py'.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "duplicatas":
        importar_decisoes()
        gerar_planilha_duplicatas()
    else:
        n = importar_decisoes()
        if not n:
            logger.info("Nenhuma decisão nova encontrada nas planilhas.")
