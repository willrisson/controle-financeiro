import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px
from datetime import datetime

# Configuração da página
st.set_page_config(
    page_title="Controle Familiar de Despesas",
    page_icon="💳",
    layout="centered"
)

# 1. Configuração do Google Sheets
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def conectar_google_sheets():
    # Puxa as credenciais dos Secrets do Streamlit
    credentials_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    # Abre a planilha pelo ID configurado nos secrets
    spreadsheet_id = st.secrets["sheets"]["spreadsheet_id"]
    sheet = client.open_by_key(spreadsheet_id)
    return sheet

try:
    planilha = conectar_google_sheets()
    aba_dados = planilha.worksheet("Dados_Brutos") # Ajuste o nome da aba se necessário
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets: {e}")

# 2. Criação das Abas no Topo
aba1, aba2 = st.tabs(["📝 Lançar Gasto", "📊 Gráficos por Mês"])

# ==========================================
# ABA 1: LANÇAR GASTO
# ==========================================
with aba1:
    st.markdown("<h2 style='text-align: center;'>💳 Controle Familiar de Despesas</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Lançador Organizado</p>", unsafe_allow_html=True)

    with st.form("form_gasto", clear_on_submit=True):
        st.markdown("### 👤 Quem está gastando?")
        quem = st.selectbox("Membro", ["Aline", "Willian", "Ambos"], label_visibility="collapsed")
        st.caption("Membro cadastrado selecionado")

        st.markdown("---")
        descricao = st.text_input("Descrição do Gasto", placeholder="Ex: Meta Quest 3s")
        valor = st.number_input("Valor Total (R$)", min_value=0.0, format="%.2f", placeholder="Ex: 50, 50,00 ou 1800,00")

        st.markdown("### 📁 Categoria do Gasto")
        col_cat1, col_cat2 = st.columns([3, 1])
        with col_cat1:
            categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Outros"], label_visibility="collapsed")
        with col_cat2:
            nova_cat = st.form_submit_button("+ Adicionar")

        col_pgto1, col_pgto2 = st.columns(2)
        with col_pgto1:
            forma_pagto = st.selectbox("Forma de Pagamento", ["Pix", "Cartão de Crédito", "Dinheiro", "Débito"])
        with col_pgto2:
            banco = st.selectbox("Banco / Emissor", ["Nubank", "Itaú", "Sicredi", "Outros"])

        parcelado = st.checkbox("Gasto Parcelado?")
        num_parcelas = st.number_input("Número de Parcelas", min_value=1, max_value=72, value=1, placeholder="Ex: 10")

        submitted = st.form_submit_button("🚀 Registrar Gasto", use_container_width=True)

        if submitted:
            if not descricao or valor <= 0:
                st.warning("⚠️ Por favor, preencha a descrição e um valor válido.")
            else:
                try:
                    data_atual = datetime.now().strftime("%d/%m/%Y")
                    # Exemplo de salvamento na planilha
                    aba_dados.append_row([data_atual, quem, descricao, valor, categoria, forma_pagto, banco, "Sim" if parcelado else "Não", num_parcelas])
                    st.success("✅ Gasto registrado com sucesso na planilha!")
                except Exception as e:
                    st.error(f"Erro ao salvar na planilha: {e}")

# ==========================================
# ABA 2: GRÁFICOS POR MÊS
# ==========================================
with aba2:
    st.markdown("<h2 style='text-align: center;'>📊 Análise de Despesas por Mês</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 Atualizar Dados da Planilha"):
        st.cache_data.clear()
        st.rerun()

    try:
        # Puxa os dados da planilha para montar os gráficos
        dados = aba_dados.get_all_records()
        if dados:
            df = pd.DataFrame(dados)
            
            # Filtro por mês se houver coluna de data
            st.markdown("### 📈 Visualização de Gastos")
            if "Categoria" in df.columns and "Valor Total (R$)" in df.columns or len(df.columns) >= 5:
                # Exemplo genérico de gráfico de pizza por categoria caso os dados estejam estruturados
                fig = px.pie(df, names=df.columns[4], values=df.columns[3], title="Gastos por Categoria")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.dataframe(df)
        else:
            st.info("ℹ️ Ainda não há dados cadastrados na planilha para gerar gráficos.")
    except Exception as e:
        st.info("ℹ️ Cadastre seu primeiro gasto na aba anterior para habilitar os gráficos.")
