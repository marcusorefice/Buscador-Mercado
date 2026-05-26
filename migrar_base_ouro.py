import os
import time
import numpy as np
from dotenv import load_dotenv
from google import genai
from utils import (
    limpar_ruido_produto,
    DESC_CATEGORIAS_MASTER,
    classificar_por_similaridade,
    PRIORITY_ANCHOR_RULES,
    read_json_file,
    write_json_file
)

load_dotenv()

lista_chaves = [k.strip().strip('"').strip("'") for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
indice_chave_atual = 0
client = genai.Client(api_key=lista_chaves[indice_chave_atual]) if lista_chaves else None

MODELO_EMBEDDING = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")
CACHE_EMBEDDINGS_FILE = os.path.join(DATA_DIR, "biblioteca_embeddings.json")

def _trocar_chave():
    global indice_chave_atual, client, lista_chaves
    num_chaves = len(lista_chaves)
    if num_chaves <= 1: return

    if num_chaves <= 2: 
        indice_chave_atual = (indice_chave_atual + 1) % num_chaves
    else:
        num_chaves_pagas = 2
        primeiro_indice_pago = num_chaves - num_chaves_pagas
        if indice_chave_atual >= primeiro_indice_pago:
            indice_relativo = (indice_chave_atual - primeiro_indice_pago + 1) % num_chaves_pagas
            indice_chave_atual = primeiro_indice_pago + indice_relativo
        else:
            indice_chave_atual += 1
            
    nova_chave = lista_chaves[indice_chave_atual]
    client = genai.Client(api_key=nova_chave)
    print(f"🔄 Chave rotacionada para o índice {indice_chave_atual}")

def get_embeddings_batch(textos, cache_emb):
    global client
    textos_faltantes = [t for t in textos if t not in cache_emb]
    if not textos_faltantes:
        return
    
    # Processa em lotes de 100 para evitar limitação de payload na API
    batch_size = 100
    for i in range(0, len(textos_faltantes), batch_size):
        lote = textos_faltantes[i:i+batch_size]
        print(f"Gerando embeddings para {len(lote)} itens...")
        
        sucesso = False
        tentativas = 0
        while not sucesso and tentativas < len(lista_chaves):
            try:
                res = client.models.embed_content(model=MODELO_EMBEDDING, contents=lote)
                for j, emb_obj in enumerate(res.embeddings):
                    cache_emb[lote[j]] = emb_obj.values
                sucesso = True
            except Exception as e:
                erro_str = str(e).upper()
                if "429" in erro_str or "QUOTA" in erro_str or "EXHAUSTED" in erro_str:
                    print(f"Aviso: Cota excedida na chave {indice_chave_atual}. Trocando...")
                    _trocar_chave()
                    tentativas += 1
                    time.sleep(1)
                else:
                    print(f"Erro ao gerar embeddings do lote: {e}")
                    break
        if not sucesso:
            print("Falha ao processar este lote após tentar todas as chaves.")
        time.sleep(1)

def migrar_base_ouro():
    print("Iniciando migração da Base de Ouro...")
    
    biblioteca = read_json_file(BIBLIOTECA_FILE, {})
    if not biblioteca:
        print("Biblioteca vazia ou não encontrada.")
        return
        
    cache_emb = read_json_file(CACHE_EMBEDDINGS_FILE, {})
    
    # 1. Preparar descrições ricas das categorias (Embeddings Mestres)
    textos_categorias = list(DESC_CATEGORIAS_MASTER.values())
    get_embeddings_batch(textos_categorias, cache_emb)
    
    categorias_embeddings = {
        cat: cache_emb[desc] 
        for cat, desc in DESC_CATEGORIAS_MASTER.items() if desc in cache_emb
    }
    
    # 2. Limpar nomes e gerar embeddings em Lote
    textos_produtos = []
    for chave, item in biblioteca.items():
        if not isinstance(item, dict): continue
        nome_limpo = limpar_ruido_produto(item.get("nome_comum", ""))
        item["nome_comum"] = nome_limpo
        if nome_limpo: textos_produtos.append(nome_limpo)
            
    get_embeddings_batch(list(set(textos_produtos)), cache_emb)
    write_json_file(CACHE_EMBEDDINGS_FILE, cache_emb) # Salva progresso na base embeddings
    
    # 3. Votação de Categoria e Atualização na Biblioteca
    alteracoes = 0
    for chave, item in biblioteca.items():
        if not isinstance(item, dict): continue
        nome = item.get("nome_comum", "").upper()
        if not nome: continue
        
        nova_categoria = next((cat for cat, keys in PRIORITY_ANCHOR_RULES.items() if any(k in nome for k in keys)), None)
                
        if not nova_categoria and cache_emb.get(item["nome_comum"]):
            nova_categoria = classificar_por_similaridade(cache_emb[item["nome_comum"]], categorias_embeddings)
                
        if nova_categoria:
            item["Categoria"], item["revisado_humano"] = nova_categoria, True
            alteracoes += 1
            
    write_json_file(BIBLIOTECA_FILE, biblioteca)
    print(f"Migração concluída! {alteracoes} produtos marcados como 'revisado_humano' na Base de Ouro.")

if __name__ == "__main__":
    migrar_base_ouro()