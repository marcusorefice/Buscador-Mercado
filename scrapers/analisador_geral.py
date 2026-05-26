import pandas as pd
import os
import sys

# Garante que o output use UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = "data"

def analisar_todas_planilhas():
    """
    Lê todas as planilhas de histórico da pasta /data, as consolida e
    gera um relatório sobre a qualidade e padronização dos dados.
    """
    arquivos_excel = [f for f in os.listdir(DATA_DIR) if f.startswith('historico_') and f.endswith('.xlsx')]

    if not arquivos_excel:
        print("Nenhuma planilha de histórico encontrada na pasta 'data'.")
        print("Execute o 'main.py' para gerar os arquivos primeiro.")
        return

    lista_dfs = []
    for arquivo in arquivos_excel:
        caminho = os.path.join(DATA_DIR, arquivo)
        try:
            # dtype={'EAN': str} é crucial para ler o EAN como texto
            df = pd.read_excel(caminho, dtype={'EAN': str})
            lista_dfs.append(df)
        except Exception as e:
            print(f"Erro ao ler o arquivo {arquivo}: {e}")

    if not lista_dfs:
        print("Não foi possível carregar os dados de nenhuma planilha.")
        return

    # Consolida todos os dados em um único DataFrame
    df_total = pd.concat(lista_dfs, ignore_index=True)
    df_total.fillna('N/A', inplace=True) # Preenche células vazias com 'N/A'

    total_produtos = len(df_total)
    print("\n" + "="*60)
    print(" 📊 ANÁLISE CONSOLIDADA DE DADOS - PADRONIZAÇÃO 📊")
    print(f"Total de produtos únicos analisados: {total_produtos}")
    print("="*60 + "\n")

    # 1. Análise de EAN
    produtos_com_ean = df_total[df_total['EAN'].ne('N/A') & df_total['EAN'].str.match(r'^\d{12,13}$', na=False)]
    perc_ean = (len(produtos_com_ean) / total_produtos) * 100
    print(f"🛒 Produtos com EAN Válido: {len(produtos_com_ean)} de {total_produtos} ({perc_ean:.2f}%)")

    # 2. Análise de Categorias
    print("\n--- Análise de Taxonomia ---")
    for coluna in ['Categoria', 'subcategoria', 'tipo_produto']:
        produtos_na = df_total[df_total[coluna] == 'N/A']
        perc_na = (len(produtos_na) / total_produtos) * 100
        print(f"- Produtos com '{coluna}' como 'N/A': {len(produtos_na)} ({perc_na:.2f}%)")

    # 3. Exemplo de valores únicos para Categoria
    print("\n--- Amostra de Valores Únicos ---")
    print("Categorias encontradas:")
    print(sorted(df_total['Categoria'].unique().tolist()))
    
    print("\nSubcategorias encontradas:")
    print(sorted(df_total['subcategoria'].unique().tolist()))

    print("\n" + "="*60)
    print("💡 PRÓXIMOS PASSOS:")
    print("1. Foque em enriquecer a 'biblioteca.json' usando os produtos que JÁ TÊM EAN.")
    print("2. Centralize a lógica de categorização na função 'validar_e_limpar_produtos' em utils.py.")
    print("3. Use a biblioteca como 'fonte da verdade' para preencher os campos 'N/A'.")
    print("="*60)


if __name__ == "__main__":
    analisar_todas_planilhas()
