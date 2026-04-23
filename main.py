import pandas as pd
import sqlite3
import os
import asyncio
from datetime import datetime
import inspect
import re

# Importações ajustadas para o novo fluxo
import scrapers.paodeacucar as paodeacucar
import scrapers.atacadao as atacadao
import scrapers.boa as boa
import scrapers.carrefour as carrefour
import scrapers.svicente as svicente
import scrapers.covabra as covabra
import scrapers.dom_olivio as dom_olivio
import scrapers.oba as oba
import scrapers.tenda as tenda
import scrapers.assai as assai
import scrapers.fort as fort
import scrapers.roldao as roldao
import scrapers.tauste as tauste
from utils import read_json_file, write_json_file, setup_logging, validar_e_limpar_produtos
from classificador_ia import classificar_taxonomia_com_ia_async, carregar_biblioteca, salvar_biblioteca, normalizar_para_cache, _criar_entrada_biblioteca_estendida

logger = setup_logging()

DATA_DIR = "data"
DB_NOME = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")

def inicializar_db():
    """Cria a tabela de ofertas com um schema fixo para garantir compatibilidade."""
    """Cria a tabela de ofertas, a tabela de busca FTS5 e os gatilhos de sincronização."""
    conn = sqlite3.connect(DB_NOME)
    cursor = conn.cursor()
    colunas = [
        "Mercado", "Categoria", "Produto", "Marca", "Preço Varejo", "Preço Atacado",
        "Qtd_Valor", "Medida", "Unidade", "Condição", "Validade", "Data_Hora", "Link_Imagem",
        "subcategoria", "tipo_produto"
    ]
    cols_sql = ", ".join([f'"{c}" TEXT' for c in colunas])
    # Adiciona UNIQUE constraint para evitar duplicatas exatas no banco
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS ofertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            {cols_sql},
            UNIQUE(Mercado, Produto, "Preço Atacado", Data_Hora)
        )
    ''')

    # Tabela virtual FTS5 para busca full-text otimizada.
    # Indexa Produto, Marca e Categoria para uma busca mais rica e relevante.
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS ofertas_fts USING fts5(
            Produto, 
            Marca, 
            Categoria, 
            subcategoria, 
            content='ofertas', 
            content_rowid='id'
        );
    ''')

    # Triggers para manter a tabela FTS sincronizada automaticamente com a tabela de ofertas.
    cursor.executescript('''
        CREATE TRIGGER IF NOT EXISTS ofertas_after_insert AFTER INSERT ON ofertas BEGIN
          INSERT INTO ofertas_fts(rowid, Produto, Marca, Categoria, subcategoria) VALUES (new.id, new.Produto, new.Marca, new.Categoria, new.subcategoria);
        END;
        CREATE TRIGGER IF NOT EXISTS ofertas_after_delete AFTER DELETE ON ofertas BEGIN
          INSERT INTO ofertas_fts(ofertas_fts, rowid, Produto, Marca, Categoria, subcategoria) VALUES ('delete', old.id, old.Produto, old.Marca, old.Categoria, old.subcategoria);
        END;
        CREATE TRIGGER IF NOT EXISTS ofertas_after_update AFTER UPDATE ON ofertas BEGIN
          INSERT INTO ofertas_fts(ofertas_fts, rowid, Produto, Marca, Categoria, subcategoria) VALUES ('delete', old.id, old.Produto, old.Marca, old.Categoria, old.subcategoria);
          INSERT INTO ofertas_fts(rowid, Produto, Marca, Categoria, subcategoria) VALUES (new.id, new.Produto, new.Marca, new.Categoria, new.subcategoria);
        END;
    ''')
    
    cursor.execute("PRAGMA optimize;") # Otimiza índices
    conn.commit()
    conn.close()

def salvar_resultados(produtos_finais):
    """Salva os resultados consolidados no banco de dados e nos arquivos Excel individuais."""
    if not produtos_finais:
        logger.warning("Nenhum produto final para salvar.")
        return

    df_total = pd.DataFrame(produtos_finais)

    # Remove duplicatas no lote de entrada antes de qualquer outra operação.
    unique_cols = ['Mercado', 'Produto', 'Marca', 'Preço Atacado', 'Data_Hora']
    df_total.drop_duplicates(subset=unique_cols, keep='first', inplace=True)

    # 1. Salvar no Banco de Dados
    try:
        conn = sqlite3.connect(DB_NOME)
        df_para_inserir = pd.DataFrame()

        try:
            # Busca o preço mais recente de cada produto já existente no banco.
            query_latest = """
                WITH ranked_ofertas AS (
                    SELECT 
                        Mercado, 
                        Produto,
                        Marca, 
                        "Preço Varejo", 
                        "Preço Atacado",
                        ROW_NUMBER() OVER(PARTITION BY Mercado, Produto, Marca ORDER BY Data_Hora DESC) as rn
                    FROM ofertas
                )
                SELECT Mercado, Produto, Marca, "Preço Varejo", "Preço Atacado"
                FROM ranked_ofertas
                WHERE rn = 1;
            """
            df_existentes_latest = pd.read_sql(query_latest, conn)

            if not df_existentes_latest.empty:
                # Compara os produtos novos com os últimos preços do banco.
                df_merged = pd.merge(
                    df_total,
                    df_existentes_latest,
                    on=['Mercado', 'Produto', 'Marca'],
                    how='left',
                    suffixes=('', '_db')
                )

                # Filtra para inserir apenas produtos novos ou com preço alterado.
                is_new = df_merged['Preço Atacado_db'].isna()
                prices_differ = (df_merged['Preço Varejo'] != df_merged['Preço Varejo_db']) | \
                                (df_merged['Preço Atacado'] != df_merged['Preço Atacado_db'])
                
                df_para_inserir = df_merged[is_new | prices_differ][df_total.columns]
            else:
                # Se o banco está vazio, todos os produtos coletados são para inserir.
                df_para_inserir = df_total

        except Exception as e:
            logger.warning(f"Não foi possível verificar duplicatas com o banco (a tabela pode ser nova). Inserindo todos os {len(df_total)} itens. Erro: {e}")
            df_para_inserir = df_total

        if not df_para_inserir.empty:
            df_para_inserir.to_sql('ofertas', conn, if_exists='append', index=False)
            conn.commit()
            logger.info(f"💾 {len(df_para_inserir)} novos registros ou com preços atualizados foram salvos no banco de dados '{DB_NOME}'.")
        else:
            logger.info("✅ Nenhum produto novo ou com alteração de preço para salvar no banco de dados.")
        
        conn.close()
    except Exception as e:
        logger.error(f"⚠️ Erro ao salvar no Banco de Dados: {e}", exc_info=True)

    # 2. Salvar Excels individuais com histórico
    if not df_para_inserir.empty:
        for mercado, df_mercado in df_para_inserir.groupby('Mercado'):
            nome_excel = f"historico_{mercado.replace(' ', '_').lower()}.xlsx"
            # Caso especial para manter o padrão de nome de arquivo existente
            if mercado.upper() == "CARREFOUR":
                nome_excel = "historico_carrefour_jundiai.xlsx"
            
            caminho_excel = os.path.join(DATA_DIR, nome_excel)
            
            if os.path.exists(caminho_excel):
                try:
                    df_antigo = pd.read_excel(caminho_excel)
                    df_final_mercado = pd.concat([df_antigo, df_mercado], ignore_index=True)
                    df_final_mercado = df_final_mercado.drop_duplicates(subset=['Mercado', 'Produto', 'Marca', 'Preço Atacado', 'Condição'], keep='last')
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao ler excel antigo para {mercado}, sobrescrevendo. Erro: {e}")
                    df_final_mercado = df_mercado
            else:
                df_final_mercado = df_mercado

            # Define a ordem desejada das colunas para o Excel, incluindo a nova taxonomia
            colunas_ordenadas = [
                "Mercado", "Categoria", "subcategoria", "tipo_produto", "Produto", "Marca", 
                "Qtd_Valor", "Medida", "Unidade", "Preço Varejo", "Preço Atacado", 
                "Condição", "Validade", "Data_Hora", "Link_Imagem"
            ]
            # Garante que apenas colunas existentes no DataFrame sejam usadas, para evitar erros
            colunas_existentes_para_salvar = [col for col in colunas_ordenadas if col in df_final_mercado.columns]

            df_final_mercado[colunas_existentes_para_salvar].to_excel(caminho_excel, index=False)
            logger.info(f"📄 Planilha '{caminho_excel}' atualizada com {len(df_mercado)} novas ofertas.")

def sanitizar_condicoes_absurdas(produtos, logger):
    """Corrige condições de atacado com quantidades que parecem erros de scraping."""
    for produto in produtos:
        condicao = produto.get("Condição", "")
        if not isinstance(condicao, str):
            continue

        # Tenta encontrar um número na string de condição. Prioriza números inteiros como palavras separadas.
        match = re.search(r'\b(\d+)\b', condicao)
        if match:
            try:
                quantidade = int(match.group(1))
                # Define um limite de bom senso para quantidade em promoção de varejo
                LIMITE_BOM_SENSO = 50
                if quantidade > LIMITE_BOM_SENSO:
                    # Heurística para não alterar condições que podem ter números grandes, mas que são válidas.
                    # Ex: "Válido até 20/05/2024", "LEVE 100 PAGUE 90", "A PARTIR DE 140 UN"
                    
                    condicao_upper = condicao.upper()
                    
                    # Palavras-chave que indicam que um número alto é provavelmente uma quantidade válida ou outra informação que não deve ser alterada.
                    palavras_chave_validas = [
                        "PAGUE", "LEVE", "UN", "UNID", "PC", "PÇ", "PEÇA", 
                        "CX", "CAIXA", "ACIMA", "PARTIR", "CADA", "VÁLID"
                    ]

                    # Se a condição contiver alguma das palavras-chave, consideramos válida e não alteramos.
                    if any(palavra in condicao_upper for palavra in palavras_chave_validas):
                        continue
                    else:
                        logger.warning(
                            f"Condição com quantidade alta ('{condicao}') detectada para o produto "
                            f"'{produto.get('Produto')}' sem um indicador de unidade claro. "
                            "Resetando para '1 UN' para evitar erro de interpretação."
                        )
                        produto["Condição"] = "1 UN"
            except ValueError:
                pass # Não era um número, ignora.
    return produtos

def aplicar_fallbacks_finais(lista_produtos):
    """Aplica regras de fallback e padronização a uma lista de produtos antes de salvar."""
    for p in lista_produtos:
        # Fallback de Categoria
        categorias_invalidas = {"", "OUTROS", "GERAL", "NAO INFORMADO", None}
        if not p.get("Categoria") or p.get("Categoria").strip().upper() in categorias_invalidas:
            p["Categoria"] = "Mercearia" # Categoria padrão final
        
        # Padronização da Condição para "1 UN" como padrão e em maiúsculas
        condicao_val = p.get("Condição", "")
        condicao_str = str(condicao_val).strip()

        # Regra específica para Covabra: "OFERTA" não é uma condição real.
        if p.get("Mercado") == "Covabra" and condicao_str.upper() == "OFERTA":
            condicao_str = "" # Trata como se não tivesse condição
        
        if not condicao_str or condicao_str.upper() in ['NAN', 'NONE', '1UN']:
            p["Condição"] = "1 UN"
        else:
            p["Condição"] = condicao_str.upper()

        # Fallback para subcategoria e tipo
        if "subcategoria" not in p or not p["subcategoria"]: p["subcategoria"] = "N/A"
        if "tipo_produto" not in p or not p["tipo_produto"]: p["tipo_produto"] = "N/A"
    return lista_produtos

async def coletar_dados_scraper(nome, func):
    """Worker assíncrono que executa cada scraper em uma thread separada."""
    """Worker assíncrono que executa scrapers síncronos e assíncronos de forma apropriada."""
    logger.info(f"🛒 Coletando: {nome}...")
    try:
        if inspect.iscoroutinefunction(func):
            # Se for uma função async, aguarda diretamente.
            dados = await func()
        else:
            # Se for uma função síncrona, executa em uma thread para não bloquear.
            dados = await asyncio.to_thread(func)
        if dados:
            logger.info(f"✅ {nome}: {len(dados)} ofertas capturadas.")
            return dados
        else:
            logger.warning(f"⚠️ {nome}: Nenhum dado capturado.")
            return []
    except Exception as e:
        logger.error(f"❌ Erro crítico em {nome}: {e}", exc_info=True)
        return []

async def main():
    """Função principal que orquestra o fluxo de coleta em etapas para otimizar o uso da IA."""
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    logger.info(f"🚀 INICIANDO ORQUESTRADOR DE SCRAPERS - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    inicializar_db()

    logger.info("📚 Carregando biblioteca de produtos em memória...")
    biblioteca_global = carregar_biblioteca()

    # ETAPA 1: Scrapers com dados estruturados que alimentam a biblioteca.
    scrapers_completos = {
        # "Carrefour": carrefour.extrair_dados,
        # "Covabra": covabra.extrair_dados,
        # "Pão de Açúcar": paodeacucar.extrair_dados,
        # "São Vicente": svicente.extrair_dados,
        # "Atacadão": atacadao.extrair_dados,
        "Dom Olívio": dom_olivio.extrair_dados,
        # "Boa Supermercados": boa.extrair_dados, 
        # "Oba Hortifruti": oba.extrair_dados,
    }
    
    # ETAPA 2: Scrapers que dependem da biblioteca e da IA para classificação.
    scrapers_para_ia_list = {
        # "Assaí Atacadista": assai.extrair_dados, 
        # "Fort Atacadista": fort.extrair_dados,
        # "Tenda Atacado": tenda.extrair_dados, 
        # "Roldão Atacadista": roldao.extrair_dados,
        # "Tauste Supermercado": tauste.extrair_dados, 
        
    }

    # Dicionário para o resumo final
    all_scrapers = {**scrapers_completos, **scrapers_para_ia_list}
    resumo_coleta = {nome: 0 for nome in all_scrapers.keys()}
    total_itens_salvos = 0
    
    # --- EXECUÇÃO DA ETAPA 1 ---
    logger.info("\n" + "="*50)
    logger.info("ETAPA 1: Executando scrapers com dados estruturados para popular a biblioteca.")
    logger.info("="*50)

    tarefas_etapa1 = [
        coletar_dados_scraper(nome, func) for nome, func in scrapers_completos.items()
    ]
    
    resultados_etapa1_raw = await asyncio.gather(*tarefas_etapa1)
    
    produtos_etapa1_para_salvar = []
    
    # Processa os resultados da Etapa 1
    for nome_mercado, produtos_mercado in zip(scrapers_completos.keys(), resultados_etapa1_raw):
        if not produtos_mercado:
            logger.warning(f"⚠️ {nome_mercado}: Nenhuma oferta coletada ou falha na execução.")
            continue

        resumo_coleta[nome_mercado] = len(produtos_mercado)
        logger.info(f"🏁 {nome_mercado} concluiu com {len(produtos_mercado)} ofertas.")

        produtos_validos = validar_e_limpar_produtos(produtos_mercado, logger)
        produtos_sanitizados = sanitizar_condicoes_absurdas(produtos_validos, logger)
        produtos_finais = aplicar_fallbacks_finais(produtos_sanitizados)
        
        if produtos_finais:
            produtos_etapa1_para_salvar.extend(produtos_finais)
            
            # ATUALIZA A BIBLIOTECA GLOBAL com dados de alta qualidade
            logger.info(f"   - [{nome_mercado}] Atualizando a biblioteca com {len(produtos_finais)} produtos.")
            for p in produtos_finais:
                nome_orig = p.get("Produto")
                img_atual = p.get("Link_Imagem")
                tem_img = img_atual and img_atual != "SEM IMAGEM" and str(img_atual).strip() != ""
                
                # Apenas adiciona/atualiza se tiver taxonomia completa e imagem
                if p.get("subcategoria", "N/A") != "N/A" and tem_img and nome_orig:
                    chave_norm = normalizar_para_cache(nome_orig)
                    
                    # Cria uma entrada nova ou atualiza a imagem de uma existente
                    if chave_norm not in biblioteca_global or not biblioteca_global.get(chave_norm):
                        # Extrai a taxonomia do próprio produto 'p' que já vem estruturado
                        taxonomia_p = {
                            "Categoria": p.get("Categoria"),
                            "subcategoria": p.get("subcategoria"),
                            "tipo_produto": p.get("tipo_produto")
                        }
                        # Usa a função centralizada para criar a entrada no formato estendido
                        biblioteca_global[chave_norm] = _criar_entrada_biblioteca_estendida(chave_norm, nome_orig, p, taxonomia_p)
                    else:
                        # Se já existe, só atualiza a imagem se a atual for vazia/inválida
                        img_cache = biblioteca_global.get(chave_norm, {}).get("imagem")
                        if not img_cache or img_cache == "SEM IMAGEM" or str(img_cache).strip() == "":
                            biblioteca_global[chave_norm]["imagem"] = img_atual

    # Salva todos os produtos da Etapa 1 de uma vez
    if produtos_etapa1_para_salvar:
        logger.info(f"💾 Salvando {len(produtos_etapa1_para_salvar)} produtos da Etapa 1 no banco e planilhas...")
        await asyncio.to_thread(salvar_resultados, produtos_etapa1_para_salvar)
        total_itens_salvos += len(produtos_etapa1_para_salvar)

    # Salva a biblioteca enriquecida antes de passar para a próxima etapa
    logger.info("💾 Salvando estado intermediário da biblioteca de produtos para garantir o cache na Etapa 2.")
    salvar_biblioteca(biblioteca_global)

    # --- EXECUÇÃO DA ETAPA 2 ---
    logger.info("\n" + "="*50)
    logger.info("ETAPA 2: Executando scrapers que dependem de IA (usando a biblioteca atualizada).")
    logger.info("="*50)

    tarefas_etapa2 = {
        asyncio.create_task(coletar_dados_scraper(nome, func)): nome 
        for nome, func in scrapers_para_ia_list.items()
    }
    
    # Processa os resultados da Etapa 2 à medida que chegam
    async for future in asyncio.as_completed(tarefas_etapa2):
        nome_mercado = tarefas_etapa2[future]
        try:
            produtos_mercado = await future
            
            if not produtos_mercado:
                logger.warning(f"⚠️ {nome_mercado}: Nenhuma oferta coletada ou falha na execução. Pulando.")
                continue

            resumo_coleta[nome_mercado] = len(produtos_mercado)
            logger.info(f"🏁 {nome_mercado} concluiu com {len(produtos_mercado)} ofertas. Iniciando classificação...")

            produtos_validos = validar_e_limpar_produtos(produtos_mercado, logger)
            produtos_sanitizados = sanitizar_condicoes_absurdas(produtos_validos, logger)

            if not produtos_sanitizados:
                logger.warning(f"[{nome_mercado}] Nenhum produto válido restante após limpeza.")
                continue

            # A biblioteca já está enriquecida. A função de IA vai usar o cache ao máximo.
            logger.info(f"   - [{nome_mercado}] Iniciando classificação com IA para {len(produtos_sanitizados)} produtos...")
            mapa_taxonomia, biblioteca_atualizada, cache_foi_modificado = await classificar_taxonomia_com_ia_async(
                produtos_sanitizados, biblioteca_global
            )
            if cache_foi_modificado:
                biblioteca_global = biblioteca_atualizada  # Mantém a biblioteca global sempre atualizada
                # Salva o cache imediatamente após a modificação para garantir persistência.
                logger.info(f"   - [{nome_mercado}] A biblioteca foi atualizada. Salvando estado para persistência.")
                salvar_biblioteca(biblioteca_global)

            # Enriquece os produtos com a taxonomia obtida
            for produto in produtos_sanitizados:
                nome_original = produto.get("Produto")
                taxonomia = mapa_taxonomia.get(nome_original)
                if not taxonomia:
                    chave_norm = normalizar_para_cache(nome_original)
                    taxonomia = biblioteca_global.get(chave_norm)

                if taxonomia:
                    produto["Categoria"] = taxonomia.get("Categoria", "MERCEARIA")
                    produto["subcategoria"] = taxonomia.get("subcategoria", "OUTROS")
                    produto["tipo_produto"] = taxonomia.get("tipo_produto", "OUTROS")
                    
                    # Tenta preencher imagem faltante com a da biblioteca
                    img_atual = produto.get("Link_Imagem")
                    if not img_atual or img_atual == "SEM IMAGEM" or str(img_atual).strip() == "":
                        chave_norm = normalizar_para_cache(nome_original)
                        tax_bib = biblioteca_global.get(chave_norm)
                        if tax_bib:
                            img_biblioteca = tax_bib.get("imagem")
                            if img_biblioteca and img_biblioteca != "SEM IMAGEM":
                                produto["Link_Imagem"] = img_biblioteca
            
            produtos_finais_mercado = aplicar_fallbacks_finais(produtos_sanitizados)

            # Salva os resultados deste mercado
            if produtos_finais_mercado:
                logger.info(f"   - [{nome_mercado}] Salvando {len(produtos_finais_mercado)} produtos finais no banco e planilhas...")
                await asyncio.to_thread(salvar_resultados, produtos_finais_mercado)
                total_itens_salvos += len(produtos_finais_mercado)
            else:
                logger.warning(f"   - [{nome_mercado}] Nenhum produto válido para salvar após processamento.")

        except Exception as e:
            logger.error(f"❌ Erro fatal no processamento do scraper '{nome_mercado}': {e}", exc_info=True)

    # --- EXIBIR RESUMO FINAL ---
    logger.info("\n" + "="*50)
    logger.info("📊 RESUMO FINAL DA EXECUÇÃO")
    logger.info("="*50)
    
    total_coletado = sum(resumo_coleta.values())
    logger.info("🛒 ITENS BRUTOS EXTRAÍDOS POR MERCADO:")
    for mercado, qtd in resumo_coleta.items():
        if qtd > 0:
            logger.info(f"  - {mercado}: {qtd} ofertas")
        else:
            logger.info(f"  - {mercado}: Falha ou zero ofertas ⚠️")
            
    logger.info("-" * 50)    
    logger.info(f"📈 TOTAL BRUTO COLETADO: {total_coletado} itens")
    logger.info(f" TOTAL DE ITENS SALVOS: {total_itens_salvos} itens")
    logger.info("="*50)
    logger.info("\n🏆 Operação concluída com sucesso! O cache da biblioteca de produtos está atualizado.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("\n🛑 Operação interrompida pelo usuário (Ctrl+C). Encerrando de forma limpa.")