import json
import os
import sys
import asyncio
import logging
import re

from buscador_ean import tentar_recuperar_ean
from utils import ean_eh_valido, otimizar_nome_produto, aplicar_title_case, ler_json_seguro, salvar_json_atomico, ArquivoCorrompidoError
from casamento_produtos import padronizar_multiplicacao, normalizar_sinonimos, CasadorProdutos, montar_equivalencias, nomes_conferem
import revisar_casamentos

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ARQUIVO_PENDENTES = os.path.join(DATA_DIR, "pendentes_ia.json")
ARQUIVO_BIBLIOTECA = os.path.join(DATA_DIR, "biblioteca_produtos.json")
ARQUIVO_PROCESSADOS = os.path.join(DATA_DIR, "itens_prontos_para_comparar.json")
ARQUIVO_QUARENTENA = os.path.join(DATA_DIR, "quarentena_anomalias.json")
ARQUIVO_CACHE_WEB = os.path.join(DATA_DIR, "cache_buscas_web.json")

# Busca de EAN na web (APIs). Desligue com "python 4_resolver_pendentes.py --sem-web" ou BUSCA_WEB_EAN=0 no .env
BUSCA_WEB = "--sem-web" not in sys.argv and os.getenv("BUSCA_WEB_EAN", "1") != "0"

# padronizar_multiplicacao e normalizar_sinonimos agora ficam em casamento_produtos.py

def id_produto_valido(ean):
    """EAN válido, grupo interno (INT_) ou variante criada pela Defesa Automática (ex: 7894900010015_LATA)."""
    ean = str(ean)
    if ean_eh_valido(ean):
        return True
    base, _, sufixo = ean.partition("_")
    return bool(sufixo) and ean_eh_valido(base)

async def resolver_ean_novo(ean, itens_crus):
    from collections import Counter
    
    # 1. Limpar e Normalizar Nomes
    nomes_limpos = []
    for item in itens_crus:
        nome_bruto = str(item.get("Produto", item.get("nome_comum", ""))).strip()
        nomes_limpos.append(otimizar_nome_produto(nome_bruto))
        
    # 2. Votação (A Moda - Nome mais frequente)
    if nomes_limpos:
        # Conta a frequência de cada nome (ignorando maiúsculas/minúsculas para a contagem)
        contagem = Counter([n.upper() for n in nomes_limpos if n])
        if contagem:
            mais_comuns = contagem.most_common()
            if len(mais_comuns) == 1 or mais_comuns[0][1] > 1:
                # Se há um vencedor claro que se repete
                melhor_nome_upper = mais_comuns[0][0]
                # Pega a string original correspondente
                melhor_nome = next(n for n in nomes_limpos if n.upper() == melhor_nome_upper)
            else:
                # Se todos os mercados mandaram nomes diferentes, escolhe o de tamanho mediano
                tamanhos = [len(n) for n in nomes_limpos if n]
                media = sum(tamanhos) / len(tamanhos)
                melhor_nome = min([n for n in nomes_limpos if n], key=lambda x: abs(len(x) - media))
        else:
            melhor_nome = "PRODUTO DESCONHECIDO"
    else:
         melhor_nome = "PRODUTO DESCONHECIDO"
         
    # 3. Formatação Title Case (Tapa no Visual)
    melhor_nome_formatado = aplicar_title_case(melhor_nome)
    
    # 4. Encontrar o item original que mais se aproxima do escolhido para herdar imagens
    melhor_item = itens_crus[0]
    for i, n in enumerate(nomes_limpos):
        if n.upper() == melhor_nome.upper():
            melhor_item = itens_crus[i]
            break

    marcas = [str(item.get("Marca", item.get("marca", ""))).strip().upper() for item in itens_crus]
    marcas_validas = [m for m in marcas if m not in ("OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "", "NONE")]
    
    if marcas_validas:
        melhor_marca = Counter(marcas_validas).most_common(1)[0][0]
    else:
        melhor_marca = marcas[0] if marcas else "OUTROS"
        
    melhor_marca_formatada = aplicar_title_case(melhor_marca) if melhor_marca != "OUTROS" else "OUTROS"
        
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
        "id": str(ean), "nome_comum": melhor_nome_formatado, "marca": melhor_marca_formatada, "ean": str(ean),
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

    # 1. Estado Físico (REMOVIDO PARA NÃO BARRAR EANs CORRETOS)
    # Palavras como "FATIADO", "BANDEJA", "PEDACOS" muitas vezes são omitidas por alguns mercados,
    # mas se o EAN é o mesmo, é o mesmo produto de fábrica.
    # termos_fisicos = ["FATIADO", "FATIADA", "RALADO", "RALADA", "CORTADO", "CORTADA", "PICADO", "PICADA", "CUBOS", "BANDEJA", "DESCASCADO", "DESCASCADA", "PEDACOS"]
    # fisico_base = {w for w in termos_fisicos if w in nome_base_norm}
    # fisico_novo = {w for w in termos_fisicos if w in nome_novo_norm}
    # if fisico_base != fisico_novo: return True

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
        # ATUALIZAÇÃO: Muitos produtos embalados de açougue/frios têm EAN fixo e um mercado bota "KG" no nome e o outro não.
        # Só vamos barrar se um deles indicar "UN" ou "UNIDADE" explicitamente, caracterizando conflito real.
        tem_un_base = bool(re.search(r'\bUN\b|\bUNIDADE\b|\bUNIDADES\b|\bPC\b|\bPECA\b', nome_base_norm))
        tem_un_novo = bool(re.search(r'\bUN\b|\bUNIDADE\b|\bUNIDADES\b|\bPC\b|\bPECA\b', nome_novo_norm))
        if tem_un_base or tem_un_novo:
            return True
        # Se nenhum diz "UN", não é conflito forte o suficiente para ignorar um EAN válido.

    # 4. Lata vs Garrafa (Especialmente para Bebidas)
    is_lata_base = "LATA" in nome_base_norm
    is_lata_novo = "LATA" in nome_novo_norm
    is_garrafa_base = "GARRAFA" in nome_base_norm or "LONG NECK" in nome_base_norm
    is_garrafa_novo = "GARRAFA" in nome_novo_norm or "LONG NECK" in nome_novo_norm
    
    if (is_lata_base and is_garrafa_novo) or (is_garrafa_base and is_lata_novo):
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

    # Biblioteca, quarentena e itens prontos são gravados de volta no final.
    # Se algum estiver corrompido, aborta: seguir com {} / [] apagaria os dados bons.
    try:
        # Decisões S/N preenchidas na planilha de revisão entram antes de tudo
        revisar_casamentos.importar_decisoes()
        biblioteca = ler_json_seguro(ARQUIVO_BIBLIOTECA, {})
        itens_quarentena = ler_json_seguro(ARQUIVO_QUARENTENA, [])
        itens_prontos_anteriores = ler_json_seguro(ARQUIVO_PROCESSADOS, [])
        casamentos = revisar_casamentos.carregar_casamentos()
    except ArquivoCorrompidoError as e:
        logger.error(f"❌ {e}")
        logger.error("   Abortando para não sobrescrever dados. Restaure o arquivo (ou o .tmp ao lado dele) e rode de novo.")
        return

    try:
        cache_buscas_web = ler_json_seguro(ARQUIVO_CACHE_WEB, {})
    except ArquivoCorrompidoError as e:
        logger.warning(f"⚠️ {e} — começando com cache de buscas vazio.")
        cache_buscas_web = {}

    # --- CASAMENTO DE NOMES (local, sem IA/API) ---
    logger.info("🧠 Montando o índice de casamento de nomes da biblioteca...")
    casador = CasadorProdutos(biblioteca, casamentos)
    # Mesmo produto com mais de um EAN: todos passam a usar o EAN principal (um card só no app)
    equivalencias = montar_equivalencias(casador, casamentos)
    logger.info(f"   {len(equivalencias)} EANs repetidos serão unificados no EAN principal.")
    sugestoes_revisao = {}
    contagem_casamento = {"confirmado": 0, "auto": 0, "revisao": 0, "interno": 0, "web_rejeitado": 0}

    def ean_web_confiavel(resultado, nome, marca):
        """
        Um EAN vindo da web (ou do cache dela) só é aceito se o nome bater:
        - se o EAN já existe na biblioteca, com o nome da biblioteca;
        - senão, com o nome que a própria fonte devolveu.
        Sem nome para conferir, é rejeitado (era assim que números aleatórios viravam EAN).
        """
        ean = str((resultado or {}).get("ean", ""))
        if not ean_eh_valido(ean) or ean.startswith("INT_"):
            return False
        ean = equivalencias.get(ean, ean)
        if ean in biblioteca:
            ref = biblioteca[ean]
            return nomes_conferem(casador, nome, marca, ref.get("nome_comum", ""), ref.get("marca"))
        encontrado = str(resultado.get("nome_encontrado") or "")
        if encontrado and encontrado != "N/A":
            return nomes_conferem(casador, nome, marca, encontrado, resultado.get("marca_encontrada"))
        return False

    itens_por_ean = {}
    itens_sem_ean = []

    def salvar_estado_intermediario():
        try:
            salvar_json_atomico(ARQUIVO_PENDENTES, pendentes)
            salvar_json_atomico(ARQUIVO_BIBLIOTECA, biblioteca)
            
            q_dict = {}
            for q in itens_quarentena:
                k = f"{q.get('EAN', '')}_{q.get('Produto', '')}_{q.get('Mercado', '')}"
                q_dict[k] = q
            salvar_json_atomico(ARQUIVO_QUARENTENA, list(q_dict.values()))
            salvar_json_atomico(ARQUIVO_CACHE_WEB, cache_buscas_web)
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
        if ean in ("N/A", "", "None", "nan") or not id_produto_valido(ean):
            itens_sem_ean.append(item)
            continue

        if ean in equivalencias:
            item["EAN_Original"] = ean
            ean = equivalencias[ean]
            item["EAN"] = ean

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
                if checar_conflito_anomalia(nome_ouro, nome_item):
                    conflito = True
                    nome_conflito = nome_ouro
            elif itens_filtrados_por_ean[ean]:
                nome_primeiro = str(itens_filtrados_por_ean[ean][0].get("Produto", "")).upper()
                if checar_conflito_anomalia(nome_primeiro, nome_item):
                    conflito = True
                    nome_conflito = nome_primeiro

            if conflito:
                sufixos = []
                if re.search(r'\bKG\b|/KG\b|\bQUILO\b', nome_item): sufixos.append("KG")
                if "RALADO" in nome_item or "RALADA" in nome_item: sufixos.append("RALADO")
                if "FATIADO" in nome_item or "FATIADA" in nome_item: sufixos.append("FATIADO")
                if "CORTADO" in nome_item or "CORTADA" in nome_item: sufixos.append("CORTADA")
                if "PICADO" in nome_item or "PICADA" in nome_item: sufixos.append("PICADA")
                if "BANDEJA" in nome_item: sufixos.append("BANDEJA")
                if "DESCASCADO" in nome_item or "DESCASCADA" in nome_item: sufixos.append("DESCASCADA")
                if "CUBOS" in nome_item: sufixos.append("CUBOS")
                if re.search(r'\b(DISPLAY|FARDO|FD|PACK)\b|\b(CX|PCT)\s+(C/|COM)\s*\d+', nome_item): sufixos.append("CX")
                if "LATA" in nome_item: sufixos.append("LATA")
                if "GARRAFA" in nome_item or "LONG NECK" in nome_item: sufixos.append("GARRAFA")
                
                suf_str = "_".join(sufixos) if sufixos else "VARIANTE"
                novo_ean = f"{ean}_{suf_str}"
                logger.warning(f"🛡️ Defesa Automática: Separando '{nome_item}' de '{nome_conflito}' (EAN: {ean} -> {novo_ean}) no mercado {mercado_item}")
                
                item["EAN"] = novo_ean
                if novo_ean not in itens_filtrados_por_ean: itens_filtrados_por_ean[novo_ean] = []
                itens_filtrados_por_ean[novo_ean].append(item)
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
                b_ean = equivalencias.get(b_ean, b_ean)
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
                
            # Casamento de nomes com a biblioteca (marca + medida + palavras-chave)
            casamento = casador.casar(nome, marca_bruta)
            if casamento and casamento["tipo"] in ("confirmado", "auto"):
                progresso_ean["atual"] += 1
                contagem_casamento[casamento["tipo"]] += 1
                b_ean = equivalencias.get(casamento["ean"], casamento["ean"])
                b_item = biblioteca.get(b_ean, {})
                item["EAN"] = b_ean
                item["Fonte_EAN"] = f"Casamento {casamento['tipo']} ({casamento['score']})"
                cat_atual = item.get("Categoria", "GERAL")
                if not cat_atual or cat_atual in ("GERAL", "OUTROS", "N/A", "None", ""):
                    item["Categoria"] = b_item.get("Categoria", "OUTROS")
                if not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM":
                    item["Link_Imagem"] = b_item.get("imagem", "")
                logger.info(f"   🧩 [{progresso_ean['atual']}/{total_sem_ean}] Casamento {casamento['tipo']} ({casamento['score']}): '{nome}' -> {b_item.get('nome_comum', b_ean)}")
                return item
            if casamento and casamento["tipo"] == "revisao":
                contagem_casamento["revisao"] += 1
                sugestoes_revisao[casamento["chave"]] = {
                    "Mercado": item.get("Mercado", ""), "Nome no mercado": nome, "Marca": marca_bruta,
                    "EAN sugerido": casamento["ean"], "Nome na biblioteca": biblioteca.get(casamento["ean"], {}).get("nome_comum", ""),
                    "Pontuação": casamento["score"], "chave": casamento["chave"],
                }

            # Lookup de Cache Imediato (só se o EAN guardado conferir com o nome)
            if chave_busca in cache_buscas_web and ean_web_confiavel(cache_buscas_web[chave_busca], nome, marca_bruta):
                progresso_ean["atual"] += 1
                resultado_cache = cache_buscas_web[chave_busca]
                item["EAN"] = equivalencias.get(str(resultado_cache["ean"]), str(resultado_cache["ean"]))
                item["Fonte_EAN"] = resultado_cache.get("fonte", "Web") + " (Cache)"
                if resultado_cache.get("Link_Imagem") and (not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM"):
                    item["Link_Imagem"] = resultado_cache.get("Link_Imagem", "")
                logger.info(f"   ⚡ [{progresso_ean['atual']}/{total_sem_ean}] EAN Web (Cache): '{nome}' -> {item['EAN']}")
                return item
                
            if not BUSCA_WEB:
                progresso_ean["atual"] += 1
                item["EAN"] = casador.agrupar_interno(nome, marca_bruta)
                item["Fonte_EAN"] = "Grupo_Interno"
                contagem_casamento["interno"] += 1
                logger.info(f"   ⚙️ [{progresso_ean['atual']}/{total_sem_ean}] Grupo interno: '{nome}' -> {item['EAN']}")
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
                if chave_busca in cache_buscas_web and ean_web_confiavel(cache_buscas_web[chave_busca], nome, marca_bruta):
                    resultado_cache = cache_buscas_web[chave_busca]
                    item["EAN"] = equivalencias.get(str(resultado_cache["ean"]), str(resultado_cache["ean"]))
                    item["Fonte_EAN"] = resultado_cache.get("fonte", "Web") + " (Cache Espera)"
                    if resultado_cache.get("Link_Imagem") and (not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM"):
                        item["Link_Imagem"] = resultado_cache.get("Link_Imagem", "")
                    logger.info(f"   ⚡ [{progresso_ean['atual']}/{total_sem_ean}] EAN Web (Cache Espera): '{nome}' -> {item['EAN']}")
                    return item
                else:
                    item["EAN"] = casador.agrupar_interno(nome, marca_bruta)
                    item["Fonte_EAN"] = "Grupo_Interno"
                    contagem_casamento["interno"] += 1
                    logger.info(f"   ⚙️ [{progresso_ean['atual']}/{total_sem_ean}] Grupo interno (Após Espera): '{nome}' -> {item['EAN']}")
                    return item

            # O finally garante que os "seguidores" nunca fiquem esperando para sempre,
            # mesmo se a busca do líder der exceção.
            try:
                async with sem_recuperacao:
                    progresso_ean["atual"] += 1
                    atual = progresso_ean["atual"]
                    prefixo_progresso = f"[{atual}/{total_sem_ean}]"
                
                    import random
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                
                    # --- Lógica Inteligente para Pular Busca Web ---
                    categoria = str(item.get("Categoria", "")).upper()
                    categorias_frescos = ["HORTIFR", "PADARIA", "PEIXARIA", "AÇOUGUE", "ACOUGUE", "FRIOS"]
                
                    # Se tem marca reconhecida (Não é "Própria", "Outros", etc), tenta salvar o EAN na web!
                    marcas_genericas = ["OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "NONE", "GERAL", "", "FEIRA", "ACOUGUE", "PADARIA"]
                    tem_marca_famosa = marca_bruta.upper() not in marcas_genericas
                
                    # Só pula a web se for fresco E não tiver marca famosa
                    is_fresco_sem_marca = any(cf in categoria for cf in categorias_frescos) and not tem_marca_famosa
                
                    if is_fresco_sem_marca:
                        resultado = None
                        logger.info(f"   ⏭️ {prefixo_progresso} Busca web pulada para item fresco genérico ({categoria}).")
                    else:
                        try:
                            resultado = await tentar_recuperar_ean(nome, marca_busca)
                        except Exception as e:
                            logger.warning(f"   ⚠️ {prefixo_progresso} Falha na busca web de '{nome}': {e}")
                            resultado = None

                    if resultado and resultado.get("ean") and not ean_web_confiavel(resultado, nome, marca_bruta):
                        contagem_casamento["web_rejeitado"] += 1
                        logger.info(f"   🚫 {prefixo_progresso} EAN da web rejeitado (nome não confere): '{nome}' x '{resultado.get('nome_encontrado')}' ({resultado.get('fonte')})")
                        resultado = None

                    if resultado and resultado.get("ean") and str(resultado["ean"]).isdigit():
                        cache_buscas_web[chave_busca] = resultado
                        item["EAN"] = equivalencias.get(str(resultado["ean"]), str(resultado["ean"]))
                        item["Fonte_EAN"] = resultado.get("fonte", "Web")
                        if resultado.get("Link_Imagem") and (not item.get("Link_Imagem") or item.get("Link_Imagem") == "SEM IMAGEM"):
                            item["Link_Imagem"] = resultado.get("Link_Imagem", "")
                        logger.info(f"   🌐 {prefixo_progresso} EAN Web ({resultado.get('fonte')}): '{nome}' -> {item['EAN']}")
                    else:
                        item["EAN"] = casador.agrupar_interno(nome, marca_bruta)
                        item["Fonte_EAN"] = "Grupo_Interno"
                        contagem_casamento["interno"] += 1
                        logger.info(f"   ⚙️ {prefixo_progresso} Grupo interno: '{nome}' -> {item['EAN']}")
                        if not is_fresco_sem_marca:
                            logger.warning("   ⏳ Esfriando IP por 3.0s após falha na busca web...")
                            await asyncio.sleep(3.0)
                
            finally:
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
                    itens_por_ean.setdefault(novo_ean, []).append(item_recuperado)
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
                    if ean.startswith("INT_"):
                        prod_ouro["origem"] = "interno"  # produto sem EAN, agrupado pelo nome
                    biblioteca[ean] = prod_ouro
                    novos_na_biblioteca += 1
                else:
                    eans_com_falha.add(ean)
                    
            logger.info(f"   💾 Salvando progresso da biblioteca (Lote {num_lote}/{len(lotes)})...")
            salvar_estado_intermediario()

    # --- TRIAGEM FINAL DE ARQUIVOS (FIM DO LOOP INFINITO) ---
    itens_prontos = list(itens_prontos_anteriores)
    itens_restantes = []
    
    q_keys = {f"{q.get('EAN', '')}_{q.get('Produto', '')}_{q.get('Mercado', '')}" for q in itens_quarentena}

    for item in pendentes:
        ean_str = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        item_k = f"{ean_str}_{item.get('Produto', '')}_{item.get('Mercado', '')}"
        
        if item_k in q_keys:
            continue

        if ean_str in ("N/A", "", "None", "nan") or not id_produto_valido(ean_str) or ean_str in eans_com_falha:
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
    salvar_json_atomico(ARQUIVO_BIBLIOTECA, biblioteca)
    salvar_json_atomico(ARQUIVO_PROCESSADOS, itens_prontos)
    salvar_json_atomico(ARQUIVO_QUARENTENA, itens_quarentena)
    salvar_json_atomico(ARQUIVO_PENDENTES, itens_restantes)

    # Planilha com os casamentos duvidosos para você marcar S/N
    n_revisao = revisar_casamentos.exportar_sugestoes(list(sugestoes_revisao.values()))
    logger.info(
        f"🧩 Casamento de nomes: {contagem_casamento['confirmado']} confirmados por você, {contagem_casamento['auto']} automáticos, "
        f"{contagem_casamento['interno']} em grupos internos (sem EAN), {contagem_casamento['web_rejeitado']} EANs da web rejeitados."
    )
    if n_revisao:
        logger.info(f"📝 {n_revisao} casamentos duvidosos em '{revisar_casamentos.ARQUIVO_REVISAO}'. Marque S/N e rode o passo 4 de novo.")

    logger.info(f"🧹 Concluído! {len(itens_prontos)} prontos, {len(itens_quarentena)} na quarentena e {len(itens_restantes)} pendentes.")

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())