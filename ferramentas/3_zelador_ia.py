import os, sys
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz do projeto (D:\Mercado)
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)  # caminhos como 'data/...' continuam funcionando de qualquer pasta

import os
import json
import asyncio
from google import genai
import logging
from utils import setup_logging, read_json_file, write_json_file
from classificador_ia import PROMPT_TAXONOMIA

# Rotaciona chave e instancia o client com base no arquivo classificador_ia.py
from classificador_ia import client, _trocar_chave_texto, lista_chaves_texto

logger = setup_logging()

DATA_DIR = "data"
BIBLIOTECA_FILE = os.path.join(DATA_DIR, "biblioteca_produtos.json")

async def padronizar_biblioteca():
    logger.info("[Iniciando] Zelador da Biblioteca (Padronização por IA)...")
    
    if not os.path.exists(BIBLIOTECA_FILE):
        logger.error(f"[Erro] Biblioteca '{BIBLIOTECA_FILE}' não encontrada.")
        return

    biblioteca = read_json_file(BIBLIOTECA_FILE)
    if not biblioteca:
        logger.warning("[Aviso] Biblioteca vazia.")
        return

    # Categorias aceitas oficialmente (as mesmas do prompt)
    categorias_oficiais = [
        "Açougue e Peixaria", "Bazar e Utilidades", "Bebê e Infantil", 
        "Bebidas", "Bebidas Alcoólicas", "Congelados e Pratos Prontos", 
        "Frios e Laticínios", "Higiene e Cuidado Pessoal", "Hortifrúti", 
        "Limpeza", "Mercearia e Despensa", "Padaria e Confeitaria", "Pet Shop"
    ]

    itens_sujos = {}
    for chave, item in biblioteca.items():
        if not isinstance(item, dict): continue
        
        # Ignora se já foi revisado pelo humano!
        if item.get("revisado_humano"):
            continue

        cat = item.get("Categoria", "")
        # Se a categoria atual não for oficial, considera o item "sujo"
        if cat not in categorias_oficiais:
            itens_sujos[chave] = item

    if not itens_sujos:
        logger.info("[Pronto] Biblioteca já está 100% limpa e padronizada!")
        return

    logger.info(f"[Zelador] Encontrados {len(itens_sujos)} itens não padronizados. Enviando para a IA...")

    # Converte para lista e envia em lotes de 150
    lista_sujos = list(itens_sujos.items())
    alteracoes = 0

    for i in range(0, len(lista_sujos), 150):
        lote = lista_sujos[i:i+150]
        nomes_lote = [item["nome_comum"] for chave, item in lote if item.get("nome_comum")]
        
        if not nomes_lote: continue
        
        logger.info(f"  -> Enviando lote de {len(nomes_lote)} produtos...")

        success = False
        for tentativa in range(len(lista_chaves_texto)):
            try:
                response = await asyncio.to_thread(client.models.generate_content,
                    model="gemini-2.5-flash", 
                    contents=PROMPT_TAXONOMIA.format(produtos_lista=json.dumps(nomes_lote, ensure_ascii=False))
                )
                
                import re
                json_clean = re.sub(r'```json|```', '', response.text).strip()
                dados_ia = json.loads(json_clean)

                # Tratamento IA retornando lista
                if isinstance(dados_ia, list):
                    novo_dict = {}
                    for item in dados_ia:
                        if isinstance(item, dict):
                            nome_prod = item.get("Produto", item.get("produto", item.get("nome")))
                            if nome_prod: novo_dict[nome_prod] = item
                            else:
                                keys = list(item.keys())
                                if len(keys) == 1 and isinstance(item[keys[0]], dict):
                                    novo_dict[keys[0]] = item[keys[0]]
                    dados_ia = novo_dict

                # Tratamento IA retornando objeto único
                if isinstance(dados_ia, dict) and len(nomes_lote) == 1 and nomes_lote[0] not in dados_ia:
                    if "Categoria" in dados_ia:
                        dados_ia = {nomes_lote[0]: dados_ia}

                if isinstance(dados_ia, dict):
                    # Agora aplica as categorias limpas de volta nos itens sujos
                    for chave_suja, item_sujo in lote:
                        nome_sujo = item_sujo.get("nome_comum")
                        if nome_sujo in dados_ia:
                            tax_nova = dados_ia[nome_sujo]
                            
                            item_sujo["Categoria"] = tax_nova.get("Categoria", "OUTROS")
                            item_sujo["subcategoria"] = tax_nova.get("subcategoria", "N/A")
                            item_sujo["tipo_produto"] = tax_nova.get("tipo_produto", "N/A")
                            
                            # Atualiza a biblioteca principal com o item corrigido
                            biblioteca[chave_suja] = item_sujo
                            alteracoes += 1
                            
                    success = True
                    # Salva após cada lote bem sucedido
                    write_json_file(BIBLIOTECA_FILE, biblioteca)
                    logger.info(f"  [Salvo] Lote concluído. {alteracoes} produtos padronizados até agora.")
                    break 

            except Exception as e:
                if "429" in str(e) or "QUOTA" in str(e).upper():
                    logger.warning("  Quota excedida. Trocando chave...")
                    _trocar_chave_texto()
                else:
                    logger.error(f"  Erro no processamento do lote pela IA: {e}")
                    break
                    
    logger.info("\n" + "="*40)
    logger.info("[Sucesso] PADRONIZAÇÃO CONCLUÍDA!")
    logger.info("="*40)
    logger.info(f"-> Total de produtos corrigidos pela IA: {alteracoes}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(padronizar_biblioteca())
