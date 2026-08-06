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

LISTA_GASTADORES_BASE = ["Willian", "Aline", "Bernardo", "Willian-ALine","Willian-Bernardo", "Aline-Bernardo", "Aline-Willian-Bernardo" ]

CABECALHO_BASE = [
    "Data/Hora",
    "Quem Gastou",
    "Local",
    "Descrição",
    "Categoria",
    "Forma de Pagamento",
    "Valor",
]

# Inicialização de estados
if "gastadores_extras" not in st.session_state:
    st.session_state["gastadores_extras"] = []

if "categorias_extras" not in st.session_state:
    st.session_state["categorias_extras"] = []

if "locais_extras" not in st.session_state:
    st.session_state["locais_extras"] = []

if "form_limpo" not in st.session_state:
    st.session_state["form_limpo"] = False

if "processando_envio" not in st.session_state:
    st.session_state["processando_envio"] = False

# Limpeza de campos se acionada
if st.session_state["form_limpo"]:
    st.session_state["input_local_novo"] = ""
    st.session_state["input_descricao"] = ""
    st.session_state["input_valor"] = ""
    st.session_state["check_parcelado"] = False
    st.session_state["input_num_parcelas"] = ""
    st.session_state["form_limpo"] = False

def garantir_coluna_local(worksheet):
    """
    Garante que a coluna fixa "Local" exista exatamente na coluna C.
    A migração usa insert_cols para deslocar Descrição, Categoria e meses
    sem sobrescrever nenhum dado já existente.
    """
    cabecalho = worksheet.row_values(1)

    if not cabecalho:
        worksheet.update("A1:G1", [CABECALHO_BASE])
        return CABECALHO_BASE.copy()

    if "Local" not in cabecalho:
        worksheet.insert_cols([["Local"]], col=3, value_input_option="USER_ENTERED")
        cabecalho = worksheet.row_values(1)

    # Corrige apenas o nome dos sete cabeçalhos fixos, preservando os dados
    # e todas as colunas mensais que já estiverem depois deles.
    for indice, nome_esperado in enumerate(CABECALHO_BASE, start=1):
        valor_atual = cabecalho[indice - 1].strip() if len(cabecalho) >= indice else ""
        if valor_atual != nome_esperado:
            worksheet.update_cell(1, indice, nome_esperado)

    return worksheet.row_values(1)


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
            st.markdown("<div style='display: flex; align-items: center; height: 38px;'><small style='color:#888'>Membro cadastrado selecionado</small></div>", unsafe_allow_html=True)

    st.markdown("---")

    # --- CONEXÃO PARA BUSCAR LOCAIS JÁ UTILIZADOS NA PLANILHA ---
    @st.cache_data(ttl=60)
    def carregar_locais_existentes():
        try:
            client = get_gspread_client()
            sh = client.open_by_key(SPREADSHEET_ID)
            worksheet = sh.worksheet(NOME_ABA)
            cabecalho = garantir_coluna_local(worksheet)

            idx_local = cabecalho.index("Local")
            valores = worksheet.get_all_values()
            locais_encontrados = set()

            for linha in valores[1:]:
                if len(linha) > idx_local and linha[idx_local].strip():
                    locais_encontrados.add(linha[idx_local].strip())

            return sorted(locais_encontrados)
        except Exception:
            return []

    lista_locais_atualizada = sorted(
        list(
            set(
                carregar_locais_existentes()
                + st.session_state["locais_extras"]
            )
        )
    )

    opcoes_local = lista_locais_atualizada or ["Selecione ou adicione um local"]

    # --- SEÇÃO DE LOCAL DO GASTO ---
    st.markdown("### 🗺️ Local do Gasto")
    col_local_sel, col_local_txt, col_local_add = st.columns([2, 2, 1])

    with col_local_sel:
        st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #555;'>Selecione o Local</div>", unsafe_allow_html=True)
        local_selecionado = st.selectbox(
            "Selecione o Local",
            opcoes_local,
            key="select_local",
            label_visibility="collapsed",
        )

    with col_local_txt:
        st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #555;'>Digite o novo local</div>", unsafe_allow_html=True)
        novo_local_input = st.text_input(
            "Criar local novo",
            placeholder="Ex: Mercado Livre",
            key="input_local_novo",
            label_visibility="collapsed",
        )

    with col_local_add:
        st.markdown("<div style='height: 22px;'></div>", unsafe_allow_html=True) # Espaçamento para alinhar com os inputs
        if st.button("➕ Add Local", use_container_width=True, key="btn_add_local"):
            local_limpo = novo_local_input.strip()
            if local_limpo:
                if local_limpo not in lista_locais_atualizada:
                    st.session_state["locais_extras"].append(local_limpo)
                    carregar_locais_existentes.clear()
                    st.success(f"Local '{local_limpo}' adicionado!")
                    time.sleep(0.4)
                    st.rerun()
                else:
                    st.warning("Já existe.")
            else:
                st.warning("Digite algo.")

    local_final = (
        local_selecionado
        if local_selecionado != "Selecione ou adicione um local"
        else ""
    )

    descricao_gasto = st.text_input("Descrição do Gasto", placeholder="Ex: Meta Quest 3s", key="input_descricao")
    
    st.markdown('<p style="font-weight: 600; color: #d9534f; margin-bottom: -10px;">Valor Total (R$)</p>', unsafe_allow_html=True)
    valor_texto = st.text_input("Valor Total (R$)", placeholder="Ex: 50, 50,00 ou 1800,00", key="input_valor", label_visibility="collapsed")

    # --- CONEXÃO PARA BUSCAR CATEGORIAS JÁ UTILIZADAS NA PLANILHA ---
    @st.cache_data(ttl=60)
    def carregar_categorias_existentes():
        try:
            client = get_gspread_client()
            sh = client.open_by_key(SPREADSHEET_ID)
            worksheet = sh.worksheet(NOME_ABA)

            cabecalho = garantir_coluna_local(worksheet)
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
        st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #555;'>Selecione a Categoria</div>", unsafe_allow_html=True)
        categoria_selecionada = st.selectbox("Selecione a Categoria", lista_categorias_atualizada, index=indice_padrao, key="select_categoria", label_visibility="collapsed")

    with col_nova_txt:
        st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #555;'>Digite a nova categoria</div>", unsafe_allow_html=True)
        nova_cat_input = st.text_input("Criar categoria nova", placeholder="Ex: Manutenção Carro", key="input_nova_categoria", label_visibility="collapsed")

    with col_btn_add:
        st.markdown("<div style='height: 22px;'></div>", unsafe_allow_html=True) # Espaçamento para alinhar com os inputs
        if st.button("➕ Add Categoria", use_container_width=True, key="btn_add_cat"):
            cat_limpa = nova_cat_input.strip()
            if cat_limpa:
                if cat_limpa not in lista_categorias_atualizada:
                    st.session_state["categorias_extras"].append(cat_limpa)
                    carregar_categorias_existentes.clear()
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
        elif not local_final:
            st.warning("Selecione ou adicione o local do gasto.")
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

                cabecalho_atual = garantir_coluna_local(worksheet)

                meses_existentes = [
                    coluna
                    for coluna in cabecalho_atual
                    if coluna.strip() and coluna not in CABECALHO_BASE
                ]

                cabecalho_final = CABECALHO_BASE + meses_existentes

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
                linha_dados[cabecalho_final.index("Local")] = local_final
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
                    st.success(f"✅ Gasto de R$ {valor_gasto:.2f} por **{quem_gastou}**, em **{local_final}**, na categoria **{categoria_final}**, parcelado em {num_parcelas}x!")
                else:
                    st.success(f"✅ Gasto de R$ {valor_gasto:.2f} por **{quem_gastou}**, em **{local_final}**, registrado na categoria **{categoria_final}**!")

                time.sleep(2)
                st.cache_data.clear()
                st.session_state["form_limpo"] = True
                st.session_state["processando_envio"] = False
                st.rerun()

# ============================================================
# DASHBOARD
# ============================================================

with tab_dashboard:
    st.markdown("### 📈 Visão Geral dos Gastos")

    @st.cache_data(ttl=120)
    def carregar_dados_planilha():
        try:
            client = get_gspread_client()
            sh = client.open_by_key(SPREADSHEET_ID)
            worksheet = sh.worksheet(NOME_ABA)
            garantir_coluna_local(worksheet)
            valores = worksheet.get_all_values()

            if not valores or len(valores) < 2:
                return pd.DataFrame()

            cabecalho = valores[0]
            dados = valores[1:]

            dados_normalizados = [
                linha + [""] * (len(cabecalho) - len(linha))
                for linha in dados
            ]

            return pd.DataFrame(dados_normalizados, columns=cabecalho)

        except Exception as e:
            st.error(f"Erro ao carregar dados: {e}")
            return pd.DataFrame()

    def converter_valor_planilha(valor):
        if valor is None:
            return 0.0

        if isinstance(valor, (int, float)):
            return float(valor)

        texto = str(valor).strip()

        if not texto:
            return 0.0

        texto = (
            texto.replace("R$", "")
            .replace("\xa0", "")
            .replace(" ", "")
        )

        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")

        try:
            return float(texto)
        except (TypeError, ValueError):
            return 0.0

    def formatar_moeda(valor):
        return (
            f"R$ {float(valor):,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    df_original = carregar_dados_planilha()

    if df_original.empty:
        st.info("Nenhum dado encontrado na planilha ainda. Lance o primeiro gasto!")
    else:
        colunas_obrigatorias = [
            "Data/Hora",
            "Quem Gastou",
            "Local",
            "Descrição",
            "Categoria",
            "Forma de Pagamento",
            "Valor",
        ]

        colunas_faltantes = [
            coluna for coluna in colunas_obrigatorias
            if coluna not in df_original.columns
        ]

        if colunas_faltantes:
            st.error(
                "Cabeçalhos essenciais não encontrados: "
                + ", ".join(colunas_faltantes)
            )
            st.stop()

        colunas_mes = [col for col in df_original.columns if col not in CABECALHO_BASE]

        df_compras = df_original.copy()
        df_compras["Valor Compra"] = df_compras["Valor"].apply(
            converter_valor_planilha
        )
        df_compras["Pessoa"] = (
            df_compras["Quem Gastou"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Outros")
        )
        df_compras["Local Tratado"] = (
            df_compras["Local"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Não informado")
        )
        df_compras["Categoria Tratada"] = (
            df_compras["Categoria"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "Outros")
        )

        registros_fluxo = []

        for _, linha in df_original.iterrows():
            pessoa = str(linha.get("Quem Gastou", "")).strip() or "Outros"
            local = str(linha.get("Local", "")).strip() or "Não informado"
            categoria = str(linha.get("Categoria", "")).strip() or "Outros"
            descricao = str(linha.get("Descrição", "")).strip() or "Sem descrição"
            forma_pagamento = (
                str(linha.get("Forma de Pagamento", "")).strip()
                or "Não informado"
            )

            for nome_mes in colunas_mes:
                valor_mes = converter_valor_planilha(linha.get(nome_mes, ""))

                if valor_mes <= 0:
                    continue

                try:
                    mes_texto, ano_texto = nome_mes.split("/")
                    data_competencia = datetime.strptime(
                        f"01/{mes_texto}/{ano_texto}",
                        "%d/%B/%Y",
                    )
                except Exception:
                    meses_pt_numero = {
                        "Janeiro": 1,
                        "Fevereiro": 2,
                        "Março": 3,
                        "Abril": 4,
                        "Maio": 5,
                        "Junho": 6,
                        "Julho": 7,
                        "Agosto": 8,
                        "Setembro": 9,
                        "Outubro": 10,
                        "Novembro": 11,
                        "Dezembro": 12,
                    }

                    try:
                        mes_texto, ano_texto = nome_mes.split("/")
                        numero_mes = meses_pt_numero[mes_texto]
                        data_competencia = datetime(
                            int(ano_texto),
                            numero_mes,
                            1,
                        )
                    except Exception:
                        continue

                registros_fluxo.append(
                    {
                        "Competência": pd.Timestamp(data_competencia),
                        "Mês/Ano": nome_mes,
                        "Ano": data_competencia.year,
                        "Mês Número": data_competencia.month,
                        "Pessoa": pessoa,
                        "Local": local,
                        "Categoria": categoria,
                        "Descrição": descricao,
                        "Forma de Pagamento": forma_pagamento,
                        "Valor Desembolsado": valor_mes,
                    }
                )

        df_fluxo = pd.DataFrame(registros_fluxo)

        if df_fluxo.empty:
            st.warning(
                "Não foram encontrados valores válidos nas colunas mensais."
            )
            st.stop()

        data_hoje = datetime.now() - timedelta(hours=3)
        ano_atual = data_hoje.year

        meses_ordem = {
            1: "Janeiro",
            2: "Fevereiro",
            3: "Março",
            4: "Abril",
            5: "Maio",
            6: "Junho",
            7: "Julho",
            8: "Agosto",
            9: "Setembro",
            10: "Outubro",
            11: "Novembro",
            12: "Dezembro",
        }

        anos_disponiveis = sorted(
            df_fluxo["Ano"].dropna().astype(int).unique().tolist(),
            reverse=True,
        )

        if ano_atual not in anos_disponiveis:
            anos_disponiveis.insert(0, ano_atual)

        with st.expander("🔎 Filtros do Dashboard", expanded=False):
            ano_selecionado = st.selectbox(
                "Ano",
                anos_disponiveis,
                index=anos_disponiveis.index(ano_atual)
                if ano_atual in anos_disponiveis
                else 0,
                key="dashboard_ano",
            )

            meses_disponiveis_num = sorted(
                df_fluxo.loc[
                    df_fluxo["Ano"] == ano_selecionado,
                    "Mês Número",
                ]
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )

            mes_atual_num = data_hoje.month

            if mes_atual_num not in meses_disponiveis_num:
                meses_disponiveis_num.append(mes_atual_num)
                meses_disponiveis_num = sorted(
                    set(meses_disponiveis_num)
                )

            nomes_meses_disponiveis = [
                meses_ordem[numero]
                for numero in meses_disponiveis_num
            ]

            indice_mes_padrao = (
                meses_disponiveis_num.index(mes_atual_num)
                if mes_atual_num in meses_disponiveis_num
                else 0
            )

            mes_nome_selecionado = st.selectbox(
                "Mês",
                nomes_meses_disponiveis,
                index=indice_mes_padrao,
                key="dashboard_mes",
            )

            pessoas_disponiveis = sorted(
                df_fluxo["Pessoa"].dropna().astype(str).unique().tolist()
            )
            categorias_disponiveis = sorted(
                df_fluxo["Categoria"].dropna().astype(str).unique().tolist()
            )
            locais_disponiveis = sorted(
                df_fluxo["Local"].dropna().astype(str).unique().tolist()
            )

            pessoa_selecionada = st.selectbox(
                "Pessoa",
                ["Todas"] + pessoas_disponiveis,
                key="dashboard_pessoa",
            )

            categoria_selecionada = st.selectbox(
                "Categoria",
                ["Todas"] + categorias_disponiveis,
                key="dashboard_categoria",
            )

            local_selecionado_dashboard = st.selectbox(
                "Local",
                ["Todos"] + locais_disponiveis,
                key="dashboard_local",
            )

        numero_mes_selecionado = next(
            numero
            for numero, nome in meses_ordem.items()
            if nome == mes_nome_selecionado
        )

        df_filtrado = df_fluxo.copy()

        if pessoa_selecionada != "Todas":
            df_filtrado = df_filtrado[
                df_filtrado["Pessoa"] == pessoa_selecionada
            ]

        if categoria_selecionada != "Todas":
            df_filtrado = df_filtrado[
                df_filtrado["Categoria"] == categoria_selecionada
            ]

        if local_selecionado_dashboard != "Todos":
            df_filtrado = df_filtrado[
                df_filtrado["Local"] == local_selecionado_dashboard
            ]

        df_mes = df_filtrado[
            (df_filtrado["Ano"] == ano_selecionado)
            & (df_filtrado["Mês Número"] == numero_mes_selecionado)
        ].copy()

        df_ano = df_filtrado[
            df_filtrado["Ano"] == ano_selecionado
        ].copy()

        total_mes = df_mes["Valor Desembolsado"].sum()
        total_ano = df_ano["Valor Desembolsado"].sum()

        resumo_mes_categoria = (
            df_mes.groupby("Categoria", as_index=False)["Valor Desembolsado"]
            .sum()
            .sort_values("Valor Desembolsado", ascending=False)
        )

        resumo_mes_pessoa = (
            df_mes.groupby("Pessoa", as_index=False)["Valor Desembolsado"]
            .sum()
            .sort_values("Valor Desembolsado", ascending=False)
        )

        resumo_mes_local = (
            df_mes.groupby(["Categoria", "Local"], as_index=False)["Valor Desembolsado"]
            .sum()
            .sort_values("Valor Desembolsado", ascending=False)
        )

        resumo_ano_local = (
            df_ano.groupby(["Categoria", "Local"], as_index=False)["Valor Desembolsado"]
            .sum()
            .sort_values("Valor Desembolsado", ascending=False)
        )

        resumo_ano_categoria = (
            df_ano.groupby("Categoria", as_index=False)["Valor Desembolsado"]
            .sum()
            .sort_values("Valor Desembolsado", ascending=False)
        )
