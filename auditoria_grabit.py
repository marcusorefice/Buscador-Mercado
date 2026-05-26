import json
import os

# Carregar os dados da fonte 7 (Ground Truth)
def carregar_dados():
    # Define o nome do arquivo de ground truth.
    # Se o seu arquivo de verdade absoluta for outro (ex: 'biblioteca_produtos.json'), altere aqui.
    ground_truth_filename = 'biblioteca_produtos_old.json'
    
    # Constrói o caminho dinamicamente a partir do diretório 'data'
    path_bib = os.path.join('data', ground_truth_filename)

    # Verifica se o arquivo existe antes de tentar abrir
    if not os.path.exists(path_bib):
        print(f"❌ Erro: Arquivo de ground truth não encontrado em '{path_bib}'")
        print("Verifique se o arquivo existe e se você está executando o script a partir do diretório 'd:\\Mercado'.")
        return None # Retorna None para ser tratado na função principal

    with open(path_bib, 'r', encoding='utf-8') as f:
        return json.load(f)

from utils import normalizar_taxonomia_grabit

# Importa a lógica real do utils.py
def categorizar_teste(item_nome, info, ean, dados):
    marca = info.get("marca", "")
    categoria, subcategoria, tipo = normalizar_taxonomia_grabit(
        nome_produto=item_nome,
        marca=marca,
        categoria_mercado="",
        subcategoria_mercado="",
        tipo_produto_mercado="",
        ean=ean,
        biblioteca=dados
    )
    return categoria

def rodar_auditoria():
    dados = carregar_dados()
    if not dados:
        return

    erros = []
    acertos = 0
    total_revisados = 0

    print(f"{'='*20} AUDITORIA GRABIT {'='*20}")

    for ean, info in dados.items():
        # Só testamos o que o Marcus já validou como certo
        if info.get("revisado_humano") == True:
            total_revisados += 1
            categoria_esperada = info.get("Categoria")
            nome = info.get("nome_comum")
            tags = info.get("tags", [])
            
            # Roda a sua lógica atual
            categoria_gerada = categorizar_teste(nome, info, ean, dados)

            if categoria_gerada != categoria_esperada:
                erros.append({
                    "ean": ean,
                    "produto": nome,
                    "esperado": categoria_esperada,
                    "gerado": categoria_gerada
                })
            else:
                acertos += 1

    # Relatório Final
    print(f"\n📊 Resultado:")
    print(f"✅ Acertos: {acertos}")
    print(f"❌ Erros de Lógica: {len(erros)}")
    print(f"🎯 Precisão: {(acertos/total_revisados)*100:.2f}%")
    
    if erros:
        print(f"\n📝 Itens para Corrigir no utils_3.py:")
        for erro in erros:
            print(f"- [{erro['ean']}] {erro['produto']}")
            print(f"  Deveria ser: {erro['esperado']} | O Bot disse: {erro['gerado']}\n")

if __name__ == "__main__":
    rodar_auditoria()