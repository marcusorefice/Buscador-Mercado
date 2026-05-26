import json
import re

def padronizar_marcas_e_tags():
    caminho_arquivo = 'data/biblioteca_produtos.json'
    
    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Regras de substituição de marcas
    correcoes_marcas = {
        'YPE': 'YPÊ',
        'FLOR DE YPE': 'FLOR DE YPÊ',
        '3 CORACOES': '3 CORAÇÕES',
        'NESTLE': 'NESTLÉ',
        'NESTLÉ NEGRESCO': 'NESTLÉ',
        'NESTLE NEGRESCO': 'NESTLÉ',
        'NESTLE SNOW FLAKES': 'NESTLÉ',
        'NESTLE CLASSIC': 'NESTLÉ',
        'JOHNSONS': "JOHNSON'S",
        'JOHNSON S': "JOHNSON'S",
        'JOHNSONS BABY': "JOHNSON'S BABY",
        'QUALITA': 'QUALITÁ',
        'SADIA': 'SADIA',
        'PERDIGAO': 'PERDIGÃO',
        'SEARA': 'SEARA',
        'HELLMANNS': "HELLMANN'S",
        'HELLMANN S': "HELLMANN'S"
    }

    # Regex para identificar pesos e volumes (ex: 1kg, 500g, 2.5l, 350ml)
    regex_peso_volume = re.compile(r'^\d+(?:[.,]\d+)?\s*(kg|g|mg|l|ml)$', re.IGNORECASE)

    # Tags genéricas para remover
    tags_genericas = {'com', 'de', 'para', 'em', 'da', 'do', 'e', 'a', 'o', 'pacote', 'caixa', 'lata', 'garrafa', 'pote'}

    for ean, item in data.items():
        # 1. Corrigir Marca
        marca_atual = item.get('marca', '')
        if marca_atual:
            marca_upper = marca_atual.strip().upper()
            if marca_upper in correcoes_marcas:
                item['marca'] = correcoes_marcas[marca_upper]
            else:
                # Substituições parciais
                marca_nova = marca_upper.replace('YPE', 'YPÊ').replace('YPÊÊ', 'YPÊ')
                marca_nova = marca_nova.replace('3 CORACOES', '3 CORAÇÕES')
                marca_nova = marca_nova.replace('NESTLE', 'NESTLÉ').replace('NESTLÉÉ', 'NESTLÉ')
                marca_nova = marca_nova.replace('JOHNSONS', "JOHNSON'S")
                if marca_nova != marca_upper:
                    item['marca'] = marca_nova

        # 2. Limpar Tags
        tags_atuais = item.get('tags', [])
        if isinstance(tags_atuais, list):
            novas_tags = []
            for tag in tags_atuais:
                tag_lower = tag.strip().lower()
                
                # Ignorar tags vazias, genéricas ou que sejam pesos/volumes
                if not tag_lower or tag_lower in tags_genericas:
                    continue
                if regex_peso_volume.match(tag_lower):
                    continue
                
                novas_tags.append(tag.strip())
            
            # Atualizar as tags removendo duplicatas mantendo a ordem (ou apenas list(set()))
            item['tags'] = list(dict.fromkeys(novas_tags))

        # 3. Corrigir Categorias Específicas
        
        # Macarrão Instantâneo Milho na Manteiga
        if ean == "7907307994300" or "Macarrão Instantâneo" in item.get('nome_comum', ''):
            if item.get('Categoria') == 'Frios e Laticínios' or item.get('subcategoria') == 'Manteigas e Margarinas':
                item['Categoria'] = 'Mercearia'
                item['subcategoria'] = 'Massas'
                item['tipo_produto'] = 'Macarrão Instantâneo'
        
        # Passata Agromonte
        if ean == "8032817240302" or "Passata" in item.get('nome_comum', ''):
            if item.get('Categoria') == 'Hortifrúti':
                item['Categoria'] = 'Mercearia'
                item['subcategoria'] = 'Molhos e Extratos'
                item['tipo_produto'] = 'Molho de Tomate'
                
        # Torta de Palmito Dom Massas
        if "Torta de Palmito" in item.get('nome_comum', ''):
            if item.get('Categoria') == 'Conservas e Enlatados':
                item['Categoria'] = 'Congelados'
                item['subcategoria'] = 'Pratos Prontos'
                item['tipo_produto'] = 'Torta Congelada'
                
        # Requeijão Cremoso Tradicional Qualitá
        if "Requeijão Cremoso" in item.get('nome_comum', ''):
            if item.get('Categoria') == 'Conservas e Enlatados':
                item['Categoria'] = 'Frios e Laticínios'
                item['subcategoria'] = 'Requeijão e Queijos Cremosos'
                item['tipo_produto'] = 'Requeijão'
                
        # Padronização de Subcategorias:
        sub = item.get('subcategoria', '')
        if sub in ['Laticínios', 'Laticínios e Iogurtes', 'Iogurtes e Lácteos', 'Leites e Bebidas Lácteas', 'Bebidas Lácteas']:
            item['Categoria'] = 'Frios e Laticínios'
            if sub in ['Leites e Bebidas Lácteas', 'Bebidas Lácteas']:
                item['subcategoria'] = 'Leites'
            elif sub == 'Iogurtes e Lácteos':
                item['subcategoria'] = 'Iogurtes'
        
        if sub in ['Queijos', 'Queijos Classicos']:
            item['Categoria'] = 'Frios e Laticínios'
            item['subcategoria'] = 'Queijos'
            
        if sub in ['Óleos e Azeites', 'Vinagres e Azeites', 'Óleos, Azeites e Vinagres']:
            item['Categoria'] = 'Mercearia'
            item['subcategoria'] = 'Óleos, Azeites e Vinagres'
            
        # Corrigir tipos "Geral" para algo mais útil se possível, baseado no nome do produto
        if item.get('tipo_produto') == 'Geral' or item.get('subcategoria') == 'Geral':
            nome = item.get('nome_comum', '').lower()
            if 'sabonete' in nome:
                item['Categoria'] = 'Higiene e Perfumaria'
                item['subcategoria'] = 'Sabonetes'
                item['tipo_produto'] = 'Sabonete em Barra' if 'barra' in nome or 'líquido' not in nome else 'Sabonete Líquido'
            elif 'chocolate' in nome or 'twix' in nome:
                item['Categoria'] = 'Doces e Sobremesas'
                item['subcategoria'] = 'Chocolates'
                item['tipo_produto'] = 'Chocolate'
                
    with open(caminho_arquivo, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    print("Correções aplicadas com sucesso.")

if __name__ == '__main__':
    padronizar_marcas_e_tags()
