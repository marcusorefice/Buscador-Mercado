from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import os
import base64
import re
import unicodedata
import threading
import uvicorn
import httpx
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from typing import List, Optional
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager, contextmanager
from dotenv import load_dotenv
from ofertas_sql import criar_visoes, sql_agregados

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
# Peso do "de/por" de um mercado só no ranking da tela inicial. O foco do app é comparar mercados, e o
# preço "de" informado pelo site às vezes é inflado; 0.5 = metade do peso de uma economia entre mercados.
PESO_DE_POR = 0.5
# Ranking "Em alta": janela de popularidade e mínimo de mercados para aparecer na tela inicial
DIAS_POPULARIDADE = 30
MIN_MERCADOS_EM_ALTA = 3
# Categorias que não são de compra do dia a dia: no "Em alta" pesam menos (até terem buscas de verdade)
RE_CATEGORIAS_FORA_DA_LISTA = "BAZAR|UTILIDADE|CASA|DECORA|ELETR|PAPELARIA|BRINQUED|AUTOMOTIV|FERRAMENT|FLORICULT|INFORMATIC"

_pool: Optional[ThreadedConnectionPool] = None
_pool_lock = threading.Lock()

def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(1, 10, DB_URL, cursor_factory=RealDictCursor)
    return _pool

# --- Interesse dos usuários (buscas e produtos abertos), usado no ranking "Em alta" ---
_tabelas_interesse_ok = False

def _garantir_tabelas_interesse(cursor):
    global _tabelas_interesse_ok
    if _tabelas_interesse_ok:
        return
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS buscas_dia (termo TEXT, dia DATE, vezes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (termo, dia));
        CREATE TABLE IF NOT EXISTS visualizacoes_dia (ean TEXT, dia DATE, vezes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (ean, dia));
    """)
    _tabelas_interesse_ok = True

def _normalizar_termo(termo):
    termo = unicodedata.normalize("NFKD", str(termo)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", termo).strip()

def _registrar_busca(termo):
    """Roda em segundo plano: contagem nunca pode atrasar nem derrubar a resposta."""
    termo = _normalizar_termo(termo)
    if len(termo) < 3 or termo.replace(" ", "").isdigit():
        return
    try:
        with get_db_cursor() as cursor:
            _garantir_tabelas_interesse(cursor)
            cursor.execute("""INSERT INTO buscas_dia (termo, dia, vezes) VALUES (%s, CURRENT_DATE, 1)
                              ON CONFLICT (termo, dia) DO UPDATE SET vezes = buscas_dia.vezes + 1""", (termo[:80],))
    except Exception as e:
        print(f"Erro ao registrar busca: {e}")

def _registrar_visualizacao(ean):
    try:
        with get_db_cursor() as cursor:
            _garantir_tabelas_interesse(cursor)
            cursor.execute("""INSERT INTO visualizacoes_dia (ean, dia, vezes) VALUES (%s, CURRENT_DATE, 1)
                              ON CONFLICT (ean, dia) DO UPDATE SET vezes = visualizacoes_dia.vezes + 1""", (ean[:80],))
    except Exception as e:
        print(f"Erro ao registrar visualização: {e}")

# --- Ofertas válidas e resumo por produto: pré-calculados no passo 5 (ver ofertas_sql.py) ---
_visoes_ok = False

def _garantir_visoes(cursor):
    """Se o passo 5 ainda não criou as visões (banco novo), cria aqui na primeira consulta."""
    global _visoes_ok
    if not _visoes_ok:
        criar_visoes(cursor)
        _visoes_ok = True

# Imagens: os sites entregam a foto original (até 1-2 MB). O card mostra uns 150 px, então pede uma
# versão de 300 px ao próprio servidor de imagens do mercado (VTEX e Pão de Açúcar sabem redimensionar).
RE_IMAGEM_VTEX = re.compile(r"(/arquivos/ids/\d+)(/)")

def _miniatura(url):
    if not url:
        return url
    if "/arquivos/ids/" in url:
        return RE_IMAGEM_VTEX.sub(r"\g<1>-300-300\g<2>", url, count=1)
    if "paodeacucar.com/img/" in url and "?" not in url:
        return url + "?ims=300x"
    return url

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

# A lista da tela inicial tem ~450 KB de JSON; comprimida fica ~55 KB (faz diferença no 4G)
app.add_middleware(GZipMiddleware, minimum_size=1000)

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

COLUNAS_OFERTA = """p.ean, p.nome_comum, p.categoria, p.marca, p.imagem, p.tags,
                   v.mercado, v.nome_original, v.preco_varejo, v.preco_atacado,
                   v.qtd_valor, v.medida, v.unidade, v.condicao, v.data_atualizacao, v.link_pdp,
                   v.preco_efetivo"""

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
                "Imagem": _miniatura(row["imagem"] or ""),
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
    background_tasks: BackgroundTasks,
    q: str = Query(None, description="Busca por nome do produto ou marca"),
    sort_by: str = Query("discount", description="Ordenação: relevance (em alta), discount ou price"),
    market: str = Query(None, description="Filtrar por mercado específico")
):
    params_texto = []
    where_clauses = []
    e_busca_ean = bool(q) and q.isdigit() and len(q) >= 8
    if q and not e_busca_ean:
        background_tasks.add_task(_registrar_busca, q)

    if q:
        # Se a busca for um número longo, trata como busca exata por EAN (usado pelo scanner e pelo modal de detalhes)
        if e_busca_ean:
            # Também acha as variantes separadas pelo passo 4 (ex: 7891991015462_LATA)
            where_clauses.append(r"(p.ean = %s OR p.ean LIKE %s)")
            params_texto.extend([q, q + r"\_%"])
        else:
            # Permite múltiplas palavras-chave
            for termo in q.split():
                where_clauses.append('(p.nome_comum ILIKE %s OR o.nome_original ILIKE %s OR p.marca ILIKE %s OR p.tags ILIKE %s)')
                params_texto.extend([f"%{termo}%"] * 4)

    filtro_mercado = bool(market) and market.lower() != "todos os mercados"
    candidatos = ""
    if where_clauses:
        candidatos = f"ean IN (SELECT p.ean FROM produtos p JOIN ofertas_atuais o ON p.ean = o.ean WHERE {' AND '.join(where_clauses)})"

    # Resumo de preço de cada produto: já vem pronto do banco (resumo_produtos); com filtro de mercado é
    # recalculado só com as ofertas daquele mercado, o que é rápido porque elas já estão prontas em ofertas_validas
    if filtro_mercado:
        # qtd_mercados continua sendo de todos os mercados: dentro de um só, todo produto teria 1 oferta
        origem = "SELECT * FROM ofertas_validas WHERE mercado = %s" + (f" AND {candidatos}" if candidatos else "")
        agregadas_sql = f"SELECT m.*, r.qtd_ofertas AS qtd_mercados FROM ({sql_agregados(origem)}) m JOIN resumo_produtos r ON r.ean = m.ean"
        params = [market] + params_texto
    else:
        agregadas_sql = "SELECT *, qtd_ofertas AS qtd_mercados FROM resumo_produtos" + (f" WHERE {candidatos}" if candidatos else "")
        params = list(params_texto)

    # "discount" = quanto a oferta mais barata está abaixo da MEDIANA das outras do mesmo produto (já sem as
    # fora da curva). Com só 2 ofertas e diferença acima de 2x não dá para saber qual está errada, então o
    # produto não é promovido. Num mercado só, usa o "de/por" da oferta com peso menor (PESO_DE_POR).
    economia_sql = f'''
            CASE
                WHEN qtd_ofertas = 2 AND maior_preco > menor_preco * 2 THEN 0
                WHEN qtd_ofertas > 1 AND mediana_outros > 0 THEN GREATEST(mediana_outros - menor_preco, 0) / mediana_outros
                WHEN maior_varejo > 0 AND menor_preco IS NOT NULL THEN {PESO_DE_POR} * GREATEST(maior_varejo - menor_preco, 0) / maior_varejo
                ELSE 0
            END'''
    filtro_relevancia = ""
    if sort_by == "price":
        order_sql = "menor_preco ASC NULLS LAST, a.ean"
    elif sort_by == "relevance":
        # "Em alta": produto que muita gente procura E é vendido em vários mercados, com peso para a economia.
        #  - quantos mercados vendem: Coca, leite e arroz estão em 6-8 mercados; itens obscuros em 1-2
        #  - quantas vezes foi aberto no app nos últimos 30 dias (cresce com o uso)
        #  - economia: o produto aparece mesmo com pouca economia, mas quanto maior, mais alto
        order_sql = f'''
            (0.15 + {economia_sql}) * LN(1 + qtd_mercados) * (1 + LN(1 + COALESCE(pop.vezes, 0)))
                * CASE WHEN UPPER(COALESCE(prod.categoria, '')) ~ '{RE_CATEGORIAS_FORA_DA_LISTA}' THEN 0.3 ELSE 1 END DESC,
            menor_preco ASC NULLS LAST, a.ean
        '''
        if q and not e_busca_ean:
            # Numa busca, primeiro o que É o produto buscado: "leite" traz antes "Leite Integral..." (nome começa
            # com o termo), depois "Doce de Leite..." (palavra no nome) e só no fim o que casou pela marca,
            # tags ou nome do mercado (ex: chocolate "ao leite")
            order_sql = '''
            CASE WHEN prod.nome_comum ILIKE %s THEN 2 WHEN ' ' || prod.nome_comum ILIKE %s THEN 1 ELSE 0 END DESC,
            ''' + order_sql
            termo = q.strip().replace("\\", "").replace("%", "").replace("_", "")
            params += [f"{termo}%", f"% {termo}%"]
        else:
            filtro_relevancia = f"WHERE qtd_mercados >= {MIN_MERCADOS_EM_ALTA}"
    else:
        order_sql = f"{economia_sql} DESC, menor_preco ASC NULLS LAST, a.ean"

    # 1º calcula o ranking e corta em 200 DENTRO do banco; 2º busca as ofertas só desses produtos.
    query_ranking = f'''
        WITH agregadas AS ({agregadas_sql}),
        popularidade AS (
            SELECT ean, SUM(vezes) AS vezes FROM visualizacoes_dia
            WHERE dia >= CURRENT_DATE - {DIAS_POPULARIDADE} GROUP BY ean
        )
        SELECT a.ean FROM agregadas a
        LEFT JOIN popularidade pop ON pop.ean = a.ean
        LEFT JOIN produtos prod ON prod.ean = a.ean
        {filtro_relevancia}
        ORDER BY {order_sql}
        LIMIT {LIMITE_PRODUTOS}
    '''

    with get_db_cursor() as cursor:
        _garantir_tabelas_interesse(cursor)
        _garantir_visoes(cursor)
        cursor.execute(query_ranking, params)
        eans_ordenados = [r["ean"] for r in cursor.fetchall()]
        if not eans_ordenados:
            return []

        # Ofertas válidas só dos produtos do ranking, respeitando o mesmo filtro de mercado
        cursor.execute(f'''
            SELECT {COLUNAS_OFERTA}
            FROM ofertas_validas v JOIN produtos p ON p.ean = v.ean
            WHERE v.ean = ANY(%s) {"AND v.mercado = %s" if filtro_mercado else ""}
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
        _garantir_visoes(cursor)
        cursor.execute(f'''
            SELECT {COLUNAS_OFERTA}
            FROM ofertas_validas v JOIN produtos p ON p.ean = v.ean
            WHERE v.ean = ANY(%s)
        ''', (lista,))
        rows = cursor.fetchall()
    return _montar_produtos(rows)

@app.get("/buscas-populares")
def buscas_populares(limite: int = Query(8, ge=1, le=20)):
    """Termos mais buscados por todos os usuários nos últimos dias (chips da tela inicial)."""
    try:
        with get_db_cursor() as cursor:
            _garantir_tabelas_interesse(cursor)
            cursor.execute(f"""
                SELECT termo FROM buscas_dia WHERE dia >= CURRENT_DATE - {DIAS_POPULARIDADE}
                GROUP BY termo HAVING SUM(vezes) >= 2
                ORDER BY SUM(vezes) DESC, termo LIMIT %s
            """, (limite,))
            return {"termos": [r["termo"] for r in cursor.fetchall()]}
    except Exception as e:
        print(f"Erro em buscas populares: {e}")
        return {"termos": []}

@app.get("/produtos/{ean}/historico")
def obter_historico(ean: str, background_tasks: BackgroundTasks):
    # O app pede o histórico quando a pessoa abre um produto: conta como visualização para o "Em alta"
    background_tasks.add_task(_registrar_visualizacao, ean)
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
