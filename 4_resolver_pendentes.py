import json
import os
import asyncio
import logging

# Importa as ferramentas da IA do seu classificador já existente
from classificador_ia import (
    _chamar_gemini_com_retry, 
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

async def resolver_ean_novo(ean, itens_crus):
    """
    Decide se apenas classifica (1 item) ou se resolve conflito (>1 itens).
    Retorna o Produto Ouro para salvar na biblioteca.
    """
    # Se só tem um item, ou todos os itens têm exatamente o mesmo nome
    nomes_unicos = {item.get("Produto", item.get("nome_comum", "")) for item in itens_crus}
    
    # --- NOVO PROMPT SIMPLIFICADO ---
    PROMPT_SIMPLIFICADO_CONFLITO = """Vários supermercados enviaram nomes diferentes para o mesmo produto (EAN: {ean}).
Sua tarefa é analisar as opções e retornar APENAS UM JSON válido com o melhor nome (mais claro e descritivo) e a marca.
Não crie tags nem categorias.

OPÇÕES RECEBIDAS:
{opcoes}

FORMATO DE SAÍDA EXATO:
{{
"nome_comum": "Melhor Nome Escolhido",
"marca": "MARCA EM CAIXA ALTA"
}}"""

    if len(nomes_unicos) == 1:
        # Só tem 1 variação de nome: NÃO USA IA! Economiza tempo e limite da API.
        item_base = itens_crus[0]
        nome = item_base.get("Produto", item_base.get("nome_comum", ""))
        marca = str(item_base.get("Marca", item_base.get("marca", ""))).upper()
        categoria = item_base.get("Categoria", "OUTROS")
        
        logger.info(f"⚡ [Pulo IA] EAN {ean} - Apenas 1 variação: {nome}")
        
        # Garante o formato do Produto Ouro
        produto_ouro = {
            "id": str(ean),
            "nome_comum": nome,
            "marca": marca,
            "ean": str(ean),
            "Categoria": categoria,
            "subcategoria": "N/A",
            "tipo_produto": "N/A",
            "tags": [],
            "revisado_humano": False
        }
        
        # Pega a imagem do primeiro item que tiver uma
        for item in itens_crus:
            img = item.get("Link_Imagem", item.get("imagem", ""))
            if img and str(img).startswith("http"):
                produto_ouro["imagem"] = img
                break
                
        return produto_ouro

    else:
        # Conflito! Múltiplas variações para o mesmo EAN, então chama a IA
        logger.info(f"⚔️ [Resolvendo Conflito IA] EAN {ean} - {len(nomes_unicos)} variações encontradas.")
        
        # Vamos passar as variações como JSON para a IA comparar
        opcoes = []
        for i, item in enumerate(itens_crus, 1):
            opcoes.append({
                "mercado": item.get("Mercado", f"Opção {i}"),
                "nome_original": item.get("Produto", item.get("nome_comum", "")),
                "marca": item.get("Marca", item.get("marca", ""))
            })
            
        prompt = PROMPT_SIMPLIFICADO_CONFLITO.format(
            ean=ean,
            opcoes=json.dumps(opcoes, ensure_ascii=False, indent=2)
        )

        # Chama a IA
        resposta_texto = await _chamar_gemini_com_retry(prompt)
        if not resposta_texto:
            return None

        try:
            import re
            match = re.search(r'\{.*\}', resposta_texto, re.DOTALL)
            json_str = match.group(0) if match else resposta_texto
            resultado_json = json.loads(json_str)
            
            # Garante o formato do Produto Ouro
            produto_ouro = {
                "id": str(ean),
                "nome_comum": resultado_json.get("nome_comum", list(nomes_unicos)[0]),
                "marca": str(resultado_json.get("marca", itens_crus[0].get("Marca", ""))).upper(),
                "ean": str(ean),
                "Categoria": itens_crus[0].get("Categoria", "OUTROS"), # Mantém a original
                "subcategoria": "N/A",
                "tipo_produto": "N/A",
                "tags": [],
                "revisado_humano": False
            }
            
            # Pega a imagem do primeiro item que tiver uma
            for item in itens_crus:
                img = item.get("Link_Imagem", item.get("imagem", ""))
                if img and str(img).startswith("http"):
                    produto_ouro["imagem"] = img
                    break
                    
            return produto_ouro

        except json.JSONDecodeError:
            logger.error(f"❌ Erro ao parsear JSON da IA para o EAN {ean}")
            return None

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
        if ean in ("N/A", "", "None", "nan") or not ean.isdigit():
            itens_sem_ean.append(item)
            continue
            
        if ean not in itens_por_ean:
            itens_por_ean[ean] = []
        itens_por_ean[ean].append(item)

    # --- TENTATIVA DE RECUPERAÇÃO DE EANs FALTANTES ---
    if itens_sem_ean:
        logger.info(f"🔍 Tentando recuperar EAN para {len(itens_sem_ean)} itens sem código...")
        
        # 1. Cria índice da biblioteca local para buscas rápidas (Nome|Marca -> EAN)
        local_lookup = {}
        for b_ean, b_item in biblioteca.items():
            b_nome = str(b_item.get("nome_comum", "")).strip().upper()
            b_marca = str(b_item.get("marca", "")).strip().upper()
            if b_nome:
                local_lookup[f"{b_nome}|{b_marca}"] = (b_ean, b_item)

        sem_recuperacao = asyncio.Semaphore(10)
        
        async def recuperar_ean(item):
            async with sem_recuperacao:
                nome = item.get("Produto", item.get("nome_comum", ""))
                marca = item.get("Marca", item.get("marca", ""))
                chave_busca = f"{str(nome).strip().upper()}|{str(marca).strip().upper()}"
                
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
                        
                    logger.info(f"   ✅ EAN Local: '{nome}' -> {item['EAN']}")
                    return item
                
                # Busca Web (Open Food Facts / Google)
                resultado = await tentar_recuperar_ean(nome, marca)
                if resultado and resultado.get("ean") and str(resultado["ean"]).isdigit():
                    item["EAN"] = str(resultado["ean"])
                    item["Fonte_EAN"] = resultado.get("fonte", "Web")
                    logger.info(f"   🌐 EAN Web ({resultado.get('fonte')}): '{nome}' -> {item['EAN']}")
                    return item
                    
                return None

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
                if ean_str in ("N/A", "", "None", "nan") or not ean_str.isdigit() or ean_str in eans_com_falha:
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
        if ean in ("N/A", "", "None", "nan") or not ean.isdigit() or ean in eans_com_falha:
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
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
