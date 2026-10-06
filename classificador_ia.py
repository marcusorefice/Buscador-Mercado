from google import genai
import json
import os
import re
import logging
import asyncio
from dotenv import load_dotenv 
from utils import setup_logging, read_json_file, write_json_file, normalizar_para_cache, CATEGORIAS_MASTER, ean_e_valido

load_dotenv()
logger = setup_logging()

# --- GERENCIAMENTO DE CHAVES ---
lista_chaves_texto = [k.strip().strip('"').strip("'") for k in os.getenv("GEMINI_API_KEYS", "").split(',') if k.strip()]
indice_chave_texto_atual = 0
_api_esgotada = False
client = None
if lista_chaves_texto:
    client = genai.Client(api_key=lista_chaves_texto[indice_chave_texto_atual])

import threading

_chave_lock = threading.Lock()

def _trocar_chave_texto(indice_falho=None):
    """Rotaciona a chave da API, fixando nas pagas se necessário."""
    global indice_chave_texto_atual, client, lista_chaves_texto
    num_chaves = len(lista_chaves_texto)
    if num_chaves <= 1: return

    with _chave_lock:
        if indice_falho is not None and indice_chave_texto_atual != indice_falho:
            return

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

DATA_DIR = "data"
BIBLIOTECA_UNIFICADA_FILE = os.path.join(DATA_DIR, "biblioteca_unificada.json")
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")
BIBLIOTECA_OLD_FILE = os.path.join(DATA_DIR, "biblioteca_produtos_old.json")
BIBLIOTECA_IA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos_IA.json")

def carregar_biblioteca():
    # Carrega EXCLUSIVAMENTE a biblioteca_produtos.json
    arquivo_alvo = BIBLIOTECA_FILE
    if os.path.exists(arquivo_alvo):
        bib = read_json_file(arquivo_alvo, default_value={})
        biblioteca_limpa = {}
        if isinstance(bib, list):
            for item in bib:
                if item and str(item.get("ean", "N/A")) != "N/A":
                    chave = str(item.get("id") or normalizar_para_cache(item.get("nome_comum", "")))
                    if chave.isdigit():
                        biblioteca_limpa[chave] = item
            return biblioteca_limpa
        if isinstance(bib, dict):
            for chave, item in bib.items():
                if str(chave).isdigit() and str(item.get("ean", "N/A")) != "N/A":
                    biblioteca_limpa[chave] = item
            return biblioteca_limpa
    return {}

def salvar_biblioteca(bib): 
    write_json_file(BIBLIOTECA_FILE, bib)

def gerar_id_unico(nome_produto, marca):
    nome_limpo = re.sub(r'[^a-zA-Z0-9]', '', str(nome_produto).upper())
    marca_limpa = re.sub(r'[^a-zA-Z0-9]', '', str(marca).upper())
    return f"{marca_limpa}_{nome_limpo}"

async def _chamar_gemini_com_retry(prompt, model="gemini-2.5-flash", max_retries=None):
    global client, indice_chave_texto_atual, _api_esgotada
    
    if _api_esgotada:
        return None
    
    # Tenta 2 vezes por cada chave disponível (ex: 3 chaves = 6 tentativas no total)
    if max_retries is None:
        max_tentativas = max(2, len(lista_chaves_texto) * 2)
    else:
        max_tentativas = max_retries
        
    for tentativa in range(max_tentativas):
        indice_usado = indice_chave_texto_atual
        cliente_usado = client
        try:
            response = await asyncio.to_thread(
                cliente_usado.models.generate_content,
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.2
                }
            )
            return response.text
        except Exception as e:
            erro_str = str(e).upper()
            if any(err in erro_str for err in ["429", "QUOTA", "EXHAUSTED", "503", "UNAVAILABLE"]):
                logger.warning(f"⚠️ Limite excedido na chave [{indice_usado}]. Rotacionando... (Tentativa {tentativa+1}/{max_tentativas})")
                _trocar_chave_texto(indice_falho=indice_usado)
                import random
                await asyncio.sleep(2 + random.uniform(0.5, 2.0))
            else:
                logger.error(f"❌ Erro na API do Gemini (Chave [{indice_usado}]): {e}")
                _trocar_chave_texto(indice_falho=indice_usado)
                import random
                await asyncio.sleep(1 + random.uniform(0.5, 1.5))
                
    logger.error("❌ Todas as tentativas esgotadas. Nenhuma chave funcionou.")
    
    # Se esgotou todas as tentativas, ativa o Circuit Breaker para não travar a fila inteira
    if max_tentativas > 0:
        _api_esgotada = True
        logger.critical("🛑 CIRCUIT BREAKER ATIVADO: A cota da API (limite financeiro) estourou. Desligando a IA para o resto desta sessão para evitar travamentos.")
        
    return None

PROMPT_CLASSIFICACAO = """Você é um assistente de IA especialista em categorização de produtos de supermercado.

Sua tarefa é classificar o seguinte produto e retornar APENAS um objeto JSON válido, sem formatação markdown (sem ```json) ou explicações.

PRODUTO PARA CLASSIFICAR:
- Nome Original: {nome}
- Marca Original: {marca}
- EAN Original: {ean}
- Categoria do Mercado (Referência): {categoria_mercado}

REGRAS OBRIGATÓRIAS (PUNIÇÃO MÁXIMA PARA DESCUMPRIMENTO):
1. CATEGORIA EXATA: Você DEVE usar EXATAMENTE uma das categorias desta lista, com a grafia exata, sem adicionar, remover ou alterar palavras:
[{categorias_validas}]
Se a categoria do mercado não bater, escolha a MAIS PRÓXIMA desta lista. NUNCA crie uma categoria nova. NUNCA repita a categoria do mercado se ela não estiver na lista acima.
2. PROIBIÇÃO DO "GERAL" E "OUTROS": É estritamente proibido usar os termos "Geral", "Outros", "Diversos" em subcategoria ou tipo_produto. Seja ESPECÍFICO (ex: use "Cerveja Lager" ao invés de "Alcoólicos Geral").
3. MARCA: Identifique a marca e coloque-a em CAIXA ALTA.
4. TAGS: Crie de 5 a 8 tags relevantes em letras minúsculas, focando em termos de busca do usuário (ex: se for leite condensado, use ["doce", "confeitaria", "leite", "sobremesa"]).
5. EAN: Se o EAN Original não for fornecido ou for "N/A", preencha o campo "ean" como "N/A".
6. NOME COMUM: Um nome limpo e amigável do produto, incluindo peso/volume se possível.

FORMATO DE SAÍDA EXATO:
{{
"ean": "{ean}",
"nome_comum": "Nome Limpo do Produto",
"marca": "MARCA_EM_CAIXA_ALTA",
"Categoria": "Categoria Exata da Lista Acima",
"subcategoria": "Subcategoria Específica",
"tipo_produto": "Tipo Exato",
"tags": ["tag1", "tag2"]
}}
"""

PROMPT_CONFLITO = """Você é um assistente de IA especialista em unificação de dados de supermercado.
Dois mercados enviaram informações diferentes para o MESMO produto (mesmo EAN: {ean}). 
Sua tarefa é analisar as duas opções e retornar APENAS UM JSON válido com o melhor conjunto de informações combinadas (o nome mais claro e descritivo, a marca mais correta e a melhor categoria).

DADOS EXISTENTES NA BIBLIOTECA (Opção A):
{dados_a}

NOVOS DADOS DO MERCADO (Opção B):
{dados_b}

REGRAS:
1. Combine as informações para criar o nome mais completo (incluindo peso/volume se houver).
2. Não invente dados que não estão em nenhuma das opções.
3. Crie tags relevantes (5 a 8 tags em minúsculas).
4. Retorne APENAS um JSON válido.

FORMATO DE SAÍDA EXATO:
{{
"nome_comum": "Melhor Nome Combinado",
"marca": "MELHOR MARCA",
"Categoria": "Melhor Categoria",
"subcategoria": "Melhor Subcategoria",
"tipo_produto": "Melhor Tipo",
"tags": ["tag1", "tag2"]
}}
"""

async def resolver_conflitos_ia_async(lista_conflitos, concurrency=10):
    if not lista_conflitos: return {}

    mapa_resolvidos = {}
    logger.info(f"🤖 Resolvendo {len(lista_conflitos)} conflitos de EAN via IA...")

    semaphore = asyncio.Semaphore(concurrency)

    async def _processar_conflito(i, conflito):
        async with semaphore:
            ean = conflito.get("EAN")
            dados_a = conflito.get("dados_biblioteca", {})
            dados_b = conflito.get("dados_novos", {})

            logger.info(f"⏳ Resolvendo conflito {i}/{len(lista_conflitos)} para EAN {ean}")

            prompt = PROMPT_CONFLITO.format(
                ean=ean,
                dados_a=json.dumps(dados_a, ensure_ascii=False, indent=2),
                dados_b=json.dumps(dados_b, ensure_ascii=False, indent=2)
            )

            sucesso = False
            tentativas = 0
            resultado_json = None

            while not sucesso and tentativas < 3:
                resposta_texto = await _chamar_gemini_com_retry(prompt)
                if not resposta_texto:
                    break

                try:
                    match = re.search(r'\{.*\}', resposta_texto, re.DOTALL)
                    json_str = match.group(0) if match else resposta_texto
                    resultado_json = json.loads(json_str)
                    sucesso = True
                except json.JSONDecodeError:
                    logger.error(f"Erro ao parsear JSON do conflito para EAN {ean}. Tentando novamente.")
                    tentativas += 1

            if sucesso and resultado_json:
                mapa_resolvidos[ean] = {
                    "ean": ean,
                    "nome_comum": str(resultado_json.get("nome_comum", dados_a.get("nome_comum", ""))),
                    "marca": str(resultado_json.get("marca", dados_a.get("marca", ""))).upper(),
                    "Categoria": str(resultado_json.get("Categoria", dados_a.get("Categoria", ""))),
                    "subcategoria": str(resultado_json.get("subcategoria", dados_a.get("subcategoria", ""))),
                    "tipo_produto": str(resultado_json.get("tipo_produto", dados_a.get("tipo_produto", ""))),
                    "tags": resultado_json.get("tags", dados_a.get("tags", []))
                }

    tasks = [_processar_conflito(i, conflito) for i, conflito in enumerate(lista_conflitos, 1)]
    await asyncio.gather(*tasks)

    logger.info(f"✅ {len(mapa_resolvidos)} conflitos resolvidos pela IA.")
    return mapa_resolvidos
async def classificar_taxonomia_com_ia_async(lista_produtos_input, biblioteca_global, concurrency=10):
    if not lista_produtos_input: return {}, {}
    
    mapa_final = {}
    novas_entradas_biblioteca = {}
    
    # Carrega base de IA para garantir EANs unicos e nova lista
    biblioteca_ia = read_json_file(BIBLIOTECA_IA_FILE, default_value=[])
    if isinstance(biblioteca_ia, dict):
        biblioteca_ia = list(biblioteca_ia.values())
        
    # FIREWALL: Remove qualquer lixo sem EAN válido que já estava salvo no JSON antigo da IA
    biblioteca_ia = [item for item in biblioteca_ia if str(item.get("ean", "N/A")) != "N/A" and str(item.get("id", "")).isdigit()]
        
    eans_processados = {item["ean"]: item for item in biblioteca_ia if item.get("ean") and item.get("ean") != "N/A"}
    ids_processados = {item.get("id"): item for item in biblioteca_ia if item.get("id")}
    
    categorias_validas_str = ", ".join(CATEGORIAS_MASTER)
    
    produtos_para_processar = []
    chaves_na_fila = set()
    
    for p in lista_produtos_input:
        nome = p.get("Produto")
        if not nome: continue
        ean = str(p.get("EAN", "N/A"))
        marca = str(p.get("Marca", ""))
        
        chave_dedup = ean if ean != "N/A" else gerar_id_unico(nome, marca)
        
        if ean != "N/A" and ean in eans_processados:
            mapa_final[chave_dedup] = eans_processados[ean]
            continue
        elif chave_dedup in ids_processados:
            mapa_final[chave_dedup] = ids_processados[chave_dedup]
            continue
            
        if chave_dedup not in chaves_na_fila:
            chaves_na_fila.add(chave_dedup)
            produtos_para_processar.append(p)
        
    if not produtos_para_processar:
        return mapa_final, {}
        
    logger.info(f"🤖 Triagem concluída: dos {len(lista_produtos_input)} produtos recebidos, {len(produtos_para_processar)} são únicos e serão enviados ao Gemini.")
    
    total_produtos = len(produtos_para_processar)
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def _processar_produto(i, p):
        async with semaphore:
            nome = p.get("Produto", "")
            logger.info(f"⏳ Processando produto {i}/{total_produtos}: {nome}")
            marca = p.get("Marca", "")
            ean = str(p.get("EAN", "N/A"))
            cat_mercado = p.get("Categoria", "")
            chave_dedup = ean if ean != "N/A" else gerar_id_unico(nome, marca)
            
            prompt = PROMPT_CLASSIFICACAO.format(
                nome=nome,
                marca=marca,
                ean=ean,
                categoria_mercado=cat_mercado,
                categorias_validas=categorias_validas_str
            )
            
            sucesso = False
            tentativas_geral = 0
            resultado_json = None
            
            while not sucesso and tentativas_geral < 3:
                resposta_texto = await _chamar_gemini_com_retry(prompt)
                if not resposta_texto:
                    break
                    
                # Verifica proibição do Geral
                if re.search(r'\b(geral|outros)\b', resposta_texto, re.IGNORECASE):
                    logger.warning(f"⚠️ Resposta da IA conteve 'Geral/Outros' para '{nome}'. Recusando e tentando novamente.")
                    tentativas_geral += 1
                    continue
                    
                try:
                    # Extrair JSON da resposta
                    match = re.search(r'\{.*\}', resposta_texto, re.DOTALL)
                    if match:
                        json_str = match.group(0)
                    else:
                        json_str = resposta_texto
                        
                    resultado_json = json.loads(json_str)
                    sucesso = True
                except json.JSONDecodeError:
                    logger.error(f"Erro ao parsear JSON da IA para '{nome}'. Tentando novamente.")
                    tentativas_geral += 1
                    
            if sucesso and resultado_json:
                final_ean = str(resultado_json.get("ean", "N/A"))
                marca_resultado = str(resultado_json.get("marca", marca)).upper()
                nome_comum = str(resultado_json.get("nome_comum", nome))
                
                # Se EAN for N/A, gera ID único
                item_id = final_ean
                if final_ean == "N/A" or not final_ean:
                    item_id = gerar_id_unico(nome_comum, marca_resultado)
                
                # Formatar item 
                item_ia = {
                    "id": item_id,
                    "ean": final_ean,
                    "nome_comum": nome_comum,
                    "marca": marca_resultado,
                    "Categoria": resultado_json.get("Categoria"),
                    "subcategoria": resultado_json.get("subcategoria"),
                    "tipo_produto": resultado_json.get("tipo_produto"),
                    "tags": resultado_json.get("tags", []),
                    "revisado_humano": False
                }
                
                async with lock:
                    # Verifica duplicatas e insere APENAS se tiver EAN válido
                    if final_ean != "N/A" and final_ean and ean_e_valido(final_ean):
                        if item_id not in ids_processados and final_ean not in eans_processados:
                            biblioteca_ia.append(item_ia)
                            eans_processados[final_ean] = item_ia
                            ids_processados[item_id] = item_ia
                            novas_entradas_biblioteca[item_id] = item_ia
                        else:
                            item_ia = ids_processados.get(item_id) or eans_processados.get(final_ean) or item_ia
                        
                    mapa_final[chave_dedup] = item_ia

    tasks = [_processar_produto(i, p) for i, p in enumerate(produtos_para_processar, 1)]
    await asyncio.gather(*tasks)

    # Exporte o resultado final para o formato exigido
    write_json_file(BIBLIOTECA_IA_FILE, biblioteca_ia)
    logger.info(f"✅ Classificação IA concluída. Base salva em {BIBLIOTECA_IA_FILE} com {len(biblioteca_ia)} itens.")
    
    return mapa_final, novas_entradas_biblioteca
