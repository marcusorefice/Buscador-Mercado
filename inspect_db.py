import json
import urllib.parse

with open('data/biblioteca_produtos.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

c = 0
for ean, info in data.items():
    link_imagem = info.get('link_imagem', '')
    if link_imagem and link_imagem != "SEM IMAGEM" and "http" in link_imagem:
        print(f"EAN: {ean}")
        print(f"Mercado Origin: {info.get('mercados_vistos', [''])[0]}")
        print(f"Nome Comum (Atual): {info.get('nome_comum')}")
        parsed_url = urllib.parse.urlparse(link_imagem)
        print(f"URL: {link_imagem}")
        print(f"Filename from URL: {parsed_url.path.split('/')[-1]}")
        print("-" * 40)
        c += 1
        if c >= 10: break
