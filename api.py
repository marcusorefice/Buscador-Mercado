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
    # Setup - run when the API starts
    print("Iniciando a API do Comparador de Preços...")
    yield
    # Cleanup - run when the API stops
    print("Encerrando a API...")

app = FastAPI(title="Comparador de Preços API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProdutoResponse(BaseModel):
    id: int
    Mercado: Optional[str]
    Categoria: Optional[str]
    Produto: Optional[str]
    Marca: Optional[str]
    Preco_Varejo: Optional[str]
    Preco_Atacado: Optional[str]
    Qtd_Valor: Optional[str]
    Medida: Optional[str]
    Unidade: Optional[str]
    Condicao: Optional[str]
    Validade: Optional[str]
    Data_Hora: Optional[str]
    Link_Imagem: Optional[str]

def get_db_connection():
    conn = sqlite3.connect(DB_NOME)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/produtos", response_model=List[ProdutoResponse])
def get_produtos(q: str = Query(None, description="Busca por nome do produto")):
    if not os.path.exists(DB_NOME):
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM ofertas'
    params = []
    
    if q:
        query += ' WHERE Produto LIKE ?'
        params.append(f"%{q}%")
        query += ' ORDER BY id DESC LIMIT 100'
    else:
        query += ' ORDER BY RANDOM() LIMIT 150'
    
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
        
    conn.close()
    
    result = []
    for row in rows:
        result.append(ProdutoResponse(
            id=row["id"],
            Mercado=row["Mercado"],
            Categoria=row["Categoria"],
            Produto=row["Produto"],
            Marca=row["Marca"],
            Preco_Varejo=str(row["Preço Varejo"]) if row["Preço Varejo"] is not None else None,
            Preco_Atacado=str(row["Preço Atacado"]) if row["Preço Atacado"] is not None else None,
            Qtd_Valor=str(row["Qtd_Valor"]) if row["Qtd_Valor"] is not None else None,
            Medida=row["Medida"],
            Unidade=row["Unidade"],
            Condicao=row["Condição"],
            Validade=row["Validade"],
            Data_Hora=row["Data_Hora"],
            Link_Imagem=row["Link_Imagem"]
        ))
    return result

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
