import re
from datetime import datetime, timedelta

import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials


SPREADSHEET_ID = "1eFK9CtarQoKqpZBBoptltnNS-cWU92pw2K7oEAXyI7k"
NOME_ABA = "Controle de Gastos"

MESES_PT = {
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

MESES_NUMERO_PARA_NOME = {numero: nome for nome, numero in MESES_PT.items()}


def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def formatar_moeda(valor):
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        valor = 0.0

    return (
        f"R$ {valor:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def converter_valor(valor):
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

    # Formato brasileiro: 1.234,56
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except (TypeError, ValueError):
        return 0.0


def converter_data_hora(valor):
    if valor is None:
        return pd.NaT

    texto = str(valor).strip().lstrip("'")

    if not texto:
        return pd.NaT

    return pd.to_datetime(
        texto,
        format="%d/%m/%Y %H:%M:%S",
        errors="coerce",
    )


def identificar_coluna_mes(nome_coluna):
    texto = str(nome_coluna).strip()
    resultado = re.fullmatch(
        r"(Janeiro|Fevereiro|Março|Abril|Maio|Junho|Julho|Agosto|Setembro|Outubro|Novembro|Dezembro)/(\d{4})",
        texto,
    )

    if resultado is None:
        return None

    nome_mes, ano = resultado.groups()

    return {
        "nome_coluna": texto,
        "mes": MESES_PT[nome_mes],
        "nome_mes": nome_mes,
        "ano": int(ano),
        "competencia": pd.Timestamp(
            year=int(ano),
            month=MESES_PT[nome_mes],
            day=1,
        ),
    }


@st.cache_data(ttl=120, show_spinner=False)
def carregar_planilha():
    client = get_gspread_client()
    planilha = client.open_by_key(SPREADSHEET_ID)
    worksheet = planilha.worksheet(NOME_ABA)

    valores = worksheet.get_all_values()

    if not valores:
        return pd.DataFrame()

    cabecalho = valores[0]
    linhas = valores[1:]

    # Garante que todas as linhas tenham o mesmo número de colunas.
    linhas_normalizadas = [
        linha + [""] * (len(cabecalho) - len(linha))
        for linha in linhas
    ]

    return pd.DataFrame(linhas_normalizadas, columns=cabecalho)


def preparar_base_compras(df_original):
    colunas_obrigatorias = [
        "Data/Hora",
        "Quem Gastou",
        "Descrição",
        "Categoria",
        "Forma de Pagamento",
        "Valor",
    ]

    faltantes = [
        coluna
        for coluna in colunas_obrigatorias
        if coluna not in df_original.columns
    ]

    if faltantes:
        raise ValueError(
            "A planilha não possui as seguintes colunas obrigatórias: "
            + ", ".join(faltantes)
        )

    df = df_original.copy()

    df["Data Compra"] = df["Data/Hora"].apply(converter_data_hora)
    df["Valor Compra"] = df["Valor"].apply(converter_valor)

    df["Pessoa"] = (
        df["Quem Gastou"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Outros")
    )

    df["Categoria Tratada"] = (
        df["Categoria"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Outros")
    )

    df["Descrição Tratada"] = (
        df["Descrição"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Sem descrição")
    )

    df["Forma Pagamento Tratada"] = (
        df["Forma de Pagamento"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Não informado")
    )

    return df


def preparar_base_fluxo(df_compras):
    colunas_mes = []

    for coluna in df_compras.columns:
        identificacao = identificar_coluna_mes(coluna)

        if identificacao is not None:
            colunas_mes.append(identificacao)

    registros = []

    hoje = pd.Timestamp(
        (datetime.now() - timedelta(hours=3)).date()
    )
    competencia_atual = hoje.replace(day=1)

    for _, linha in df_compras.iterrows():
        for coluna_mes in colunas_mes:
            valor_pago = converter_valor(
                linha.get(coluna_mes["nome_coluna"], "")
            )

            if valor_pago <= 0:
                continue

            competencia = coluna_mes["competencia"]

            if competencia < competencia_atual:
                situacao = "Passado"
            elif competencia == competencia_atual:
                situacao = "Mês atual"
            else:
                situacao = "Futuro"

            registros.append(
                {
                    "Data Compra": linha["Data Compra"],
                    "Pessoa": linha["Pessoa"],
                    "Descrição": linha["Descrição Tratada"],
                    "Categoria": linha["Categoria Tratada"],
                    "Forma de Pagamento": linha[
                        "Forma Pagamento Tratada"
                    ],
                    "Valor Compra": linha["Valor Compra"],
                    "Competência": competencia,
                    "Ano": coluna_mes["ano"],
                    "Mês Número": coluna_mes["mes"],
                    "Mês": coluna_mes["nome_mes"],
                    "Mês/Ano": coluna_mes["nome_coluna"],
                    "Valor Desembolsado": valor_pago,
                    "Situação": situacao,
                }
            )

    if not registros:
        return pd.DataFrame(
            columns=[
                "Data Compra",
                "Pessoa",
                "Descrição",
                "Categoria",
                "Forma de Pagamento",
                "Valor Compra",
                "Competência",
                "Ano",
                "Mês Número",
                "Mês",
                "Mês/Ano",
                "Valor Desembolsado",
                "Situação",
            ]
        )

    return pd.DataFrame(registros)


def criar_grafico_rosca(df, coluna_nome, titulo):
    resumo = (
        df.groupby(coluna_nome, as_index=False)["Valor Desembolsado"]
        .sum()
        .sort_values("Valor Desembolsado", ascending=False)
    )

    total = resumo["Valor Desembolsado"].sum()

    fig = px.pie(
        resumo,
        values="Valor Desembolsado",
        names=coluna_nome,
        hole=0.38,
    )

    fig.update_traces(
        textposition="inside",
        texttemplate=(
            "%{label}<br>"
            "%{percent}<br>"
            "R$ %{value:,.2f}"
        ),
        hovertemplate=(
            "<b>%{label}</b><br>"
            "Valor: R$ %{value:,.2f}<br>"
            "Percentual: %{percent}"
            "<extra></extra>"
        ),
    )

    fig.update_layout(
        title={
            "text": f"{titulo}<br><sup>Total: {formatar_moeda(total)}</sup>",
            "x": 0.5,
            "xanchor": "center",
        },
        legend_title_text="",
        height=510,
        margin=dict(l=20, r=20, t=90, b=60),
    )

    return fig


def criar_grafico_evolucao(df_ano):
    resumo = (
        df_ano.groupby(
            ["Mês Número", "Mês"],
            as_index=False,
        )["Valor Desembolsado"]
        .sum()
        .sort_values("Mês Número")
    )

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=resumo["Mês"],
            y=resumo["Valor Desembolsado"],
            text=[
                formatar_moeda(valor)
                for valor in resumo["Valor Desembolsado"]
            ],
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Desembolso: R$ %{y:,.2f}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title="Evolução mensal dos desembolsos",
        xaxis_title="Mês",
        yaxis_title="Valor desembolsado",
        height=460,
        margin=dict(l=20, r=20, t=60, b=40),
    )

    return fig


def mostrar_dashboard():
    st.markdown("## 📊 Dashboard Financeiro Familiar")

    col_atualizar, col_info = st.columns([1, 3])

    with col_atualizar:
        if st.button(
            "🔄 Atualizar dados",
            use_container_width=True,
        ):
            carregar_planilha.clear()
            st.rerun()

    with col_info:
        st.caption(
            "Os indicadores mensais usam as colunas de parcelas da planilha, "
            "portanto mostram o valor realmente desembolsado em cada mês."
        )

    try:
        df_original = carregar_planilha()
    except Exception as erro:
        st.error("Não foi possível carregar a planilha.")
        st.exception(erro)
        return

    if df_original.empty:
        st.info("A planilha ainda não possui lançamentos.")
        return

    try:
        df_compras = preparar_base_compras(df_original)
        df_fluxo = preparar_base_fluxo(df_compras)
    except Exception as erro:
        st.error("Não foi possível preparar os dados financeiros.")
        st.exception(erro)
        return

    if df_fluxo.empty:
        st.warning(
            "Não foram encontrados valores nas colunas mensais da planilha."
        )
        return

    agora = datetime.now() - timedelta(hours=3)
    ano_atual = agora.year
    mes_atual = agora.month
    competencia_atual = pd.Timestamp(
        year=ano_atual,
        month=mes_atual,
        day=1,
    )

    anos_disponiveis = sorted(
        df_fluxo["Ano"].dropna().astype(int).unique().tolist(),
        reverse=True,
    )

    ano_padrao = (
        ano_atual
        if ano_atual in anos_disponiveis
        else anos_disponiveis[0]
    )

    st.markdown("### Filtros")

    filtro_ano, filtro_mes, filtro_pessoa, filtro_categoria = st.columns(4)

    with filtro_ano:
        ano_selecionado = st.selectbox(
            "Ano",
            anos_disponiveis,
            index=anos_disponiveis.index(ano_padrao),
        )

    meses_do_ano = (
        df_fluxo.loc[
            df_fluxo["Ano"] == ano_selecionado,
            ["Mês Número", "Mês"],
        ]
        .drop_duplicates()
        .sort_values("Mês Número")
    )

    opcoes_mes = ["Todos"] + meses_do_ano["Mês"].tolist()

    mes_padrao = (
        MESES_NUMERO_PARA_NOME[mes_atual]
        if (
            ano_selecionado == ano_atual
            and MESES_NUMERO_PARA_NOME[mes_atual] in opcoes_mes
        )
        else "Todos"
    )

    with filtro_mes:
        mes_selecionado = st.selectbox(
            "Mês",
            opcoes_mes,
            index=opcoes_mes.index(mes_padrao),
        )

    pessoas_disponiveis = sorted(
        df_fluxo["Pessoa"].dropna().unique().tolist()
    )

    with filtro_pessoa:
        pessoa_selecionada = st.selectbox(
            "Pessoa",
            ["Todos"] + pessoas_disponiveis,
        )

    categorias_disponiveis = sorted(
        df_fluxo["Categoria"].dropna().unique().tolist()
    )

    with filtro_categoria:
        categoria_selecionada = st.selectbox(
            "Categoria",
            ["Todas"] + categorias_disponiveis,
        )

    df_filtrado = df_fluxo[
        df_fluxo["Ano"] == ano_selecionado
    ].copy()

    if mes_selecionado != "Todos":
        df_filtrado = df_filtrado[
            df_filtrado["Mês"] == mes_selecionado
        ]

    if pessoa_selecionada != "Todos":
        df_filtrado = df_filtrado[
            df_filtrado["Pessoa"] == pessoa_selecionada
        ]

    if categoria_selecionada != "Todas":
        df_filtrado = df_filtrado[
            df_filtrado["Categoria"] == categoria_selecionada
        ]

    df_mes_atual = df_fluxo[
        df_fluxo["Competência"] == competencia_atual
    ]

    df_ano_atual = df_fluxo[
        df_fluxo["Ano"] == ano_atual
    ]

    df_futuro = df_fluxo[
        df_fluxo["Competência"] > competencia_atual
    ]

    desembolso_mes = df_mes_atual["Valor Desembolsado"].sum()
    desembolso_ano = df_ano_atual["Valor Desembolsado"].sum()
    parcelas_futuras = df_futuro["Valor Desembolsado"].sum()

    compras_mes = df_compras[
        (df_compras["Data Compra"].dt.year == ano_atual)
        & (df_compras["Data Compra"].dt.month == mes_atual)
    ]["Valor Compra"].sum()

    meses_com_gasto_ano = (
        df_ano_atual.loc[
            df_ano_atual["Valor Desembolsado"] > 0,
            "Mês Número",
        ]
        .nunique()
    )

    media_mensal = (
        desembolso_ano / meses_com_gasto_ano
        if meses_com_gasto_ano > 0
        else 0.0
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Desembolso no mês",
        formatar_moeda(desembolso_mes),
    )

    col2.metric(
        "Compras no mês",
        formatar_moeda(compras_mes),
    )

    col3.metric(
        "Desembolso no ano",
        formatar_moeda(desembolso_ano),
    )

    col4.metric(
        "Parcelas futuras",
        formatar_moeda(parcelas_futuras),
    )

    st.caption(
        f"Média mensal de desembolso em {ano_atual}: "
        f"{formatar_moeda(media_mensal)}"
    )

    st.markdown("---")

    if df_filtrado.empty:
        st.info(
            "Nenhum lançamento corresponde aos filtros selecionados."
        )
        return

    grafico_categoria = criar_grafico_rosca(
        df_filtrado,
        "Categoria",
        "Desembolso por categoria",
    )

    grafico_pessoa = criar_grafico_rosca(
        df_filtrado,
        "Pessoa",
        "Desembolso por pessoa",
    )

    st.plotly_chart(
        grafico_categoria,
        use_container_width=True,
    )

    st.plotly_chart(
        grafico_pessoa,
        use_container_width=True,
    )

    st.markdown("---")

    df_ano_selecionado = df_fluxo[
        df_fluxo["Ano"] == ano_selecionado
    ]

    grafico_anual_categoria = criar_grafico_rosca(
        df_ano_selecionado,
        "Categoria",
        f"Categorias no ano de {ano_selecionado}",
    )

    st.plotly_chart(
        grafico_anual_categoria,
        use_container_width=True,
    )

    grafico_evolucao = criar_grafico_evolucao(
        df_ano_selecionado
    )

    st.plotly_chart(
        grafico_evolucao,
        use_container_width=True,
    )

    st.markdown("---")
    st.markdown("### 📅 Compromissos futuros")

    resumo_futuro = (
        df_futuro.groupby(
            ["Competência", "Mês/Ano"],
            as_index=False,
        )["Valor Desembolsado"]
        .sum()
        .sort_values("Competência")
    )

    if resumo_futuro.empty:
        st.success("Não existem parcelas futuras registradas.")
    else:
        resumo_futuro["Valor"] = resumo_futuro[
            "Valor Desembolsado"
        ].apply(formatar_moeda)

        st.dataframe(
            resumo_futuro[
                ["Mês/Ano", "Valor"]
            ].rename(
                columns={
                    "Mês/Ano": "Competência",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")
    st.markdown("### 🏆 Resumo estratégico")

    resumo_categoria = (
        df_filtrado.groupby(
            "Categoria",
            as_index=False,
        )["Valor Desembolsado"]
        .sum()
        .sort_values(
            "Valor Desembolsado",
            ascending=False,
        )
    )

    resumo_pessoa = (
        df_filtrado.groupby(
            "Pessoa",
            as_index=False,
        )["Valor Desembolsado"]
        .sum()
        .sort_values(
            "Valor Desembolsado",
            ascending=False,
        )
    )

    col_resumo1, col_resumo2 = st.columns(2)

    with col_resumo1:
        if not resumo_categoria.empty:
            maior_categoria = resumo_categoria.iloc[0]
            st.metric(
                "Maior categoria no filtro",
                maior_categoria["Categoria"],
                formatar_moeda(
                    maior_categoria["Valor Desembolsado"]
                ),
            )

    with col_resumo2:
        if not resumo_pessoa.empty:
            maior_pessoa = resumo_pessoa.iloc[0]
            st.metric(
                "Maior gastador no filtro",
                maior_pessoa["Pessoa"],
                formatar_moeda(
                    maior_pessoa["Valor Desembolsado"]
                ),
            )

    with st.expander("Ver lançamentos detalhados"):
        detalhado = df_filtrado[
            [
                "Mês/Ano",
                "Pessoa",
                "Descrição",
                "Categoria",
                "Forma de Pagamento",
                "Valor Desembolsado",
            ]
        ].copy()

        detalhado["Valor Desembolsado"] = detalhado[
            "Valor Desembolsado"
        ].apply(formatar_moeda)

        st.dataframe(
            detalhado.rename(
                columns={
                    "Mês/Ano": "Competência",
                    "Valor Desembolsado": "Valor",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
