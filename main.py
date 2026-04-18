import pandas as pd
import sqlite3
import os
import asyncio
from datetime import datetime

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
from utils import read_json_file, write_json_file, setup_logging
from classificador_ia import resolver_geral_com_ia

logger = setup_logging()

DATA_DIR = "data"
DB_NOME = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")
CACHE_ARQUIVO = os.path.join(DATA_DIR, "cache_categorias.json")

def inicializar_db():
    """Cria a tabela de ofertas com um schema fixo para garantir compatibilidade."""
    conn = sqlite3.connect(DB_NOME)
    colunas = [
        "Mercado", "Categoria", "Produto", "Marca", "Preço Varejo", "Preço Atacado",
        "Qtd_Valor", "Medida", "Unidade", "Condição", "Validade", "Data_Hora", "Link_Imagem"
    ]
    cols_sql = ", ".join([f'"{c}" TEXT' for c in colunas])
    # Adiciona UNIQUE constraint para evitar duplicatas exatas no banco
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS ofertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            {cols_sql},
            UNIQUE(Mercado, Produto, "Preço Atacado", Data_Hora)
        )
    ''')
    conn.close()

def salvar_resultados(produtos_finais):
    """Salva os resultados consolidados no banco de dados e nos arquivos Excel individuais."""
    if not produtos_finais:
        logger.warning("Nenhum produto final para salvar.")
        return

    df_total = pd.DataFrame(produtos_finais)

    # 1. Salvar no Banco de Dados
    try:
        conn = sqlite3.connect(DB_NOME)
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
            
        df_final_mercado.to_excel(caminho_excel, index=False)
        logger.info(f"📄 Planilha '{caminho_excel}' atualizada com {len(df_mercado)} novas ofertas.")

async def coletar_dados_scraper(nome, func):
    """Worker assíncrono que executa cada scraper em uma thread separada."""
    logger.info(f"🛒 Coletando: {nome}...")
    try:
        # Executa a função síncrona do scraper em uma thread para não bloquear o loop de eventos
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
    logger.info(f"🚀 INICIANDO ORQUESTRADOR DE SCRAPERS - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    inicializar_db()

    scrapers = {
        "Assaí Atacadista": assai.extrair_dados,
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
        # "São Vicente": svicente.extrair_dados
    }

    # 1. Chamar os scrapers em paralelo
    tarefas_coleta = [coletar_dados_scraper(nome, func) for nome, func in scrapers.items()]
    resultados_por_mercado = await asyncio.gather(*tarefas_coleta)
    todos_os_produtos = [produto for resultado in resultados_por_mercado for produto in resultado]

    if not todos_os_produtos:
        logger.warning("🚨 Nenhuma oferta coletada de nenhum mercado. Encerrando.")
        return

    # 2. Usar o cache para categorizar
    logger.info("\n🧠 Aplicando cache de categorias...")
    cache = read_json_file(CACHE_ARQUIVO, default_value={})
    produtos_a_classificar, produtos_finais = [], []

    for produto in todos_os_produtos:
        if produto.get("Produto") in cache:
            produto["Categoria"] = cache[produto.get("Produto")]
            produtos_finais.append(produto)
        else:
            produtos_a_classificar.append(produto)
    
    logger.info(f"👍 {len(produtos_finais)} produtos categorizados via cache.")

    # 3. Passar novos itens pela IA (DESATIVADO)
    if produtos_a_classificar:
        logger.info(f"🤖 {len(produtos_a_classificar)} produtos novos encontrados. Mantendo categoria original do site.")
        for produto in produtos_a_classificar:
            # Mantém a categoria que já veio do scraper (ex: Atacadão já traz via padronizar_categoria)
            produtos_finais.append(produto)
    
    # 4. Salvar o resultado final
    logger.info("\n💾 Salvando todos os resultados...")
    await asyncio.to_thread(salvar_resultados, produtos_finais)
    
    logger.info("\n🏆 Operação concluída com sucesso!")

if __name__ == "__main__":
    inicializar_db()
    asyncio.run(main())

    # assai
    # fort
    # roldao
    # tauste
    # tenda