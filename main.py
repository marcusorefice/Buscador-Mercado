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
import scrapers.oba as oba
import scrapers.tenda as tenda
import scrapers.assai as assai
import scrapers.fort as fort
import scrapers.roldao as roldao
import scrapers.tauste as tauste
from utils import read_json_file, write_json_file, setup_logging, validar_e_limpar_produtos
from classificador_ia import classificar_taxonomia_com_ia

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

    # Adicionado: Remove duplicatas no lote de entrada antes de qualquer outra operação.
    # Isso previne a falha de 'UNIQUE constraint' se um scraper coletar o mesmo item duas vezes na mesma execução.
    unique_cols = ['Mercado', 'Produto', 'Preço Atacado', 'Data_Hora']
    df_total.drop_duplicates(subset=unique_cols, keep='first', inplace=True)

    # 1. Salvar no Banco de Dados
    try:
        conn = sqlite3.connect(DB_NOME)
        # Carrega dados existentes para evitar duplicatas que violam a constraint UNIQUE
        try:
            existentes = pd.read_sql('SELECT "Mercado", "Produto", "Preço Atacado", "Data_Hora" FROM ofertas', conn)
            # Remove do df_total o que já existe no banco
            df_total = df_total.merge(existentes, on=['Mercado', 'Produto', 'Preço Atacado', 'Data_Hora'], 
                                    how='left', indicator=True).query('_merge == "left_only"').drop('_merge', axis=1)
        except Exception as e:
            logger.warning(f"Não foi possível verificar duplicatas com o banco. A tabela pode ser nova. Erro: {e}")

        if not df_total.empty:
            df_total.to_sql('ofertas', conn, if_exists='append', index=False)
        conn.commit()
        conn.close()
        logger.info(f"💾 {len(df_total)} registros salvos/atualizados no banco de dados '{DB_NOME}'.")
    except Exception as e:
        logger.error(f"⚠️ Erro ao salvar no Banco de Dados: {e}", exc_info=True)

    # 2. Salvar Excels individuais com histórico
    for mercado, df_mercado in df_total.groupby('Mercado'):
        nome_excel = f"historico_{mercado.replace(' ', '_').lower()}.xlsx"
        # Caso especial para manter o padrão de nome de arquivo existente
        if mercado.upper() == "CARREFOUR":
            nome_excel = "historico_carrefour_jundiai.xlsx"
        
        caminho_excel = os.path.join(DATA_DIR, nome_excel)
        
        if os.path.exists(caminho_excel):
            try:
                df_antigo = pd.read_excel(caminho_excel)
                df_final_mercado = pd.concat([df_antigo, df_mercado], ignore_index=True)
                df_final_mercado = df_final_mercado.drop_duplicates(subset=['Mercado', 'Produto', 'Preço Atacado', 'Condição'], keep='last')
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
    """Função principal que orquestra todo o fluxo de forma assíncrona."""
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    logger.info(f"🚀 INICIANDO ORQUESTRADOR DE SCRAPERS - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    inicializar_db()

    scrapers = {
        # "Assaí Atacadista": assai.extrair_dados,
        # "Fort Atacadista": fort.extrair_dados,
        # "Tenda Atacado": tenda.extrair_dados,
        # "Roldão Atacadista": roldao.extrair_dados,
        # "Tauste Supermercado": tauste.extrair_dados,
        # "Atacadão": atacadao.extrair_dados,
        # "Boa Supermercados": boa.extrair_dados,
        # "Carrefour": carrefour.extrair_dados,
        # "Covabra": covabra.extrair_dados,
        # "Oba Hortifruti": oba.extrair_dados,
        # "Pão de Açúcar": paodeacucar.extrair_dados,
        "São Vicente": svicente.extrair_dados
    }

    # 1. Chamar os scrapers em paralelo
    tarefas_coleta = [coletar_dados_scraper(nome, func) for nome, func in scrapers.items()]
    resultados_por_mercado = await asyncio.gather(*tarefas_coleta)
    todos_os_produtos = [produto for resultado in resultados_por_mercado for produto in resultado]

    if not todos_os_produtos:
        logger.warning("🚨 Nenhuma oferta coletada de nenhum mercado. Encerrando.")
        return

    # Etapa de Validação Central: Remove itens com dados essenciais faltando antes de qualquer processamento.
    todos_os_produtos = validar_e_limpar_produtos(todos_os_produtos, logger)

    # Adiciona uma camada de sanitização para evitar condições irreais
    logger.info("\n🧠 Verificando e corrigindo condições de oferta com valores irreais...")
    todos_os_produtos = sanitizar_condicoes_absurdas(todos_os_produtos, logger)

    # --- NOVA LÓGICA DE EXECUÇÃO EM FASES ---
    # 2. Separa produtos prontos dos que precisam de IA
    produtos_prontos = []
    produtos_para_ia = []
    for p in todos_os_produtos:
        # Um produto está "pronto" se já tem uma subcategoria válida vinda do scraper
        if p.get("subcategoria", "N/A") != "N/A":
            produtos_prontos.append(p)
        else:
            produtos_para_ia.append(p)

    logger.info(f"\n📊 Divisão de produtos: {len(produtos_prontos)} prontos para salvar, {len(produtos_para_ia)} para classificar pela IA.")

    # 3. Salva imediatamente os produtos que já vieram classificados
    if produtos_prontos:
        produtos_prontos_final = aplicar_fallbacks_finais(produtos_prontos)
        logger.info(f"\n💾 FASE 1: Salvando {len(produtos_prontos_final)} produtos já classificados pelos scrapers...")
        await asyncio.to_thread(salvar_resultados, produtos_prontos_final)

    # 4. Processa e salva os produtos restantes que dependem da IA
    if produtos_para_ia:
        logger.info("\n🧠 FASE 2: Iniciando classificação de taxonomia com IA para produtos restantes...")
        # Passa a lista de dicionários de produtos, não apenas os nomes, para que a imagem seja salva no cache
        mapa_taxonomia = await asyncio.to_thread(classificar_taxonomia_com_ia, produtos_para_ia)

        # Carregamos a biblioteca atualizada para usar como rede de segurança
        from classificador_ia import carregar_biblioteca, normalizar_para_cache
        biblioteca = carregar_biblioteca()

        # Aplica a taxonomia de volta
        for produto in produtos_para_ia:
            nome_original = produto.get("Produto")
            
            # 1. Tenta o nome exato que a IA devolveu
            taxonomia = mapa_taxonomia.get(nome_original)
            
            # 2. Se falhou, tenta buscar pelo nome "limpo" na biblioteca (REDE DE SEGURANÇA)
            if not taxonomia:
                chave_norm = normalizar_para_cache(nome_original)
                taxonomia = biblioteca.get(chave_norm)

            if taxonomia:
                produto["Categoria"] = taxonomia.get("Categoria", "MERCEARIA")
                produto["subcategoria"] = taxonomia.get("subcategoria", "OUTROS")
                produto["tipo_produto"] = taxonomia.get("tipo_produto", "OUTROS")
        
        produtos_ia_final = aplicar_fallbacks_finais(produtos_para_ia)
        logger.info(f"\n💾 FASE 2: Salvando {len(produtos_ia_final)} produtos classificados pela IA...")
        await asyncio.to_thread(salvar_resultados, produtos_ia_final)
    else:
        logger.info("\n✅ Nenhum produto precisou de classificação pela IA.")
    
    logger.info("\n🏆 Operação concluída com sucesso!")

if __name__ == "__main__":
    asyncio.run(main())

    # assai
    # fort
    # roldao
    # tauste
    # tenda