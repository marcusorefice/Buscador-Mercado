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
    
    # --- Construção da Query Dinâmica ---
    # A query base é sempre a mesma, selecionando da tabela 'ofertas'.
    # A busca por texto usará LIKE, que não requer tabelas adicionais como FTS (causa do erro).
    query_parts = ["""
        SELECT Mercado, Categoria, Produto, Marca,
               Preco_Varejo AS "Preço Varejo",
               Preco_Atacado AS "Preço Atacado",
               Qtd_Valor, Medida, Condicao AS "Condição"
        FROM ofertas
    """]
    where_clauses = ["1=1"]
    params = []
    
    # A ordenação padrão é pela data mais recente. Se houver busca, ordena pelo preço.
    order_by_clause = "ORDER BY Data_Hora DESC"
    if termo_busca:
        order_by_clause = 'ORDER BY CAST(REPLACE(REPLACE(Preco_Atacado, \'R$ \', \'\'), \',\', \'.\') AS REAL) ASC, Produto ASC'

    if termo_busca:
        # Adiciona a condição de busca por texto nos campos Produto e Marca.
        where_clauses.append("(Produto LIKE ? OR Marca LIKE ?)")
        params.extend([f"%{termo_busca}%", f"%{termo_busca}%"])

    if mercado:
        where_clauses.append("Mercado = ?")
        params.append(mercado)
        
    if categoria:
        where_clauses.append("Categoria = ?")
        params.append(categoria)
    
    query_parts.append(f"WHERE {' AND '.join(where_clauses)}")
    query_parts.append(order_by_clause)
    if limite is not None:
        query_parts.append("LIMIT ?")
        params.append(limite)

    full_query = " ".join(query_parts)

    try:
        df = pd.read_sql_query(full_query, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        print(f"❌ Erro ao executar consulta: {e}")
        conn.close()
        return pd.DataFrame()

if __name__ == "__main__":
    print("=== Sistema de Consulta de Ofertas ===")
    termo = input("Digite o produto para buscar (ou Enter para todos): ").strip()

    if termo:
        # Para uma busca específica, removemos o limite para ver todos os resultados.
        resultados = consultar_itens(termo_busca=termo, limite=None)
    else:
        # Para uma visão geral, mostramos os 50 mais recentes.
        resultados = consultar_itens(limite=50)

    if not resultados.empty:
        print(f"\n🔍 Encontrados {len(resultados)} resultados:")
        # Abrevia o nome do produto para 30 caracteres para melhor exibição no terminal
        if 'Produto' in resultados.columns:
            resultados['Produto'] = resultados['Produto'].apply(lambda x: (x[:27] + '...') if len(str(x)) > 30 else x)
        # Exibe todas as colunas disponíveis no DataFrame
        print(resultados.to_string(index=False))
    else:
        print("\n⚠️ Nenhum item encontrado para os critérios informados.")
