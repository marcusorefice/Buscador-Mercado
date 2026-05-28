from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Optional
from pydantic import BaseModel
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# URL do Banco de Dados Supabase (PostgreSQL)
DB_URL = os.getenv("DATABASE_URL")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Iniciando a nova API Agrupada do Comparador de Preços...")
    yield
    print("Encerrando a API...")

app = FastAPI(title="Comparador de Preços API - V2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

def get_db_connection():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

@app.get("/debug")
def debug_connection():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as qtd FROM ofertas_atuais")
        qtd = cursor.fetchone()["qtd"]
        conn.close()
        return {"status": "SUCESSO", "ofertas_na_nuvem": qtd, "url_configurada": bool(DB_URL)}
    except Exception as e:
        return {"status": "ERRO", "detalhe": str(e), "url_configurada": bool(DB_URL)}

@app.get("/produtos", response_model=List[ProdutoAgrupadoResponse])
def get_produtos(
    q: str = Query(None, description="Busca por nome do produto ou marca"),
    sort_by: str = Query("discount", description="Ordenação: discount ou price"),
    market: str = Query(None, description="Filtrar por mercado específico")
):
    # Busca cruzando a Biblioteca Ouro com as Ofertas Atuais dos mercados
    query = '''
        SELECT p.ean, p.nome_comum, p.categoria, p.marca, p.imagem, p.tags,
               o.mercado, o.nome_original, o.preco_varejo, o.preco_atacado, 
               o.qtd_valor, o.medida, o.unidade, o.condicao, o.data_atualizacao, o.link_pdp
        FROM produtos p
        JOIN ofertas_atuais o ON p.ean = o.ean
    '''

    conn = get_db_connection()
    cursor = conn.cursor()
    params = []
    where_clauses = []

    if q:
        # Se a busca for um número longo, trata como busca exata por EAN (usado pelo modal de detalhes)
        if q.isdigit() and len(q) >= 8:
            where_clauses.append('p.ean = %s')
            params.append(q)
        else:
            # Permite múltiplas palavras-chave
            termos = q.split()
            for termo in termos:
                where_clauses.append('(p.nome_comum ILIKE %s OR o.nome_original ILIKE %s OR p.marca ILIKE %s OR p.tags ILIKE %s)')
                params.extend([f"%{termo}%", f"%{termo}%", f"%{termo}%", f"%{termo}%"])

    if market and market.lower() != "todos os mercados":
        where_clauses.append('o.mercado = %s')
        params.append(market)

    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    # Agrupa os resultados pelo EAN
    agrupados = {}
    for row in rows:
        ean = row["ean"]
        if ean not in agrupados:
            raw_tags = row["tags"]
            tags_list = [t.strip() for t in raw_tags.split(',')] if raw_tags else []
            
            agrupados[ean] = {
                "EAN": ean,
                "Produto_Ouro": row["nome_comum"] or "Produto Sem Nome",
                "Categoria_Ouro": row["categoria"] or "OUTROS",
                "Marca": row["marca"] or "",
                "Imagem": row["imagem"] or "",
                "Tags": tags_list,
                "Ofertas": []
            }
            
        oferta = {
            "Mercado": row["mercado"] or "Desconhecido",
            "Preco_Varejo": float(row["preco_varejo"]) if row["preco_varejo"] else 0.0,
            "Preco_Atacado": float(row["preco_atacado"]) if row["preco_atacado"] else 0.0,
            "Nome_Original": row["nome_original"] or "",
            "Qtd_Valor": row["qtd_valor"] or "1",
            "Medida": row["medida"] or "UN",
            "Unidade": row["unidade"] or "UN",
            "Condicao": row["condicao"] or "",
            "Data_Atualizacao": row["data_atualizacao"] or "",
            "Link_PDP": row["link_pdp"] or ""
        }
        agrupados[ean]["Ofertas"].append(oferta)

    result = []
    for data in agrupados.values():
        if not data["Ofertas"]:
            continue
            
        # Determina o menor preço de cada oferta (considerando varejo ou atacado se existir e for maior que 0)
        for o in data["Ofertas"]:
            p_varejo = o["Preco_Varejo"]
            p_atacado = o["Preco_Atacado"]
            # O preço efetivo mínimo dessa oferta é o menor valor > 0 entre varejo e atacado.
            precos_oferta = [p for p in (p_varejo, p_atacado) if p > 0]
            o["preco_efetivo"] = min(precos_oferta) if precos_oferta else 999999.0

        # Encontra o menor preço absoluto disponível hoje para esse EAN (entre todas as ofertas)
        menor_preco = min([o["preco_efetivo"] for o in data["Ofertas"]])
        data["Menor_Preco"] = menor_preco if menor_preco != 999999.0 else 0.0
        
        # Ordena a lista de ofertas do mais barato para o mais caro baseado no preço efetivo mínimo
        data["Ofertas"] = sorted(data["Ofertas"], key=lambda x: x["preco_efetivo"])
        
        # Removemos o campo auxiliar 'preco_efetivo' antes de retornar
        for o in data["Ofertas"]:
            del o["preco_efetivo"]
            
        result.append(ProdutoAgrupadoResponse(**data))
        
    # Calcula o desconto (diferença percentual) para ordenar os produtos
    def calcular_desconto(produto):
        precos_varejo = [o.Preco_Varejo for o in produto.Ofertas if o.Preco_Varejo > 0]
        if not precos_varejo:
            return 0.0
        maior_preco = max(precos_varejo)
        menor_preco = produto.Menor_Preco
        if maior_preco <= 0 or menor_preco >= maior_preco:
            return 0.0
        return (maior_preco - menor_preco) / maior_preco

    if sort_by == "price":
        # Ordena por Menor Preço Absoluto
        result = sorted(result, key=lambda x: x.Menor_Preco)
    else:
        # Ordena por Maior Desconto (Padrão)
        result = sorted(result, key=lambda x: calcular_desconto(x), reverse=True)
    
    # Limita o retorno para não travar o app
    return result[:200]

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
