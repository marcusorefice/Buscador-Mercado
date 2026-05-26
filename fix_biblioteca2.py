import json
import re
from utils import normalizar_taxonomia_grabit, TERMOS_GENERICOS, STOP_WORDS, extrair_tags_inteligentes

def fix_biblioteca():
    arquivos = ['data/biblioteca_unificada.json', 'data/biblioteca_produtos.json']
    
    for arquivo in arquivos:
        try:
            with open(arquivo, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Erro ao abrir {arquivo}: {e}")
            continue

        mudancas = 0

        # Usando list() para permitir deletar chaves durante iteração
        for k, v in list(data.items()):
            # 1. Corrigir EAN 12 dígitos
            ean = str(v.get('ean', 'N/A'))
            if ean != 'N/A' and len(ean) == 12 and ean.isdigit():
                new_ean = "0" + ean
                v['ean'] = new_ean
                if k == ean:
                    data[new_ean] = v
                    del data[k]
                mudancas += 1

            nome = str(v.get('nome_comum', ''))
            nome_orig = nome
            
            # 2. Corrigir Acentuação e Nomes
            replaces = {
                r'\bACUCAR\b': 'AÇÚCAR', r'\bAcucar\b': 'Açúcar',
                r'\bMACA\b': 'MAÇÃ', r'\bMaca\b': 'Maçã',
                r'\bPIMENTAO\b': 'PIMENTÃO', r'\bPimentao\b': 'Pimentão',
                r'\bMACARRAO\b': 'MACARRÃO', r'\bMacarrao\b': 'Macarrão',
                r'\bFEIJAO\b': 'FEIJÃO', r'\bFeijao\b': 'Feijão',
                r'\bAO LEITE\b': 'ao Leite', r'\bAo leite\b': 'ao Leite',
                r'\bPao\b': 'Pão', r'\bPAO\b': 'PÃO',
            }
            for old, new in replaces.items():
                nome = re.sub(old, new, nome)
            
            if nome != nome_orig:
                v['nome_comum'] = nome
                mudancas += 1

            # 3. Corrigir Categorização (Requeijão, Twix, Torta)
            cat = v.get('Categoria', '')
            sub = v.get('subcategoria', '')
            tipo = v.get('tipo_produto', '')
            marca = v.get('marca', '')

            cat_orig = cat
            sub_orig = sub
            tipo_orig = tipo
            
            if 'REQUEIJÃO' in nome.upper() or 'REQUEIJAO' in nome.upper():
                cat = 'Frios e Laticínios'
                sub = 'Requeijão e Queijos Cremosos'
                tipo = 'Requeijão'
            elif 'TORTA DE PALMITO' in nome.upper():
                cat = 'Congelados e Pratos Prontos'
                sub = 'Pizzas e Salgados'
                tipo = 'Torta de Palmito'
            elif 'TWIX' in nome.upper():
                cat = 'Mercearia e Despensa'
                sub = 'Chocolates e Doces'
                tipo = 'Chocolate'

            if sub == 'Geral' or tipo == 'Geral' or sub == 'Conservas e Enlatados' and 'REQUEIJÃO' in nome.upper():
                new_cat, new_sub, new_tipo = normalizar_taxonomia_grabit(
                    nome_produto=nome,
                    marca=marca,
                    categoria_mercado=cat,
                    subcategoria_mercado=sub,
                    tipo_produto_mercado=tipo,
                    ean=v.get('ean', 'N/A'),
                    biblioteca={}
                )
                v['Categoria'] = new_cat
                v['subcategoria'] = new_sub
                v['tipo_produto'] = new_tipo
            else:
                v['Categoria'] = cat
                v['subcategoria'] = sub
                v['tipo_produto'] = tipo

            if v['Categoria'] != cat_orig or v['subcategoria'] != sub_orig or v['tipo_produto'] != tipo_orig:
                mudancas += 1

            # 4. Corrigir Tags
            tags = v.get('tags', [])
            tags_orig_str = str(tags)
            if isinstance(tags, list):
                tags_lower = [str(t).lower() for t in tags]
                tags_limpas = [t for t in tags_lower if t not in TERMOS_GENERICOS and t not in STOP_WORDS]
                novas_tags = extrair_tags_inteligentes(v)
                tags_finais = sorted(list(set(tags_limpas + novas_tags)))
                if str(tags_finais) != tags_orig_str:
                    v['tags'] = tags_finais
                    mudancas += 1

        with open(arquivo, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print(f"Finalizado {arquivo}. Total de alterações: {mudancas}")

if __name__ == '__main__':
    fix_biblioteca()
