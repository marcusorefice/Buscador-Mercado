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

async def resolver_ean_novo(ean, itens_crus):
    """
    Cria o Produto Ouro a partir dos itens recebidos.
    Usa heurísticas de prioridade (sem IA) para garantir velocidade máxima e
    evitar estourar o limite de requisições da API.
    """
    # Encontra o item raiz que tem o nome mais longo e detalhado
    melhor_item = max(itens_crus, key=lambda x: len(str(x.get("Produto", x.get("nome_comum", ""))).strip()))
    melhor_nome = str(melhor_item.get("Produto", melhor_item.get("nome_comum", ""))).strip() or "PRODUTO DESCONHECIDO"
    
    # Escolhe a melhor marca (mais frequente, ignorando genéricas)
    marcas = [str(item.get("Marca", item.get("marca", ""))).strip().upper() for item in itens_crus]
    marcas_validas = [m for m in marcas if m not in ("OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "", "NONE")]
    
    if marcas_validas:
        from collections import Counter
        melhor_marca = Counter(marcas_validas).most_common(1)[0][0]
    else:
        melhor_marca = marcas[0] if marcas else "OUTROS"
        
    categoria = itens_crus[0].get("Categoria", "OUTROS")
    
    # ANTI-FRANKENSTEIN: Atrela a imagem ao MESMO item que forneceu o nome!
    imagem_escolhida = melhor_item.get("Link_Imagem", melhor_item.get("imagem", ""))
    
    # Se o melhor item não tiver imagem, busca nos outros de forma segura
    if not imagem_escolhida or not str(imagem_escolhida).startswith("http"):
        for item in itens_crus:
            img = item.get("Link_Imagem", item.get("imagem", ""))
            if img and str(img).startswith("http"):
                nome_deste = str(item.get("Produto", item.get("nome_comum", ""))).strip().upper()
                p1 = nome_deste.split()[0] if nome_deste.split() else ""
                p2 = melhor_nome.upper().split()[0] if melhor_nome.split() else ""
                # Só pega a imagem emprestada se a primeira palavra do produto bater (Ex: DESODORANTE)
                if p1 and p2 and p1 == p2:
                    imagem_escolhida = img
                    break
    
    produto_ouro = {
        "id": str(ean),
        "nome_comum": melhor_nome,
        "marca": melhor_marca,
        "ean": str(ean),
        "Categoria": categoria,
        "subcategoria": "N/A",
        "tipo_produto": "N/A",
        "imagem": imagem_escolhida,
        "tags": [],
        "revisado_humano": False
    }
            
    return produto_ouro

def checar_conflito_anomalia(nome_base, nome_novo):
    nome_base, nome_novo = str(nome_base).upper(), str(nome_novo).upper()
    def tem(padrao, texto): return bool(re.search(padrao, texto))
    
    p_kg = r'\bKG\b|/KG\b|\bQUILO\b'
    p_cx = r'\bCX\b|\bCAIXA\b|\bDISPLAY\b|\bFARDO\b|\bFD\b'
    
    if tem(p_kg, nome_base) != tem(p_kg, nome_novo): return True
    if ("RALADO" in nome_base) != ("RALADO" in nome_novo): return True
    if ("FATIADO" in nome_base) != ("FATIADO" in nome_novo): return True
    if (" PEDAÇO" in nome_base or " PEDACO" in nome_base) != (" PEDAÇO" in nome_novo or " PEDACO" in nome_novo): return True
    if tem(p_cx, nome_base) != tem(p_cx, nome_novo): return True
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

    # Carrega a biblioteca de produtos "Ouro"
    biblioteca = {}
    if os.path.exists(ARQUIVO_BIBLIOTECA):
        try:
            with open(ARQUIVO_BIBLIOTECA, "r", encoding="utf-8") as f:
                biblioteca = json.load(f)
        except Exception as e:
            logger.error(f"❌ Erro ao ler biblioteca: {e}")

    # Agrupa os itens pendentes por EAN
    itens_por_ean = {}
    itens_sem_ean = []

    for item in pendentes:
        ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        nome_item = str(item.get("Produto", item.get("nome_comum", ""))).strip().upper()
        mercado_item = item.get("Mercado", "")
        
        # DEFESA AUTOMÁTICA DE EAN (Universal Anti-Collision)
        if ean != "N/A" and ean_eh_valido(ean):
            conflito = False
            nome_conflito = ""
            
            # 1. Checa contra a base Ouro existente
            if ean in biblioteca:
                nome_ouro = str(biblioteca[ean].get("nome_comum", "")).upper()
                if checar_conflito_anomalia(nome_ouro, nome_item):
                    conflito = True
                    nome_conflito = nome_ouro
            # 2. Checa contra o mesmo lote (itens novos)
            elif ean in itens_por_ean:
                nome_primeiro = str(itens_por_ean[ean][0].get("Produto", "")).upper()
                if checar_conflito_anomalia(nome_primeiro, nome_item):
                    conflito = True
                    nome_conflito = nome_primeiro
                    
            if conflito:
                sufixos = []
                if re.search(r'\bKG\b|/KG\b|\bQUILO\b', nome_item) or item.get("Unidade") == "KG": sufixos.append("KG")
                if "RALADO" in nome_item: sufixos.append("RALADO")
                if "FATIADO" in nome_item: sufixos.append("FATIADO")
                if re.search(r'\bCX\b|\bCAIXA\b|\bDISPLAY\b|\bFARDO\b|\bFD\b', nome_item): sufixos.append("CX")
                
                suf_str = "_".join(sufixos) if sufixos else "VARIANTE"
                novo_ean = f"INT_{ean}_{suf_str}"
                logger.warning(f"🛡️ Defesa Automática: Separando '{nome_item}' de '{nome_conflito}' (EAN: {ean} -> {novo_ean}) no mercado {mercado_item}")
                ean = novo_ean
                item["EAN"] = novo_ean

        if ean in ("N/A", "", "None", "nan") or not ean_eh_valido(ean):
            item["EAN"] = "N/A"
            itens_sem_ean.append(item)
            continue
            
        if ean not in itens_por_ean:
            itens_por_ean[ean] = []
        itens_por_ean[ean].append(item)

    # --- TENTATIVA DE RECUPERAÇÃO DE EANs FALTANTES ---
    if itens_sem_ean:
        total_sem_ean = len(itens_sem_ean)
        logger.info(f"🔍 Tentando recuperar EAN para {total_sem_ean} itens sem código...")
        
        # 1. Cria índice da biblioteca local para buscas rápidas (Nome|Marca -> EAN)
        local_lookup = {}
        for b_ean, b_item in biblioteca.items():
            b_nome = str(b_item.get("nome_comum", "")).strip().upper()
            b_marca = str(b_item.get("marca", "")).strip().upper()
            if b_nome:
                local_lookup[f"{b_nome}|{b_marca}"] = (b_ean, b_item)

        # Reduzindo a concorrência para 2 para evitar bloqueio (429) do Google Search
        sem_recuperacao = asyncio.Semaphore(2)
        progresso_ean = {"atual": 0}
        
        async def recuperar_ean(item):
            async with sem_recuperacao:
                progresso_ean["atual"] += 1
                atual = progresso_ean["atual"]
                prefixo_progresso = f"[{atual}/{total_sem_ean}]"
                
                import random
                await asyncio.sleep(random.uniform(1.0, 2.5)) # Atraso para simular um humano pesquisando e não tomar block
                nome = str(item.get("Produto", item.get("nome_comum", ""))).strip()
                marca_bruta = str(item.get("Marca", item.get("marca", ""))).strip()
                
                # Remove marcas genéricas que estragam a busca na API/Google
                marca_busca = marca_bruta if marca_bruta.upper() not in ["OUTROS", "PRÓPRIA", "PROPRIA", "N/A", "NONE", "GERAL"] else ""
                chave_busca = f"{nome.upper()}|{marca_bruta.upper()}"
                
                # Busca Local
                if chave_busca in local_lookup:
                    b_ean, b_item = local_lookup[chave_busca]
                    item["EAN"] = b_ean
                    
                    # Herda todos os dados de categorização se o item estiver sem
                    cat_atual = item.get("Categoria", "GERAL")
                    if not cat_atual or cat_atual in ("GERAL", "OUTROS", "N/A", "None", ""):
                        item["Categoria"] = b_item.get("Categoria", "OUTROS")
                        item["subcategoria"] = b_item.get("subcategoria", "N/A")
                        item["tipo_produto"] = b_item.get("tipo_produto", "N/A")
                        
                    logger.info(f"   ✅ {prefixo_progresso} EAN Local: '{nome}' -> {item['EAN']}")
                    return item
                
                # 2. Busca Externa (Open Food Facts -> Google Custom Search -> Cosmos API)
                resultado = await tentar_recuperar_ean(nome, marca_busca)
                if resultado and resultado.get("ean") and str(resultado["ean"]).isdigit():
                    item["EAN"] = str(resultado["ean"])
                    item["Fonte_EAN"] = resultado.get("fonte", "Web")
                    logger.info(f"   🌐 {prefixo_progresso} EAN Web ({resultado.get('fonte')}): '{nome}' -> {item['EAN']}")
                    return item
                    
                # 3. Fallback: EAN Interno (Para não ficar preso no pendentes_ia.json para sempre)
                nome_limpo = re.sub(r'[^a-zA-Z0-9]', '', str(nome).upper())
                marca_limpa = re.sub(r'[^a-zA-Z0-9]', '', str(marca_bruta).upper())
                id_interno = f"INT_{marca_limpa}_{nome_limpo}"[:50]
                
                item["EAN"] = id_interno
                item["Fonte_EAN"] = "Gerado_Internamente"
                logger.info(f"   ⚙️ {prefixo_progresso} EAN Interno gerado: '{nome}' -> {item['EAN']}")
                return item

        TAMANHO_LOTE_REC = 50
        lotes_recuperacao = [itens_sem_ean[i:i + TAMANHO_LOTE_REC] for i in range(0, len(itens_sem_ean), TAMANHO_LOTE_REC)]
        
        itens_sem_ean_restantes = []
        for num_lote, lote in enumerate(lotes_recuperacao, 1):
            if len(lotes_recuperacao) > 1:
                logger.info(f"\n📦 Lote de Recuperação de EAN {num_lote}/{len(lotes_recuperacao)}...")
                
            tarefas_recuperacao = [recuperar_ean(i) for i in lote]
            resultados_recuperacao = await asyncio.gather(*tarefas_recuperacao)
            
            salvou_algo = False
            for i, item_original in enumerate(lote):
                item_recuperado = resultados_recuperacao[i]
                if item_recuperado:
                    novo_ean = item_recuperado["EAN"]
                    if novo_ean not in itens_por_ean:
                        itens_por_ean[novo_ean] = []
                    itens_por_ean[novo_ean].append(item_recuperado)
                    salvou_algo = True
                else:
                    itens_sem_ean_restantes.append(item_original)
                    
            if salvou_algo:
                try:
                    # Salva os EANs encontrados diretamente no arquivo pendentes_ia.json
                    with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
                        json.dump(pendentes, f, ensure_ascii=False, indent=4)
                    logger.info(f"   💾 [AUTOSAVE] EANs encontrados no Lote {num_lote} já foram salvos no pendentes_ia.json!")
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao salvar pendentes_ia.json no lote {num_lote}: {e}")

        itens_sem_ean = itens_sem_ean_restantes

    logger.info(f"📊 Total de EANs válidos prontos para processar: {len(itens_por_ean)}")
    
    novos_na_biblioteca = 0
    eans_com_falha = set()
    
    # Processa os EANs
    eans_para_processar = []
    for ean, lista_itens_crus in itens_por_ean.items():
        if ean not in biblioteca:
            eans_para_processar.append((ean, lista_itens_crus))
            
    if eans_para_processar:
        total_processar = len(eans_para_processar)
        TAMANHO_LOTE = 50
        logger.info(f"🚀 Iniciando processamento de {total_processar} novos EANs em lotes de {TAMANHO_LOTE} (Salvamento Automático)...")
        
        # Exibe qual chave está sendo usada no momento (mascarada por segurança)
        if classificador_ia.lista_chaves_texto:
            idx = classificador_ia.indice_chave_texto_atual
            chave = classificador_ia.lista_chaves_texto[idx]
            chave_mascarada = f"{chave[:8]}...{chave[-4:]}" if len(chave) > 12 else "***"
            logger.info(f"🔑 Chave API inicial em uso: Índice [{idx}] -> {chave_mascarada}")
        
        itens_processados_count = 0
        concorrencia = 20
        semaphore = asyncio.Semaphore(concorrencia)
        
        async def processar_item(ean, lista_itens_crus):
            nonlocal itens_processados_count
            async with semaphore:
                itens_processados_count += 1
                progresso = f"[{itens_processados_count}/{total_processar}]"
                logger.info(f"⏳ {progresso} Processando EAN {ean}...")
                resultado = await resolver_ean_novo(ean, lista_itens_crus)
                return ean, resultado
                
        # Divide os EANs em Lotes
        lotes = [eans_para_processar[i:i + TAMANHO_LOTE] for i in range(0, total_processar, TAMANHO_LOTE)]
        
        for num_lote, lote in enumerate(lotes, 1):
            if len(lotes) > 1:
                logger.info(f"\n📦 Processando Lote {num_lote}/{len(lotes)}...")
                
            tasks = [processar_item(ean, lista) for ean, lista in lote]
            resultados = await asyncio.gather(*tasks)

            salvou_algo_no_lote = False
            for ean, produto_ouro in resultados:
                if produto_ouro:
                    biblioteca[ean] = produto_ouro
                    novos_na_biblioteca += 1
                    logger.info(f"✅ Produto Ouro criado: {produto_ouro['nome_comum']} ({ean})")
                    salvou_algo_no_lote = True
                else:
                    eans_com_falha.add(ean)

            # Salva os arquivos parcialmente no final de cada lote (evita perda de dados se o script falhar)
            if salvou_algo_no_lote:
                with open(ARQUIVO_BIBLIOTECA, "w", encoding="utf-8") as f:
                    json.dump(biblioteca, f, ensure_ascii=False, indent=4)
                    
            # Atualiza e salva pendentes e processados imediatamente
            itens_prontos = []
            itens_restantes = []
            for item in pendentes:
                ean_str = str(item.get("EAN", item.get("ean", "N/A"))).strip()
                if ean_str in ("N/A", "", "None", "nan") or not ean_eh_valido(ean_str) or ean_str in eans_com_falha:
                    itens_restantes.append(item)
                elif ean_str in biblioteca:
                    # Garante que o item herde a categoria correta da biblioteca antes de ir para os prontos
                    b_item = biblioteca[ean_str]
                    cat_atual = item.get("Categoria", "GERAL")
                    if not cat_atual or cat_atual in ("GERAL", "OUTROS", "N/A", "None", ""):
                        item["Categoria"] = b_item.get("Categoria", "OUTROS")
                        item["subcategoria"] = b_item.get("subcategoria", "N/A")
                        item["tipo_produto"] = b_item.get("tipo_produto", "N/A")
                    itens_prontos.append(item)
                else:
                    # Ainda vai ser processado nos próximos lotes (ou sofreu erro)
                    itens_restantes.append(item)
                    
            with open(ARQUIVO_PROCESSADOS, "w", encoding="utf-8") as f:
                json.dump(itens_prontos, f, ensure_ascii=False, indent=4)
            try:
                with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
                    json.dump(itens_restantes, f, ensure_ascii=False, indent=4)
                logger.info(f"   💾 [AUTOSAVE] Progresso do Lote {num_lote} salvo com sucesso no disco!")
            except Exception as e:
                logger.warning(f"⚠️ Não foi possível atualizar '{ARQUIVO_PENDENTES}' no lote {num_lote}: {e}")

        logger.info(f"\n💾 Processamento concluído! Biblioteca atualizada com {novos_na_biblioteca} novos produtos Ouro!")
    else:
        logger.info("\n✅ Nenhum novo produto precisou ser adicionado à biblioteca.")

    # Fazemos a separação final garantida para o caso de não ter entrado no loop de lotes
    itens_prontos = []
    itens_restantes = []
    for item in pendentes:
        ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        if ean in ("N/A", "", "None", "nan") or not ean_eh_valido(ean) or ean in eans_com_falha:
            itens_restantes.append(item)
        elif ean in biblioteca:
            # Garante a herança também na verificação final
            b_item = biblioteca[ean]
            cat_atual = item.get("Categoria", "GERAL")
            if not cat_atual or cat_atual in ("GERAL", "OUTROS", "N/A", "None", ""):
                item["Categoria"] = b_item.get("Categoria", "OUTROS")
                item["subcategoria"] = b_item.get("subcategoria", "N/A")
                item["tipo_produto"] = b_item.get("tipo_produto", "N/A")
            itens_prontos.append(item)
        else:
            itens_restantes.append(item)

    with open(ARQUIVO_PROCESSADOS, "w", encoding="utf-8") as f:
        json.dump(itens_prontos, f, ensure_ascii=False, indent=4)
        
    logger.info(f"📦 {len(itens_prontos)} itens prontos foram disponibilizados para o comparador de preços em '{ARQUIVO_PROCESSADOS}'.")

    try:
        with open(ARQUIVO_PENDENTES, "w", encoding="utf-8") as f:
            json.dump(itens_restantes, f, ensure_ascii=False, indent=4)
        if itens_restantes:
            logger.info(f"⚠️ {len(itens_restantes)} itens continuam em 'pendentes_ia.json' (falha na IA ou sem EAN).")
        else:
            logger.info("🧹 Arquivo 'pendentes_ia.json' foi esvaziado (todos os itens processados com sucesso).")
    except Exception as e:
        logger.warning(f"⚠️ Não foi possível atualizar o arquivo 'pendentes_ia.json': {e}")

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
