import json

def limpeza_final_grabit(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        produtos = json.load(f)

    # 1. Mapeamento de Correções de Subcategoria e Dados Fiscais
    correcoes_especificas = {
        "611269101713": {"subcategoria": "Energéticos e Isotônicos"},  # Red Bull Sugar Free
        "7896051130116": {"subcategoria": "Laticínios e Iogurtes"},     # Leite Pó Itambé
        "7896004400297": {"subcategoria": "Conservas e Enlatados"},    # Leite de Coco Mais Coco
        "7896094919853": {"subcategoria": "Temperos e Condimentos"},   # Adoçante Zero-cal
        "7896283800801": {"tipo_produto": "Leite Longa Vida Integral"} # Jussara Integral
    }

    # 2. Listas de Tags de "Ruído" para remoção seletiva
    tags_comida_em_higiene = ["frios", "laticinios", "leite", "bebidas", "despensa", "mercearia"]
    tags_carne_em_pet = ["acougue", "peixaria", "carne"]
    tags_pet_em_limpeza = ["pet", "shop"]

    for ean, info in produtos.items():
        # Aplicar correções manuais de subcategoria[cite: 2]
        if ean in correcoes_especificas:
            info.update(correcoes_especificas[ean])

        # Limpeza específica do Toddynho (remover 'todeschini' das tags)[cite: 2]
        if ean == "7894321722016":
            info['tags'] = [t for t in info['tags'] if t != "todeschini"]

        # Limpeza de Sabonetes e Higiene (Remover tags de comida)[cite: 2]
        if info['Categoria'] == "Higiene e Cuidado Pessoal":
            info['tags'] = [t for t in info['tags'] if t not in tags_comida_em_higiene]
        
        # Limpeza de Água Oxigenada (Remover 'bebidas')[cite: 2]
        if ean == "7896213300111":
            info['tags'] = [t for t in info['tags'] if t != "bebidas"]

        # Limpeza de Rações e Proteína de Soja (Remover tags de carne humana)[cite: 2]
        if info['Categoria'] == "Pet Shop" or "soja" in info['nome_comum'].lower():
            info['tags'] = [t for t in info['tags'] if t not in tags_carne_carne_em_pet]

        # Limpeza de Odorizadores (Bom Ar) (Remover 'pet' e 'shop')[cite: 2]
        if "bom ar" in info['nome_comum'].lower():
            info['tags'] = [t for t in info['tags'] if t not in tags_pet_em_limpeza]

    # Salvar o arquivo final saneado
    with open('biblioteca_produtos_final.json', 'w', encoding='utf-8') as f:
        json.dump(produtos, f, indent=4, ensure_ascii=False)
    
    print("Saneamento concluído com sucesso!")

# Execução
limpeza_final_grabit('data/biblioteca_produtos_new.json')