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
    
    if len(nomes_unicos) == 1:
        # Só tem 1 variação de nome: Classifica normalmente
        item_base = itens_crus[0]
        logger.info(f"🧠 [Classificando] EAN {ean} - Apenas 1 variação: {item_base.get('Produto')}")
        
        prompt = PROMPT_CLASSIFICACAO.format(
            nome=item_base.get("Produto", item_base.get("nome_comum", "")),
            marca=item_base.get("Marca", item_base.get("marca", "")),
            ean=ean,
            categoria_mercado=item_base.get("Categoria", ""),
            categorias_validas=", ".join(CATEGORIAS_MASTER)
        )
    else:
        # Conflito! Múltiplas variações para o mesmo EAN
        logger.info(f"⚔️ [Resolvendo Conflito] EAN {ean} - {len(nomes_unicos)} variações encontradas.")
        
        # Vamos passar as variações como JSON para a IA comparar
        opcoes = []
        for i, item in enumerate(itens_crus, 1):
            opcoes.append({
                "mercado": item.get("Mercado", f"Opção {i}"),
                "nome_original": item.get("Produto", item.get("nome_comum", "")),
                "marca_original": item.get("Marca", item.get("marca", "")),
                "categoria_mercado": item.get("Categoria", "")
            })
            
        prompt = PROMPT_CONFLITO.format(
            ean=ean,
            dados_a=json.dumps(opcoes[0], ensure_ascii=False, indent=2), # Usamos o primeiro como base "A"
            dados_b=json.dumps(opcoes[1:], ensure_ascii=False, indent=2) # Usamos o resto como base "B"
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
            "nome_comum": resultado_json.get("nome_comum", ""),
            "marca": str(resultado_json.get("marca", "")).upper(),
            "ean": str(ean),
            "Categoria": resultado_json.get("Categoria", "OUTROS"),
            "subcategoria": resultado_json.get("subcategoria", ""),
            "tipo_produto": resultado_json.get("tipo_produto", ""),
            "tags": resultado_json.get("tags", []),
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
    
    # Processa os EANs
    for ean, lista_itens_crus in itens_por_ean.items():
        if ean in biblioteca:
            # O Produto Ouro já existe! Não precisamos chamar a IA.
            # Os itens crus continuam existindo e poderão ser comparados pelo EAN.
            continue
            
        # O EAN não existe na biblioteca. Vamos usar a IA para criar o Produto Ouro.
        produto_ouro = await resolver_ean_novo(ean, lista_itens_crus)
        
        if produto_ouro:
            biblioteca[ean] = produto_ouro
            novos_na_biblioteca += 1
            logger.info(f"✅ Produto Ouro criado: {produto_ouro['nome_comum']} ({ean})")

    # Salva a biblioteca atualizada
    if novos_na_biblioteca > 0:
        with open(ARQUIVO_BIBLIOTECA, "w", encoding="utf-8") as f:
            json.dump(biblioteca, f, ensure_ascii=False, indent=4)
        logger.info(f"\n💾 Biblioteca atualizada com {novos_na_biblioteca} novos produtos Ouro!")
    else:
        logger.info("\n✅ Nenhum novo produto precisou ser adicionado à biblioteca.")

    # Salva TODOS os itens pendentes originais em um novo arquivo (eles não foram modificados)
    # Agora você pode usar esse arquivo para o seu comparador de preços!
    with open(ARQUIVO_PROCESSADOS, "w", encoding="utf-8") as f:
        json.dump(pendentes, f, ensure_ascii=False, indent=4)
        
    logger.info(f"📦 Todos os {len(pendentes)} itens crus (originais) foram disponibilizados para o comparador de preços em '{ARQUIVO_PROCESSADOS}'.")
    logger.info(f"⚠️ Atenção: {len(itens_sem_ean)} itens não possuíam EAN válido.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
