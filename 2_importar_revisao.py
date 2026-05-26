import json
import os
import pandas as pd
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils import extrair_tags_inteligentes

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos_IA.json")
EXCEL_REVISAO = os.path.join(DATA_DIR, "01_revisao_biblioteca.xlsx")
SAIDA_FILE = os.path.join(DATA_DIR, "biblioteca_revisada.json")

def importar_revisao():
    if not os.path.exists(EXCEL_REVISAO):
        print(f"[Erro] Arquivo de revisão '{EXCEL_REVISAO}' não encontrado.")
        return

    if not os.path.exists(BIBLIOTECA_FILE):
        print(f"[Erro] Biblioteca original '{BIBLIOTECA_FILE}' não encontrada.")
        return

    # 1. Carrega a Biblioteca Atual e converte para dicionário caso seja uma lista
    with open(BIBLIOTECA_FILE, 'r', encoding='utf-8') as f:
        dados_json = json.load(f)
        
    biblioteca = {}
    if isinstance(dados_json, list):
        for item in dados_json:
            chave = str(item.get("id") or item.get("ean", ""))
            if chave:
                biblioteca[chave] = item
    elif isinstance(dados_json, dict):
        biblioteca = dados_json

    # 2. Carrega o Excel revisado
    print(f"[Aviso] Lendo planilha de revisão: {EXCEL_REVISAO}")
    df_revisado = pd.read_excel(EXCEL_REVISAO, dtype={"EAN_ID (NÃO ALTERAR)": str})

    # 3. Processa as atualizações
    alteracoes = 0
    confirmacoes = 0

    for index, row in df_revisado.iterrows():
        chave_ean = str(row.get("EAN_ID (NÃO ALTERAR)", "")).strip()
        
        # Ignora linhas sem EAN válido (Ex: NaN do pandas)
        if not chave_ean or chave_ean == "nan":
            continue

        # Se o item estiver no Excel mas não na biblioteca, cria um registro novo com estrutura completa
        if chave_ean not in biblioteca:
            nome_orig = str(row.get("Produto", "")).strip() if "Produto" in row else ""
            marca_orig = str(row.get("Marca", "N/A")).strip() if "Marca" in row else "N/A"
            
            biblioteca[chave_ean] = {
                "id": chave_ean,
                "nome_comum": nome_orig,
                "marca": marca_orig,
                "ean": chave_ean if chave_ean.isdigit() else "N/A",
                "Categoria": "OUTROS",
                "subcategoria": "N/A",
                "tipo_produto": "N/A",
                "imagem": "",
                "tags": [],
                "revisado_humano": False
            }

        item_bib = biblioteca[chave_ean]
        if "nome_comum" not in item_bib: item_bib["nome_comum"] = ""
        if "marca" not in item_bib: item_bib["marca"] = "N/A"
        if "imagem" not in item_bib: item_bib["imagem"] = ""
        if "tags" not in item_bib: item_bib["tags"] = []
        
        novo_nome = str(row.get("0. NOVO NOME (Opcional - Padroniza o nome para todos os mercados)", "")).strip()
        nova_cat = str(row.get("1. NOVA CATEGORIA (Preencha se estiver errado)", "")).strip()
        nova_sub = str(row.get("2. NOVA SUBCATEGORIA (Opcional)", "")).strip()
        novo_tipo = str(row.get("3. NOVO TIPO (Opcional)", "")).strip()
        confirmar = str(row.get("4. CONFIRMAR (Digite 'OK' se a categoria atual estiver certa)", "")).strip().upper()

        # O item foi alterado?
        item_alterado = False

        if novo_nome and novo_nome != "nan":
            item_bib["nome_comum"] = novo_nome.upper()
            item_alterado = True

        if nova_cat and nova_cat != "nan":
            item_bib["Categoria"] = nova_cat
            item_alterado = True
        
        if nova_sub and nova_sub != "nan":
            item_bib["subcategoria"] = nova_sub
            item_alterado = True
            
        if novo_tipo and novo_tipo != "nan":
            item_bib["tipo_produto"] = novo_tipo
            item_alterado = True

        # Marca o item como revisado por um humano se ele foi alterado ou se foi explicitamente confirmado
        if item_alterado:
            alteracoes += 1
            item_bib["revisado_humano"] = True
        elif confirmar == "OK":
            if not item_bib.get("revisado_humano"):
                item_bib["revisado_humano"] = True
                confirmacoes += 1

        # Atualiza as tags se o item foi modificado ou se não tinha tags
        if item_alterado or not item_bib.get("tags"):
            item_bib["tags"] = extrair_tags_inteligentes(item_bib)

    # 4. Salva a biblioteca em um novo arquivo no formato correto (Dicionário)
    with open(SAIDA_FILE, 'w', encoding='utf-8') as f:
        json.dump(biblioteca, f, indent=4, ensure_ascii=False)

    print("\n" + "="*40)
    print("[Sucesso] IMPORTAÇÃO CONCLUÍDA!")
    print("="*40)
    print(f"-> Produtos corrigidos manualmente: {alteracoes}")
    print(f"-> Produtos confirmados como corretos: {confirmacoes}")
    print(f"-> Nova biblioteca gerada em: {SAIDA_FILE}")

if __name__ == "__main__":
    importar_revisao()