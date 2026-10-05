import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import json
import os
import re
from urllib.parse import unquote

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")

def format_title_case(text):
    if not text: return text
    # Palavras a serem ignoradas na capitalização
    ignore_words = {'e', 'de', 'da', 'do', 'das', 'dos', 'com', 'sem', 'para', 'ou', 'em'}
    words = str(text).lower().split()
    capitalized_words = [word.capitalize() if word not in ignore_words or i == 0 else word for i, word in enumerate(words)]
    return " ".join(capitalized_words)

def clean_logistics_noise(text):
    if not text: return text
    # Remove termos como Kg, Un, C/4
    patterns_to_remove = [
        r'\bkg\b', r'\bg\b', r'\bml\b', r'\bl\b', r'\blts\b',
        r'\bun\b', r'\bunid\b', r'\bpc\b', r'\bpct\b', r'\bpacote\b', r'\blata\b', r'\bgarrafa\b',
        r'\bc/\s*\d+\b', r'\bcx\b', r'\bfd\b', r'\bdisplay\b',
        r'\bgratis\b', r'\bgrátis\b', r'\bpromo\b', r'\boferta\b'
    ]
    cleaned = text
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    # Remove hífens sobrando e espaços duplos
    cleaned = re.sub(r'-\s*-', '-', cleaned)
    cleaned = re.sub(r'^\s*-\s*', '', cleaned)
    cleaned = re.sub(r'\s*-\s*$', '', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()

def fix_product_names():
    if not os.path.exists(BIBLIOTECA_FILE):
        print(f"Erro: Arquivo '{BIBLIOTECA_FILE}' não encontrado.")
        return

    with open(BIBLIOTECA_FILE, 'r', encoding='utf-8') as f:
        biblioteca = json.load(f)

    if not biblioteca:
        print("A biblioteca está vazia.")
        return

    items_corrected = 0

    for chave, item in biblioteca.items():
        if not isinstance(item, dict): continue

        nome_comum = str(item.get("nome_comum", "")).strip()
        marca = str(item.get("marca", "")).strip()
        tipo_produto = str(item.get("tipo_produto", "")).strip()
        imagem_url = str(item.get("imagem", ""))

        nome_lower = nome_comum.lower()
        marca_lower = marca.lower()
        tipo_lower = tipo_produto.lower()

        is_poor_name = False
        words_in_name = len(nome_lower.split())

        # 1. Identificação de Nomes Pobres
        # Nome é só a marca
        if nome_lower == marca_lower and marca_lower != "":
            is_poor_name = True
        # Nome tem a marca e muito pouca coisa a mais (ex: "Perdigão" ou "Toddy 1kg")
        elif marca_lower != "" and len(nome_lower.replace(marca_lower, "").strip()) < 4: 
            is_poor_name = True
        # Nome tem apenas 1 ou 2 palavras no total e não é uma exceção conhecida
        elif words_in_name <= 2 and tipo_lower not in ["n/a", "geral", "outros", ""]:
            is_poor_name = True

        novo_nome = nome_comum

        # Tenta extrair da URL da imagem do São Vicente primeiro (pois é o mais preciso)
        extracted_from_url = False
        if "svicente.com" in imagem_url and "/Produtos/" in imagem_url:
            match = re.search(r'/Produtos/\d+-(?:\d+-)?(.+?)-[^-]+-\d+\.jpg', imagem_url, re.IGNORECASE)
            if match:
                nome_da_url = unquote(match.group(1)).replace('-', ' ').strip()
                if nome_da_url and len(nome_da_url) > len(nome_comum):
                    novo_nome = nome_da_url
                    extracted_from_url = True
                    is_poor_name = False # Já resolvemos o problema do nome pobre

        # Se ainda for nome pobre e não extraiu da URL, reconstrói usando [Tipo] + [Marca]
        if is_poor_name and not extracted_from_url:
            if tipo_produto and tipo_produto.lower() not in ["n/a", "geral", "outros", ""]:
                if marca:
                    novo_nome = f"{tipo_produto} {marca}"
                else:
                    novo_nome = tipo_produto

        # Limpeza e Padronização
        nome_limpo = clean_logistics_noise(novo_nome)
        nome_formatado = format_title_case(nome_limpo)

        # Atualiza apenas se houve mudança
        if nome_formatado and nome_formatado != nome_comum:
            item["nome_comum"] = nome_formatado
            items_corrected += 1

    # Salvar o arquivo corrigido
    with open(BIBLIOTECA_FILE, 'w', encoding='utf-8') as f:
        json.dump(biblioteca, f, indent=4, ensure_ascii=False)

    print(f"Processo concluído! {items_corrected} nomes de produtos foram corrigidos e padronizados.")

if __name__ == "__main__":
    fix_product_names()
