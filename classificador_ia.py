from google import genai
import json
import os
import re
import logging
import unicodedata
import urllib.parse
import asyncio
from curl_cffi import requests as async_requests
from dotenv import load_dotenv
from thefuzz import process
from utils import setup_logging, read_json_file, write_json_file, normalizar_para_cache, criar_entrada_biblioteca

load_dotenv()

# --- GERENCIAMENTO DE CHAVES (Preservando sua lógica original) ---
lista_chaves_texto = [k.strip().strip('"').strip("'") for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
indice_chave_texto_atual = 0
client = None
if lista_chaves_texto:
    client = genai.Client(api_key=lista_chaves_texto[indice_chave_texto_atual])

logger = setup_logging()

def _trocar_chave_texto():
    """Rotaciona a chave da API, fixando nas pagas se necessário (Sua lógica original)."""
    global indice_chave_texto_atual, client, lista_chaves_texto
    num_chaves = len(lista_chaves_texto)
    if num_chaves <= 1: return

    if num_chaves <= 2: 
        indice_chave_texto_atual = (indice_chave_texto_atual + 1) % num_chaves
    else:
        num_chaves_pagas = 2
        primeiro_indice_pago = num_chaves - num_chaves_pagas
        if indice_chave_texto_atual >= primeiro_indice_pago:
            indice_relativo = (indice_chave_texto_atual - primeiro_indice_pago + 1) % num_chaves_pagas
            indice_chave_texto_atual = primeiro_indice_pago + indice_relativo
        else:
            indice_chave_texto_atual += 1
            
    nova_chave = lista_chaves_texto[indice_chave_texto_atual]
    client = genai.Client(api_key=nova_chave)
    logger.info(f"🔄 Chave rotacionada para o índice {indice_chave_texto_atual}")

# --- PROMPT E CONFIGURAÇÕES ---
PROMPT_TAXONOMIA = """
Você é um especialista em taxonomia de produtos. Classifique em: "Categoria", "subcategoria" e "tipo_produto".
Categorias válidas: BEBIDAS, MERCEARIA, LIMPEZA, HIGIENE E BELEZA, FRIOS E LATICÍNIOS, PADARIA, CONGELADOS, PET SHOP, AÇOUGUE, HORTIFRUTI, BAZAR.
Responda APENAS o JSON puro.
Produtos: {produtos_lista}
"""

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")

# --- SUAS FUNÇÕES DE BIBLIOTECA E TAGS (MANTIDAS) ---
def carregar_biblioteca():
    if os.path.exists(BIBLIOTECA_FILE):
        bib = read_json_file(BIBLIOTECA_FILE, default_value={})
        if isinstance(bib, list): # Migração automática que você criou
            return { (item.get('id') or normalizar_para_cache(item.get('nome_comum'))): item for item in bib if item }
        return bib
    return {}

def salvar_biblioteca(bib): write_json_file(BIBLIOTECA_FILE, bib)

# --- FUNÇÃO PRINCIPAL CORRIGIDA ---
async def classificar_taxonomia_com_ia_async(lista_produtos_input, biblioteca_global):
    """
    Classifica produtos usando Gemini 2.0-Flash com suporte a sua lógica de 600 linhas.
    Retorna um mapa com as taxonomias corrigidas e um dicionário com as novas entradas para a biblioteca.
    """
    if not lista_produtos_input: return {}, {}
    
    mapa_final = {}
    novas_entradas_biblioteca = {}
    
    # A lista de entrada agora é sempre uma lista de dicionários de produtos
    produtos_a_processar = {p.get("Produto"): p for p in lista_produtos_input if p.get("Produto")}
    produtos_para_ia = {}

    # 1. Cache e Fuzzy Matching (Sua inteligência original)
    for nome, info in produtos_a_processar.items():
        chave = info.get("EAN") if info.get("EAN") and info.get("EAN") != "N/A" else normalizar_para_cache(nome)
        if chave in biblioteca_global:
            mapa_final[nome] = biblioteca_global[chave]
        else:
            produtos_para_ia[nome] = info

    if not produtos_para_ia: return mapa_final, {}

    # 2. Lote da IA (Corrigido para gemini-2.0-flash e tratamento de erros)
    lista_ia_items = list(produtos_para_ia.items())
    for i in range(0, len(lista_ia_items), 50):
        chunk_dict = dict(lista_ia_items[i:i+50])
        nomes = list(chunk_dict.keys())
        
        success = False
        for tentativa in range(len(lista_chaves_texto)):
            try:
                response = await asyncio.to_thread(client.models.generate_content,
                    model="gemini-2.5-flash", 
                    contents=PROMPT_TAXONOMIA.format(produtos_lista=json.dumps(nomes, ensure_ascii=False))
                )
                
                json_clean = re.sub(r'```json|```', '', response.text).strip()
                dados_ia = json.loads(json_clean)

                # --- NOVO: Tratamento para quando a IA retorna um único objeto em vez de um mapa ---
                # Se pedimos 1 produto e a resposta não tem esse produto como chave,
                # e a resposta contém a chave "Categoria", assumimos que a IA retornou um objeto único.
                if len(nomes) == 1 and nomes[0] not in dados_ia:
                    if "Categoria" in dados_ia:
                        logger.info(f"IA retornou objeto único para '{nomes[0]}'. Reconstruindo para o formato de mapa.")
                        dados_ia = {nomes[0]: dados_ia}

                if isinstance(dados_ia, dict):
                    for nome_ia, tax in dados_ia.items():
                        if not isinstance(tax, dict):
                            logger.warning(f"A IA retornou um valor inesperado (não é um dicionário) para '{nome_ia}': {tax}")
                            continue

                        # Garante que a taxonomia tenha as chaves esperadas, mesmo que a IA omita alguma.
                        tax_corrigida = {
                            "Categoria": tax.get("Categoria", "OUTROS"),
                            "subcategoria": tax.get("subcategoria", "N/A"),
                            "tipo_produto": tax.get("tipo_produto", "N/A")
                        }

                        info_orig = chunk_dict.get(nome_ia, {"Produto": nome_ia})
                        
                        # Atualiza o dicionário original com a taxonomia da IA antes de criar a entrada
                        info_orig.update(tax_corrigida)
                        
                        # Usa a nova função centralizada para criar a entrada da biblioteca
                        chave, entrada = criar_entrada_biblioteca(info_orig)
                        
                        if chave and entrada:
                            novas_entradas_biblioteca[chave] = entrada
                            mapa_final[nome_ia] = entrada
                    success = True
                    break 
                
            except Exception as e:
                if "429" in str(e) or "QUOTA" in str(e).upper():
                    _trocar_chave_texto()
                else:
                    logger.error(f"Erro no processamento da IA: {e}")
                    break

    return mapa_final, novas_entradas_biblioteca