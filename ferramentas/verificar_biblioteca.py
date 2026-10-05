import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import json
import re

caminho_json = r"d:\Mercado\data\biblioteca_produtos.json"
caminho_teste = r"d:\Mercado\test_taxonomia_todas.py"

# 1. Carregar a biblioteca JSON
with open(caminho_json, 'r', encoding='utf-8') as f:
    biblioteca = json.load(f)

# Criar um dicionário para busca rápida com variações (nome e marca)
produtos_biblioteca = {}
for v in biblioteca.values():
    nome_lib = v.get("nome_comum", "").strip().lower()
    marca_lib = v.get("marca", "").strip().lower()
    produtos_biblioteca[nome_lib] = v
    produtos_biblioteca[f"{nome_lib} {marca_lib}"] = v
    produtos_biblioteca[f"{marca_lib} {nome_lib}"] = v

def encontrar_produto(nome_teste, produtos_lib):
    nome_teste = nome_teste.strip().lower()
    if nome_teste in produtos_lib: return produtos_lib[nome_teste]
    nome_sem_peso = re.sub(r'\s*\d+\s*(kg|g|ml|l|unidades|unid\.?|un)\b', '', nome_teste).strip()
    if nome_sem_peso in produtos_lib: return produtos_lib[nome_sem_peso]
    for n_lib, prod in produtos_lib.items():
        if len(nome_sem_peso) > 5 and nome_sem_peso in n_lib: return prod
    return None

# 2. Analisar o arquivo de teste
with open(caminho_teste, 'r', encoding='utf-8') as f:
    conteudo_teste = f.read()

# Regex para pegar os argumentos da função self._testar("nome", "cat", "sub", "tipo")
padrao = re.compile(r'self\._testar\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)')
matches = padrao.findall(conteudo_teste)

nao_encontrados = []
divergentes = []
iguais = []

for match in matches:
    nome, cat_esp, sub_esp, tipo_esp = match
    
    prod_lib = encontrar_produto(nome, produtos_biblioteca)
    if not prod_lib:
        nao_encontrados.append(nome)
    else:
        cat_lib = prod_lib.get("Categoria", "")
        sub_lib = prod_lib.get("subcategoria", "")
        tipo_lib = prod_lib.get("tipo_produto", "")
        
        erros = []
        if cat_esp != cat_lib:
            erros.append(f"Categoria (Teste: '{cat_esp}' | Lib: '{cat_lib}')")
        if sub_esp != sub_lib:
            erros.append(f"Subcategoria (Teste: '{sub_esp}' | Lib: '{sub_lib}')")
        if tipo_esp != tipo_lib:
            erros.append(f"Tipo (Teste: '{tipo_esp}' | Lib: '{tipo_lib}')")
            
        if erros:
            divergentes.append((nome, erros))
        else:
            iguais.append(nome)

print("="*40)
print(f"Total de Produtos nos Testes: {len(matches)}")
print(f"✅ Iguais na biblioteca: {len(iguais)}")
print(f"⚠️ Com divergências: {len(divergentes)}")
print(f"❌ Não encontrados na biblioteca: {len(nao_encontrados)}")
print("="*40 + "\n")

if divergentes:
    print("--- ⚠️ PRODUTOS COM DIVERGÊNCIAS ---")
    for n, errs in divergentes:
        print(f"- {n}:")
        for e in errs:
            print(f"  {e}")
    print("\n")

if nao_encontrados:
    print("--- ❌ PRODUTOS NÃO ENCONTRADOS PELO NOME ---")
    for n in nao_encontrados:
        print(f"- {n}")
    print("\n")