from google import genai
import json
import os
import re
import unicodedata
import logging
import urllib.parse
import asyncio
from curl_cffi import requests as async_requests
from dotenv import load_dotenv
from thefuzz import process
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
    """
    Carrega a biblioteca de produtos, que deve ser um dicionário (JSON object) para performance.
    Se encontrar o formato antigo (lista), faz a migração na hora para otimizar futuras execuções.
    """
    if os.path.exists(BIBLIOTECA_FILE):
        biblioteca = read_json_file(BIBLIOTECA_FILE, default_value={})
        # Lógica de migração: Se for uma lista (formato antigo), converte para dicionário.
        # Isso causa a lentidão que você percebeu. Após a primeira execução com esta correção,
        # o arquivo será salvo como dicionário e as próximas leituras serão instantâneas.
        if isinstance(biblioteca, list):
            logger.warning("Formato de biblioteca antigo (lista) detectado. Convertendo para dicionário para otimizar performance...")
            biblioteca_dict = {}
            for item in biblioteca:
                # A chave da biblioteca é o nome do produto normalizado (slug)
                chave = item.get('id') or normalizar_para_cache(item.get('nome_comum') or item.get('Produto'))
                if chave:
                    biblioteca_dict[chave] = item
            
            salvar_biblioteca(biblioteca_dict) # Salva no formato otimizado
            logger.info("Conversão para dicionário concluída. As próximas execuções serão mais rápidas.")
            return biblioteca_dict
        return biblioteca

    # Se a biblioteca principal não existe, tenta migrar do cache legado.
    elif os.path.exists(OLD_CACHE_FILE):
        logger.info(f"Detectado cache antigo '{OLD_CACHE_FILE}'. Migrando para o novo formato em '{BIBLIOTECA_FILE}'...")
        antigo_cache = read_json_file(OLD_CACHE_FILE, default_value={})
        nova_biblioteca = {}
        for nome_produto, categoria in antigo_cache.items():
            chave = normalizar_para_cache(nome_produto)
            if chave:
                nova_biblioteca[chave] = {"Categoria": categoria, "subcategoria": "N/A", "tipo_produto": "N/A", "imagem": "SEM IMAGEM"}
        salvar_biblioteca(nova_biblioteca)
        try:
            os.remove(OLD_CACHE_FILE)
            logger.info(f"Migração concluída. Cache antigo '{OLD_CACHE_FILE}' foi removido.")
        except OSError as e:
            logger.error(f"Não foi possível remover o arquivo de cache antigo '{OLD_CACHE_FILE}': {e}")
        return nova_biblioteca
    
    return {}

def salvar_biblioteca(biblioteca_dict):
    """Salva a biblioteca de produtos (dicionário) em um arquivo JSON."""
    write_json_file(BIBLIOTECA_FILE, biblioteca_dict)

def _reconstruir_json_remix_carrefour(dados_flat, index=0):
    """Traduz o formato de índices do Remix (usado pelo Carrefour) para um JSON legível."""
    if index is None or not (0 <= index < len(dados_flat)):
        return None
    
    node = dados_flat[index]
    
    if isinstance(node, list):
        return [_reconstruir_json_remix_carrefour(dados_flat, i) for i in node]
    
    if isinstance(node, dict):
        res = {}
        for k, v in node.items():
            if k.startswith('_'):
                try:
                    key_idx = int(k[1:])
                    chave_real = _reconstruir_json_remix_carrefour(dados_flat, key_idx)
                    res[chave_real] = _reconstruir_json_remix_carrefour(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
                except: continue
            else:
                res[k] = _reconstruir_json_remix_carrefour(dados_flat, v) if isinstance(v, (int, float)) and v < len(dados_flat) else v
        return res
    return node

def _criar_entrada_biblioteca_estendida(chave_id, nome_produto, p_info, taxonomia):
    """Cria um dicionário completo para a biblioteca de produtos no formato estendido."""
    
    marca = p_info.get("Marca", "")
    
    # Constrói a string de medida apenas se não for o padrão "1 UN"
    qtd_valor = p_info.get("Qtd_Valor", "")
    medida_un = p_info.get("Medida", "")
    medida_str = ""
    if qtd_valor and medida_un and not (str(qtd_valor) == "1" and medida_un.upper() == "UN"):
        medida_str = f"{qtd_valor}{medida_un}".strip()

    categoria = taxonomia.get("Categoria", "OUTROS")
    subcategoria = taxonomia.get("subcategoria", "N/A")
    tipo_produto = taxonomia.get("tipo_produto", "N/A")

    # --- Geração de Tags ---
    # Usa o nome do produto, taxonomia e marca para gerar tags de busca relevantes.
    full_text_for_tags = f"{nome_produto} {categoria} {subcategoria} {tipo_produto}".lower()
    tags_set = set(re.findall(r'\b[a-zA-ZÀ-ÿ0-9]+\b', full_text_for_tags))
        
    stopwords = {'de', 'com', 'sem', 'e', 'a', 'o', 'do', 'da', 'dos', 'das', 'para', 'em', 'um', 'uma', 'na', 'no', 'n/a', 'outros'}
    tags = [t for t in tags_set if t not in stopwords and len(t) > 2]
    
    if marca and marca.lower() not in [t.lower() for t in tags]:
        tags.append(marca.lower())
        
    # Normaliza tags para ascii (remove acentos) e remove duplicatas
    tags_ascii = []
    for t in tags:
        try:
            tag_normalizada = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii')
            if tag_normalizada:
                tags_ascii.append(tag_normalizada)
        except Exception:
            pass # Ignora erros de normalização
    tags = sorted(list(set(tags_ascii)))

    return {
        "id": chave_id,
        "nome_comum": nome_produto,
        "marca": marca,
        "medida": medida_str,
        "Categoria": categoria, "subcategoria": subcategoria, "tipo_produto": tipo_produto,
        "imagem": p_info.get("Link_Imagem", "SEM IMAGEM"),
        "tags": tags
    }

def normalizar_para_cache(nome):
    if not nome: return ""
    nfkd = unicodedata.normalize('NFKD', str(nome).lower())
    texto = "".join([c for c in nfkd if not unicodedata.combining(c)])
    texto = re.sub(r'\d+(?:[.,]\d+)?\s*(KG|G|ML|L|UN|M|ROLOS|FLS|CAPS|UNIDADES|MT|POTS|GR)', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'[^a-z0-9\s]', '', texto)
    return " ".join(texto.split())

async def _buscar_taxonomia_em_lote_atacadao(session: async_requests.AsyncSession, lote_termos: list, sem: asyncio.Semaphore):
    """
    Usa o endpoint de sugestão do Atacadão para uma classificação rápida EM LOTE.
    Constrói uma única query GraphQL com múltiplos aliases para reduzir o número de requisições.
    """
    if not lote_termos:
        return {}

    async with sem:
        # Constrói a parte interna da query com aliases
        queries_internas = []
        for i, termo in enumerate(lote_termos):
            # Limpa o termo para ser seguro dentro da string GraphQL
            termo_limpo = termo.replace("\"", "").replace("\\", "")
            queries_internas.append(f'p{i}: productSuggestions(fullText: "{termo_limpo}") {{ products {{ productName categoryTree {{ name }} }} }}')
        
        query_completa = f"query BatchedSuggestions {{ {' '.join(queries_internas)} }}"
        payload = {"query": query_completa}

        url = "https://www.atacadao.com.br/_v/segment/graphql/v1"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json'
        }

        try:
            # Timeout maior para requisições em lote que são mais pesadas
            response = await session.post(url, json=payload, headers=headers, timeout=45)
            if response.status_code == 200:
                data = response.json()
                suggestions_data = data.get('data', {})
                
                resultados_lote = {}
                if suggestions_data:
                    for i, termo_original in enumerate(lote_termos):
                        resultado_alias = suggestions_data.get(f'p{i}', {})
                        products = resultado_alias.get('products', [])
                        if products:
                            item = products[0]
                            arvore = [c.get('name', '').upper() for c in item.get('categoryTree', [])]
                            if len(arvore) >= 1:
                                resultados_lote[termo_original] = {
                                    "Categoria": arvore[0] if len(arvore) > 0 else "OUTROS",
                                    "subcategoria": arvore[1] if len(arvore) > 1 else "N/A",
                                    "tipo_produto": arvore[2] if len(arvore) > 2 else "N/A"
                                }
                return resultados_lote
        except Exception as e:
            logger.debug(f"Busca rápida em lote falhou: {e}")
        
        return {}

async def _buscar_taxonomia_em_lote_pda(session, lote_termos, sem):
    """Busca rápida de taxonomia na API do Pão de Açúcar."""
    resultados = {}
    async def _fetch(termo):
        async with sem:
            try:
                url = f"https://api.vendas.gpa.digital/pa/search/v2?q={urllib.parse.quote(termo)}&page=1&resultsPerPage=1&storeId=461"
                res = await session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    produto = data.get('products', [{}])[0]
                    if produto and produto.get('categories'):
                        partes = [p for p in produto['categories'][0].strip('/').split('/') if p]
                        if len(partes) > 0:
                            resultados[termo] = {
                                "Categoria": partes[0].upper(),
                                "subcategoria": partes[1].upper() if len(partes) > 1 else "N/A",
                                "tipo_produto": partes[2].upper() if len(partes) > 2 else "N/A"
                            }
            except Exception: pass
    await asyncio.gather(*[_fetch(termo) for termo in lote_termos])
    return resultados

async def _buscar_taxonomia_em_lote_vtex(session, base_url, lote_termos, sem):
    """Busca rápida de taxonomia em APIs VTEX (Covabra, Oba)."""
    resultados = {}
    async def _fetch(termo):
        async with sem:
            try:
                url = f"{base_url}/api/catalog_system/pub/products/search?ft={urllib.parse.quote(termo)}&_from=0&_to=0"
                res = await session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if data and data[0].get('categories'):
                        partes = [p for p in data[0]['categories'][0].strip('/').split('/') if p]
                        if len(partes) > 0:
                            resultados[termo] = {
                                "Categoria": partes[0].upper(),
                                "subcategoria": partes[1].upper() if len(partes) > 1 else "N/A",
                                "tipo_produto": partes[2].upper() if len(partes) > 2 else "N/A"
                            }
            except Exception: pass
    await asyncio.gather(*[_fetch(termo) for termo in lote_termos])
    return resultados

async def _buscar_taxonomia_em_lote_carrefour(session, lote_termos, sem):
    """Busca rápida de taxonomia na API do Carrefour."""
    resultados = {}
    async def _fetch(termo):
        async with sem:
            try:
                termo_url = urllib.parse.quote(termo)
                url = f"https://mercado.carrefour.com.br/{termo_url}.data?q={termo_url}&map=ft&_routes=layout%2Fdefault%2Croutes%2Fsearch%23%24term"
                res = await session.get(url, timeout=15)
                if res.status_code == 200:
                    dados_brutos = res.json()
                    dados_limpos = _reconstruir_json_remix_carrefour(dados_brutos, 0)
                    colecao = dados_limpos.get("routes/search#$term", {})
                    produto = colecao.get("products", [{}])[0]
                    if produto:
                        item = produto.get('node', produto)
                        cat_tree = item.get('categoryTree', [])
                        if cat_tree and isinstance(cat_tree[0], dict):
                            resultados[termo] = {
                                "Categoria": cat_tree[0].get('name', '').upper() if len(cat_tree) > 0 else "OUTROS",
                                "subcategoria": cat_tree[1].get('name', '').upper() if len(cat_tree) > 1 else "N/A",
                                "tipo_produto": cat_tree[2].get('name', '').upper() if len(cat_tree) > 2 else "N/A"
                            }
            except Exception: pass
    await asyncio.gather(*[_fetch(termo) for termo in lote_termos])
    return resultados

async def _buscar_taxonomia_em_lote_boa(session, lote_termos, sem):
    """Busca rápida de taxonomia na API GraphQL do Boa."""
    resultados = {}
    async def _fetch(termo):
        async with sem:
            try:
                variables = {"input": {"term": termo, "page": 1, "sort": "score_desc", "activeSalesChannel": "1", "postalCode": "13211-745"}}
                params = {
                    "operationName": "GetProductsQuery",
                    "operationHash": "ae50c5a735b1464f0ba48be4f2b32f7289ce6284",
                    "variables": json.dumps(variables, separators=(',', ':'))
                }
                url = f"https://www.boasupermercados.com.br/api/graphql?{urllib.parse.urlencode(params)}"
                res = await session.get(url, timeout=15)
                if res.status_code == 200:
                    edge = res.json().get('data', {}).get('getProducts', {}).get('data', {}).get('products', {}).get('edges', [{}])[0]
                    if edge:
                        cat_tree = edge.get('node', {}).get('categoryTree', [])
                        def get_last_path_part(path_str: str) -> str:
                            if not isinstance(path_str, str): return ""
                            parts = [part for part in path_str.split('/') if part]
                            return parts[-1] if parts else ""
                        categorias_extraidas = [get_last_path_part(c).upper() for c in cat_tree]
                        if categorias_extraidas:
                             resultados[termo] = {
                                "Categoria": categorias_extraidas[0] if len(categorias_extraidas) > 0 else "OUTROS",
                                "subcategoria": categorias_extraidas[1] if len(categorias_extraidas) > 1 else "N/A",
                                "tipo_produto": categorias_extraidas[2] if len(categorias_extraidas) > 2 else "N/A"
                            }
            except Exception: pass
    await asyncio.gather(*[_fetch(termo) for termo in lote_termos])
    return resultados

async def _run_fast_lane_providers(produtos_a_buscar_dict):
    """
    Executa múltiplos provedores de busca rápida em paralelo para classificar produtos.
    """
    resultados_finais = {}
    termos_restantes = list(produtos_a_buscar_dict.keys())

    # Ordem de prioridade dos provedores
    provedores = [
        ("Atacadão", _buscar_taxonomia_em_lote_atacadao),
        ("Pão de Açúcar", _buscar_taxonomia_em_lote_pda),
        ("Carrefour", _buscar_taxonomia_em_lote_carrefour),
        ("Covabra", lambda s, t, sem: _buscar_taxonomia_em_lote_vtex(s, "https://www.covabra.com.br", t, sem)),
        ("Oba Hortifruti", lambda s, t, sem: _buscar_taxonomia_em_lote_vtex(s, "https://www.obahortifruti.com.br", t, sem)),
        ("Boa Supermercados", _buscar_taxonomia_em_lote_boa)
    ]

    async with async_requests.AsyncSession(impersonate="chrome120") as session:
        for nome_provedor, func_provedor in provedores:
            if not termos_restantes:
                break # Todos os itens foram classificados

            logger.info(f"   -> Acionando provedor de busca rápida: {nome_provedor} para {len(termos_restantes)} itens.")
            
            # O Atacadão usa lotes, os outros são individuais.
            if nome_provedor == "Atacadão":
                TAMANHO_LOTE_BUSCA = 50 
                CONCURRENCY_BUSCA_RAPIDA = 10
                sem = asyncio.Semaphore(CONCURRENCY_BUSCA_RAPIDA)
                lotes = [termos_restantes[i:i + TAMANHO_LOTE_BUSCA] for i in range(0, len(termos_restantes), TAMANHO_LOTE_BUSCA)]
                tarefas = [func_provedor(session, lote, sem) for lote in lotes]
                resultados_provedor_lotes = await asyncio.gather(*tarefas)
                resultados_provedor = {k: v for d in resultados_provedor_lotes for k, v in d.items()}
            else:
                sem = asyncio.Semaphore(15) # Mais concorrência para chamadas individuais
                resultados_provedor = await func_provedor(session, termos_restantes, sem)

            if resultados_provedor:
                logger.info(f"      ✓ {nome_provedor} classificou {len(resultados_provedor)} itens.")
                termos_ainda_restantes = []
                for termo in termos_restantes:
                    if termo in resultados_provedor:
                        resultados_finais[termo] = resultados_provedor[termo]
                    else:
                        termos_ainda_restantes.append(termo)
                termos_restantes = termos_ainda_restantes

    return resultados_finais

async def classificar_taxonomia_com_ia_async(lista_produtos_dict, biblioteca_global):
    """
    Classifica produtos em uma taxonomia de 3 níveis, usando cache para evitar chamadas repetidas à IA.
    Retorna o mapa de taxonomia e a biblioteca atualizada.
    """
    if not lista_produtos_dict: return {}, biblioteca_global, False

    biblioteca = biblioteca_global # Usa a biblioteca passada como argumento, que é um dicionário
    mapa_final_taxonomia = {}

    # Garante que estamos trabalhando com produtos únicos pelo nome, mas mantendo o dict completo
    produtos_a_processar = {p.get("Produto"): p for p in lista_produtos_dict if p.get("Produto")}

    produtos_para_ia = {}
    cache_modificado = False

    # 1. Verificar cache
    for p_nome, p_info in produtos_a_processar.items():
        chave = normalizar_para_cache(p_nome)
        if chave in biblioteca and isinstance(biblioteca[chave], dict) and "Categoria" in biblioteca[chave]:
            # Cache HIT com formato novo
            mapa_final_taxonomia[p_nome] = biblioteca[chave]
            
            # Atualiza a imagem na biblioteca se o produto atual tiver uma e a biblioteca não
            img_nova = p_info.get("Link_Imagem")
            if img_nova and img_nova != "SEM IMAGEM" and str(img_nova).strip() != "":
                img_cache = biblioteca[chave].get("imagem")
                if not img_cache or img_cache == "SEM IMAGEM" or str(img_cache).strip() == "":
                    biblioteca[chave]["imagem"] = img_nova
                    cache_modificado = True
        elif chave in biblioteca and "categoria" in biblioteca[chave]: # Cache HIT com formato antigo (chave 'categoria' minúscula)
            # **Auto-correção da Biblioteca:**
            # Este bloco corrige em memória as entradas que estão no formato antigo.
            # Na próxima vez que o programa rodar, esta entrada já estará no formato novo, evitando reprocessamento.
            logger.warning(f"Detectado e corrigindo formato antigo para o produto: '{p_nome}'")
            entrada_antiga = biblioteca[chave]
            
            # Converte a entrada antiga para o novo formato, preservando todos os outros campos.
            entrada_antiga['Categoria'] = str(entrada_antiga.pop('categoria', 'OUTROS')).upper()
            if 'subcategoria' in entrada_antiga:
                entrada_antiga['subcategoria'] = str(entrada_antiga['subcategoria']).upper()
            if 'tipo_produto' in entrada_antiga:
                entrada_antiga['tipo_produto'] = str(entrada_antiga['tipo_produto']).upper()

            mapa_final_taxonomia[p_nome] = entrada_antiga # Usa o dado corrigido para a execução atual
            cache_modificado = True # Garante que a biblioteca corrigida seja salva no final
            # Não adicionamos à 'produtos_para_ia', pois o objetivo aqui é corrigir o cache, não reclassificar.
        else:
            # Cache MISS
            produtos_para_ia[p_nome] = p_info

    # 2. Tenta a "fila rápida" do Atacadão antes de usar a IA
    produtos_para_ia_final = {}
    if produtos_para_ia:
        logger.info(f"⚡ Otimizando... Usando busca rápida em {len(produtos_para_ia)} produtos com múltiplos provedores.")
        resultados_da_busca_rapida = await _run_fast_lane_providers(produtos_para_ia)

        # Processa os resultados da busca rápida
        logger.info(f"   - {len(resultados_da_busca_rapida)} produtos classificados pela busca rápida multi-provedor.")
        for p_nome, taxonomia in resultados_da_busca_rapida.items():
            chave = normalizar_para_cache(p_nome)
            p_info = produtos_para_ia.get(p_nome, {})
            mapa_final_taxonomia[p_nome] = taxonomia

            biblioteca[chave] = _criar_entrada_biblioteca_estendida(chave, p_nome, p_info, taxonomia)
            cache_modificado = True
        
        # Determina o que sobrou para a IA
        for p_nome, p_info in produtos_para_ia.items():
            if p_nome not in resultados_da_busca_rapida:
                produtos_para_ia_final[p_nome] = p_info
        
        # 3. Tenta Fuzzy Matching contra a biblioteca existente como um passo intermediário
        if produtos_para_ia_final and biblioteca:
            logger.info(f"⚡ Otimizando... Usando Fuzzy Matching para {len(produtos_para_ia_final)} produtos restantes.")
            
            # Prepara a lista de nomes da biblioteca para o fuzzy matching
            # Usamos um dicionário para mapear o nome comum de volta para a chave da biblioteca
            nomes_biblioteca = {item['nome_comum']: chave for chave, item in biblioteca.items() if 'nome_comum' in item and item.get('nome_comum')}
            
            if nomes_biblioteca:
                produtos_ainda_sem_match = {}
                fuzzy_matches_found = 0
                
                for p_nome, p_info in produtos_para_ia_final.items():
                    # extractOne retorna (escolha, pontuação)
                    melhor_match, score = process.extractOne(p_nome, nomes_biblioteca.keys())
                    
                    # Usamos um score alto (>= 90) para ter alta confiança e evitar falsos positivos.
                    if score >= 90:
                        fuzzy_matches_found += 1
                        chave_biblioteca_match = nomes_biblioteca[melhor_match]
                        item_encontrado = biblioteca[chave_biblioteca_match]
                        
                        # Usa a taxonomia do item encontrado no fuzzy match
                        taxonomia_fuzzy = {
                            "Categoria": item_encontrado.get("Categoria"),
                            "subcategoria": item_encontrado.get("subcategoria"),
                            "tipo_produto": item_encontrado.get("tipo_produto")
                        }
                        mapa_final_taxonomia[p_nome] = taxonomia_fuzzy
                        
                        # Adiciona a nova variação ao cache para acelerar futuras execuções
                        chave_nova_variacao = normalizar_para_cache(p_nome)
                        if chave_nova_variacao not in biblioteca:
                            biblioteca[chave_nova_variacao] = _criar_entrada_biblioteca_estendida(chave_nova_variacao, p_nome, p_info, taxonomia_fuzzy)
                            cache_modificado = True
                    else:
                        produtos_ainda_sem_match[p_nome] = p_info
                
                if fuzzy_matches_found > 0:
                    logger.info(f"   - {fuzzy_matches_found} produtos classificados via Fuzzy Matching (Score >= 90).")
                
                # O que sobrou finalmente vai para a IA
                produtos_para_ia_final = produtos_ainda_sem_match

        # A biblioteca será salva uma única vez no final pelo main.py
    elif cache_modificado:
        pass # A biblioteca será salva uma única vez no final pelo main.py
    
    if not produtos_para_ia_final:
        logger.info("✅ Todos os produtos foram classificados via cache ou busca rápida. Nenhuma chamada à IA foi necessária.")
        return mapa_final_taxonomia, biblioteca, cache_modificado

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
                
                # Executa a chamada síncrona da API em uma thread separada para não bloquear o loop de eventos
                response = await asyncio.to_thread(client.models.generate_content,
                    model="models/gemini-flash-latest",
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

                    # Encontra o produto original no lote para pegar informações completas (nome exato, imagem, etc.)
                    imagem_url = "SEM IMAGEM"
                    p_info_original = {}
                    nome_original_produto = prod_nome_ia # Fallback
                    for p_orig_nome, p_orig_info in chunk_dict.items():                        
                        if normalizar_para_cache(p_orig_nome) == chave_ia:
                            p_info_original = p_orig_info
                            nome_original_produto = p_orig_nome
                            imagem_url = p_orig_info.get("Link_Imagem", "SEM IMAGEM")
                            mapa_final_taxonomia[p_orig_nome] = taxonomia_padronizada
                            break

                    # Salva na biblioteca para consultas futuras (Cache).
                    biblioteca[chave_ia] = _criar_entrada_biblioteca_estendida(
                        chave_ia, nome_original_produto, p_info_original, taxonomia_padronizada
                    )
                    cache_modificado = True
                
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
    return mapa_final_taxonomia, biblioteca, cache_modificado