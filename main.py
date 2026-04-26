import pandas as pd
import sqlite3
import os
import asyncio
from datetime import datetime

# Importações dos scrapers
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

from utils import read_json_file, write_json_file, setup_logging, validar_e_limpar_produtos, criar_entrada_biblioteca
from classificador_ia import classificar_taxonomia_com_ia_async, carregar_biblioteca, salvar_biblioteca

logger = setup_logging()

DATA_DIR = "data"
DB_NOME = os.path.join(DATA_DIR, "monitoramento_Jundiai.db")

# ==========================================
# FUNÇÕES DE SUPORTE (DATABASE E EXCEL)
# ==========================================

def garantir_tabela_ofertas(db_path):
    """Garante que o diretório de dados e a tabela 'ofertas' no banco de dados existam com a estrutura correta."""
    data_dir = os.path.dirname(db_path)
    if data_dir and not os.path.exists(data_dir):
        os.makedirs(data_dir)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Cria a tabela se o sistema não a encontrar, mantendo a estrutura completa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ofertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Mercado TEXT,
            EAN TEXT,
            Categoria TEXT,
            subcategoria TEXT,
            tipo_produto TEXT,
            Produto TEXT,
            Marca TEXT,
            Preco_Varejo TEXT, 
            Preco_Atacado TEXT, 
            Qtd_Valor TEXT,
            Medida TEXT,
            Unidade TEXT,
            Condicao TEXT,
            Data_Hora TEXT,
            Link_Imagem TEXT,
            UNIQUE(Mercado, Produto, Qtd_Valor, Medida)
        )
    ''')
    conn.commit()
    conn.close()

def salvar_dados_mercado(produtos, nome_mercado):
    """Salva os dados no SQLite e gera a planilha individual."""
    if not produtos:
        return
    
    # --- SALVAMENTO NO SQLITE ---
    conn = sqlite3.connect(DB_NOME)
    cursor = conn.cursor()
    
    # Otimização: Prepara todos os dados para uma única operação 'executemany'
    dados_para_inserir = [
        (
            p['Mercado'], p['EAN'], p['Categoria'], p['subcategoria'], p['tipo_produto'],
            p['Produto'], p['Marca'], p['Preço Varejo'], p['Preço Atacado'], 
            p['Qtd_Valor'], p['Medida'], p['Unidade'], p['Condição'], p['Data_Hora'], p['Link_Imagem']
        ) for p in produtos
    ]
    
    # Usamos executemany para uma performance muito superior em lotes
    cursor.executemany('''
        INSERT INTO ofertas (
            Mercado, EAN, Categoria, subcategoria, tipo_produto, Produto, Marca, 
            Preco_Varejo, Preco_Atacado, Qtd_Valor, Medida, Unidade, Condicao, Data_Hora, Link_Imagem
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(Mercado, Produto, Qtd_Valor, Medida) DO UPDATE SET
            EAN = excluded.EAN,
            Categoria = excluded.Categoria,
            subcategoria = excluded.subcategoria,
            tipo_produto = excluded.tipo_produto,
            Preco_Varejo = excluded.Preco_Varejo,
            Preco_Atacado = excluded.Preco_Atacado,
            Condicao = excluded.Condicao,
            Data_Hora = excluded.Data_Hora,
            Link_Imagem = excluded.Link_Imagem
    ''', dados_para_inserir)
    
    conn.commit()
    conn.close()

    # --- SALVAMENTO NO EXCEL ---
    filename = os.path.join(DATA_DIR, f"historico_{nome_mercado.lower().replace(' ', '_')}.xlsx")
    df_novos = pd.DataFrame(produtos)
    # Garante que o EAN seja tratado como texto para evitar notação científica no Excel
    if 'EAN' in df_novos.columns:
        df_novos['EAN'] = df_novos['EAN'].astype(str)
    
    if os.path.exists(filename):
        try:
            # Ao ler o arquivo antigo, também garantimos que o EAN é texto
            df_antigo = pd.read_excel(filename, dtype={'EAN': str})
            df_final = pd.concat([df_antigo, df_novos]).drop_duplicates(
                subset=['Produto', 'Marca', 'Qtd_Valor', 'Medida'], keep='last'
            )
            df_final.to_excel(filename, index=False)
        except Exception as e:
            logger.error(f"Erro ao atualizar Excel de {nome_mercado}: {e}")
            df_novos.to_excel(filename, index=False)
    else:
        df_novos.to_excel(filename, index=False)

# ==========================================
# PROCESSO PRINCIPAL (ORQUESTRADOR)
# ==========================================

async def main():
    logger.info(f"🚀 INICIANDO ORQUESTRADOR - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    garantir_tabela_ofertas(DB_NOME)
    biblioteca = carregar_biblioteca()
    resumo_geral = {}

    # ---------------------------------------------------------
    # ETAPA 1: MERCADOS COM DADOS ESTRUTURADOS (API / JSON)
    # ---------------------------------------------------------
    scrapers_api = [
        # (atacadao, "Atacadão"),
        # (carrefour, "Carrefour"), não funcionou o EAN, fazer os outros mercados primeiro para enriquecer a biblioteca e depois tentar corrigir o carrefour
        (boa, "Boa"),
        # (paodeacucar, "Pão de Açúcar"),
        # (svicente, "S. Vicente"),
        # (covabra, "Covabra"),
        # (oba, "Oba Hortifruti"),
        # (dom_olivio, "Dom Olívio")
    ]

    logger.info("\n=== ETAPA 1: COLETANDO DADOS ESTRUTURADOS (API) ===")
    for modulo, nome_mercado in scrapers_api:
        try:
            logger.info(f"🛒 Processando: {nome_mercado}")
            produtos_brutos = await modulo.extrair_dados()
            
            if not produtos_brutos:
                logger.warning(f"⚠️ {nome_mercado}: Nenhuma oferta capturada."); continue

            # Limpeza, Enriquecimento (com a biblioteca) e Auditoria (Flag PRECISA_DE_IA definida no utils.py)
            produtos_validados = validar_e_limpar_produtos(produtos_brutos, logger, biblioteca)

            # Separação de itens para conferência da IA
            itens_ok = [p for p in produtos_validados if not p.get("PRECISA_DE_IA")]
            itens_suspeitos = [p for p in produtos_validados if p.get("PRECISA_DE_IA")]

            # --- LÓGICA DE BIBLIOTECA PARA ITENS JÁ CORRETOS ---
            # Adiciona à biblioteca os itens que passaram na validação e não precisam de IA
            novas_entradas_ok = {}
            for p_ok in itens_ok:
                chave, entrada = criar_entrada_biblioteca(p_ok)
                if chave and chave not in biblioteca:
                    novas_entradas_ok[chave] = entrada

            if novas_entradas_ok:
                logger.info(f"📚 Adicionando {len(novas_entradas_ok)} produtos validados diretamente à biblioteca.")
                biblioteca.update(novas_entradas_ok)

            if itens_suspeitos:
                logger.info(f"🧠 Auditor detetou {len(itens_suspeitos)} anomalias no {nome_mercado}. Corrigindo com IA...")
                
                # Pega a resposta da IA e as novas entradas para a biblioteca
                mapa_corrigido, novas_entradas = await classificar_taxonomia_com_ia_async(itens_suspeitos, biblioteca)
                
                # Atualiza a biblioteca em memória com as novas classificações
                if novas_entradas:
                    logger.info(f"📚 Adicionando {len(novas_entradas)} produtos corrigidos pela IA à biblioteca.")
                    biblioteca.update(novas_entradas)
                
                if isinstance(mapa_corrigido, dict):
                    for p in itens_suspeitos:
                        correcao = mapa_corrigido.get(p['Produto'])
                        if isinstance(correcao, dict):
                            # Correção: As chaves no dicionário da biblioteca são capitalizadas.
                            p['Categoria'] = correcao.get('Categoria', p['Categoria'])
                            p['subcategoria'] = correcao.get('subcategoria', p['subcategoria'])
                            p['tipo_produto'] = correcao.get('tipo_produto', p['tipo_produto'])
                else:
                    logger.error(f"⚠️ A IA devolveu um erro ou formato inválido. Mantendo as categorias originais.")

            # Junta tudo (mesmo se a IA falhou, o programa continua)
            lista_final = itens_ok + itens_suspeitos
            salvar_dados_mercado(lista_final, nome_mercado)
            resumo_geral[nome_mercado] = len(lista_final)
            
        except Exception as e:
            logger.error(f"❌ Erro no scraper {nome_mercado}: {e}")

    # ---------------------------------------------------------
    # ETAPA 2: MERCADOS QUE DEPENDEM DE IA (FOLHETOS / IMAGENS)
    # ---------------------------------------------------------
    scrapers_ia = [
        # (assai, "Assaí"),
        # (fort, "Fort Atacadão"),
        # (roldao, "Roldão"),
        # (tenda, "Tenda"),
        # (tauste, "Tauste")
       
    ]

    logger.info("\n=== ETAPA 2: COLETANDO FOLHETOS E OFERTAS VIA IA ===")
    for modulo, nome_mercado in scrapers_ia:
        try:
            logger.info(f"📸 Lendo Folheto: {nome_mercado}")
            produtos_brutos = await modulo.extrair_dados()
            
            if not produtos_brutos: continue

            # Para folhetos, a IA já processou os dados, fazemos apenas a limpeza final
            produtos_validados = validar_e_limpar_produtos(produtos_brutos, logger)
            salvar_dados_mercado(produtos_validados, nome_mercado)
            resumo_geral[nome_mercado] = len(produtos_validados)
            
        except Exception as e:
            logger.error(f"❌ Erro no folheto de {nome_mercado}: {e}")

    # Finalização
    salvar_biblioteca(biblioteca)
    logger.info("\n" + "="*50 + "\n📊 RESUMO FINAL DA EXECUÇÃO:\n" + "="*50)
    for m, q in resumo_geral.items():
        logger.info(f"  - {m}: {q} produtos")
    logger.info("🏆 Operação concluída com sucesso!")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())