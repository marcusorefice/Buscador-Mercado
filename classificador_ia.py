from google import genai
import json
import os
import re
import unicodedata
import logging
import asyncio
from curl_cffi import requests as async_requests
from dotenv import load_dotenv
from utils import setup_logging, read_json_file, write_json_file
load_dotenv()

# --- NOVA LÓGICA DE GERENCIAMENTO DE CHAVES ---
lista_chaves_texto = [k.strip().strip('"').strip("'") for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
indice_chave_texto_atual = 0
client = None
if lista_chaves_texto:
    client = genai.Client(api_key=lista_chaves_texto[indice_chave_texto_atual])
else:
    setup_logging().critical("Nenhuma chave de API Gemini encontrada no .env. A classificação de IA não funcionará.")

def _trocar_chave_texto():
    """Rotaciona a chave da API para classificação de texto, com lógica para chaves pagas."""
    global indice_chave_texto_atual, client, lista_chaves_texto
    
    num_chaves = len(lista_chaves_texto)
    if num_chaves <= 1:
        logger.warning("Nenhuma outra chave de API para rotacionar.")
        return

    if num_chaves <= 2: # Assume que se tem 2 ou menos, são pagas e cicla entre elas
        indice_chave_texto_atual = (indice_chave_texto_atual + 1) % num_chaves
    else:
        num_chaves_pagas = 2
        primeiro_indice_pago = num_chaves - num_chaves_pagas

        if indice_chave_texto_atual >= primeiro_indice_pago:
            # Cicla dentro das chaves pagas
            indice_relativo = (indice_chave_texto_atual - primeiro_indice_pago + 1) % num_chaves_pagas
            indice_chave_texto_atual = primeiro_indice_pago + indice_relativo
            logger.warning("Permanecendo em chaves pagas para garantir a operação de classificação.")
        else:
            # Avança para a próxima chave
            indice_chave_texto_atual += 1
            if indice_chave_texto_atual >= primeiro_indice_pago:
                logger.warning("Chaves gratuitas de texto esgotadas. Escalando para chaves pagas.")

    nova_chave = lista_chaves_texto[indice_chave_texto_atual]
    client = genai.Client(api_key=nova_chave)
    logger.info(f"🔄 Classificador de texto alternou para a chave API de índice {indice_chave_texto_atual}")
logger = setup_logging()

PROMPT_TAXONOMIA = """
Você é um especialista em taxonomia de produtos de supermercado.
Classifique cada produto em uma estrutura de 3 níveis: "Categoria", "subcategoria" e "tipo_produto".
As categorias pai válidas são: BEBIDAS, MERCEARIA, LIMPEZA, HIGIENE E BELEZA, FRIOS E LATICÍNIOS, PADARIA, CONGELADOS, PET SHOP, AÇOUGUE, HORTIFRUTI, BAZAR.
Seja conciso e direto.

Responda APENAS com um dicionário JSON onde a chave é o nome do produto e o valor é um objeto com a taxonomia.
Exemplo de Resposta:
{{
  "ARROZ TIPO 1 CAMIL 5KG": {{
    "Categoria": "MERCEARIA",
    "subcategoria": "GRÃOS E CEREAIS",
    "tipo_produto": "ARROZ BRANCO"
  }}
}}

Produtos para classificar:
{produtos_lista}
"""

# --- Lógica de Cache e Migração ---
DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")
OLD_CACHE_FILE = "cache_categorias.json" # Localização antiga na raiz

def carregar_biblioteca():
    """Carrega a biblioteca de produtos. Se não existir, tenta migrar do cache antigo."""
    # Se o novo arquivo de biblioteca já existe, use-o.
    if os.path.exists(BIBLIOTECA_FILE):
        return read_json_file(BIBLIOTECA_FILE, default_value={})

    # Se a nova biblioteca não existe, mas o cache antigo sim, faça a migração.
    if os.path.exists(OLD_CACHE_FILE):
        logger.info(f"Detectado cache antigo '{OLD_CACHE_FILE}'. Migrando para o novo formato em '{BIBLIOTECA_FILE}'...")
        antigo_cache = read_json_file(OLD_CACHE_FILE, default_value={})
        nova_biblioteca = {}
        for nome_produto, categoria in antigo_cache.items():
            chave = normalizar_para_cache(nome_produto)
            if chave:
                nova_biblioteca[chave] = {"categoria": categoria, "imagem": "SEM IMAGEM"}
        
        salvar_biblioteca(nova_biblioteca) # Salva no novo local
        try:
            os.remove(OLD_CACHE_FILE)
            logger.info(f"Migração concluída. Cache antigo '{OLD_CACHE_FILE}' foi removido.")
        except OSError as e:
            logger.error(f"Não foi possível remover o arquivo de cache antigo '{OLD_CACHE_FILE}': {e}")
        return nova_biblioteca

    return {} # Nenhum arquivo de cache encontrado

def salvar_biblioteca(nova_biblioteca):
    write_json_file(BIBLIOTECA_FILE, nova_biblioteca)

def normalizar_para_cache(nome):
    if not nome: return ""
    nfkd = unicodedata.normalize('NFKD', str(nome).lower())
    texto = "".join([c for c in nfkd if not unicodedata.combining(c)])
    texto = re.sub(r'\d+(?:[.,]\d+)?\s*(KG|G|ML|L|UN|M|ROLOS|FLS|CAPS|UNIDADES|MT|POTS|GR)', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'[^a-z0-9\s]', '', texto)
    return " ".join(texto.split())

async def _buscar_taxonomia_rapida_atacadao(session: async_requests.AsyncSession, termo: str, sem: asyncio.Semaphore):
    """
    Usa o endpoint de sugestão do Atacadão para uma classificação rápida.
    Baseado na sua descoberta com o `teste.py`.
    """
    async with sem:
        url = "https://www.atacadao.com.br/_v/segment/graphql/v1"
        # Construção mais limpa da query GraphQL, alinhada com seu teste.
        # O termo de busca deve estar entre aspas, e aspas dentro do termo são removidas para segurança.
        query_string = f'query {{ productSuggestions(fullText: "{termo.replace("\"", "")}") {{ products {{ productName categoryTree {{ name }} }} }} }}'
        payload = {"query": query_string}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json'
        }

        try:
            response = await session.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                suggestions = data.get('data', {}).get('productSuggestions', {})
                products = suggestions.get('products', [])

                if products:
                    item = products[0]
                    arvore = [c.get('name', '').upper() for c in item.get('categoryTree', [])]
                    
                    if len(arvore) >= 1: # Precisa de pelo menos a categoria principal
                        return termo, {
                            "Categoria": arvore[0] if len(arvore) > 0 else "OUTROS",
                            "subcategoria": arvore[1] if len(arvore) > 1 else "N/A",
                            "tipo_produto": arvore[2] if len(arvore) > 2 else "N/A"
                        }
        except Exception as e:
            logger.debug(f"Busca rápida para '{termo}' falhou: {e}")
        
        return termo, None # Retorna tupla para mapeamento

def classificar_taxonomia_com_ia(lista_produtos_dict):
    """
    Classifica produtos em uma taxonomia de 3 níveis, usando cache para evitar chamadas repetidas à IA.
    """
    if not lista_produtos_dict: return {}

    biblioteca = carregar_biblioteca()
    mapa_final_taxonomia = {}

    # Garante que estamos trabalhando com produtos únicos pelo nome, mas mantendo o dict completo
    produtos_a_processar = {p.get("Produto"): p for p in lista_produtos_dict if p.get("Produto")}

    produtos_para_ia = {}

    # 1. Verificar cache
    for p_nome, p_info in produtos_a_processar.items():
        chave = normalizar_para_cache(p_nome)
        if chave in biblioteca and isinstance(biblioteca[chave], dict) and "Categoria" in biblioteca[chave]:
            # Cache HIT com formato novo
            mapa_final_taxonomia[p_nome] = biblioteca[chave]
        elif chave in biblioteca and isinstance(biblioteca[chave].get("categoria"), str): # Cache HIT com formato antigo
            # Migração on-the-fly
            taxonomia_migrada = {
                "Categoria": biblioteca[chave]["categoria"],
                "subcategoria": "N/A",
                "tipo_produto": "N/A"
            }
            mapa_final_taxonomia[p_nome] = taxonomia_migrada
            # Adiciona à lista para reclassificar e obter mais detalhes no futuro
            produtos_para_ia[p_nome] = p_info
        else:
            # Cache MISS
            produtos_para_ia[p_nome] = p_info

    # 2. Tenta a "fila rápida" do Atacadão antes de usar a IA
    produtos_para_ia_final = {}
    if produtos_para_ia:
        logger.info(f"⚡ Otimizando... Usando busca rápida paralela do Atacadão para {len(produtos_para_ia)} produtos.")

        async def _run_parallel_search(produtos_a_buscar_dict):
            CONCURRENCY_BUSCA_RAPIDA = 20 # Concorrência maior para esta API leve
            sem = asyncio.Semaphore(CONCURRENCY_BUSCA_RAPIDA)
            resultados_encontrados = {}
            
            async with async_requests.AsyncSession(impersonate="chrome120") as session:
                tarefas = [_buscar_taxonomia_rapida_atacadao(session, p_nome, sem) for p_nome in produtos_a_buscar_dict]
                
                total_a_buscar = len(tarefas)
                contador = 0
                
                for f in asyncio.as_completed(tarefas):
                    resultado = await f
                    contador += 1
                    if contador % 50 == 0 or contador == total_a_buscar:
                        logger.info(f"   - Progresso da busca rápida: {contador}/{total_a_buscar}")
                    
                    if resultado and resultado[1]:
                        p_nome, taxonomia = resultado
                        resultados_encontrados[p_nome] = taxonomia
            return resultados_encontrados

        # Executa a função assíncrona de busca paralela
        try:
            resultados_da_busca_rapida = asyncio.run(_run_parallel_search(list(produtos_para_ia.keys())))
        except RuntimeError:
            # Se já houver um loop de eventos rodando (raro neste contexto de thread)
            loop = asyncio.get_event_loop()
            resultados_da_busca_rapida = loop.run_until_complete(_run_parallel_search(list(produtos_para_ia.keys())))

        # Processa os resultados da busca rápida
        logger.info(f"   - {len(resultados_da_busca_rapida)} produtos classificados pela busca rápida.")
        for p_nome, taxonomia in resultados_da_busca_rapida.items():
            chave = normalizar_para_cache(p_nome)
            mapa_final_taxonomia[p_nome] = taxonomia

            # Pega a URL da imagem do dicionário original
            imagem_url = produtos_para_ia.get(p_nome, {}).get("Link_Imagem", "SEM IMAGEM")

            biblioteca[chave] = {**biblioteca.get(chave, {}), **taxonomia}
            if "imagem" not in biblioteca[chave] or biblioteca[chave]["imagem"] == "SEM IMAGEM":
                biblioteca[chave]["imagem"] = imagem_url
        
        # Determina o que sobrou para a IA
        for p_nome, p_info in produtos_para_ia.items():
            if p_nome not in resultados_da_busca_rapida:
                produtos_para_ia_final[p_nome] = p_info
        
        salvar_biblioteca(biblioteca) # Salva o que foi encontrado na busca rápida
    
    if not produtos_para_ia_final:
        logger.info("✅ Todos os produtos foram classificados via cache ou busca rápida. Nenhuma chamada à IA foi necessária.")
        return mapa_final_taxonomia

    # 3. Chamar IA em lotes para os produtos restantes
    CHUNK_SIZE = 150 # Um bom número para não estourar o limite de tokens do prompt
    lista_produtos_ia_items = list(produtos_para_ia_final.items())
    total_lotes = (len(lista_produtos_ia_items) + CHUNK_SIZE - 1) // CHUNK_SIZE

    logger.info(f"🧠 {len(lista_produtos_ia_items)} produtos serão enviados para a IA em {total_lotes} lotes.")

    for i in range(0, len(lista_produtos_ia_items), CHUNK_SIZE):
        lote_atual = i // CHUNK_SIZE + 1
        chunk_items = lista_produtos_ia_items[i:i + CHUNK_SIZE]
        chunk_dict = dict(chunk_items)
        chunk_nomes = list(chunk_dict.keys())
        
        logger.info(f"   - Processando Lote {lote_atual}/{total_lotes} com {len(chunk_nomes)} produtos...")
        
        produtos_str = json.dumps(chunk_nomes, indent=2, ensure_ascii=False)
        prompt_final = PROMPT_TAXONOMIA.format(produtos_lista=produtos_str)

        success = False
        for tentativa in range(len(lista_chaves_texto)): # Tenta com todas as chaves disponíveis
            try:
                if not client:
                    logger.error("Cliente da API Gemini não inicializado. Pulando classificação.")
                    break
                
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt_final
                )
                txt = response.text.strip()
                
                if "```json" in txt: 
                    txt = txt.split("```json")[-1].split("```")[0].strip()
                elif "```" in txt:
                    txt = txt.replace("```", "").strip()
                    
                novas_taxonomias_lote = json.loads(txt)

                # 3. Atualizar cache e mapa de resultados para o lote atual
                for prod_nome_ia, taxonomia in novas_taxonomias_lote.items():
                    chave_ia = normalizar_para_cache(prod_nome_ia)
                    
                    taxonomia_padronizada = {
                        "Categoria": str(taxonomia.get("Categoria", "OUTROS")).upper(),
                        "subcategoria": str(taxonomia.get("subcategoria", "OUTROS")).upper(),
                        "tipo_produto": str(taxonomia.get("tipo_produto", "OUTROS")).upper()
                    }

                    # Pega a URL da imagem do dicionário original do lote
                    imagem_url = "SEM IMAGEM"
                    for p_orig_nome, p_orig_info in chunk_dict.items():
                        # Compara a versão limpa do nome que veio da IA com a versão limpa do nome original
                        if normalizar_para_cache(p_orig_nome) == chave_ia:
                            imagem_url = p_orig_info.get("Link_Imagem", "SEM IMAGEM")
                            # Agora sim, preenchemos o mapa que o orquestrador vai ler
                            mapa_final_taxonomia[p_orig_nome] = taxonomia_padronizada
                            break

                    # Salva na biblioteca para consultas futuras (Cache)
                    biblioteca[chave_ia] = {**taxonomia_padronizada, "imagem": imagem_url}
                
                salvar_biblioteca(biblioteca)
                logger.info(f"   - Lote {lote_atual} concluído. Cache atualizado.")
                success = True
                break # Sai do loop de tentativas se for bem-sucedido

            except Exception as e:
                erro_msg = str(e).upper()
                if any(err in erro_msg for err in ["429", "QUOTA", "EXHAUSTED", "503", "UNAVAILABLE"]):
                    logger.warning(f"Cota/Disponibilidade esgotada na chave {indice_chave_texto_atual}. Tentando próxima...")
                    _trocar_chave_texto()
                else:
                    logger.error(f"Erro inesperado no Lote {lote_atual} da IA (tentativa {tentativa + 1}): {e}")
                    _trocar_chave_texto() # Tenta a próxima chave mesmo em erro inesperado
        
        if not success:
            logger.error(f"FALHA GERAL NO LOTE: Nenhuma chave da API conseguiu processar o lote {lote_atual}.")
            continue # Pula para o próximo lote
            
    logger.info(f"✅ Classificação por IA concluída.")
    return mapa_final_taxonomia