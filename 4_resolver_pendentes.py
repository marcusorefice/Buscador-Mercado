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

    logger.info(f"📊 Total de EANs válidos encontrados nos pendentes: {len(itens_por_ean)}")
    
    novos_na_biblioteca = 0
    eans_com_falha = set()
    
    # Processa os EANs
    eans_para_processar = []
    for ean, lista_itens_crus in itens_por_ean.items():
        if ean not in biblioteca:
            eans_para_processar.append((ean, lista_itens_crus))
            
    if eans_para_processar:
        total_processar = len(eans_para_processar)
        logger.info(f"🚀 Iniciando processamento CONTÍNUO de {total_processar} novos EANs via IA (Alta Concorrência)...")
        
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
                
        # Dispara todos os itens de uma vez, o semáforo controla a quantidade simultânea
        tasks = [processar_item(ean, lista) for ean, lista in eans_para_processar]
        resultados = await asyncio.gather(*tasks)

        for ean, produto_ouro in resultados:
            if produto_ouro:
                biblioteca[ean] = produto_ouro
                novos_na_biblioteca += 1
                logger.info(f"✅ Produto Ouro criado: {produto_ouro['nome_comum']} ({ean})")
            else:
                eans_com_falha.add(ean)

    # Salva a biblioteca atualizada
    if novos_na_biblioteca > 0:
        with open(ARQUIVO_BIBLIOTECA, "w", encoding="utf-8") as f:
            json.dump(biblioteca, f, ensure_ascii=False, indent=4)
        logger.info(f"\n💾 Biblioteca atualizada com {novos_na_biblioteca} novos produtos Ouro!")
    else:
        logger.info("\n✅ Nenhum novo produto precisou ser adicionado à biblioteca.")

    # Separa os itens: o que deu certo vai para o banco, o que falhou (ou não tem EAN) continua pendente
    itens_prontos = []
    itens_restantes = []
    for item in pendentes:
        ean = str(item.get("EAN", item.get("ean", "N/A"))).strip()
        if ean in ("N/A", "", "None", "nan") or not ean.isdigit():
            itens_restantes.append(item)
        elif ean in eans_com_falha:
            itens_restantes.append(item)
        else:
            itens_prontos.append(item)

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
