import json
import os
import pandas as pd
import hashlib

# Defina os caminhos absolutos dos seus arquivos
BASE_DIR = r"d:\Mercado"
DATA_DIR = os.path.join(BASE_DIR, "data")

ARQUIVO_PRINCIPAL = os.path.join(DATA_DIR, "biblioteca_produtos.json")
ARQUIVO_IA = os.path.join(DATA_DIR, "biblioteca_produtos_IA.json")
ARQUIVO_OLD = os.path.join(DATA_DIR, "biblioteca_produtos_old.json")
ARQUIVO_EXCEL = os.path.join(DATA_DIR, "historico_atacadao.xlsx")

ARQUIVO_SAIDA = os.path.join(DATA_DIR, "biblioteca_unificada.json")

def gerar_id_unico(nome, marca):
    """Gera um hash MD5 baseado no nome e marca caso não haja EAN."""
    texto = f"{str(nome).strip().upper()}|{str(marca).strip().upper()}"
    return hashlib.md5(texto.encode('utf-8')).hexdigest()[:13]

def limpar_ean(ean_raw):
    """Garante que o EAN seja uma string limpa."""
    ean = str(ean_raw).strip()
    if ean.endswith('.0'):
        ean = ean[:-2]
    if ean in ('', 'nan', 'None', 'N/A', '0'):
        return "N/A"
    return ean

def unificar_bases():
    produtos_unificados = {}
    estatisticas = {"inseridos": 0, "atualizados": 0}

    def processar_item(p):
        nome = p.get("nome_comum") or p.get("Produto") or p.get("nome") or ""
        if not nome:
            return # Ignora itens sem nome
            
        marca = p.get("marca") or p.get("Marca") or "N/A"
        ean_raw = p.get("ean") or p.get("EAN") or "N/A"
        ean = limpar_ean(ean_raw)
        
        if ean == "N/A":
            return # Ignora itens sem EAN
        
        # Chave de deduplicação
        id_produto = ean
        
        # Formata o produto no padrão exigido
        produto_formatado = {
            "id": id_produto,
            "nome_comum": nome,
            "marca": marca,
            "ean": ean,
            "Categoria": p.get("Categoria") or p.get("categoria", "OUTROS"),
            "subcategoria": p.get("subcategoria", "N/A"),
            "tipo_produto": p.get("tipo_produto", "N/A"),
            "imagem": p.get("imagem", ""),
            "tags": p.get("tags") if isinstance(p.get("tags"), list) else [],
            "revisado_humano": p.get("revisado_humano", False)
        }
        
        # Limpa chaves vazias ou nulas
        produto_formatado = {k: v for k, v in produto_formatado.items() if v}
        if "tags" not in produto_formatado: produto_formatado["tags"] = []

        if id_produto not in produtos_unificados:
            produtos_unificados[id_produto] = produto_formatado
            estatisticas["inseridos"] += 1
        else:
            # Atualiza apenas campos que estão faltando na base consolidada
            existente = produtos_unificados[id_produto]
            
            for chave, valor in produto_formatado.items():
                # Se o campo não existe no atual, ou seccionarmos uma imagem nova
                if chave not in existente or not existente[chave]:
                    if valor:
                        existente[chave] = valor
                        
            # Se o novo for revisado_humano e o velho não for, força a atualização da taxonomia
            if produto_formatado.get("revisado_humano") and not existente.get("revisado_humano", False):
                existente["Categoria"] = produto_formatado.get("Categoria", existente.get("Categoria"))
                existente["subcategoria"] = produto_formatado.get("subcategoria", existente.get("subcategoria"))
                existente["tipo_produto"] = produto_formatado.get("tipo_produto", existente.get("tipo_produto"))
                existente["revisado_humano"] = True
                
            produtos_unificados[id_produto] = existente
            estatisticas["atualizados"] += 1

    def carregar_json(caminho, nome_arquivo):
        if os.path.exists(caminho):
            print(f"Lendo {nome_arquivo}...")
            with open(caminho, 'r', encoding='utf-8') as f:
                dados = json.load(f)
                # Aceita tanto se for lista quanto se for dict
                lista_dados = dados.values() if isinstance(dados, dict) else dados
                for item in lista_dados:
                    processar_item(item)
        else:
            print(f"Aviso: Arquivo {nome_arquivo} não encontrado.")

    # 1. Carrega o principal (maior qualidade)
    carregar_json(ARQUIVO_PRINCIPAL, "biblioteca_produtos.json")
    
    # 2. Carrega o da IA
    carregar_json(ARQUIVO_IA, "biblioteca_produtos_IA.json")
    
    # 3. Carrega o antigo
    carregar_json(ARQUIVO_OLD, "biblioteca_produtos_old.json")
    
    # 4. Carrega os dados da planilha do Atacadão
    if os.path.exists(ARQUIVO_EXCEL):
        print("Lendo historico_atacadao.xlsx...")
        try:
            df_atacadao = pd.read_excel(ARQUIVO_EXCEL)
            # Remove duplicatas exatas dentro da própria planilha antes de iterar
            df_atacadao = df_atacadao.drop_duplicates(subset=['EAN', 'Produto', 'Marca'])
            
            # Converte NaN para string vazia
            df_atacadao = df_atacadao.fillna('')
            
            for registro in df_atacadao.to_dict('records'):
                processar_item(registro)
        except Exception as e:
            print(f"Erro ao ler planilha: {e}")
    else:
        print("Aviso: historico_atacadao.xlsx não encontrado.")

    # Salvar o resultado final
    print(f"\nSalvando dados unificados em {ARQUIVO_SAIDA}...")
    with open(ARQUIVO_SAIDA, 'w', encoding='utf-8') as f:
        json.dump(produtos_unificados, f, indent=4, ensure_ascii=False)

    print("\nResumo da Unificação:")
    print(f"Total de produtos únicos criados: {len(produtos_unificados)}")
    print(f"Total de inserções processadas: {estatisticas['inseridos']}")
    print(f"Total de atualizações/mesclagens: {estatisticas['atualizados']}")
    print("\nVocê pode renomear 'biblioteca_unificada.json' para 'biblioteca_produtos.json' e usa-la como sua nova base oficial.")

if __name__ == "__main__":
    unificar_bases()