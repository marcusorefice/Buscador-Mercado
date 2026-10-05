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

LIMITE_PRODUTOS = 200

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

# Unidades do produto na oferta (pack vendido com o EAN da unidade, ex: Red Bull "4 LATAS" -> 4)
SQL_UNIDADES_PACK = '''
    CASE WHEN o.medida = 'UN' AND o.qtd_valor ~ '^[0-9]+$' THEN GREATEST(CAST(o.qtd_valor AS INTEGER), 1) ELSE 1 END
'''

# Preço efetivo POR UNIDADE: o menor valor > 0 entre varejo e atacado, dividido pelas unidades do pack
SQL_PRECO_EFETIVO = f'''
    (CASE
        WHEN o.preco_atacado > 0 AND o.preco_varejo > 0 THEN LEAST(o.preco_atacado, o.preco_varejo)
        WHEN o.preco_atacado > 0 THEN o.preco_atacado
        ELSE o.preco_varejo
    END) / ({SQL_UNIDADES_PACK})
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

    # "discount" = economia real: diferença entre o mercado mais caro e o mais barato para o MESMO produto.
    # Quando só há um mercado (ex: filtro por mercado), usa o "de/por" da própria oferta.
    if sort_by == "price":
        order_sql = "menor_preco ASC NULLS LAST, ean"
    else:
        order_sql = '''
            CASE
                WHEN qtd_ofertas > 1 AND maior_preco > 0 THEN (maior_preco - menor_preco) / maior_preco
                WHEN maior_varejo > 0 AND menor_preco IS NOT NULL THEN GREATEST(maior_varejo - menor_preco, 0) / maior_varejo
                ELSE 0
            END DESC, menor_preco ASC NULLS LAST, ean
        '''

    # 1º calcula o ranking e corta em 200 DENTRO do banco; 2º busca as ofertas só desses produtos.
    query_ranking = f'''
        WITH filtradas AS (
            SELECT o.ean, o.mercado, o.preco_varejo / ({SQL_UNIDADES_PACK}) AS preco_varejo, NULLIF({SQL_PRECO_EFETIVO}, 0) AS preco_efetivo
            FROM produtos p
            JOIN ofertas_atuais o ON p.ean = o.ean
            {where_sql}
        ),
        agregadas AS (
            SELECT ean,
                   MIN(preco_efetivo) AS menor_preco,
                   MAX(preco_efetivo) AS maior_preco,
                   MAX(preco_varejo) AS maior_varejo,
                   COUNT(*) AS qtd_ofertas
            FROM filtradas
            GROUP BY ean
        )
        SELECT ean FROM agregadas
        ORDER BY {order_sql}
        LIMIT {LIMITE_PRODUTOS}
    '''

    with get_db_cursor() as cursor:
        cursor.execute(query_ranking, params)
        eans_ordenados = [r["ean"] for r in cursor.fetchall()]
        if not eans_ordenados:
            return []

        # Busca as ofertas só dos produtos do ranking, respeitando o mesmo filtro de mercado
        filtro_mercado = ''
        params_ofertas = [eans_ordenados]
        if market and market.lower() != "todos os mercados":
            filtro_mercado = ' AND o.mercado = %s'
            params_ofertas.append(market)
        cursor.execute(f'''
            SELECT p.ean, p.nome_comum, p.categoria, p.marca, p.imagem, p.tags,
                   o.mercado, o.nome_original, o.preco_varejo, o.preco_atacado,
                   o.qtd_valor, o.medida, o.unidade, o.condicao, o.data_atualizacao, o.link_pdp,
                   {SQL_PRECO_EFETIVO} AS preco_efetivo
            FROM produtos p
            JOIN ofertas_atuais o ON p.ean = o.ean
            WHERE p.ean = ANY(%s){filtro_mercado}
        ''', params_ofertas)
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
            SELECT p.ean, p.nome_comum, p.categoria, p.marca, p.imagem, p.tags,
                   o.mercado, o.nome_original, o.preco_varejo, o.preco_atacado,
                   o.qtd_valor, o.medida, o.unidade, o.condicao, o.data_atualizacao, o.link_pdp,
                   {SQL_PRECO_EFETIVO} AS preco_efetivo
            FROM produtos p
            JOIN ofertas_atuais o ON p.ean = o.ean
            WHERE p.ean = ANY(%s)
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
