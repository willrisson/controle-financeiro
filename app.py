import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Controle Financeiro Familiar", page_icon="💳", layout="centered")

GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
SPREADSHEET_ID = "1eFK9CtarQoKqpZBBoptltnNS-cWU92pw2K7oEAXyI7k"
NOME_ABA = "Controle de Gastos"

# Função auxiliar unificada para autenticação segura via Secrets
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

LISTA_CATEGORIAS_BASE = [
    "Lazer", "Presente", "Alimentação", "Transporte", "Moradia",
    "Saúde", "Vestuário", "Manutenção", "Educação", "Infraestrutura", "Outros"
]

LISTA_GASTADORES_BASE = ["Willian", "Aline", "Bernardo"]

# Inicialização de estados
if "gastadores_extras" not in st.session_state:
    st.session_state["gastadores_extras"] = []

if "categorias_extras" not in st.session_state:
    st.session_state["categorias_extras"] = []

if "form_limpo" not in st.session_state:
    st.session_state["form_limpo"] = False

if "processando_envio" not in st.session_state:
    st.session_state["processando_envio"] = False

# Limpeza de campos se acionada
if st.session_state["form_limpo"]:
    st.session_state["input_descricao"] = ""
    st.session_state["input_valor"] = ""
    st.session_state["check_parcelado"] = False
    st.session_state["input_num_parcelas"] = ""
    st.session_state["form_limpo"] = False

def obter_nome_mes_ano(data):
    meses_pt = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }
    return f"{meses_pt[data.month]}/{data.year}"

def classificar_categoria_groq(descricao, status_container, categorias_disponiveis):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    cats_str = ", ".join(categorias_disponiveis)
    prompt = f"""
Analise a descrição desta despesa: "{descricao}".
Classifique-a na categoria mais adequada entre as opções disponíveis: {cats_str}.
Responda EXATAMENTE no formato JSON: {{"categoria": "Nome da Categoria"}}
"""
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    try:
        if status_container:
            status_container.write("🤖 Consultando inteligência artificial (Groq)...")
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        data = res.json()
        if "choices" in data and len(data["choices"]) > 0:
            cat = json.loads(data['choices'][0]['message'].get('content', '{}')).get("categoria", "Outros")
            if cat in categorias_disponiveis:
                return cat
    except Exception:
        pass
    return "Outros"

# ==========================================
# APLICATIVO PRINCIPAL
# ==========================================
st.title("💳 Controle Familiar de Despesas")
st.markdown("**Lançador Organizado**")

# --- ABAS ---
tab_lancamento, tab_dashboard = st.tabs(["📝 Lançar Gasto", "📊 Dashboard"])

with tab_lancamento:
    # --- SEÇÃO DE QUEM ESTÁ GASTANDO ---
    st.markdown("### 👤 Quem está gastando?")
    lista_gastadores_atualizada = sorted(list(set(LISTA_GASTADORES_BASE + st.session_state["gastadores_extras"])))
    lista_gastadores_com_outro = lista_gastadores_atualizada + ["Outro..."]

    col_q_sel, col_q_txt = st.columns([2, 2])
    with col_q_sel:
        quem_gastou_selecionado = st.selectbox("Selecione o membro", lista_gastadores_com_outro, key="select_gastador", label_visibility="collapsed")

    quem_gastou = quem_gastou_selecionado
    if quem_gastou_selecionado == "Outro...":
        with col_q_txt:
            outro_membro_input = st.text_input("Nome do outro membro", placeholder="Digite o nome...", key="input_outro_membro", label_visibility="collapsed")
            if outro_membro_input.strip():
                quem_gastou = outro_membro_input.strip()
    else:
        with col_q_txt:
            st.markdown("<br><small style='color:#888'>Membro cadastrado selecionado</small>", unsafe_allow_html=True)

    st.markdown("---")

    descricao_gasto = st.text_input("Descrição do Gasto", placeholder="Ex: Meta Quest 3s", key="input_descricao")
    valor_texto = st.text_input("Valor Total (R$)", placeholder="Ex: 50, 50,00 ou 1800,00", key="input_valor")

    # --- CONEXÃO PARA BUSCAR CATEGORIAS JÁ UTILIZADAS NA PLANILHA ---
    @st.cache_data(ttl=60)
    def carregar_categorias_existentes():
        try:
            client = get_gspread_client()
            sh = client.open_by_key(SPREADSHEET_ID)
            worksheet = sh.worksheet(NOME_ABA)

            cabecalho = worksheet.row_values(1)
            if "Categoria" in cabecalho:
                idx_cat = cabecalho.index("Categoria")
                colunas_valores = worksheet.get_all_values()
                cats_encontradas = set(LISTA_CATEGORIAS_BASE)
                for linha in colunas_valores[1:]:
                    if len(linha) > idx_cat and linha[idx_cat].strip():
                        cats_encontradas.add(linha[idx_cat].strip())
                return sorted(list(cats_encontradas))
        except Exception:
            pass
        return LISTA_CATEGORIAS_BASE

    lista_base_carregada = carregar_categorias_existentes()
    lista_categorias_atualizada = sorted(list(set(lista_base_carregada + st.session_state["categorias_extras"])))

    categoria_sugerida = "Outros"
    if descricao_gasto and descricao_gasto.strip():
        categoria_sugerida = classificar_categoria_groq(descricao_gasto, None, lista_categorias_atualizada)

    try:
        indice_padrao = lista_categorias_atualizada.index(categoria_sugerida)
    except ValueError:
        indice_padrao = 0

    # --- SEÇÃO DE CATEGORIA ---
    st.markdown("### 📂 Categoria do Gasto")
    col_cat_sel, col_nova_txt, col_btn_add = st.columns([2, 2, 1])

    with col_cat_sel:
        categoria_selecionada = st.selectbox("Selecione a Categoria", lista_categorias_atualizada, index=indice_padrao, key="select_categoria", label_visibility="collapsed")

    with col_nova_txt:
        nova_cat_input = st.text_input("Criar categoria nova", placeholder="Ex: Manutenção Carro", key="input_nova_categoria", label_visibility="collapsed")

    with col_btn_add:
        if st.button("➕ Adicionar", use_container_width=True, key="btn_add_cat"):
            cat_limpa = nova_cat_input.strip()
            if cat_limpa:
                if cat_limpa not in lista_categorias_atualizada:
                    st.session_state["categorias_extras"].append(cat_limpa)
                    st.success(f"Categoria '{cat_limpa}' adicionada!")
                    time.sleep(0.4)
                    st.rerun()
                else:
                    st.warning("Já existe.")
            else:
                st.warning("Digite algo.")

    categoria_final = categoria_selecionada

    col_forma, col_banco = st.columns(2)
    with col_forma:
        forma_pagamento = st.selectbox("Forma de Pagamento", ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro", "Boleto"], key="select_forma")
    with col_banco:
        banco_emissor = st.selectbox("Banco / Emissor", ["Nubank", "Mercado Pago", "Inter", "Banrisul", "Santander", "Banco do Brasil", "Itaú", "Caixa", "Bradesco", "Outro"], key="select_banco")

    col_parc_check, col_parc_num = st.columns(2)
    with col_parc_check:
        parcelado = st.checkbox("Gasto Parcelado?", key="check_parcelado")
    with col_parc_num:
        num_parcelas_str = st.text_input("Número de Parcelas", disabled=not parcelado, placeholder="Ex: 10", key="input_num_parcelas")

    # Botão principal com bloqueio ativo por session_state
    btn_enviar = st.button("🚀 Registrar Gasto", type="primary", use_container_width=True, disabled=st.session_state["processando_envio"])

    if btn_enviar:
        if not quem_gastou or quem_gastou == "Outro...":
            st.warning("Por favor, selecione ou digite o nome de quem está gastando.")
        elif not descricao_gasto or not descricao_gasto.strip() or not valor_texto or not valor_texto.strip():
            st.warning("Preencha a descrição e o valor.")
        else:
            st.session_state["processando_envio"] = True
            st.rerun()

    # Executa o salvamento apenas se a flag estiver ativa
    if st.session_state["processando_envio"]:
        try:
            v_limpo = valor_texto.strip().replace("R$", "").replace(" ", "")
            if "," in v_limpo and "." in v_limpo:
                v_limpo = v_limpo.replace(".", "").replace(",", ".")
            elif "," in v_limpo:
                v_limpo = v_limpo.replace(",", ".")

            valor_gasto = float(v_limpo)
            if valor_gasto <= 0:
                raise ValueError()
        except ValueError:
            st.error("Formato de valor inválido! Use números como 50 ou 1800,00")
            valor_gasto = 0.0
            st.session_state["processando_envio"] = False

        try:
            num_parcelas = int(num_parcelas_str) if parcelado and num_parcelas_str.strip() else 1
            if num_parcelas < 1:
                num_parcelas = 1
        except ValueError:
            num_parcelas = 1

        if valor_gasto > 0:
            with st.status("Processando lançamento...", expanded=True) as status:

                status.write("🔑 Lendo credenciais e autenticando no Google...")
                try:
                    client = get_gspread_client()
                    status.write("✅ Autenticação realizada com sucesso.")
                except Exception as e:
                    status.update(label="❌ Erro na Autenticação!", state="error")
                    st.error(f"Detalhe: {e}")
                    st.session_state["processando_envio"] = False
                    st.stop()

                status.write(f"📂 Conectando à planilha e buscando aba '{NOME_ABA}'...")
                try:
                    sh = client.open_by_key(SPREADSHEET_ID)
                    worksheet = sh.worksheet(NOME_ABA)
                    status.write("✅ Planilha e aba localizadas.")
                except Exception as e:
                    status.update(label="❌ Erro ao localizar a planilha/aba!", state="error")
                    st.error(f"Detalhe: {e}")
                    st.session_state["processando_envio"] = False
                    st.stop()

                status.write("🗓️ Mapeando e garantindo cabeçalhos exatos...")

                cabecalho_base = ["Data/Hora", "Quem Gastou", "Descrição", "Categoria", "Forma de Pagamento", "Valor"]

                cabecalho_atual = worksheet.row_values(1)

                meses_existentes = []
                if len(cabecalho_atual) > 6:
                    meses_existentes = [m for m in cabecalho_atual[6:] if m.strip()]

                cabecalho_final = cabecalho_base + [m for m in meses_existentes if m not in cabecalho_base]

                data_hoje = datetime.now() - timedelta(hours=3)
                detalhe_pagamento = f"{forma_pagamento} ({banco_emissor})"
                valor_parcela = round(valor_gasto / num_parcelas, 2) if parcelado and num_parcelas > 1 else valor_gasto

                parcelas_info = []
                for i in range(num_parcelas):
                    mes_alvo = data_hoje.month - 1 + i
                    ano_alvo = data_hoje.year + mes_alvo // 12
                    mes_alvo = mes_alvo % 12 + 1

                    data_vencimento = datetime(ano_alvo, mes_alvo, min(data_hoje.day, 28))
                    nome_mes_coluna = obter_nome_mes_ano(data_vencimento)

                    parcelas_info.append({
                        "mes_ano": nome_mes_coluna,
                        "valor": valor_parcela
                    })

                for p in parcelas_info:
                    mes_str = p["mes_ano"]
                    if mes_str not in cabecalho_final:
                        cabecalho_final.append(mes_str)

                def numero_para_coluna(num):
                    resultado = ""
                    while num > 0:
                        num, remainder = divmod(num - 1, 26)
                        resultado = chr(65 + remainder) + resultado
                    return resultado

                letra_ultima_coluna = numero_para_coluna(len(cabecalho_final))
                worksheet.update(f"A1:{letra_ultima_coluna}1", [cabecalho_final])

                linha_dados = [""] * len(cabecalho_final)

                linha_dados[cabecalho_final.index("Data/Hora")] = f"'{data_hoje.strftime('%d/%m/%Y %H:%M:%S')}"
                linha_dados[cabecalho_final.index("Quem Gastou")] = quem_gastou
                linha_dados[cabecalho_final.index("Descrição")] = descricao_gasto if not parcelado else f"{descricao_gasto} ({num_parcelas}x)"
                linha_dados[cabecalho_final.index("Categoria")] = categoria_final
                linha_dados[cabecalho_final.index("Forma de Pagamento")] = detalhe_pagamento
                linha_dados[cabecalho_final.index("Valor")] = float(valor_gasto)

                for p in parcelas_info:
                    mes_str = p["mes_ano"]
                    if mes_str in cabecalho_final:
                        idx_mes = cabecalho_final.index(mes_str)
                        linha_dados[idx_mes] = float(p["valor"])

                status.write("✍️ Gravando linha alinhada na planilha...")

                todas_linhas = worksheet.get_all_values()
                proxima_linha = len(todas_linhas) + 1

                intervalo = f"A{proxima_linha}:{letra_ultima_coluna}{proxima_linha}"

                worksheet.batch_clear([intervalo])
                worksheet.update(intervalo, [linha_dados], value_input_option='USER_ENTERED')

                status.update(label="🎉 Gasto registrado com sucesso!", state="complete", expanded=False)
                if parcelado:
                    st.success(f"✅ Gasto de R$ {valor_gasto:.2f} por **{quem_gastou}** na categoria **{categoria_final}** parcelado em {num_parcelas}x!")
                else:
                    st.success(f"✅ Gasto de R$ {valor_gasto:.2f} por **{quem_gastou}** registrado na categoria **{categoria_final}**!")

                time.sleep(2)
                st.session_state["form_limpo"] = True
                st.session_state["processando_envio"] = False
                st.rerun()

# ============================================================
# DASHBOARD (tudo novo a partir daqui)
# ============================================================
with tab_dashboard:
    st.markdown("### 📈 Visão Geral dos Gastos")

    @st.cache_data(ttl=120)
    def carregar_dados_planilha():
        try:
            client = get_gspread_client()
            sh = client.open_by_key(SPREADSHEET_ID)
            worksheet = sh.worksheet(NOME_ABA)
            valores = worksheet.get_all_values()
            if not valores or len(valores) < 2:
                return None, None
            cabecalho = valores[0]
            dados = valores[1:]
            return cabecalho, dados
        except Exception as e:
            st.error(f"Erro ao carregar dados: {e}")
            return None, None

    cabecalho, dados = carregar_dados_planilha()

    if cabecalho is None or dados is None:
        st.info("Nenhum dado encontrado na planilha ainda. Lance o primeiro gasto!")
    else:
        # Índices das colunas fixas
        try:
            idx_quem = cabecalho.index("Quem Gastou")
            idx_cat = cabecalho.index("Categoria")
            idx_valor = cabecalho.index("Valor")
        except ValueError:
            st.error("Cabeçalhos essenciais não encontrados na planilha.")
            st.stop()

        # Colunas de mês (tudo a partir da 7ª coluna)
        colunas_mes = cabecalho[6:] if len(cabecalho) > 6 else []

        data_hoje = datetime.now() - timedelta(hours=3)
        mes_atual_str = obter_nome_mes_ano(data_hoje)
        ano_atual = str(data_hoje.year)

        # =====================================================
        # 1. DADOS DO MÊS VIGENTE
        # =====================================================
        gastos_mes_categoria = {}
        gastos_mes_pessoa = {}
        total_mes = 0.0

        idx_mes_atual = None
        if mes_atual_str in cabecalho:
            idx_mes_atual = cabecalho.index(mes_atual_str)

        for linha in dados:
            if len(linha) <= max(idx_quem, idx_cat):
                continue

            pessoa = linha[idx_quem].strip() if linha[idx_quem] else "Outros"
            categoria = linha[idx_cat].strip() if linha[idx_cat] else "Outros"

            # Normaliza pessoa
            if pessoa not in LISTA_GASTADORES_BASE:
                pessoa = "Outros"

            valor_mes = 0.0
            if idx_mes_atual is not None and len(linha) > idx_mes_atual:
                try:
                    v = linha[idx_mes_atual].replace(",", ".").strip()
                    if v:
                        valor_mes = float(v)
                except:
                    pass

            if valor_mes > 0:
                gastos_mes_categoria[categoria] = gastos_mes_categoria.get(categoria, 0) + valor_mes
                gastos_mes_pessoa[pessoa] = gastos_mes_pessoa.get(pessoa, 0) + valor_mes
                total_mes += valor_mes

        # =====================================================
        # 2. DADOS DO ANO TODO
        # =====================================================
        gastos_ano_categoria = {}
        total_ano = 0.0

        for linha in dados:
            if len(linha) <= idx_cat:
                continue
            categoria = linha[idx_cat].strip() if linha[idx_cat] else "Outros"

            for i, col_nome in enumerate(colunas_mes):
                if col_nome.endswith(f"/{ano_atual}"):
                    idx = 6 + i
                    if len(linha) > idx:
                        try:
                            v = linha[idx].replace(",", ".").strip()
                            if v:
                                valor = float(v)
                                if valor > 0:
                                    gastos_ano_categoria[categoria] = gastos_ano_categoria.get(categoria, 0) + valor
                                    total_ano += valor
                        except:
                            pass

        # =====================================================
        # MÉTRICA TOTAL GERAL (topo)
        # =====================================================
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("💰 Total Mês Atual", f"R$ {total_mes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        with col2:
            st.metric("📅 Total Ano", f"R$ {total_ano:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        with col3:
            st.metric("📆 Mês de Referência", mes_atual_str)

        st.markdown("---")

        # =====================================================
        # GRÁFICO 1 – PIZZA DO MÊS POR CATEGORIA
        # =====================================================
        st.subheader(f"📊 Gastos por Categoria – {mes_atual_str}")

        if total_mes > 0:
            df_mes = pd.DataFrame({
                "Categoria": list(gastos_mes_categoria.keys()),
                "Valor": list(gastos_mes_categoria.values())
            }).sort_values("Valor", ascending=False)

            fig1 = px.pie(
                df_mes,
                values="Valor",
                names="Categoria",
                title=f"Total do mês: R$ {total_mes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                hole=0.35
            )
            fig1.update_traces(
                textposition="inside",
                textinfo="percent+label+value",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
                texttemplate="%{label}<br>%{percent}<br>R$ %{value:,.2f}"
            )
            fig1.update_layout(
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2),
                margin=dict(t=50, b=50, l=20, r=20),
                height=480
            )
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info(f"Nenhum gasto registrado em {mes_atual_str} ainda.")

        st.markdown("---")

        # =====================================================
        # GRÁFICO 2 – PIZZA POR PESSOA (MÊS ATUAL)
        # =====================================================
        st.subheader(f"👥 Gastos por Pessoa – {mes_atual_str}")

        if total_mes > 0:
            # Garante ordem e inclui quem não gastou
            pessoas_ordem = ["Willian", "Aline", "Bernardo", "Outros"]
            valores_pessoa = [gastos_mes_pessoa.get(p, 0) for p in pessoas_ordem]

            df_pessoa = pd.DataFrame({
                "Pessoa": pessoas_ordem,
                "Valor": valores_pessoa
            })
            df_pessoa = df_pessoa[df_pessoa["Valor"] > 0]  # só mostra quem gastou

            fig2 = px.pie(
                df_pessoa,
                values="Valor",
                names="Pessoa",
                title=f"Total do mês: R$ {total_mes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                hole=0.35,
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig2.update_traces(
                textposition="inside",
                textinfo="percent+label+value",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
                texttemplate="%{label}<br>%{percent}<br>R$ %{value:,.2f}"
            )
            fig2.update_layout(
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                margin=dict(t=50, b=50, l=20, r=20),
                height=450
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Nenhum gasto por pessoa neste mês.")

        st.markdown("---")

        # =====================================================
        # GRÁFICO 3 – PIZZA ANUAL POR CATEGORIA
        # =====================================================
        st.subheader(f"📅 Gastos Anuais por Categoria – {ano_atual}")

        if total_ano > 0:
            df_ano = pd.DataFrame({
                "Categoria": list(gastos_ano_categoria.keys()),
                "Valor": list(gastos_ano_categoria.values())
            }).sort_values("Valor", ascending=False)

            fig3 = px.pie(
                df_ano,
                values="Valor",
                names="Categoria",
                title=f"Total do ano: R$ {total_ano:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                hole=0.35
            )
            fig3.update_traces(
                textposition="inside",
                textinfo="percent+label+value",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
                texttemplate="%{label}<br>%{percent}<br>R$ %{value:,.2f}"
            )
            fig3.update_layout(
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25),
                margin=dict(t=50, b=80, l=20, r=20),
                height=520
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info(f"Nenhum gasto registrado em {ano_atual} ainda.")

        # =====================================================
        # TABELA RESUMO (opcional, mas útil)
        # =====================================================
        with st.expander("📋 Ver tabela detalhada do mês"):
            if total_mes > 0:
                df_resumo = pd.DataFrame({
                    "Categoria": list(gastos_mes_categoria.keys()),
                    "Valor (R$)": [round(v, 2) for v in gastos_mes_categoria.values()],
                    "%": [round(v / total_mes * 100, 1) for v in gastos_mes_categoria.values()]
                }).sort_values("Valor (R$)", ascending=False)
                st.dataframe(df_resumo, use_container_width=True, hide_index=True)
            else:
                st.write("Sem dados.")
