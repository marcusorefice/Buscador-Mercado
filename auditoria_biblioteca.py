import os
from utils import read_json_file, CATEGORIAS_MASTER, MAPA_DE_PARA_SUBCATEGORIAS

def auditar_biblioteca():
    caminho_bib = os.path.join("data", "biblioteca_produtos.json")
    biblioteca = read_json_file(caminho_bib, {})
    
    if not biblioteca:
        print("❌ Biblioteca não encontrada ou está vazia.")
        return

    erros_categoria = []
    erros_subcategoria = []
    erros_plu = []
    erros_nulos = []

    for chave, item in biblioteca.items():
        nome = item.get("nome_comum", "DESCONHECIDO")
        cat = item.get("Categoria")
        sub = item.get("subcategoria")
        ean = str(item.get("ean", ""))

        # 1. Checa Categorias Master inválidas
        if cat not in CATEGORIAS_MASTER:
            erros_categoria.append(f"Produto: {nome} | Categoria Inválida: '{cat}'")

        # 2. Checa Subcategorias que deveriam ter sido atualizadas pelo MAPA DE/PARA
        if sub in MAPA_DE_PARA_SUBCATEGORIAS:
            erros_subcategoria.append(f"Produto: {nome} | Subcategoria Defasada: '{sub}' (Deveria ser '{MAPA_DE_PARA_SUBCATEGORIAS[sub]}')")

        # 3. Checa EANs que são lixo de balança (PLU)
        if chave.startswith("2") and len(chave) == 13 and chave.isdigit():
            erros_plu.append(f"Produto: {nome} | Chave/EAN PLU Interno (Lixo): {chave}")
            
        # 4. Checa falhas de preenchimento
        if cat == "OUTROS" or sub == "N/A":
            erros_nulos.append(f"Produto: {nome} | Precisa de revisão humana (Categoria: {cat}, Sub: {sub})")

    # --- RELATÓRIO FINAL ---
    print(f"\n{'='*50}\n 📊 RELATÓRIO DE AUDITORIA DA BIBLIOTECA\n{'='*50}")
    print(f"Total de Produtos Analisados: {len(biblioteca)}")
    
    def imprimir_erros(titulo, lista, max_exibir=15):
        print(f"\n🔴 {titulo} ({len(lista)} encontrados):")
        if not lista: print("   ✅ Tudo perfeito!")
        for erro in lista[:max_exibir]: print(f"   - {erro}")
        if len(lista) > max_exibir: print(f"   ... e mais {len(lista) - max_exibir} itens.")

    imprimir_erros("CATEGORIAS MASTER INVÁLIDAS", erros_categoria)
    imprimir_erros("SUBCATEGORIAS DEFASADAS", erros_subcategoria)
    imprimir_erros("CÓDIGOS PLU INTERNOS (Açougue/Padaria)", erros_plu)
    imprimir_erros("ITENS COM TAXONOMIA POBRE (OUTROS / N/A)", erros_nulos)
    print("\n" + "="*50)

if __name__ == "__main__":
    auditar_biblioteca()