import os
import json
from utils import normalizar_taxonomia_grabit, MAPA_DE_PARA_SUBCATEGORIAS, CATEGORIAS_MASTER

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")

def corrigir_biblioteca():
    if not os.path.exists(BIBLIOTECA_FILE):
        print(f"❌ Arquivo '{BIBLIOTECA_FILE}' não encontrado.")
        return

    with open(BIBLIOTECA_FILE, 'r', encoding='utf-8') as f:
        biblioteca = json.load(f)

    correcoes_cat = 0
    correcoes_sub = 0
    enriquecimentos = 0

    for chave, item in biblioteca.items():
        if not isinstance(item, dict): continue
        
        cat_atual = item.get("Categoria", "")
        sub_atual = item.get("subcategoria", "N/A")
        tipo_atual = item.get("tipo_produto", "N/A")
        nome = item.get("nome_comum", "")
        marca = item.get("marca", "")

        # 1. Corrigir Categorias Inválidas (Hardcoded com base na auditoria)
        if cat_atual == "Frios e Laticínios.":
            item["Categoria"] = "Frios e Laticínios"
            cat_atual = "Frios e Laticínios"
            correcoes_cat += 1
        elif cat_atual == "Congelados":
            item["Categoria"] = "Congelados e Pratos Prontos"
            cat_atual = "Congelados e Pratos Prontos"
            correcoes_cat += 1

        # 2. Corrigir Subcategorias Defasadas pelo Mapa
        if sub_atual in MAPA_DE_PARA_SUBCATEGORIAS:
            item["subcategoria"] = MAPA_DE_PARA_SUBCATEGORIAS[sub_atual]
            sub_atual = item["subcategoria"]
            correcoes_sub += 1

        # 3. Re-avaliar Taxonomia usando o motor GrabIt atual (para corrigir erros antigos)
        nova_cat, nova_sub, novo_tipo = normalizar_taxonomia_grabit(
            nome_produto=nome, marca=marca, categoria_mercado=cat_atual if cat_atual != "OUTROS" else "",
            subcategoria_mercado="", tipo_produto_mercado="", ean="N/A", biblioteca={}, mercado_nome=""
        )
        
        if nova_cat != cat_atual or nova_sub != sub_atual or novo_tipo != tipo_atual:
            item["Categoria"] = nova_cat
            item["subcategoria"] = nova_sub
            item["tipo_produto"] = novo_tipo
            enriquecimentos += 1

    with open(BIBLIOTECA_FILE, 'w', encoding='utf-8') as f:
        json.dump(biblioteca, f, indent=4, ensure_ascii=False)

    print(f"\n{'='*50}\n ✅ BIBLIOTECA CORRIGIDA COM SUCESSO!\n{'='*50}")
    print(f"-> Categorias Master corrigidas: {correcoes_cat}")
    print(f"-> Subcategorias defasadas atualizadas: {correcoes_sub}")
    print(f"-> Produtos 'N/A' enriquecidos com novas regras: {enriquecimentos}\n")

if __name__ == "__main__":
    corrigir_biblioteca()