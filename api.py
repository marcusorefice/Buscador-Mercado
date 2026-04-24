from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import os
import uvicorn
from typing import List, Optional, Any
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
    Data_Hora: Optional[str]
    Link_Imagem: Optional[str]

def get_db_connection():
    conn = sqlite3.connect(DB_NOME)
    conn.row_factory = sqlite3.Row
    return conn

def get_value_from_row(row: sqlite3.Row, keys: List[str], default: Any = None) -> Optional[str]:
    """
    Tenta obter um valor de um objeto 'row' do sqlite de forma segura.
    Testa uma lista de possíveis nomes de chave (ex: "Preço Varejo", "Preco_Varejo").
    Retorna o valor como string, ou None se não for encontrado.
    """
    for key in keys:
        if key in row.keys():
            val = row[key]
            return str(val) if val is not None else None
    return default

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
        query += ' ORDER BY id DESC LIMIT 1000'
    else:
        # Retorna os itens com maior percentual de desconto.
        # Ampliado para 3000 para alimentar o cache do app "Onde mais tem?"
        query = """
            WITH PrecosNumericos AS (
                SELECT
                    id,
                    CAST(REPLACE(REPLACE("Preço Varejo", 'R$ ', ''), ',', '.') AS REAL) as preco_v,
                    CAST(REPLACE(REPLACE("Preço Atacado", 'R$ ', ''), ',', '.') AS REAL) as preco_a
                FROM ofertas
            )
            SELECT o.*
            FROM ofertas o
            JOIN PrecosNumericos pn ON o.id = pn.id
            WHERE pn.preco_v > 0 AND pn.preco_a > 0 AND pn.preco_v > pn.preco_a
            ORDER BY (pn.preco_v - pn.preco_a) / pn.preco_v DESC
            LIMIT 3000;
        """
    
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []
        
    conn.close()
    
    result = []
    for row in rows:
        produto_data = {
            "id": row["id"],
            "Mercado": get_value_from_row(row, ["Mercado"]),
            "Categoria": get_value_from_row(row, ["Categoria"]),
            "Produto": get_value_from_row(row, ["Produto"]),
            "Marca": get_value_from_row(row, ["Marca"]),
            "Preco_Varejo": get_value_from_row(row, ["Preço Varejo", "Preco_Varejo"]),
            "Preco_Atacado": get_value_from_row(row, ["Preço Atacado", "Preco_Atacado"]),
            "Qtd_Valor": get_value_from_row(row, ["Qtd_Valor"]),
            "Medida": get_value_from_row(row, ["Medida"]),
            "Unidade": get_value_from_row(row, ["Unidade"]),
            "Condicao": get_value_from_row(row, ["Condição", "Condicao"]),
            "Data_Hora": get_value_from_row(row, ["Data_Hora"]),
            "Link_Imagem": get_value_from_row(row, ["Link_Imagem"]),
        }
        result.append(ProdutoResponse(**produto_data))
    return result

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
