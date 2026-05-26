import json
import os
import pandas as pd

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")
EXCEL_REVISAO = os.path.join(DATA_DIR, "01_revisao_biblioteca.xlsx")

def exportar_para_revisao():
    if not os.path.exists(BIBLIOTECA_FILE):
        print(f"❌ Arquivo '{BIBLIOTECA_FILE}' não encontrado.")
        return

    with open(BIBLIOTECA_FILE, 'r', encoding='utf-8') as f:
        biblioteca = json.load(f)

    if not biblioteca:
        print("⚠️ A biblioteca está vazia.")
        return

    # Suporta tanto dicionários quanto listas
    if isinstance(biblioteca, dict):
        itens_para_iterar = biblioteca.items()
    elif isinstance(biblioteca, list):
        itens_para_iterar = [(item.get("id", str(i)), item) for i, item in enumerate(biblioteca) if isinstance(item, dict)]
    else:
        print("⚠️ Formato de biblioteca não suportado.")
        return

    linhas = []
    for chave, item in itens_para_iterar:
        # Filtra entradas inválidas ou vazias
        if not isinstance(item, dict): continue
        
        # Pega a Categoria Atual (pode vir do mercado ou da IA antiga)
        cat_atual = item.get("Categoria", "OUTROS")
        sub_atual = item.get("subcategoria", "N/A")
        tipo_atual = item.get("tipo_produto", "N/A")

        linhas.append({
            "EAN_ID (NÃO ALTERAR)": chave,
            "Produto_Atual": item.get("nome_comum", ""),
            "Marca": item.get("marca", ""),
            "Categoria_Atual": cat_atual,
            "Subcategoria_Atual": sub_atual,
            "Tipo_Atual": tipo_atual,
            "0. NOVO NOME (Opcional - Padroniza o nome para todos os mercados)": "",
            "1. NOVA CATEGORIA (Preencha se estiver errado)": "",
            "2. NOVA SUBCATEGORIA (Opcional)": "",
            "3. NOVO TIPO (Opcional)": "",
            "4. CONFIRMAR (Digite 'OK' se a categoria atual estiver certa)": "",
            "Revisado_Humano": item.get("revisado_humano", False)
        })

    df = pd.DataFrame(linhas)

    # Ordena por Categoria e Subcategoria para facilitar a revisão em lote "pelo olho"
    df = df.sort_values(by=["Categoria_Atual", "Subcategoria_Atual", "Produto_Atual"])

    # Exporta para Excel
    try:
        # Usa um Writer para formatar a largura das colunas
        with pd.ExcelWriter(EXCEL_REVISAO, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Revisão de Taxonomia")
            
            # Ajustando a largura das colunas (Opcional, mas ajuda muito na visualização)
            worksheet = writer.sheets["Revisão de Taxonomia"]
            for i, col in enumerate(df.columns):
                # Pega o tamanho do cabeçalho ou max de 15
                max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.column_dimensions[chr(65 + i)].width = min(max_len, 50) # Limita a 50 de largura

        print(f"[Sucesso] Planilha gerada em: {EXCEL_REVISAO}")
        print("-> Instruções: Abra a planilha, olhe os itens agrupados.")
        print("   Se a 'Categoria_Atual' estiver correta, deixe as colunas 'NOVA...' em branco.")
        print("   Se estiver errada, digite a correta nas colunas 'NOVA CATEGORIA' etc.")
    except Exception as e:
        print(f"[Erro] ao exportar para Excel: {e}")

if __name__ == "__main__":
    print("[Iniciando] Exportando Biblioteca para Revisão...")
    exportar_para_revisao()
