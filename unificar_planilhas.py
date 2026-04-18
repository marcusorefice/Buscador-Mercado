import pandas as pd
import os
import glob
import re
from datetime import datetime

from utils import setup_logging
logger = setup_logging()

# ==========================================
# CONFIGURAÇÕES DO COMPARADOR MESTRE
# ==========================================
PASTA_RAIZ = os.path.dirname(os.path.abspath(__file__))
PASTA_DADOS = os.path.join(PASTA_RAIZ, 'data')
ARQUIVO_FINAL = os.path.join(PASTA_RAIZ, 'RELATORIO_FINAL_COMPARADOR.xlsx')

def limpar_preco(valor):
    """Converte 'R$ 10,99' em float 10.99 para cálculos matemáticos"""
    if pd.isna(valor) or valor == "": return 0.0
    try:
        if isinstance(valor, str):
            return float(valor.replace('R$', '').replace('.', '').replace(',', '.').strip())
        return float(valor)
    except: return 0.0

def criar_chave(row):
    """Cria uma identidade única para o produto ignorando palavras bobas e marca"""
    nome = str(row['Produto']).upper()
    marca = str(row['Marca']).upper() if pd.notna(row['Marca']) else ""
    
    # Tira a marca de dentro do nome para não duplicar
    if marca and marca != 'NAN':
        nome = nome.replace(marca, "")
        
    # Limpa caracteres especiais e embalagens que atrapalham
    nome = re.sub(r'\b(LATA|PACOTE|PCT|CX|CAIXA|TP|PET|VD|VIDRO|GARRAFA|GF|SACHE|UN|UNIDADE|LV|PG|GRATIS|GRÁTIS|POTE|BANDEJA)\b', '', nome)
    nome = re.sub(r'[^\w\s]', '', nome)
    
    # Pega as 3 palavras principais do produto
    words = [w for w in nome.split() if w not in ['DE', 'COM', 'EM', 'PARA']]
    base_name = " ".join(words[:3]) 
    
    # Pega o volume/peso
    qtd = str(row['Qtd_Valor']).replace('.0', '') if pd.notna(row['Qtd_Valor']) else ""
    if qtd.lower() == 'nan': qtd = ""
    med = str(row['Medida']).upper() if pd.notna(row['Medida']) else ""
    if med.lower() == 'nan': med = ""
    
    # Se a IA comeu a quantidade, tenta resgatar do nome (Ex: 16 UNIDADES)
    if qtd == "":
        match = re.search(r'(\d+)\s*(UNIDADE|UNIDADES|UN|PEÇAS|FOLHAS)', str(row['Produto']).upper())
        if match:
            qtd = match.group(1)
            med = "UN"
            
    return f"{base_name} | {marca} | {qtd}{med}".strip()

def unificar_planilhas():
    logger.info("✨ Iniciando a Magia de Unificação Inteligente...")
    
    arquivos = glob.glob(os.path.join(PASTA_DADOS, "historico_*.xlsx"))
    
    if not arquivos:
        logger.warning("❌ Nenhuma planilha de histórico encontrada na pasta.")
        return

    lista_dfs = []
    for arquivo in arquivos:
        nome_mercado = os.path.basename(arquivo).replace('historico_', '').replace('.xlsx', '').upper()
        logger.info(f"📦 Lendo dados de: {nome_mercado}...")
        try:
            df = pd.read_excel(arquivo)
            df['Preço Varejo Num'] = df['Preço Varejo'].apply(limpar_preco)
            df['Preço Atacado Num'] = df['Preço Atacado'].apply(limpar_preco)
            lista_dfs.append(df)
        except Exception as e:
            logger.error(f"⚠️ Erro ao ler {arquivo}: {e}", exc_info=True)

    df_geral = pd.concat(lista_dfs, ignore_index=True)

    # ==========================================
    # A MENTE DO COMPARADOR (AGRUPAMENTO)
    # ==========================================
    logger.info("🧠 Criando identidades únicas para cruzar os produtos de mercados diferentes...")
    df_geral['Chave'] = df_geral.apply(criar_chave, axis=1)

    # Conta em quantos mercados diferentes o produto apareceu
    mercados_por_chave = df_geral.groupby('Chave')['Mercado'].nunique()

    # Encontra o menor preço do mercado para aquela "Chave"
    melhores_precos = df_geral.groupby('Chave')['Preço Atacado Num'].min().reset_index()
    melhores_precos.rename(columns={'Preço Atacado Num': 'Menor Preço Encontrado'}, inplace=True)

    # Cruza a informação de volta com a tabela principal
    df_final = pd.merge(df_geral, melhores_precos, on='Chave')

    # ==========================================
    # A MEDALHA DE OURO (SÓ PARA QUEM COMPETE)
    # ==========================================
    df_final['Destaque'] = ""
    mask_barato = df_final['Preço Atacado Num'] == df_final['Menor Preço Encontrado']
    mask_competicao = df_final['Chave'].map(mercados_por_chave) > 1

    # Ganha estrela SE for o menor preço E estiver sendo vendido em 2 ou mais mercados
    df_final.loc[mask_barato & mask_competicao, 'Destaque'] = "⭐ MELHOR PREÇO"
    
    # Se só um mercado vende, não tem competição, ganha tag de exclusividade
    df_final.loc[~mask_competicao, 'Destaque'] = "🛒 Oferta Única"

    # Organiza a planilha final agrupando os produtos idênticos um embaixo do outro para você comparar de olho!
    df_final = df_final.sort_values(by=['Categoria', 'Chave', 'Preço Atacado Num'])

    # Remove o lixo de cálculo e as colunas feias
    df_final = df_final.drop(columns=['Preço Varejo Num', 'Preço Atacado Num', 'Menor Preço Encontrado', 'Chave'])

    df_final.to_excel(ARQUIVO_FINAL, index=False)
    
    logger.info("-" * 50)
    logger.info(f"🏆 SUCESSO! {len(df_final)} itens cruzados com perfeição.")
    logger.info(f"📂 O relatório definitivo está em: {ARQUIVO_FINAL}")
    logger.info("=" * 50)

if __name__ == "__main__":
    unificar_planilhas()