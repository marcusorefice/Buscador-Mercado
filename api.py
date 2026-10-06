from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import base64
import threading
import uvicorn
import httpx
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from typing import List, Optional
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager, contextmanager
from dotenv import load_dotenv

load_dotenv()

# URL do Banco de Dados Supabase (PostgreSQL)
DB_URL = os.getenv("DATABASE_URL")
# Webhook do Discord para sugestões/bugs (fica só no servidor, nunca no app)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
# Typesense (autocomplete da busca). O app não fala direto com ele: o Android bloqueia HTTP sem
# criptografia nos APKs, então a API (HTTPS) faz a consulta e devolve só as sugestões.
TYPESENSE_URL = f'{os.getenv("TYPESENSE_PROTOCOL", "http")}://{os.getenv("TYPESENSE_HOST", "34.16.54.234")}:{os.getenv("TYPESENSE_PORT", "8108")}'
TYPESENSE_SEARCH_KEY = os.getenv("TYPESENSE_SEARCH_KEY")

LIMITE_PRODUTOS = 200
# Com 3 ou mais ofertas, a que estiver acima de FATOR_OUTLIER x a mediana do produto (ou abaixo de mediana / FATOR)
# é descartada: quase sempre é kit, combo, pack não detectado ou cadastro errado do mercado.
FATOR_OUTLIER = 2.5
# Peso do "de/por" de um mercado só no ranking da tela inicial. O foco do app é comparar mercados, e o
# preço "de" informado pelo site às vezes é inflado; 0.5 = metade do peso de uma economia entre mercados.
PESO_DE_POR = 0.5

_pool: Optional[ThreadedConnectionPool] = None
_pool_lock = threading.Lock()

def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(1, 10, DB_URL, cursor_factory=RealDictCursor)
    return _pool

@contextmanager
def get_db_cursor():
    """Pega uma conexão do pool e devolve sempre, mesmo se der erro."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cursor:
            yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Iniciando a nova API Agrupada do Comparador de Preços...")
    yield
    if _pool is not None:
        _pool.closeall()
    print("Encerrando a API...")

app = FastAPI(title="Comparador de Preços API - V2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class OfertaResponse(BaseModel):
    Mercado: str
    Preco_Varejo: float
    Preco_Atacado: float
    Nome_Original: str
    Qtd_Valor: str
    Medida: str
    Unidade: str
    Condicao: str
    Data_Atualizacao: str
    Link_PDP: Optional[str] = ""

@app.get("/")
def read_root():
    return {"status": "ONLINE", "mensagem": "API do Comparador de Preços funcionando perfeitamente!"}

class ProdutoAgrupadoResponse(BaseModel):
    EAN: str
    Produto_Ouro: str
    Categoria_Ouro: str
    Marca: str
    Imagem: str
    Tags: List[str]
    Menor_Preco: float
    Ofertas: List[OfertaResponse]

@app.get("/debug")
def debug_connection():
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as qtd FROM ofertas_atuais")
            qtd = cursor.fetchone()["qtd"]
        return {"status": "SUCESSO", "ofertas_na_nuvem": qtd, "url_configurada": bool(DB_URL)}
    except Exception as e:
        print(f"Erro no /debug: {e}")
        return {"status": "ERRO", "url_configurada": bool(DB_URL)}

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

COLUNAS_OFERTA = """p.ean, p.nome_comum, p.categoria, p.marca, p.imagem, p.tags,
                   v.mercado, v.nome_original, v.preco_varejo, v.preco_atacado,
                   v.qtd_valor, v.medida, v.unidade, v.condicao, v.data_atualizacao, v.link_pdp,
                   v.preco_efetivo"""

def _sql_ofertas_validas(eans_candidatos_sql):
    """
    CTEs que produzem `validas`: as ofertas dos produtos candidatos, já sem as que fogem da curva.
    A mediana é calculada com TODAS as ofertas do produto (de todos os mercados), mesmo quando há filtro.
    """
    return f'''
        base AS (
            SELECT o.*, NULLIF({SQL_PRECO_EFETIVO}, 0) AS preco_efetivo,
                   o.preco_varejo / ({SQL_UNIDADES_PACK}) AS preco_varejo_unidade
            FROM ofertas_atuais o
            WHERE o.ean IN ({eans_candidatos_sql})
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
        ),
        validas AS (
            SELECT b.*, m.n AS ofertas_do_produto
            FROM mesma_unidade b JOIN medianas m ON m.ean = b.ean
            WHERE m.n < 3 OR b.preco_efetivo BETWEEN m.mediana / {FATOR_OUTLIER} AND m.mediana * {FATOR_OUTLIER}
        )
    '''

def _montar_produtos(rows):
    """Agrupa as linhas (produto x oferta) por EAN, mantendo a ordem em que os EANs chegaram."""
    agrupados = {}
    for row in rows:
        ean = row["ean"]
        if ean not in agrupados:
            raw_tags = row["tags"]
            agrupados[ean] = {
                "EAN": ean,
                "Produto_Ouro": row["nome_comum"] or "Produto Sem Nome",
                "Categoria_Ouro": row["categoria"] or "OUTROS",
                "Marca": row["marca"] or "",
                "Imagem": row["imagem"] or "",
                "Tags": [t.strip() for t in raw_tags.split(',')] if raw_tags else [],
                "Ofertas": [],
                "_precos": [],
            }
        preco_efetivo = float(row["preco_efetivo"]) if row["preco_efetivo"] and row["preco_efetivo"] > 0 else None
        agrupados[ean]["_precos"].append(preco_efetivo)
        agrupados[ean]["Ofertas"].append({
            "Mercado": row["mercado"] or "Desconhecido",
            "Preco_Varejo": float(row["preco_varejo"]) if row["preco_varejo"] else 0.0,
            "Preco_Atacado": float(row["preco_atacado"]) if row["preco_atacado"] else 0.0,
            "Nome_Original": row["nome_original"] or "",
            "Qtd_Valor": row["qtd_valor"] or "1",
            "Medida": row["medida"] or "UN",
            "Unidade": row["unidade"] or "UN",
            "Condicao": row["condicao"] or "",
            "Data_Atualizacao": row["data_atualizacao"] or "",
            "Link_PDP": row["link_pdp"] or "",
        })

    result = []
    for data in agrupados.values():
        precos = data.pop("_precos")
        # Ordena as ofertas do mais barato para o mais caro (ofertas sem preço vão para o fim)
        pares = sorted(zip(precos, data["Ofertas"]), key=lambda x: x[0] if x[0] is not None else float("inf"))
        data["Ofertas"] = [o for _, o in pares]
        validos = [p for p in precos if p is not None]
        data["Menor_Preco"] = min(validos) if validos else 0.0
        result.append(ProdutoAgrupadoResponse(**data))
    return result

@app.get("/produtos", response_model=List[ProdutoAgrupadoResponse])
def get_produtos(
    q: str = Query(None, description="Busca por nome do produto ou marca"),
    sort_by: str = Query("discount", description="Ordenação: discount ou price"),
    market: str = Query(None, description="Filtrar por mercado específico")
):
    params = []
    where_clauses = []

    if q:
        # Se a busca for um número longo, trata como busca exata por EAN (usado pelo scanner e pelo modal de detalhes)
        if q.isdigit() and len(q) >= 8:
            # Também acha as variantes separadas pelo passo 4 (ex: 7891991015462_LATA)
            where_clauses.append(r"(p.ean = %s OR p.ean LIKE %s)")
            params.extend([q, q + r"\_%"])
        else:
            # Permite múltiplas palavras-chave
            for termo in q.split():
                where_clauses.append('(p.nome_comum ILIKE %s OR o.nome_original ILIKE %s OR p.marca ILIKE %s OR p.tags ILIKE %s)')
                params.extend([f"%{termo}%"] * 4)

    if market and market.lower() != "todos os mercados":
        where_clauses.append('o.mercado = %s')
        params.append(market)

    where_sql = (' WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

    filtro_mercado = market and market.lower() != "todos os mercados"

    # "discount" = quanto a oferta mais barata está abaixo da MEDIANA das outras do mesmo produto (já sem as
    # fora da curva). Com só 2 ofertas e diferença acima de 2x não dá para saber qual está errada, então o
    # produto não é promovido. Num mercado só, usa o "de/por" da oferta com peso menor (PESO_DE_POR).
    if sort_by == "price":
        order_sql = "menor_preco ASC NULLS LAST, ean"
    else:
        order_sql = f'''
            CASE
                WHEN qtd_ofertas = 2 AND maior_preco > menor_preco * 2 THEN 0
                WHEN qtd_ofertas > 1 AND mediana_outros > 0 THEN GREATEST(mediana_outros - menor_preco, 0) / mediana_outros
                WHEN maior_varejo > 0 AND menor_preco IS NOT NULL THEN {PESO_DE_POR} * GREATEST(maior_varejo - menor_preco, 0) / maior_varejo
                ELSE 0
            END DESC, menor_preco ASC NULLS LAST, ean
        '''

    # 1º calcula o ranking e corta em 200 DENTRO do banco; 2º busca as ofertas só desses produtos.
    candidatos = f"SELECT p.ean FROM produtos p JOIN ofertas_atuais o ON p.ean = o.ean {where_sql}"
    query_ranking = f'''
        WITH {_sql_ofertas_validas(candidatos)},
        ordenadas AS (
            SELECT v.*, ROW_NUMBER() OVER (PARTITION BY ean ORDER BY preco_efetivo) AS posicao
            FROM validas v
            {"WHERE mercado = %s" if filtro_mercado else ""}
        ),
        agregadas AS (
            SELECT ean,
                   MIN(preco_efetivo) AS menor_preco,
                   MAX(preco_efetivo) AS maior_preco,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY preco_efetivo) FILTER (WHERE posicao > 1) AS mediana_outros,
                   MAX(preco_varejo_unidade) AS maior_varejo,
                   COUNT(*) AS qtd_ofertas
            FROM ordenadas
            GROUP BY ean
        )
        SELECT ean FROM agregadas
        ORDER BY {order_sql}
        LIMIT {LIMITE_PRODUTOS}
    '''

    with get_db_cursor() as cursor:
        cursor.execute(query_ranking, params + ([market] if filtro_mercado else []))
        eans_ordenados = [r["ean"] for r in cursor.fetchall()]
        if not eans_ordenados:
            return []

        # Ofertas válidas só dos produtos do ranking, respeitando o mesmo filtro de mercado
        cursor.execute(f'''
            WITH {_sql_ofertas_validas("SELECT unnest(%s::text[])")}
            SELECT {COLUNAS_OFERTA}
            FROM validas v JOIN produtos p ON p.ean = v.ean
            {"WHERE v.mercado = %s" if filtro_mercado else ""}
        ''', [eans_ordenados] + ([market] if filtro_mercado else []))
        rows = cursor.fetchall()

    posicao = {ean: i for i, ean in enumerate(eans_ordenados)}
    rows.sort(key=lambda r: posicao[r["ean"]])
    return _montar_produtos(rows)

@app.get("/produtos/lote", response_model=List[ProdutoAgrupadoResponse])
def get_produtos_lote(eans: str = Query(..., description="EANs separados por vírgula (máx. 200)")):
    """Usado pela lista de compras para atualizar os preços dos itens salvos no celular."""
    lista = [e.strip() for e in eans.split(',') if e.strip()][:LIMITE_PRODUTOS]
    if not lista:
        return []
    with get_db_cursor() as cursor:
        cursor.execute(f'''
            WITH {_sql_ofertas_validas("SELECT unnest(%s::text[])")}
            SELECT {COLUNAS_OFERTA}
            FROM validas v JOIN produtos p ON p.ean = v.ean
        ''', (lista,))
        rows = cursor.fetchall()
    return _montar_produtos(rows)

@app.get("/produtos/{ean}/historico")
def obter_historico(ean: str):
    # data_hora é gravado em ISO (AAAA-MM-DD HH:MM:SS), então ordenar o texto ordena por data
    with get_db_cursor() as cursor:
        cursor.execute("""
            SELECT mercado,
                   CASE
                       WHEN preco_atacado > 0 AND preco_varejo > 0 THEN LEAST(preco_atacado, preco_varejo)
                       WHEN preco_atacado > 0 THEN preco_atacado
                       ELSE preco_varejo
                   END as preco,
                   data_hora
            FROM historico_precos
            WHERE ean = %s
            ORDER BY data_hora DESC
            LIMIT 50
        """, (ean,))
        return cursor.fetchall()

class SugestaoRequest(BaseModel):
    texto: str = Field(..., min_length=1, max_length=2000)
    imagem_base64: Optional[str] = None
    imagem_nome: Optional[str] = "print.jpg"

MAX_IMAGEM_BYTES = 8 * 1024 * 1024  # limite de anexo do Discord

@app.get("/autocompletar")
def autocompletar(q: str = Query(..., min_length=1, max_length=100)):
    """Sugestões de nome de produto enquanto a pessoa digita (Typesense)."""
    if not TYPESENSE_SEARCH_KEY:
        raise HTTPException(status_code=503, detail="Autocomplete não configurado.")
    try:
        resp = httpx.get(
            f"{TYPESENSE_URL}/collections/produtos/documents/search",
            params={"q": q, "query_by": "nome_comum,marca,tags", "per_page": 8, "prefix": "true"},
            headers={"X-TYPESENSE-API-KEY": TYPESENSE_SEARCH_KEY},
            timeout=3,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Erro no Typesense: {e}")
        raise HTTPException(status_code=502, detail="Autocomplete indisponível.")
    sugestoes = []
    for hit in resp.json().get("hits", []):
        nome = hit.get("document", {}).get("nome_comum")
        if nome and nome not in sugestoes:
            sugestoes.append(nome)
    return {"sugestoes": sugestoes[:6]}

@app.post("/sugestoes")
def enviar_sugestao(sugestao: SugestaoRequest):
    """Repassa a sugestão do app para o Discord. A URL do webhook nunca sai do servidor."""
    if not DISCORD_WEBHOOK_URL:
        raise HTTPException(status_code=503, detail="Envio de sugestões não configurado.")

    data = {"content": f"💡 **Nova Sugestão / Bug:**\n{sugestao.texto}"}
    files = None
    if sugestao.imagem_base64:
        try:
            imagem = base64.b64decode(sugestao.imagem_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Imagem inválida.")
        if len(imagem) > MAX_IMAGEM_BYTES:
            raise HTTPException(status_code=413, detail="Imagem muito grande.")
        nome = os.path.basename(sugestao.imagem_nome or "print.jpg")
        ext = nome.rsplit('.', 1)[-1].lower() if '.' in nome else 'jpeg'
        files = {"file": (nome, imagem, f"image/{'jpeg' if ext == 'jpg' else ext}")}

    try:
        resp = httpx.post(DISCORD_WEBHOOK_URL, data=data, files=files, timeout=20)
    except httpx.HTTPError as e:
        print(f"Erro ao enviar sugestão ao Discord: {e}")
        raise HTTPException(status_code=502, detail="Falha ao enviar a sugestão.")
    if resp.status_code >= 300:
        print(f"Discord respondeu {resp.status_code}: {resp.text[:200]}")
        raise HTTPException(status_code=502, detail="Falha ao enviar a sugestão.")
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
