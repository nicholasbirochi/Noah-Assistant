import json

import pytest

import config
from sites.application_profile import (
    ensure_profile_template,
    load_application_profile,
    load_referral_contacts,
    profile_path,
    referral_contacts_path,
)


def test_profile_path_lives_under_local_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert profile_path() == tmp_path / "application_profile.env"


@pytest.mark.parametrize("current,expected", [(None, None), ("new", "new"), ("", None)])
def test_profile_reads_noah_values(monkeypatch, tmp_path, current, expected):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    lines = []
    if current is not None:
        lines.append(f"NOAH_APPLICATION_EXCEL_NIVEL={current}")
    profile_path().write_text("\n".join(lines), encoding="utf-8")

    assert load_application_profile()["excel_nivel"] == expected


def test_load_application_profile_returns_all_none_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    profile = load_application_profile()

    assert profile == {
        "rg": None,
        "rg_orgao_estado": None,
        "cpf": None,
        "nome_mae": None,
        "nome_pai": None,
        "naturalidade": None,
        "raca_cor": None,
        "pcd": None,
        "salary_estagio": None,
        "salary_junior": None,
        "salary_pleno": None,
        "salary_current": None,
        "marital_status": None,
        "cargo_atual": None,
        "parentes_na_empresa": None,
        "semestre_formatura": None,
        "cnh": None,
        "cnh_categoria": None,
        "disponibilidade_viagem": None,
        "disponibilidade_fds": None,
        "disponibilidade_hibrido": None,
        "escolaridade": None,
        "altura": None,
        "tamanho_uniforme": None,
        "excel_nivel": None,
        "sql_nivel": None,
        "powerbi_nivel": None,
        "disponibilidade_estagio_09_16": None,
        "estatistica_matematica_financeira": None,
        "call_center_experiencia": None,
        "power_query_dax": None,
        "power_automate_nivel": None,
        "google_sheets_nivel": None,
        "ia_experiencia": None,
        "susep_conhecimento": None,
        "txt_csv_conhecimento": None,
        "kpis_comerciais_experiencia": None,
        "indicadores_experiencia": None,
        "projeto_automacao_digitalizacao": None,
        "experiencia_setores_diversos": None,
        "pep_status": None,
        "anima_vinculo_comercial": None,
        "anima_clt_historico": None,
        "disponibilidade_temporario": None,
        "ferramentas_analise_dominadas": None,
        "ferramentas_visualizacao_dominadas": None,
        "como_constroi_dashboards": None,
        "resultado_real_dados": None,
        "diferencial_analista": None,
        "atividades_vaga_experiencia": None,
        "etl_ferramentas_experiencia": None,
        "python_dbt_conhecimento": None,
        "contas_pagar_receber": None,
        "dre_relatorios_financeiros": None,
        "tecnologia_area_financeira": None,
        "analise_dados_financeiros": None,
        "mmm_experiencia": None,
        "inteligencia_mercado_experiencia": None,
        "market_share_indicadores": None,
        "relatorios_executivos_experiencia": None,
        "crm_experiencia": None,
        "looker_apps_script": None,
        "python_dados_nivel": None,
        "melhoria_continua_exemplo": None,
        "graduacao_area_tecnica": None,
        "mestrado_concluido": None,
        "conte_sua_experiencia": None,
        "databricks_nivel": None,
        "rag_experiencia": None,
        "python_tempo_profissional": None,
        "java_dotnet_experiencia": None,
        "frontend_tecnologia": None,
        "api_rest_experiencia": None,
        "devops_experiencia": None,
        "consentimento_dados_ia": None,
        "pricing_revenue_experiencia": None,
        "disponibilidade_regiao_especifica": None,
        "vw_ja_foi_funcionario": None,
        "fisia_nike_ja_trabalhou": None,
        "caixa_vida_parentes_concorrente": None,
        "caixa_vida_societaria": None,
    }


def test_load_application_profile_reads_real_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text(
        "\n".join(
            [
                "# comentário deve ser ignorado",
                "",
                "NOAH_APPLICATION_RG=12.345.678-9",
                "NOAH_APPLICATION_RG_ORGAO_ESTADO=SSP-SP",
                "NOAH_APPLICATION_CPF=123.456.789-00",
                "NOAH_APPLICATION_NOME_MAE=Maria da Silva",
                "NOAH_APPLICATION_NOME_PAI=João da Silva",
                "NOAH_APPLICATION_NATURALIDADE=São Paulo - SP",
                "NOAH_APPLICATION_RACA_COR=Branco",
                "NOAH_APPLICATION_PCD=Não",
                "NOAH_APPLICATION_SALARY_ESTAGIO=R$ 3.000,00",
                "NOAH_APPLICATION_SALARY_JUNIOR=R$ 4.500,00",
                "NOAH_APPLICATION_SALARY_PLENO=R$ 6.500,00",
                "NOAH_APPLICATION_SALARY_CURRENT=R$ 2.500,00",
                "NOAH_APPLICATION_MARITAL_STATUS=Solteiro",
                "NOAH_APPLICATION_CNH=Sim, categoria B",
                "NOAH_APPLICATION_CNH_CATEGORIA=B",
                "NOAH_APPLICATION_DISPONIBILIDADE_VIAGEM=Sim",
                "NOAH_APPLICATION_DISPONIBILIDADE_FDS=Não",
                "NOAH_APPLICATION_DISPONIBILIDADE_HIBRIDO=Sim",
                "NOAH_APPLICATION_ESCOLARIDADE=Ensino superior incompleto (cursando)",
                "NOAH_APPLICATION_CARGO_ATUAL=Não estou empregado no momento",
                "NOAH_APPLICATION_PARENTES_NA_EMPRESA=Não",
                "NOAH_APPLICATION_SEMESTRE_FORMATURA=2º semestre de 2027",
                "NOAH_APPLICATION_ALTURA=1,75 m",
                "NOAH_APPLICATION_TAMANHO_UNIFORME=G",
                "NOAH_APPLICATION_EXCEL_NIVEL=Avançado",
                "NOAH_APPLICATION_SQL_NIVEL=Intermediário-avançado",
                "NOAH_APPLICATION_POWERBI_NIVEL=Intermediário-avançado",
                "NOAH_APPLICATION_MMM_EXPERIENCIA=0 anos. Não possuo experiência específica com Marketing Mix Modeling.",
                "NOAH_APPLICATION_MESTRADO_CONCLUIDO=Não",
                "NOAH_APPLICATION_CRM_EXPERIENCIA=Não há experiência com CRM ou Salesforce.",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_application_profile()

    assert profile == {
        "rg": "12.345.678-9",
        "rg_orgao_estado": "SSP-SP",
        "cpf": "123.456.789-00",
        "nome_mae": "Maria da Silva",
        "nome_pai": "João da Silva",
        "naturalidade": "São Paulo - SP",
        "raca_cor": "Branco",
        "pcd": "Não",
        "salary_estagio": "R$ 3.000,00",
        "salary_junior": "R$ 4.500,00",
        "salary_pleno": "R$ 6.500,00",
        "salary_current": "R$ 2.500,00",
        "marital_status": "Solteiro",
        "cnh": "Sim, categoria B",
        "cnh_categoria": "B",
        "disponibilidade_viagem": "Sim",
        "disponibilidade_fds": "Não",
        "disponibilidade_hibrido": "Sim",
        "escolaridade": "Ensino superior incompleto (cursando)",
        "cargo_atual": "Não estou empregado no momento",
        "parentes_na_empresa": "Não",
        "semestre_formatura": "2º semestre de 2027",
        "altura": "1,75 m",
        "tamanho_uniforme": "G",
        "excel_nivel": "Avançado",
        "sql_nivel": "Intermediário-avançado",
        "powerbi_nivel": "Intermediário-avançado",
        "disponibilidade_estagio_09_16": None,
        "estatistica_matematica_financeira": None,
        "call_center_experiencia": None,
        "power_query_dax": None,
        "power_automate_nivel": None,
        "google_sheets_nivel": None,
        "ia_experiencia": None,
        "susep_conhecimento": None,
        "txt_csv_conhecimento": None,
        "kpis_comerciais_experiencia": None,
        "indicadores_experiencia": None,
        "projeto_automacao_digitalizacao": None,
        "experiencia_setores_diversos": None,
        "pep_status": None,
        "anima_vinculo_comercial": None,
        "anima_clt_historico": None,
        "disponibilidade_temporario": None,
        "ferramentas_analise_dominadas": None,
        "ferramentas_visualizacao_dominadas": None,
        "como_constroi_dashboards": None,
        "resultado_real_dados": None,
        "diferencial_analista": None,
        "atividades_vaga_experiencia": None,
        "etl_ferramentas_experiencia": None,
        "python_dbt_conhecimento": None,
        "contas_pagar_receber": None,
        "dre_relatorios_financeiros": None,
        "tecnologia_area_financeira": None,
        "analise_dados_financeiros": None,
        "mmm_experiencia": "0 anos. Não possuo experiência específica com Marketing Mix Modeling.",
        "inteligencia_mercado_experiencia": None,
        "market_share_indicadores": None,
        "relatorios_executivos_experiencia": None,
        "crm_experiencia": "Não há experiência com CRM ou Salesforce.",
        "looker_apps_script": None,
        "python_dados_nivel": None,
        "melhoria_continua_exemplo": None,
        "graduacao_area_tecnica": None,
        "mestrado_concluido": "Não",
        "conte_sua_experiencia": None,
        "databricks_nivel": None,
        "rag_experiencia": None,
        "python_tempo_profissional": None,
        "java_dotnet_experiencia": None,
        "frontend_tecnologia": None,
        "api_rest_experiencia": None,
        "devops_experiencia": None,
        "consentimento_dados_ia": None,
        "pricing_revenue_experiencia": None,
        "disponibilidade_regiao_especifica": None,
        "vw_ja_foi_funcionario": None,
        "fisia_nike_ja_trabalhou": None,
        "caixa_vida_parentes_concorrente": None,
        "caixa_vida_societaria": None,
    }


def test_load_application_profile_treats_blank_value_as_none(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("NOAH_APPLICATION_RG=\n", encoding="utf-8")

    profile = load_application_profile()

    assert profile["rg"] is None


def test_load_application_profile_ignores_unknown_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("SOME_OTHER_KEY=valor\n", encoding="utf-8")

    profile = load_application_profile()

    assert all(v is None for v in profile.values())


def test_ensure_profile_template_creates_a_real_editable_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    path = ensure_profile_template()

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "NOAH_APPLICATION_RG=" in content
    assert "NOAH_APPLICATION_RG_ORGAO_ESTADO=" in content
    assert "NOAH_APPLICATION_CPF=" in content
    assert "NOAH_APPLICATION_NOME_MAE=" in content
    assert "NOAH_APPLICATION_NOME_PAI=" in content
    assert "NOAH_APPLICATION_NATURALIDADE=" in content
    assert "NOAH_APPLICATION_SALARY_ESTAGIO=" in content
    assert "NOAH_APPLICATION_SALARY_JUNIOR=" in content
    assert "NOAH_APPLICATION_SALARY_PLENO=" in content
    assert "NOAH_APPLICATION_MARITAL_STATUS=" in content


def test_ensure_profile_template_never_overwrites_existing_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "application_profile.env").write_text("NOAH_APPLICATION_RG=12.345.678-9\n", encoding="utf-8")

    ensure_profile_template()

    content = (tmp_path / "application_profile.env").read_text(encoding="utf-8")
    assert "12.345.678-9" in content


def test_referral_contacts_path_lives_under_local_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert referral_contacts_path() == tmp_path / "referral_contacts.json"


def test_load_referral_contacts_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)

    assert load_referral_contacts() == {}


def test_load_referral_contacts_reads_real_values(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    data = {"itau": {"name": "Ana Beatriz Ferreira", "email": "ana.ferreira@itau-unibanco.com.br"}}
    (tmp_path / "referral_contacts.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert load_referral_contacts() == data


def test_load_referral_contacts_returns_empty_on_malformed_json(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)
    (tmp_path / "referral_contacts.json").write_text("not valid json{{{", encoding="utf-8")

    assert load_referral_contacts() == {}
