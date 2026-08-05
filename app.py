import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json
import datetime

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Controle Financeiro Familiar",
    page_icon="💰",
    layout="wide"
)

# Constantes da Planilha
SPREADSHEET_ID = "1-m8bs297sytwdnfvuhsjht" # Substitua se necessário
NOME_ABA = "planilha_1_bruta"

# Autenticação Google Sheets via Secrets do Streamlit
@st.cache_resource
def get_gspread_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    else:
        # Fallback caso use arquivo local
        creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)
    return client

def converter_valor_limpo(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    if not val_str or val_str == "" or val_str.lower() == "nan":
        return 0.0
    
    # Limpa formatações e converte vírgula para ponto decimal
    try:
        val_str_limpa = val_str.replace("R$", "").strip()
        if "," in val_str_limpa and "." in val_str_limpa:
            val_str_limpa = val_str_limpa.replace(".", "").replace(",", ".")
        elif "," in val_str_limpa:
            val_str_limpa = val_str_limpa.replace(",", ".")
        else:
            val_str_limpa = val_str_limpa.replace(".", "") # Caso venha com ponto sem vírgula de milhar indesejada
        return float(val_str_limpa)
    except:
        try:
            # Tentativa alternativa simples
            return float(val_str.replace("R$", "").replace(" ", "").replace(".", "").replace(",", "."))
        except:
            return 0.0

# ==========================================
# INTERFACE PRINCIPAL
# ==========================================
st.markdown("<h1 style='text-align: center;'>💰 Controle Financeiro Familiar</h1>", unsafe_allow_html=True)

aba1, aba2 = st.tabs(["📝 Inserir / Visualizar Dados", "📊 Gráficos e Balanços"])

# ==========================================
# ABA 1: GERENCIAMENTO E CADASTRO
# ==========================================
with aba1:
    st.markdown("### 📋 Tabela e Gestão de Lançamentos")
    
    if st.button("🔄 Atualizar Tabela", key="btn_refresh_aba1"):
        st.cache_data.clear()
        st.rerun()

    try:
        client = get_gspread_client()
        sh = client.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet(NOME_ABA)
        
        rows = worksheet.get_all_values()
        if len(rows) > 0:
            cabecalho = [col.strip() for col in rows[0]]
            dados_linhas = rows[1:]
            df_geral = pd.DataFrame(dados_linhas, columns=cabecalho)
            st.dataframe(df_geral, use_container_width=True)
        else:
            st.info("A planilha está vazia.")
    except Exception as e:
        st.error(f"Erro ao carregar os dados da planilha: {e}")

# ==========================================
# ABA 2: GRÁFICOS E RELATÓRIOS
# ==========================================
with aba2:
    st.markdown("<h2 style='text-align: center;'>📊 Central de Gráficos e Balanços</h2>", unsafe_allow_html=True)
    
    if st.button("🔄 Atualizar Dados dos Gráficos", key="btn_refresh_aba2"):
        st.cache_data.clear()
        st.rerun()

    try:
        client = get_gspread_client()
        sh = client.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet(NOME_ABA)
        
        rows = worksheet.get_all_values()
        
        if len(rows) > 1:
            cabecalho = [col.strip() for col in rows[0]]
            dados_linhas = rows[1:]
            df = pd.DataFrame(dados_linhas, columns=cabecalho)
            
            # Garantir conversão da coluna Valor principal se existir
            if "Valor" in df.columns:
                df["Valor"] = df["Valor"].apply(converter_valor_limpo)
            
            # Identifica colunas de meses (contêm '/' ou nomes de meses)
            colunas_meses = [c for c in df.columns if "/" in c or any(m in c.lower() for m in ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"])]
            
            # Converte todas as colunas de meses para numérico float de forma estrita
            for m in colunas_meses:
                df[m] = df[m].apply(converter_valor_limpo)

            col_cat = next((c for c in df.columns if "categoria" in c.lower()), None)
            col_quem = next((c for c in df.columns if "quem" in c.lower() or "gastou" in c.lower()), None)
            col_banco = next((c for c in df.columns if "banco" in c.lower() or "emissor" in c.lower()), None)

            sub_aba1, sub_aba2, sub_aba3 = st.tabs(["📅 Balanço Mensal", "🌐 Balanço Anual", "💳 Controle de Parcelamentos"])

            # ==========================================
            # SUB-ABA 1: BALANÇO MENSAL
            # ==========================================
            with sub_aba1:
                st.markdown("### 🗓️ Filtrar por Mês Específico")
                if colunas_meses:
                    mes_selecionado = st.selectbox("Escolha o mês:", colunas_meses, key="select_mes")
                    
                    df_mes = df.copy()
                    df_mes_filtrado = df_mes[df_mes[mes_selecionado] > 0].copy()
                    df_mes_filtrado["Valor_Mes"] = df_mes_filtrado[mes_selecionado]
                    
                    total_mes = df_mes_filtrado["Valor_Mes"].sum()
                    st.metric(label=f"💰 Total Gasto em {mes_selecionado} (100%)", value=f"R$ {total_mes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    st.markdown("---")
                    
                    col_m1, col_m2, col_m3 = st.columns(3)
                    
                    # Gráfico 1: Categoria
                    with col_m1:
                        st.markdown("#### Por Categoria")
                        if col_cat and not df_mes_filtrado.empty:
                            df_c = df_mes_filtrado.groupby(col_cat, as_index=False)["Valor_Mes"].sum()
                            df_c = df_c[df_c["Valor_Mes"] > 0]
                            if not df_c.empty:
                                fig = px.pie(df_c, names=col_cat, values="Valor_Mes", hole=0.4, template="plotly_white")
                                fig.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
                                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), height=350, showlegend=True)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sem dados.")
                        else:
                            st.info("Sem dados.")

                    # Gráfico 2: Quem Gastou
                    with col_m2:
                        st.markdown("#### Quem Gastou")
                        if col_quem and not df_mes_filtrado.empty:
                            df_q = df_mes_filtrado.groupby(col_quem, as_index=False)["Valor_Mes"].sum()
                            df_q = df_q[df_q["Valor_Mes"] > 0]
                            if not df_q.empty:
                                fig = px.pie(df_q, names=col_quem, values="Valor_Mes", hole=0.4, template="plotly_white")
                                fig.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
                                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), height=350, showlegend=True)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sem dados.")
                        else:
                            st.info("Sem dados.")

                    # Gráfico 3: Banco / Emissor
                    with col_m3:
                        st.markdown("#### Por Banco / Cartão")
                        if col_banco and not df_mes_filtrado.empty:
                            df_b = df_mes_filtrado.groupby(col_banco, as_index=False)["Valor_Mes"].sum()
                            df_b = df_b[df_b["Valor_Mes"] > 0]
                            if not df_b.empty:
                                fig = px.pie(df_b, names=col_banco, values="Valor_Mes", hole=0.4, template="plotly_white")
                                fig.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
                                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), height=350, showlegend=True)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sem dados.")
                        else:
                            st.info("Sem dados.")
                else:
                    st.info("Ainda não há colunas de meses cadastradas na planilha.")

            # ==========================================
            # SUB-ABA 2: BALANÇO ANUAL
            # ==========================================
            with sub_aba2:
                st.markdown("### 🌐 Panorama Geral do Ano")
                
                if colunas_meses:
                    df_anual = df.copy()
                    
                    # Soma a linha inteira dos meses convertidos para obter o total anual por linha
                    df_anual["Total_Linha_Ano"] = df_anual[colunas_meses].sum(axis=1)
                    total_geral_ano = df_anual["Total_Linha_Ano"].sum()
                    
                    st.metric(label="💰 Total Geral Acumulado no Ano (100%)", value=f"R$ {total_geral_ano:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    st.markdown("---")
                    
                    col_a1, col_a2, col_a3 = st.columns(3)
                    
                    with col_a1:
                        st.markdown("#### Por Categoria (Anual)")
                        if col_cat and not df_anual.empty:
                            df_ca = df_anual.groupby(col_cat, as_index=False)["Total_Linha_Ano"].sum()
                            df_ca = df_ca[df_ca["Total_Linha_Ano"] > 0]
                            if not df_ca.empty:
                                fig = px.pie(df_ca, names=col_cat, values="Total_Linha_Ano", hole=0.4, template="plotly_white")
                                fig.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
                                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), height=350, showlegend=True)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sem valores somáveis.")

                    with col_a2:
                        st.markdown("#### Quem Gastou (Anual)")
                        if col_quem and not df_anual.empty:
                            df_qa = df_anual.groupby(col_quem, as_index=False)["Total_Linha_Ano"].sum()
                            df_qa = df_qa[df_qa["Total_Linha_Ano"] > 0]
                            if not df_qa.empty:
                                fig = px.pie(df_qa, names=col_quem, values="Total_Linha_Ano", hole=0.4, template="plotly_white")
                                fig.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
                                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), height=350, showlegend=True)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sem valores somáveis.")

                    with col_a3:
                        st.markdown("#### Por Banco (Anual)")
                        if col_banco and not df_anual.empty:
                            df_ba = df_anual.groupby(col_banco, as_index=False)["Total_Linha_Ano"].sum()
                            df_ba = df_ba[df_ba["Total_Linha_Ano"] > 0]
                            if not df_ba.empty:
                                fig = px.pie(df_ba, names=col_banco, values="Total_Linha_Ano", hole=0.4, template="plotly_white")
                                fig.update_traces(textinfo="percent+label", hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>")
                                fig.update_layout(margin=dict(t=20, b=20, l=10, r=10), height=350, showlegend=True)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("Sem valores somáveis.")
                else:
                    st.info("Ainda não há colunas de meses cadastradas na planilha.")

            # ==========================================
            # SUB-ABA 3: CONTROLE DE PARCELAMENTOS
            # ==========================================
            with sub_aba3:
                st.markdown("### 💳 Acompanhamento de Parcelas e Extensões")
                if colunas_meses:
                    st.dataframe(df, use_container_width=True)
                else:
                    st.info("Nenhuma coluna de parcelamento/mês identificada.")

            st.markdown("---")
            st.markdown("### 📋 Tabela Completa de Dados")
            st.dataframe(df, use_container_width=True)
            
        else:
            st.info("ℹ️ Ainda não há dados cadastrados na planilha para gerar gráficos.")
    except Exception as e:
        st.error(f"Erro ao carregar: {e}")
