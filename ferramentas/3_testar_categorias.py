import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import json
import os
import sys

# Importa a lista oficial de categorias do seu utils.py
from utils import CATEGORIAS_MASTER

ARQUIVO_REVISADO = os.path.join("data", "biblioteca_unificada.json")

def testar_base():
    if not os.path.exists(ARQUIVO_REVISADO):
        print(f"❌ Arquivo não encontrado: {ARQUIVO_REVISADO}")
        return
        
    with open(ARQUIVO_REVISADO, 'r', encoding='utf-8') as f:
        biblioteca = json.load(f)
        
    certos = 0
    erros = []
    
    for ean, item in biblioteca.items():
        cat = item.get("Categoria", "NÃO DEFINIDA")
        if cat not in CATEGORIAS_MASTER:
            erros.append(f"- {ean}: {item.get('nome_comum')} -> [{cat}]")
        else:
            certos += 1
            
    print(f"\n✅ {certos} produtos categorizados corretamente nas {len(CATEGORIAS_MASTER)} CATEGORIAS_MASTER.")
    if erros:
        print(f"\n⚠️ {len(erros)} produtos com Categoria fora do padrão:")
        for erro in erros:
            print(erro)

if __name__ == "__main__":
    testar_base()