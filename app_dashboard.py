import streamlit as st
import pandas as pd
import sqlite3
import os
import re

# ==========================================
# CONFIGURAÇÃO PREMIUM DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Comparador Mestre",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .block-container {padding-top: 2rem;}
    </style>
""", unsafe_allow_html=True)

DB_NOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'monitoramento_Jundiai.db')

@st.cache_data
def carregar_dados():
    """Carrega os dados diretamente do banco de dados SQLite."""
    if not os.path.exists(DB_NOME):
        return pd.DataFrame()

    conn = sqlite3.connect(DB_NOME)
    try:
        # A query simples 'SELECT *' é suficiente, o pandas lida com os nomes das colunas
        df = pd.read_sql_query("SELECT * FROM ofertas", conn)
    finally:
        conn.close()

    df.fillna("", inplace=True)
    
    def tratar_melhor_preco(row):
        def limpar(val):
            try:
                if not val or str(val).lower() == 'nan': return 0.0
                return float(str(val).replace('R$', '').replace('.', '').replace(',', '.').strip())
            except: return 0.0

        varejo = limpar(row.get('Preço Varejo', 0))
        atacado = limpar(row.get('Preço Atacado', 0))

        if atacado == 0: return varejo
        if varejo == 0: return atacado
        return min(varejo, atacado)
        
    df['Preço Numérico'] = df.apply(tratar_melhor_preco, axis=1)
    return df

df = carregar_dados()

# ==========================================
# CABEÇALHO MODERNO
# ==========================================
col_logo, col_titulo = st.columns([1, 8])
with col_logo:
    st.markdown("## 🛒")
with col_titulo:
    st.title("Central de Inteligência")
    st.markdown("Encontre o menor preço nos supermercados de Jundiaí.")

if df.empty:
    st.warning(f"⚠️ Nenhuma base de dados encontrada em: {DB_NOME}")
    st.stop()

# ==========================================
# MOTOR DE LIMPEZA DOS DADOS E CORREÇÕES
# ==========================================
df = df.loc[:, ~df.columns.duplicated()].copy()

# 1. Unificador de Categorias (Remove acentos e espaços extras)
df['Categoria'] = df['Categoria'].astype(str).str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8').str.upper().str.strip()

# 2. Tratamento da Condição Vazia -> "1 UN"
def tratar_condicao(val):
    v = str(val).strip().upper()
    if v in ['', 'NAN', 'NONE']:
        return '1 UN'
    return val

df['Condição'] = df['Condição'].apply(tratar_condicao)

# 3. Limpeza do Nome do Produto
produtos_limpos = []
for p, m in zip(df['Produto'], df['Marca']):
    prod, marca = str(p), str(m)
    if marca and marca.lower() != 'nan' and marca != "":
        prod = prod.replace(f" - {marca}", "").replace(marca, "").strip(' -')
    
    prod = re.sub(r'\b(\d+[,.]?\d*\s*(KG|G|ML|L|UN|LITRO|LITROS)|KG|UN|ML|LITRO|LITROS)\b', '', prod, flags=re.IGNORECASE)
    prod = re.sub(r'\s+', ' ', prod).strip(' -')
    produtos_limpos.append(prod)

df['Produto'] = produtos_limpos
df['Tamanho'] = df['Qtd_Valor'].astype(str).str.replace('.0', '', regex=False) + " " + df['Medida'].astype(str)
df['Tamanho'] = df['Tamanho'].str.replace('nan nan', '').str.replace('nan', '').str.strip()

# ==========================================
# BUSCA E FILTROS ALINHADOS LADO A LADO
# ==========================================
st.markdown("---")

col_busca, col_categoria = st.columns([7, 3])

with col_busca:
    busca_texto = st.text_input("🔍 Qual produto você quer comparar?", placeholder="Ex: Cebola, Arroz, Fralda...")

with col_categoria:
    categorias = ["Todas as Categorias"] + sorted([c for c in df['Categoria'].unique() if c != ""])
    filtro_categoria = st.selectbox("📂 Filtrar por Categoria:", options=categorias)

# BARRA LATERAL
st.sidebar.markdown("### ⚙️ Filtro de Loja")
mercados = sorted(df['Mercado'].unique())
filtro_mercado = st.sidebar.multiselect("Ocultar ou mostrar mercados:", options=mercados, placeholder="Todas as lojas")
st.sidebar.markdown("---")
st.sidebar.info(f"Última atualização:\n\n**{df['Data_Hora'].max()[:10] if 'Data_Hora' in df.columns else 'N/A'}**")

# ==========================================
# APLICAÇÃO DOS FILTROS NO MOTOR
# ==========================================
df_filtrado = df.copy()

if busca_texto:
    termo = busca_texto.upper()
    df_filtrado = df_filtrado[df_filtrado['Produto'].str.contains(termo) | df_filtrado['Marca'].str.contains(termo)]

if filtro_categoria != "Todas as Categorias":
    df_filtrado = df_filtrado[df_filtrado['Categoria'] == filtro_categoria]

if filtro_mercado:
    df_filtrado = df_filtrado[df_filtrado['Mercado'].isin(filtro_mercado)]

# ==========================================
# VISUALIZAÇÃO DIRETA AO PONTO
# ==========================================
configuracao_colunas = {
    "Mercado": st.column_config.TextColumn("Mercado", width="medium"),
    "Produto": st.column_config.TextColumn("Produto", width="large"),
    "Marca": st.column_config.TextColumn("Marca", width="medium"),
    "Tamanho": st.column_config.TextColumn("Vol/Peso", width="small"),
    "Condição": st.column_config.TextColumn("Condição da Oferta", width="medium"),
    "Preço Numérico": st.column_config.NumberColumn("Preço Atual", format="R$ %.2f", width="small"),
}

colunas_para_exibir = ['Mercado', 'Produto', 'Marca', 'Tamanho', 'Preço Numérico', 'Condição']

if not df_filtrado.empty:
    df_filtrado = df_filtrado.sort_values(by=['Preço Numérico', 'Produto'])
    
    if busca_texto or filtro_categoria != "Todas as Categorias":
        campeao = df_filtrado.iloc[0]
        preco_formatado = f"{campeao['Preço Numérico']:.2f}".replace('.', ',')
        cond = str(campeao['Condição']).strip()

        # Lógica do banner de destaque aprimorada para exibir a condição claramente.
        texto_condicao = ""
        if cond and cond.upper() not in ['NAN', '1 UN', '']:
            texto_condicao = f" (condição: **{cond}**)"

        st.success(f"🏆 **MELHOR OPÇÃO:** {campeao['Produto']} por **R$ {preco_formatado}** no **{campeao['Mercado']}**{texto_condicao}")
        st.markdown("#### 📋 Ranking de Preços nos outros mercados:")
    else:
        st.markdown("#### 📋 Todas as Ofertas (Do mais barato ao mais caro):")

    st.dataframe(df_filtrado[colunas_para_exibir], column_config=configuracao_colunas, hide_index=True, use_container_width=True, height=600)
else:
    st.info("Nenhuma oferta encontrada com esses filtros.")