"""
Cálculo das ofertas válidas e do resumo de preço de cada produto (usado pela API e pelo passo 5).

Calcular a mediana de todas as ~77 mil ofertas a cada abertura do app levava mais de 1 s por consulta.
Por isso o resultado fica guardado em duas visões materializadas, recalculadas no fim do passo 5
(única etapa que muda as ofertas):
  - ofertas_validas: as ofertas sem as que fogem da curva, já com o preço efetivo por unidade/kg
  - resumo_produtos: menor preço, maior preço, mediana das outras ofertas etc. de cada produto
"""

# Com 3 ou mais ofertas, a que estiver acima de FATOR_OUTLIER x a mediana do produto (ou abaixo de mediana / FATOR)
# é descartada: quase sempre é kit, combo, pack não detectado ou cadastro errado do mercado.
FATOR_OUTLIER = 2.5

# Por quanto dividir o preço da oferta para chegar ao preço comparável:
#  - pack vendido com o EAN da unidade (Red Bull "4 LATAS") -> 4 unidades
#  - item vendido por peso: o preço gravado é o da peça/embalagem, Qtd_Valor é o peso dela -> preço por kg
#    (ex: queijo no Oba: peça de 0,2 kg por R$ 29,98 -> R$ 149,90/kg)
SQL_UNIDADES_PACK = '''
    CASE
        WHEN o.medida = 'UN' AND o.qtd_valor ~ '^[0-9]+$' THEN GREATEST(CAST(o.qtd_valor AS INTEGER), 1)
        WHEN UPPER(o.unidade) = 'KG' AND o.medida = 'KG' AND o.qtd_valor ~ '^[0-9]+([.][0-9]+)?$'
            THEN COALESCE(NULLIF(CAST(o.qtd_valor AS NUMERIC), 0), 1)
        WHEN UPPER(o.unidade) = 'KG' AND o.medida = 'G' AND o.qtd_valor ~ '^[0-9]+([.][0-9]+)?$'
            THEN COALESCE(NULLIF(CAST(o.qtd_valor AS NUMERIC), 0), 1000) / 1000
        ELSE 1
    END
'''

# Preço efetivo POR UNIDADE: o menor valor > 0 entre varejo e atacado, dividido pelas unidades do pack
SQL_PRECO_EFETIVO = f'''
    (CASE
        WHEN o.preco_atacado > 0 AND o.preco_varejo > 0 THEN LEAST(o.preco_atacado, o.preco_varejo)
        WHEN o.preco_atacado > 0 THEN o.preco_atacado
        ELSE o.preco_varejo
    END) / ({SQL_UNIDADES_PACK})
'''

# A mediana é calculada com TODAS as ofertas do produto (de todos os mercados)
SQL_OFERTAS_VALIDAS = f'''
    WITH base AS (
        SELECT o.ean, o.mercado, o.nome_original, o.preco_varejo, o.preco_atacado, o.condicao,
               o.data_atualizacao, o.link_pdp, o.qtd_valor, o.medida, o.unidade,
               NULLIF({SQL_PRECO_EFETIVO}, 0) AS preco_efetivo,
               o.preco_varejo / ({SQL_UNIDADES_PACK}) AS preco_varejo_unidade
        FROM ofertas_atuais o
    ),
    unidade_principal AS (
        -- Preço por KG e por unidade não se comparam: vale a unidade da maioria das ofertas do produto
        SELECT DISTINCT ON (ean) ean, unidade_norm
        FROM (SELECT ean, COALESCE(NULLIF(UPPER(unidade), ''), 'UN') AS unidade_norm, COUNT(*) AS qtd
              FROM base WHERE preco_efetivo IS NOT NULL GROUP BY 1, 2) c
        ORDER BY ean, qtd DESC, (unidade_norm = 'UN') DESC
    ),
    mesma_unidade AS (
        SELECT b.* FROM base b JOIN unidade_principal u ON u.ean = b.ean
        WHERE b.preco_efetivo IS NOT NULL AND COALESCE(NULLIF(UPPER(b.unidade), ''), 'UN') = u.unidade_norm
    ),
    medianas AS (
        SELECT ean, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY preco_efetivo) AS mediana, COUNT(*) AS n
        FROM mesma_unidade
        GROUP BY ean
    )
    SELECT b.*, m.n AS ofertas_do_produto
    FROM mesma_unidade b JOIN medianas m ON m.ean = b.ean
    WHERE m.n < 3 OR b.preco_efetivo BETWEEN m.mediana / {FATOR_OUTLIER} AND m.mediana * {FATOR_OUTLIER}
'''

# Agregados de um conjunto de ofertas válidas (`origem`), um por produto.
# mediana_outros = mediana das ofertas tirando a mais barata (base do "quanto economiza")
def sql_agregados(origem):
    return f'''
        SELECT ean,
               MIN(preco_efetivo) AS menor_preco,
               MAX(preco_efetivo) AS maior_preco,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY preco_efetivo) FILTER (WHERE posicao > 1) AS mediana_outros,
               MAX(preco_varejo_unidade) AS maior_varejo,
               COUNT(*) AS qtd_ofertas
        FROM (SELECT v.*, ROW_NUMBER() OVER (PARTITION BY ean ORDER BY preco_efetivo) AS posicao FROM ({origem}) v) ordenadas
        GROUP BY ean
    '''

def criar_visoes(cursor):
    """Cria as visões (se ainda não existirem) com seus índices."""
    cursor.execute(f"CREATE MATERIALIZED VIEW IF NOT EXISTS ofertas_validas AS {SQL_OFERTAS_VALIDAS}")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ofertas_validas_ean_mercado ON ofertas_validas (ean, mercado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ofertas_validas_mercado ON ofertas_validas (mercado)")
    cursor.execute(f"CREATE MATERIALIZED VIEW IF NOT EXISTS resumo_produtos AS {sql_agregados('SELECT * FROM ofertas_validas')}")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resumo_produtos_ean ON resumo_produtos (ean)")

def atualizar_visoes(cursor):
    """Recalcula as visões depois que as ofertas mudaram. CONCURRENTLY: o app continua lendo enquanto isso."""
    criar_visoes(cursor)
    cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY ofertas_validas")
    cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY resumo_produtos")
