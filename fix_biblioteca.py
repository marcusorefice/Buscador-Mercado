import json
import re
import urllib.parse

def title_case(s):
    # Trata exceções comuns em title case
    words = s.split()
    if not words: return s
    lower_words = {'de', 'da', 'do', 'das', 'dos', 'e', 'com', 'sem', 'para'}
    title_words = []
    for i, word in enumerate(words):
        word_lower = word.lower()
        if i > 0 and word_lower in lower_words:
            title_words.append(word_lower)
        else:
            title_words.append(word.capitalize())
    return ' '.join(title_words)

def remove_ruido(nome):
    nome_limpo = nome
    padroes = [
        r'\bC/\s*\d+\b',       # C/4, C/ 12
        r'\bCX\'\bTP\b',
        r'\bLV\s?\d+P\s?G?\d+\b', # LV3PG2
        r'\bUNID?\.?\b',       # UN ou UNID
        r'\bCX\b',             # CX
        r'\bFD\b'              # FD
    ]
    for p in padroes:
        nome_limpo = re.sub(p, '', nome_limpo, flags=re.IGNORECASE)
    
    # Remove "Kg" e etc apenas se estiverem "soltos" ou de forma que polui. O usuário pediu para manter se essencial, 
    # mas também pediu para remover. Vou remover as variações mais poluentes:
    # Retirando pesos e medidas que ficam sozinhos no final (ex: "Produto 1 Kg" -> "Produto 1kg") - na verdade vamos manter
    # para distinguir o produto, como instruído "Mantenha se essencial".
    
    return ' '.join(nome_limpo.split())

def extrair_nome_da_url(url, ean):
    if not url: return None
    # Verifica padrão S. Vicente: .../1115790-7501843503480-acendedor bic multiuso-bic-1.jpg
    if 'svicente' in url.lower() or 'demandware.static' in url.lower():
        parsed = urllib.parse.urlparse(url)
        filename = urllib.parse.unquote(parsed.path.split('/')[-1])
        if filename.endswith('.jpg') or filename.endswith('.png') or filename.endswith('.jpeg'):
            # Tira a extensão
            filename = filename.rsplit('.', 1)[0]
            # Busca o EAN no nome
            if ean in filename:
                partes = filename.split(f"{ean}-")
                if len(partes) > 1:
                    resto = partes[1]
                    # O resto é tipo "nome-do-produto-marca-1"
                    # Podemos limpar as últimas partes se forem a marca ou número
                    # S. Vicente usa espaços em vez de hifens na string de nome?
                    # Ex: 16861-7891021006125-cafe melitta tradicional a vacuo 500g-melitta-1
                    # A parte após o EAN é "cafe melitta tradicional a vacuo 500g-melitta-1"
                    nome_extraido = resto.rsplit('-', 2)[0] # tira o "-melitta-1"
                    return title_case(nome_extraido.replace('-', ' '))
    return None

def is_nome_pobre(nome, marca):
    n = nome.upper().strip()
    m = marca.upper().strip()
    if not n or n == m:
        return True
    
    # Se o nome tem apenas 1 ou 2 palavras e são iguais à marca
    palavras = n.split()
    if len(palavras) <= 2 and all(p in m for p in palavras):
        return True
        
    return False

def main():
    filepath = 'data/biblioteca_produtos.json'
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    modificados = 0
    for ean, info in data.items():
        nome_comum = info.get('nome_comum', '').strip()
        marca = info.get('marca', 'PRÓPRIA').strip()
        tipo_produto = info.get('tipo_produto', '').strip()
        imagem = info.get('imagem', '') # a chave certa é 'imagem'

        nome_original = nome_comum
        
        # 1. Limpeza de Ruído
        nome_comum = remove_ruido(nome_comum)
        
        # 2. Identificação de Nomes Pobres
        if is_nome_pobre(nome_comum, marca):
            # Tenta pegar da URL primeiro
            nome_url = extrair_nome_da_url(imagem, ean)
            if nome_url:
                nome_comum = nome_url
            else:
                # 3. Reconstrução: [tipo_produto] + [marca]
                if tipo_produto and tipo_produto.upper() != "N/A":
                    nome_comum = f"{tipo_produto} {marca}"
                else:
                    nome_comum = f"Produto {marca}"
        
        # Se não era pobre, mas a gente quer garantir que o S. Vicente com nome ruim (ex: cortado) pegue o da URL
        # Na dúvida, se tem URL e o nome atual é muito menor que o da URL
        else:
            nome_url = extrair_nome_da_url(imagem, ean)
            if nome_url and len(nome_url) > len(nome_comum) + 5:
                 # Usa o nome da URL se ele parecer mais completo
                 nome_comum = nome_url
                 
        # 4. Padronização de Formato: Title Case
        nome_comum = title_case(nome_comum)
        
        if nome_comum != nome_original:
            info['nome_comum'] = nome_comum
            modificados += 1

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Foram corrigidos/modificados {modificados} itens.")

if __name__ == '__main__':
    main()
