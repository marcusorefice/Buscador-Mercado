"""
Remove os EANs que vieram da busca na web SEM confirmação (o bug do Yahoo/Bing/DuckDuckGo,
que pegava qualquer número da página de resultados).

  python ferramentas/limpar_eans_web_suspeitos.py             -> só mostra o que seria removido
  python ferramentas/limpar_eans_web_suspeitos.py --executar  -> faz backup e remove

O que é removido:
  - do cache da web: as buscas cujo EAN não confere com o nome procurado (mesma regra do passo 4)
  - da biblioteca e do banco (Supabase + SQLite): produtos/ofertas/histórico com esses EANs
Os itens verdadeiros voltam na próxima coleta (main.py / main_full.py -> passo 4 -> passo 5),
agora casados pelo nome ou agrupados como INT_.
"""
import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import shutil
import sqlite3
from collections import Counter
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

from utils import ler_json_seguro, salvar_json_atomico, ean_eh_valido
from casamento_produtos import CasadorProdutos, nomes_conferem

load_dotenv(os.path.join(RAIZ, ".env"))
ARQ_CACHE = os.path.join("data", "cache_buscas_web.json")
ARQ_BIBLIOTECA = os.path.join("data", "biblioteca_produtos.json")
ARQ_SQLITE = os.path.join("data", "monitoramento_Jundiai.db")

def confere(resultado, nome, marca, casador):
    """
    Só vale se a PRÓPRIA fonte devolveu o nome do produto e ele bate com o item.
    (Comparar com a biblioteca não serve aqui: a entrada pode ter sido criada a partir do
    próprio EAN falso, e aí o item sempre "confere" consigo mesmo.)
    """
    ean = str(resultado.get("ean", ""))
    if not ean_eh_valido(ean) or ean.startswith("INT_"):
        return False
    encontrado = str(resultado.get("nome_encontrado") or "")
    if encontrado and encontrado != "N/A":
        return nomes_conferem(casador, nome, marca, encontrado, resultado.get("marca_encontrada"))
    return False

def main():
    executar = "--executar" in sys.argv
    cache = ler_json_seguro(ARQ_CACHE, {})
    biblioteca = ler_json_seguro(ARQ_BIBLIOTECA, {})
    casador = CasadorProdutos(biblioteca)

    validos, rejeitados = {}, {}
    for chave, resultado in cache.items():
        nome, _, marca = chave.partition("|")
        (validos if confere(resultado, nome, marca, casador) else rejeitados)[chave] = resultado

    eans_validos = {str(r["ean"]) for r in validos.values()}
    eans_ruins = {str(r["ean"]) for r in rejeitados.values()} - eans_validos
    na_biblioteca = [e for e in eans_ruins if e in biblioteca]
    revisados = [e for e in na_biblioteca if biblioteca[e].get("revisado_humano")]

    print(f"Cache da web: {len(cache)} buscas | {len(validos)} conferem | {len(rejeitados)} serão removidas")
    print(f"  fontes removidas: {Counter(r.get('fonte') for r in rejeitados.values()).most_common()}")
    print(f"EANs suspeitos: {len(eans_ruins)} | na biblioteca: {len(na_biblioteca)} (revisados por você: {len(revisados)})")

    conn_pg = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur_pg = conn_pg.cursor()
    lista = list(eans_ruins)
    cur_pg.execute("SELECT mercado, COUNT(*) FROM ofertas_atuais WHERE ean = ANY(%s) GROUP BY 1 ORDER BY 2 DESC", (lista,))
    por_mercado = cur_pg.fetchall()
    print(f"Ofertas no Supabase com EAN suspeito: {sum(n for _, n in por_mercado)} -> {por_mercado}")

    if not executar:
        print("\n(Simulação. Rode com --executar para aplicar.)")
        return

    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy(ARQ_CACHE, f"{ARQ_CACHE}.backup-{carimbo}")
    shutil.copy(ARQ_BIBLIOTECA, f"{ARQ_BIBLIOTECA}.backup-{carimbo}")

    salvar_json_atomico(ARQ_CACHE, validos)
    for e in na_biblioteca:
        del biblioteca[e]
    salvar_json_atomico(ARQ_BIBLIOTECA, biblioteca)

    for tabela in ("ofertas_atuais", "historico_precos", "produtos"):
        cur_pg.execute(f"DELETE FROM {tabela} WHERE ean = ANY(%s)", (lista,))
        print(f"  Supabase {tabela}: {cur_pg.rowcount} linhas removidas")
    conn_pg.commit()
    conn_pg.close()

    if os.path.exists(ARQ_SQLITE):
        sl = sqlite3.connect(ARQ_SQLITE)
        sl.execute("CREATE TEMP TABLE eans_ruins (ean TEXT PRIMARY KEY)")
        sl.executemany("INSERT INTO eans_ruins VALUES (?)", [(e,) for e in lista])
        for tabela in ("ofertas_atuais", "historico_precos", "produtos"):
            n = sl.execute(f"DELETE FROM {tabela} WHERE ean IN (SELECT ean FROM eans_ruins)").rowcount
            print(f"  SQLite {tabela}: {n} linhas removidas")
        sl.commit()
        sl.close()

    print(f"\n✅ Pronto. Backups: {ARQ_CACHE}.backup-{carimbo} e {ARQ_BIBLIOTECA}.backup-{carimbo}")
    print("👉 Rode a coleta de novo (main.py ou main_full.py), depois o passo 4 e o passo 5.")

if __name__ == "__main__":
    main()
