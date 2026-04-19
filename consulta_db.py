import sqlite3
import os
import pandas as pd

# Configurações de caminho baseadas no projeto
DATA_DIR = "data"
DB_NOME = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")

def consultar_itens(termo_busca=None, mercado=None, categoria=None, limite=50):
    """
    Consulta itens no banco de dados com filtros opcionais.
    """
    if not os.path.exists(DB_NOME):
        print(f"❌ Erro: Banco de dados não encontrado em {DB_NOME}")
        return pd.DataFrame()

    conn = sqlite3.connect(DB_NOME)
    
    # Construção da Query Dinâmica
    # Seleciona todas as colunas exceto Link_Imagem
    query = """
        SELECT "Mercado", "Categoria", "Produto", "Marca", "Preço Varejo", "Preço Atacado",
               "Qtd_Valor", "Medida", "Condição" 
        FROM ofertas WHERE 1=1"""
    params = []
    # --- Lógica de Busca Otimizada com FTS5 ---
    if termo_busca:
        # A busca agora é feita na tabela FTS e ordenada por relevância (rank).
        # Juntamos com a tabela original para obter todos os dados.
        query = """
            SELECT o.* FROM ofertas AS o
            JOIN (
                SELECT rowid, rank FROM ofertas_fts
                WHERE ofertas_fts MATCH ?
                ORDER BY rank
            ) AS fts ON o.id = fts.rowid
            WHERE 1=1
        """
        # Formata o termo de busca para FTS5, permitindo busca por prefixo com '*'
        params = [f'"{termo_busca}"*']
    else:
        # Se não houver termo de busca, retorna as ofertas mais recentes.
        query = "SELECT * FROM ofertas WHERE 1=1"
        params = []

    if termo_busca:
        query += " AND (Produto LIKE ? OR Marca LIKE ?)"
        params.extend([f"%{termo_busca}%", f"%{termo_busca}%"])
    
    if mercado:
        query += " AND Mercado = ?"
        query += " AND o.Mercado = ?" if termo_busca else " AND Mercado = ?"
        params.append(mercado)
        
    if categoria:
        query += " AND Categoria = ?"
        query += " AND o.Categoria = ?" if termo_busca else " AND Categoria = ?"
        params.append(categoria)
    
    query += f" ORDER BY Data_Hora DESC LIMIT {limite}"
    if not termo_busca:
        query += " ORDER BY Data_Hora DESC"

    query += f" LIMIT {limite}"

    try:
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        print(f"❌ Erro ao executar consulta: {e}")
        conn.close()
        return pd.DataFrame()

if __name__ == "__main__":
    print("=== Sistema de Consulta de Ofertas ===")
    termo = input("Digite o produto para buscar (ou Enter para todos): ").strip()
    
    resultados = consultar_itens(termo_busca=termo if termo else None)

    if not resultados.empty:
        print(f"\n🔍 Encontrados {len(resultados)} resultados:")
        # Abrevia o nome do produto para 30 caracteres para melhor exibição no terminal
        if 'Produto' in resultados.columns:
            resultados['Produto'] = resultados['Produto'].apply(lambda x: (x[:27] + '...') if len(str(x)) > 30 else x)
        # Exibe todas as colunas disponíveis no DataFrame
        print(resultados.to_string(index=False))
    else:
        print("\n⚠️ Nenhum item encontrado para os critérios informados.")
