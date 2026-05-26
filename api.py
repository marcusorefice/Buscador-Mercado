from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import os
import uvicorn
from typing import List, Optional
from pydantic import BaseModel
from contextlib import asynccontextmanager

DATA_DIR = "data"
DB_NOME = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")

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
    Condicao: str
    Data_Atualizacao: str

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
    conn = sqlite3.connect(DB_NOME)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/produtos", response_model=List[ProdutoAgrupadoResponse])
def get_produtos(
    q: str = Query(None, description="Busca por nome do produto ou marca"),
    sort_by: str = Query("discount", description="Ordenação: discount ou price"),
    market: str = Query(None, description="Filtrar por mercado específico")
):
    if not os.path.exists(DB_NOME):
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Busca cruzando a Biblioteca Ouro com as Ofertas Atuais dos mercados
    query = '''
        SELECT p.ean, p.nome_comum, p.categoria, p.marca, p.imagem, p.tags,
               o.mercado, o.nome_original, o.preco_varejo, o.preco_atacado, o.condicao, o.data_atualizacao
        FROM produtos p
        JOIN ofertas_atuais o ON p.ean = o.ean
    '''
    
    params = []
    
    where_clauses = []
    if q:
        # Permite múltiplas palavras-chave
        termos = q.split()
        for termo in termos:
            where_clauses.append('(p.nome_comum LIKE ? OR o.nome_original LIKE ? OR p.marca LIKE ? OR p.tags LIKE ?)')
            params.extend([f"%{termo}%", f"%{termo}%", f"%{termo}%", f"%{termo}%"])
            
    if market and market.lower() != "todos os mercados":
        where_clauses.append('o.mercado = ?')
        params.append(market)

    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)
        
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Erro no banco de dados: {e}")
        conn.close()
        return []
        
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
            "Condicao": row["condicao"] or "",
            "Data_Atualizacao": row["data_atualizacao"] or ""
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
