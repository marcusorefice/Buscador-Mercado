import json
import os
from difflib import SequenceMatcher

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")

# A lista MESTRA e inegociável de categorias
CATEGORIAS_MASTER = [
    "Mercearia e Despensa",
    "Limpeza",
    "Higiene e Cuidado Pessoal",
    "Bebidas",
    "Bebidas Alcoólicas",
    "Frios e Laticínios",
    "Açougue e Peixaria",
    "Padaria e Confeitaria",
    "Congelados e Pratos Prontos",
    "Hortifrúti",
    "Bebê e Infantil",
    "Pet Shop",
    "Bazar e Utilidades"
]

def similaridade(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def encontrar_melhor_categoria(cat_atual):
    if not cat_atual:
        return "Mercearia e Despensa" # Fallback
        
    cat_atual = str(cat_atual).strip()
    
    # Se já está na master, retorna ela mesma
    if cat_atual in CATEGORIAS_MASTER:
        return cat_atual
        
    # Mapeamentos manuais para erros comuns da IA
    cat_lower = cat_atual.lower()
    if "higiene" in cat_lower or "perfumaria" in cat_lower or "pessoal" in cat_lower or "cabelo" in cat_lower or "banho" in cat_lower:
        return "Higiene e Cuidado Pessoal"
    if "limpeza" in cat_lower or "casa" in cat_lower or "sabão" in cat_lower or "detergente" in cat_lower:
        return "Limpeza"
    if "alcoól" in cat_lower or "alcool" in cat_lower or "cerveja" in cat_lower or "vinho" in cat_lower or "destilado" in cat_lower:
        return "Bebidas Alcoólicas"
    if "bebida" in cat_lower or "suco" in cat_lower or "refrigerante" in cat_lower or "água" in cat_lower:
        return "Bebidas"
    if "frios" in cat_lower or "laticínio" in cat_lower or "leite" in cat_lower or "queijo" in cat_lower or "iogurte" in cat_lower:
        return "Frios e Laticínios"
    if "açougue" in cat_lower or "carne" in cat_lower or "peixe" in cat_lower or "frango" in cat_lower:
        return "Açougue e Peixaria"
    if "padaria" in cat_lower or "pão" in cat_lower or "confeitaria" in cat_lower or "bolo" in cat_lower:
        return "Padaria e Confeitaria"
    if "congelado" in cat_lower or "prato pronto" in cat_lower or "sorvete" in cat_lower:
        return "Congelados e Pratos Prontos"
    if "hortifrúti" in cat_lower or "fruta" in cat_lower or "legume" in cat_lower or "verdura" in cat_lower:
        return "Hortifrúti"
    if "bebê" in cat_lower or "infantil" in cat_lower or "fralda" in cat_lower:
        return "Bebê e Infantil"
    if "pet" in cat_lower or "cão" in cat_lower or "gato" in cat_lower or "ração" in cat_lower:
        return "Pet Shop"
    if "bazar" in cat_lower or "utilidade" in cat_lower or "eletro" in cat_lower or "casa" in cat_lower:
        return "Bazar e Utilidades"
        
    # Se não caiu em nenhum mapping, tenta similaridade de string
    melhor_match = "Mercearia e Despensa"
    maior_score = 0
    for master_cat in CATEGORIAS_MASTER:
        score = similaridade(cat_atual, master_cat)
        if score > maior_score:
            maior_score = score
            melhor_match = master_cat
            
    # Se a similaridade for muito baixa, joga em Mercearia
    if maior_score < 0.4:
        return "Mercearia e Despensa"
        
    return melhor_match

def main():
    if not os.path.exists(BIBLIOTECA_FILE):
        print("Biblioteca não encontrada.")
        return
        
    with open(BIBLIOTECA_FILE, "r", encoding="utf-8") as f:
        biblioteca = json.load(f)
        
    alterados = 0
    
    # Varre a biblioteca arrumando a Categoria
    for ean, item in biblioteca.items():
        cat_atual = item.get("Categoria")
        melhor_cat = encontrar_melhor_categoria(cat_atual)
        
        if cat_atual != melhor_cat:
            item["Categoria"] = melhor_cat
            alterados += 1
            
    # Salva de volta
    if alterados > 0:
        with open(BIBLIOTECA_FILE, "w", encoding="utf-8") as f:
            json.dump(biblioteca, f, ensure_ascii=False, indent=4)
        print(f"Sucesso! {alterados} produtos tiveram suas categorias corrigidas/padronizadas.")
    else:
        print("Todas as categorias já estavam padronizadas.")

if __name__ == "__main__":
    main()
