import json
import os
import asyncio
import logging
import re

# Importa as ferramentas da IA do seu classificador já existente
from classificador_ia import (
    PROMPT_CLASSIFICACAO, 
    PROMPT_CONFLITO,
    CATEGORIAS_MASTER
)
import classificador_ia
from buscador_ean import tentar_recuperar_ean

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ARQUIVO_PENDENTES = os.path.join(DATA_DIR, "pendentes_ia.json")
ARQUIVO_BIBLIOTECA = os.path.join(DATA_DIR, "biblioteca_produtos.json")
ARQUIVO_PROCESSADOS = os.path.join(DATA_DIR, "itens_prontos_para_comparar.json")
ARQUIVO_QUARENTENA = os.path.join(DATA_DIR, "quarentena_anomalias.json")
ARQUIVO_CACHE_WEB = os.path.join(DATA_DIR, "cache_buscas_web.json")

def ean_eh_valido(ean_str):
    ean_str = str(ean_str).strip()
    if ean_str.startswith('INT_'): return True
    if not ean_str.isdigit(): return False
    if len(ean_str) not in (8, 12, 13, 14): return False
    if len(set(ean_str)) == 1: return False
    if ean_str.startswith('0000000'): return False
    
    padded = ean_str.zfill(14)
    total = sum(int(padded[i]) * (3 if i % 2 == 0 else 1) for i in range(13))
    return str((10 - (total % 10)) % 10) == padded[13]

def padronizar_multiplicacao(texto):
    # Garante caixa alta, remove espaços extras e mantém ponto decimal limpo
    texto = str(texto).upper().replace("\xa0", " ").replace(",", ".")
    
    # 1. Promoções "LEVE X PAGUE Y" / "LV X PG Y"
    padrao_promo = r"\b(LEVE|LV)\s*(\d+)\s*(PAGUE|PG)\s*(\d+)\b"
    match_promo = re.search(padrao_promo, texto)
    
    # 2. Padrão Clássico (ex: 10X5.2, 3X90G, 300/190ML)
    padrao_x = r"(\d+)\s*[X/]\s*(\d+\.?\d*)\s*(G|KG|ML|L|UN)?"
    def replacer_x(match):
        qtd = float(match.group(1))
        peso_unitario = float(match.group(2))
        unidade = match.group(3) if match.group(3) else "G"
        if "/" in match.group(0):
            return f"{int(qtd)}{unidade} {int(peso_unitario)}{unidade}"
        peso_total = qtd * peso_unitario
        return f"{int(peso_total) if peso_total.is_integer() else peso_total}{unidade} {int(qtd)}UN"
    texto = re.sub(padrao_x, replacer_x, texto)
    
    # 3. Padrão Descritivo Comercial (ex: "10 UNIDADES 8G CADA", "10 UN 11G CADA")
    padrao_cada = r"(\d+)\s*(?:UN|UNID|UNIDADES|SACHES|CAPSULA|CAPSULAS)?\s*(?:DE)?\s*(\d+\.?\d*)\s*(G|KG|ML|L)\s*CADA"
    def replacer_cada(match):
        qtd = float(match.group(1))
        peso_unitario = float(match.group(2))
        unidade = match.group(3)
        peso_total = qtd * peso_unitario
        return f"{int(peso_total) if peso_total.is_integer() else peso_total}{unidade} {int(qtd)}UN"
    texto = re.sub(padrao_cada, replacer_cada, texto)
    
    return texto

def normalizar_sinonimos(texto):
    texto = str(texto).upper()
    substituicoes = {
        r"\bUNIDADES\b": "UN", r"\bUNIDADE\b": "UN", r"\bUNID\b": "UN", r"\bSACHÊS\b": "UN", r"\bSACHES\b": "UN",
        r"\bCÁPSULA\b": "CAPSULA", r"\bCÁPSULAS\b": "CAPSULA", r"\bKIT\b": "PACK", r"\bMUÇARELA\b": "MUSSARELA",
        r"\bMUCSSARELA\b": "MUSSARELA", r"\bMACARRÃO\b": "MASSA", r"\bMASSA ITALIANA\b": "MASSA", r"\bFETTUCINE\b": "FETTUCCINE",
        r"\bLIMÃO\b": "LIMAO", r"\bMAÇÃ\b": "MACA", r"\bAÇÚCAR\b": "ACUCAR", r"\bCAFÉ\b": "CAFE", r"\bCAFÊ\b": "CAFE",
        r"\bCAFA\b": "CAFE", r"\bCHÁ\b": "CHA", r"\bFRALDAS\b": "FRALDA", r"\bPCTS\b": "PCT", r"\bPACOTES\b": "PCT",
        r"\bPACOTE\b": "PCT", r"\bCAIXAS\b": "CX", r"\bCAIXA\b": "CX", r"\bTETRA PAK\b": "CX", r"\bTETRAPAK\b": "CX",
        r"\bLITRO\b": "L", r"\bLITROS\b": "L", r"\bBEBIDA EM CÁPSULAS\b": "CAFE EM CAPSULA",
        r"\bCHOCOLATE QUENTE EM CÁPSULA\b": "CAFE EM CAPSULA", r"\bMOCHACCINO EM CÁPSULA\b": "CAFE EM CAPSULA"
    }
    for padrao, substituto in substituicoes.items():
        texto = re.sub(padrao, substituto, texto)
    return texto

async def resolver_ean_novo(ean, itens_crus):
    melhor_item = max(itens_crus, key=lambda x: len(str(x.get("Produto", x.get("nome_comum", ""))).strip()))
    melhor_nome = str(melhor_item.get("Produto", melhor_item.get("nome_comum", ""))).strip() or "PRODUTO DESCONHECIDO"
    
    marcas = [str(item.get("Marca", item.get("marca", ""))).strip().upper() for item in itens_crus]
    marcas_validas = [m for m in marcas if m not in ("OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "", "NONE")]
    
    if marcas_validas:
        from collections import Counter
        melhor_marca = Counter(marcas_validas).most_common(1)[0][0]
    else:
        melhor_marca = marcas[0] if marcas else "OUTROS"
        
    categoria = itens_crus[0].get("Categoria", "OUTROS")
    imagem_escolhida = melhor_item.get("Link_Imagem", melhor_item.get("imagem", ""))
    
    if not imagem_escolhida or not str(imagem_escolhida).startswith("http"):
        for item in itens_crus:
            img = item.get("Link_Imagem", item.get("imagem", ""))
            if img and str(img).startswith("http"):
                nome_deste = str(item.get("Produto", item.get("nome_comum", ""))).strip().upper()
                p1 = nome_deste.split()[0] if nome_deste.split() else ""
                p2 = melhor_nome.upper().split()[0] if melhor_nome.split() else ""
                if p1 and p2 and p1 == p2:
                    imagem_escolhida = img
                    break
    
    produto_ouro = {
        "id": str(ean), "nome_comum": melhor_nome, "marca": melhor_marca, "ean": str(ean),
        "Categoria": categoria, "subcategoria": "N/A", "tipo_produto": "N/A", "imagem": imagem_escolhida,
        "tags": [], "revisado_humano": False
    }
    return produto_ouro

def checar_conflito_anomalia(nome_base, nome_novo):
    def pre_limpar_string(texto):
        texto = str(texto).upper().replace("\xa0", " ").replace(",", ".")
        texto = re.sub(r'(?<!\d)-(?!\d)', ' ', texto) 
        substituicoes = {
            r"CAF[ÉÊA]": "CAFE", r"CH[ÁA]": "CHA", r"M[AÇÃ]A": "MACA", r"A[ÇÚ]CAR": "ACUCAR",
            r"C[ÁA]PSULA[S]?": "CAPSULA", r"UNIDADE[S]?": "UN", r"UNID": "UN", r"SACH[ÊE][S]?": "UN",
            r"\bCOOKIE[S]?\b": "BISCOITO_COOKIE", r"\bBISCOITO PIRAQUE COOKIES\b": "BISCOITO_COOKIE PIRAQUE"
        }
        for p, s in substituicoes.items():
            texto = re.sub(p, s, texto)
        return texto

    nome_base_norm = normalizar_sinonimos(padronizar_multiplicacao(pre_limpar_string(nome_base)))
    nome_novo_norm = normalizar_sinonimos(padronizar_multiplicacao(pre_limpar_string(nome_novo)))
    
    if nome_base_norm.replace(" ", "") == nome_novo_norm.replace(" ", ""):
        return False

    def extrair_metricas(t):
        pesos = re.findall(r'\b(\d+[,.]?\d*)\s*(KG|G|ML|L)\b', t)
        unidades = re.findall(r'\b(\d+)\s*UN\b', t)
        return {
            "peso_num": float(pesos[0][0]) if pesos else None, 
            "peso_uni": pesos[0][1] if pesos else None,
            "unidades": int(unidades[0]) if unidades else None
        }

    m_base = extrair_metricas(nome_base_norm)
    m_novo = extrair_metricas(nome_novo_norm)
    peso_omitido = (m_base["peso_num"] is None) != (m_novo["peso_num"] is None)

    # --- REGRA DE EXCEÇÃO DO PINHO SOL ATUALIZADA ---
    if "PINHO SOL" in nome_base_norm or "PINHO SOL" in nome_novo_norm:
        if m_base["peso_num"] and m_novo["peso_num"] and m_base["peso_uni"] == m_novo["peso_uni"]:
            v_max = max(m_base["peso_num"], m_novo["peso_num"])
            v_min = min(m_base["peso_num"], m_novo["peso_num"])
            if v_max / v_min > 1.5: 
                return True 
        return False 

    # 1. Estado Físico
    fisico_base = {w for w in ["FATIADO", "RALADO"] if w in nome_base_norm}
    fisico_novo = {w for w in ["FATIADO", "RALADO"] if w in nome_novo_norm}
    if fisico_base != fisico_novo and not peso_omitido:
        if m_base["peso_num"] != m_novo["peso_num"]: return True

    # 2. Validação Flexível de Atacado / Diferença de Volume (Diferença de UN ou Peso)
    if m_base["unidades"] and m_novo["unidades"] and m_base["unidades"] != m_novo["unidades"]:
        eh_fralda = "FRALDA" in nome_base_norm or "FRALDA" in nome_novo_norm
        if eh_fralda and abs(m_base["unidades"] - m_novo["unidades"]) <= 6:
            return False
        return True

    if m_base["peso_num"] and m_novo["peso_num"]:
        v1 = m_base["peso_num"] * 1000 if m_base["peso_uni"] in ("L", "KG") else m_base["peso_num"]
        v2 = m_novo["peso_num"] * 1000 if m_novo["peso_uni"] in ("L", "KG") else m_novo["peso_num"]
        
        v_max = max(v1, v2)
        v_min = min(v1, v2)
        if v_max / v_min > 1.5 and not peso_omitido: 
            return True

    # 3. Diferença de venda por peso vs unidade
    # Se um nome indica explicitamente venda por KG e o outro não indica nada ou indica UN.
    tem_kg_base = bool(re.search(r'\bKG\b|/KG\b|\bQUILO\b', nome_base_norm))
    tem_kg_novo = bool(re.search(r'\bKG\b|/KG\b|\bQUILO\b', nome_novo_norm))
    if tem_kg_base != tem_kg_novo and (m_base["peso_num"] is None and m_novo["peso_num"] is None):
        # Só barra se for explicitamente diferente em conceito de KG vs UN e não houver métricas de peso comparáveis
        return True

    # Ignora divergências puras de nome (assinatura e similaridade de texto foram removidas)
    return False

async def main():
    if not os.path.exists(ARQUIVO_PENDENTES):
        logger.info("✅ Arquivo pendentes_ia.json não existe. Nenhum item para processar.")
        return

    try:
        with open(ARQUIVO_PENDENTES, "r", encoding="utf-8") as f:
            pendentes = json.load(f)
    except Exception as e:
        logger.error(f"❌ Erro ao ler pendentes: {e}")
        return

    if not isinstance(pendentes, list) or not pendentes:
        logger.info("✅ Nenhum produto pendente na lista.")
        return

    biblioteca = {}
    if os.path.exists(ARQUIVO_BIBLIOTECA):
        try:
            with open(ARQUIVO_BIBLIOTECA, "r", encoding="utf-8") as f:
                biblioteca = json.load(f)
        except Exception as e:
            logger.error(f"❌ Erro ao ler biblioteca: {e}")

    cache_buscas_web = {}
    if os.path.exists(ARQUIVO_CACHE_WEB):
        try:
            with open(ARQUIVO_CACHE_WEB, "r", encoding="utf-8") as f:
                cache_buscas_web = json.load(f)
        except Exception as e:
            logger.error(f"❌ Erro ao ler cache_buscas_web: {e}")

    itens_por_ean = {}
    itens_sem_ean = []
    itens_quarentena = []

    if os.path.exists(ARQUIVO_QUARENTENA):
        try:
            with open(ARQUIVO_QUARENTENA, "r", encoding="utf-8") as f:
                itens_quarentena = json.load(f)
        except:
            itens_quarentena = []

    def salvar_estado_intermediario():
        try:
            with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
                json.dump(pendentes, f, ensure_ascii=False, indent=4)
            with open(ARQUIVO_BIBLIOTECA, "w", encoding="utf-8") as f:
                json.dump(biblioteca, f, ensure_ascii=False, indent=4)
            
            q_dict = {}
            for q in itens_quarentena:
                k = f"{q.get('EAN', '')}_{q.get('Produto', '')}_{q.get('Mercado', '')}"
                q_dict[k] = q
            with open(ARQUIVO_QUARENTENA, "w", encoding="utf-8") as f:
                json.dump(list(q_dict.values()), f, ensure_ascii=False, indent=4)
            with open(ARQUIVO_CACHE_WEB, "w", encoding="utf-8") as f:
                json.dump(cache_buscas_web, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"   ❌ Erro ao salvar estado intermediário: {e}")

    # --- PASSO CRÍTICO: HIGIENIZAÇÃO PRÉVIA DE TODO O LOTE ---
    for item in pendentes:
        nome_bruto = item.get("Produto", item.get("nome_comum", ""))
        if nome_bruto:
            nome_tratado = normalizar_sinonimos(padronizar_multiplicacao(nome_bruto))
            nome_tratado = nome_tratado.replace("\xa0", " ").strip()
            if "Produto" in item: item["Produto"] = nome_tratado
            if "nome_comum" in item: item["nome_comum"] = nome_tratado

    # --- MONTAGEM COMPACTA DE GRUPOS POR EAN ---
    for item in pendentes:
        ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        if ean in ("N/A", "", "None", "nan") or not ean_eh_valido(ean):
            itens_sem_ean.append(item)
            continue
            
        if ean not in itens_por_ean:
            itens_por_ean[ean] = []
        itens_por_ean[ean].append(item)

    # --- LOOP DE VALIDAÇÃO DA DEFESA AUTOMÁTICA ---
    itens_filtrados_por_ean = {}
    for ean, lista_itens in itens_por_ean.items():
        itens_filtrados_por_ean[ean] = []
        for item in lista_itens:
            nome_item = str(item.get("Produto", item.get("nome_comum", ""))).strip().upper()
            mercado_item = item.get("Mercado", "")
            conflito = False
            nome_conflito = ""

            if ean in biblioteca:
                nome_ouro = str(biblioteca[ean].get("nome_comum", "")).upper()
                # --- DESATIVADO TEMPORARIAMENTE: Defesa Automática ---
                # if checar_conflito_anomalia(nome_ouro, nome_item):
                #     conflito = True
                #     nome_conflito = nome_ouro
            elif itens_filtrados_por_ean[ean]:
                nome_primeiro = str(itens_filtrados_por_ean[ean][0].get("Produto", "")).upper()
                # --- DESATIVADO TEMPORARIAMENTE: Defesa Automática ---
                # if checar_conflito_anomalia(nome_primeiro, nome_item):
                #     conflito = True
                #     nome_conflito = nome_primeiro

            if conflito:
                sufixos = []
                if re.search(r'\bKG\b|/KG\b|\bQUILO\b', nome_item): sufixos.append("KG")
                if "RALADO" in nome_item: sufixos.append("RALADO")
                if "FATIADO" in nome_item: sufixos.append("FATIADO")
                if re.search(r'\b(DISPLAY|FARDO|FD|PACK)\b|\b(CX|PCT)\s+(C/|COM)\s*\d+', nome_item): sufixos.append("CX")
                
                suf_str = "_".join(sufixos) if sufixos else "VARIANTE"
                novo_ean = f"INT_{ean}_{suf_str}"
                logger.warning(f"🛡️ Defesa Automática: Separando '{nome_item}' de '{nome_conflito}' (EAN: {ean} -> {novo_ean}) no mercado {mercado_item}")
                
                item["EAN"] = novo_ean
                itens_quarentena.append(item)
            else:
                itens_filtrados_por_ean[ean].append(item)

    itens_por_ean = {k: v for k, v in itens_filtrados_por_ean.items() if v}

    # --- TENTATIVA DE RECUPERAÇÃO DE EANs FALTANTES ---
    if itens_sem_ean:
        total_sem_ean = len(itens_sem_ean)
        logger.info(f"🔍 Tentando recuperar EAN para {total_sem_ean} itens sem código...")
        
        local_lookup = {}
        for b_ean, b_item in biblioteca.items():
            b_nome = str(b_item.get("nome_comum", "")).strip().upper()
            b_marca = str(b_item.get("marca", "")).strip().upper()
            if b_nome:
                local_lookup[f"{b_nome}|{b_marca}"] = (b_ean, b_item)

        sem_recuperacao = asyncio.Semaphore(4)
        progresso_ean = {"atual": 0}
        buscas_em_andamento = {}
        
        async def recuperar_ean(item):
            nome = str(item.get("Produto", item.get("nome_comum", ""))).strip()
            marca_bruta = str(item.get("Marca", item.get("marca", ""))).strip()
            marca_busca = marca_bruta if marca_bruta.upper() not in ["OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "NONE", "GERAL"] else ""
            chave_busca = f"{nome.upper()}|{marca_bruta.upper()}"
            
            # Lookup Local Imediato (Sem bloquear Semáforo de Web)
            if chave_busca in local_lookup:
                progresso_ean["atual"] += 1
                b_ean, b_item = local_lookup[chave_busca]
                item["EAN"] = b_ean
                cat_atual = item.get("Categoria", "GERAL")
                if not cat_atual or cat_atual in ("GERAL", "OUTROS", "N/A", "None", ""):
                    item["Categoria"] = b_item.get("Categoria", "OUTROS")
                    item["subcategoria"] = b_item.get("subcategoria", "N/A")
                    item["tipo_produto"] = b_item.get("tipo_produto", "N/A")
                if not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM":
                    item["Link_Imagem"] = b_item.get("imagem", "")
                logger.info(f"   ✅ [{progresso_ean['atual']}/{total_sem_ean}] EAN Local (Exato): '{nome}' -> {item['EAN']}")
                return item
                
            # Lookup de Cache Imediato
            if chave_busca in cache_buscas_web:
                progresso_ean["atual"] += 1
                resultado_cache = cache_buscas_web[chave_busca]
                item["EAN"] = str(resultado_cache["ean"])
                item["Fonte_EAN"] = resultado_cache.get("fonte", "Web") + " (Cache)"
                if resultado_cache.get("Link_Imagem") and (not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM"):
                    item["Link_Imagem"] = resultado_cache.get("Link_Imagem", "")
                logger.info(f"   ⚡ [{progresso_ean['atual']}/{total_sem_ean}] EAN Web (Cache): '{nome}' -> {item['EAN']}")
                return item
                
            # Desduplicação Inteligente Lider vs Seguidor
            if chave_busca not in buscas_em_andamento:
                buscas_em_andamento[chave_busca] = asyncio.Event()
                sou_lider = True
            else:
                sou_lider = False

            if not sou_lider:
                await buscas_em_andamento[chave_busca].wait()
                progresso_ean["atual"] += 1
                if chave_busca in cache_buscas_web:
                    resultado_cache = cache_buscas_web[chave_busca]
                    item["EAN"] = str(resultado_cache["ean"])
                    item["Fonte_EAN"] = resultado_cache.get("fonte", "Web") + " (Cache Espera)"
                    if resultado_cache.get("Link_Imagem") and (not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM"):
                        item["Link_Imagem"] = resultado_cache.get("Link_Imagem", "")
                    logger.info(f"   ⚡ [{progresso_ean['atual']}/{total_sem_ean}] EAN Web (Cache Espera): '{nome}' -> {item['EAN']}")
                    return item
                else:
                    nome_limpo = re.sub(r'[^a-zA-Z0-9]', '', str(nome).upper())
                    marca_limpa = re.sub(r'[^a-zA-Z0-9]', '', str(marca_bruta).upper())
                    id_interno = f"INT_{marca_limpa}_{nome_limpo}"[:50]
                    item["EAN"] = id_interno
                    item["Fonte_EAN"] = "Gerado_Internamente"
                    logger.info(f"   ⚙️ [{progresso_ean['atual']}/{total_sem_ean}] EAN Interno gerado (Após Espera): '{nome}' -> {item['EAN']}")
                    return item

            async with sem_recuperacao:
                progresso_ean["atual"] += 1
                atual = progresso_ean["atual"]
                prefixo_progresso = f"[{atual}/{total_sem_ean}]"
                
                import random
                await asyncio.sleep(random.uniform(0.5, 1.5))

                resultado = await tentar_recuperar_ean(nome, marca_busca)
                if resultado and resultado.get("ean") and str(resultado["ean"]).isdigit():
                    cache_buscas_web[chave_busca] = resultado
                    item["EAN"] = str(resultado["ean"])
                    item["Fonte_EAN"] = resultado.get("fonte", "Web")
                    if resultado.get("Link_Imagem") and (not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM"):
                        item["Link_Imagem"] = resultado.get("Link_Imagem", "")
                    logger.info(f"   🌐 {prefixo_progresso} EAN Web ({resultado.get('fonte')}): '{nome}' -> {item['EAN']}")
                else:
                    nome_limpo = re.sub(r'[^a-zA-Z0-9]', '', str(nome).upper())
                    marca_limpa = re.sub(r'[^a-zA-Z0-9]', '', str(marca_bruta).upper())
                    id_interno = f"INT_{marca_limpa}_{nome_limpo}"[:50]
                    item["EAN"] = id_interno
                    item["Fonte_EAN"] = "Gerado_Internamente"
                    logger.info(f"   ⚙️ {prefixo_progresso} EAN Interno gerado: '{nome}' -> {item['EAN']}")
                    logger.warning("   ⏳ Esfriando IP por 3.0s após falha na busca web...")
                    await asyncio.sleep(3.0)
                
                buscas_em_andamento[chave_busca].set()
                return item

        TAMANHO_LOTE_REC = 200
        lotes_recuperacao = [itens_sem_ean[i:i + TAMANHO_LOTE_REC] for i in range(0, len(itens_sem_ean), TAMANHO_LOTE_REC)]
        itens_sem_ean_restantes = []
        
        for num_lote, lote in enumerate(lotes_recuperacao, 1):
            tarefas_recuperacao = [recuperar_ean(i) for i in lote]
            resultados_recuperacao = await asyncio.gather(*tarefas_recuperacao)
            
            for i, item_original in enumerate(lote):
                item_recuperado = resultados_recuperacao[i]
                if item_recuperado:
                    novo_ean = item_recuperado["EAN"]
                    if novo_ean.startswith("INT_"):
                        itens_quarentena.append(item_recuperado)
                    else:
                        if novo_ean not in itens_por_ean: itens_por_ean[novo_ean] = []
                        itens_por_ean[novo_ean].append(item_recuperado)
                else:
                    itens_sem_ean_restantes.append(item_original)
                    
            logger.info(f"   💾 Salvando progresso intermediário (Lote {num_lote}/{len(lotes_recuperacao)})...")
            salvar_estado_intermediario()
            
        itens_sem_ean = itens_sem_ean_restantes

    # --- PROCESSAMENTO E SALVAMENTO EM LOTES ---
    eans_para_processar = [(ean, lista) for ean, lista in itens_por_ean.items() if ean not in biblioteca]
    total_processar = len(eans_para_processar)
    novos_na_biblioteca = 0
    eans_com_falha = set()

    if eans_para_processar:
        TAMANHO_LOTE = 500
        logger.info(f"🚀 Processando {total_processar} novos EANs...")
        semaphore = asyncio.Semaphore(20)
        itens_processados_count = 0

        async def processar_item(ean, lista):
            nonlocal itens_processados_count
            async with semaphore:
                itens_processados_count += 1
                return ean, await resolver_ean_novo(ean, lista)

        lotes = [eans_para_processar[i:i + TAMANHO_LOTE] for i in range(0, total_processar, TAMANHO_LOTE)]
        for num_lote, lote in enumerate(lotes, 1):
            tasks = [processar_item(ean, lista) for ean, lista in lote]
            resultados = await asyncio.gather(*tasks)
            
            for ean, prod_ouro in resultados:
                if prod_ouro:
                    biblioteca[ean] = prod_ouro
                    novos_na_biblioteca += 1
                else:
                    eans_com_falha.add(ean)
                    
            logger.info(f"   💾 Salvando progresso da biblioteca (Lote {num_lote}/{len(lotes)})...")
            salvar_estado_intermediario()

    # --- TRIAGEM FINAL DE ARQUIVOS (FIM DO LOOP INFINITO) ---
    itens_prontos = []
    itens_restantes = []
    
    q_keys = {f"{q.get('EAN', '')}_{q.get('Produto', '')}_{q.get('Mercado', '')}" for q in itens_quarentena}

    for item in pendentes:
        ean_str = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        item_k = f"{ean_str}_{item.get('Produto', '')}_{item.get('Mercado', '')}"
        
        if item_k in q_keys or ean_str.startswith("INT_"):
            if item_k not in q_keys: 
                itens_quarentena.append(item)
                q_keys.add(item_k)
            continue

        if ean_str in ("N/A", "", "None", "nan") or not ean_eh_valido(ean_str) or ean_str in eans_com_falha:
            itens_restantes.append(item)
        elif ean_str in biblioteca:
            b_item = biblioteca[ean_str]
            cat_atual = item.get("Categoria", "GERAL")
            if not cat_atual or cat_atual in ("GERAL", "OUTROS", "N/A", "None", ""):
                item["Categoria"] = b_item.get("Categoria", "OUTROS")
                item["subcategoria"] = b_item.get("subcategoria", "N/A")
                item["tipo_produto"] = b_item.get("tipo_produto", "N/A")
            itens_prontos.append(item)
        else:
            itens_restantes.append(item)

    # Escrita final e persistência em disco
    with open(ARQUIVO_BIBLIOTECA, "w", encoding="utf-8") as f:
        json.dump(biblioteca, f, ensure_ascii=False, indent=4)
    with open(ARQUIVO_PROCESSADOS, "w", encoding="utf-8") as f:
        json.dump(itens_prontos, f, ensure_ascii=False, indent=4)
    with open(ARQUIVO_QUARENTENA, "w", encoding="utf-8") as f:
        json.dump(itens_quarentena, f, ensure_ascii=False, indent=4)
    with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
        json.dump(itens_restantes, f, ensure_ascii=False, indent=4)

    logger.info(f"🧹 Concluído! {len(itens_prontos)} prontos, {len(itens_quarentena)} na quarentena e {len(itens_restantes)} pendentes.")

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())