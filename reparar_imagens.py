"""Repara fotos de produtos que não carregam mais.

Os sites dos mercados trocam/apagam imagens; a biblioteca guarda a URL de quando o produto foi visto
pela primeira vez, então com o tempo parte das fotos vira "Imagem indisponível" no app (o Atacadão era o
pior caso: ~3 de cada 4). Este script:
  1. testa a foto atual de cada produto que está à venda;
  2. para as que não carregam, abre a página do produto nos outros mercados (link_pdp das ofertas) e pega a
     foto de lá (og:image / JSON-LD), conferindo se ela realmente carrega;
  3. grava a foto nova na biblioteca (com backup) e na tabela produtos.

Por padrão só simula e mostra o resultado. Para gravar:  python reparar_imagens.py --aplicar
Para testar numa amostra:                              python reparar_imagens.py --amostra 100
"""
import argparse
import concurrent.futures as cf
import html
import json
import os
import random
import re
import shutil
import sys
from datetime import datetime
from urllib.parse import urljoin

import psycopg2
from curl_cffi import requests as http
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
BIBLIOTECA_PATH = os.path.join(BASE, "data", "biblioteca_produtos.json")
THREADS = 24
TIMEOUT = 15

# Mercados com foto mais estável primeiro; o Atacadão (o que mais perde imagem) fica por último
ORDEM_MERCADOS = ["Covabra", "Dom Olivio", "Boa Supermercados", "Carrefour", "Oba Hortifruti",
                  "Pão de Açúcar", "São Vicente", "Atacadão"]

RE_OG_IMAGE = re.compile(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
RE_OG_IMAGE_2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']', re.I)
RE_JSONLD_IMAGE = re.compile(r'"image"\s*:\s*\[?\s*(?:\{[^{}]*?"url"\s*:\s*)?"(https?:[^"]+)"', re.I)


def imagem_carrega(url):
    """True se a URL devolve uma imagem de verdade (200 e mais que alguns bytes)."""
    if not url or not url.startswith("http"):
        return False
    try:
        r = http.get(url, timeout=TIMEOUT, impersonate="chrome120", allow_redirects=True)
        tipo = r.headers.get("content-type", "")
        return r.status_code == 200 and len(r.content) > 500 and ("image" in tipo or "octet" in tipo)
    except Exception:
        return False


def imagem_da_pagina(link):
    """Foto principal da página do produto, ou None."""
    try:
        r = http.get(link, timeout=TIMEOUT, impersonate="chrome120", allow_redirects=True)
        if r.status_code != 200:
            return None
        texto = r.text
    except Exception:
        return None
    for regex in (RE_OG_IMAGE, RE_OG_IMAGE_2, RE_JSONLD_IMAGE):
        m = regex.search(texto)
        if m:
            return urljoin(link, html.unescape(m.group(1)))
    return None


def reparar_produto(args):
    ean, atual, links = args
    if imagem_carrega(atual):
        return ean, "ok", None
    for mercado, link in links:
        nova = imagem_da_pagina(link)
        if nova and imagem_carrega(nova):
            return ean, "reparada", (nova, mercado)
    return ean, "sem_solucao", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="grava a biblioteca e o banco (padrão: só simula)")
    ap.add_argument("--amostra", type=int, default=0, help="testa só N produtos (sorteados)")
    args = ap.parse_args()

    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("""
        SELECT p.ean, p.imagem, o.mercado, o.link_pdp
        FROM produtos p JOIN ofertas_atuais o ON o.ean = p.ean
        WHERE p.imagem LIKE 'http%%' AND o.link_pdp LIKE 'http%%'
    """)
    por_ean = {}
    for ean, imagem, mercado, link in cur.fetchall():
        item = por_ean.setdefault(ean, [imagem, []])
        item[1].append((mercado, link))

    def prioridade(par):
        try:
            return ORDEM_MERCADOS.index(par[0])
        except ValueError:
            return len(ORDEM_MERCADOS)

    tarefas = [(ean, img, sorted(links, key=prioridade)) for ean, (img, links) in por_ean.items()]
    random.shuffle(tarefas)
    if args.amostra:
        tarefas = tarefas[:args.amostra]
    print(f"Testando {len(tarefas)} produtos...", flush=True)

    resultados = {"ok": 0, "reparada": 0, "sem_solucao": 0}
    novas = {}
    por_mercado = {}
    with cf.ThreadPoolExecutor(THREADS) as ex:
        for i, (ean, estado, nova) in enumerate(ex.map(reparar_produto, tarefas), 1):
            resultados[estado] += 1
            if nova:
                novas[ean] = nova[0]
                por_mercado[nova[1]] = por_mercado.get(nova[1], 0) + 1
            if i % 500 == 0:
                print(f"  {i}/{len(tarefas)}  {resultados}", flush=True)

    print("\nResultado:", resultados)
    print("Fotos novas vindas de:", por_mercado)
    if not args.aplicar:
        print("Simulação: nada foi gravado. Use --aplicar para gravar.")
        return
    if not novas:
        print("Nada a gravar.")
        return

    # Biblioteca (fonte da verdade do passo 5; sem isso a próxima atualização do banco volta a foto quebrada)
    backup = f"{BIBLIOTECA_PATH}.backup-{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copy2(BIBLIOTECA_PATH, backup)
    with open(BIBLIOTECA_PATH, encoding="utf-8") as f:
        biblioteca = json.load(f)
    alteradas = 0
    for ean, url in novas.items():
        if ean in biblioteca:
            biblioteca[ean]["imagem"] = url
            alteradas += 1
    tmp = BIBLIOTECA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(biblioteca, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BIBLIOTECA_PATH)

    cur.executemany("UPDATE produtos SET imagem = %s WHERE ean = %s", [(url, ean) for ean, url in novas.items()])
    conn.commit()
    print(f"Gravado: {alteradas} na biblioteca (backup em {backup}) e {len(novas)} no banco.")


if __name__ == "__main__":
    sys.exit(main())
