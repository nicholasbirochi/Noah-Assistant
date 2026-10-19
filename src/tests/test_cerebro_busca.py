"""Tests for the local BM25 read path (assistant/cerebro_busca.py) and how
cerebro.consultar() uses it. Offline: a throwaway temp vault, no model, and the
vault CLI is only reached through a fake subprocess.run."""

import os
import re

import pytest

import config
from assistant import cerebro, cerebro_busca as cb

PROTOCOLO = "# Protocolo dos Agentes\n\n- notas são contexto.\n"


def _nota(tipo="aprendizado", status="ativo", projeto=None, corpo=""):
    meta = f"---\ntipo: {tipo}\nstatus: {status}\n"
    if projeto:
        meta += f"projeto: {projeto}\n"
    return meta + "---\n" + corpo


@pytest.fixture
def cofre(tmp_path):
    base = tmp_path / "Cérebro Busca"
    (base / "00 - Regras para Agentes").mkdir(parents=True)
    (base / cb.PROTOCOLO).write_text(PROTOCOLO, encoding="utf-8")

    def escrever(rel, texto):
        caminho = base / rel
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8")
        return caminho

    return base, escrever


def _rels(saida):
    """Caminhos das notas, na ordem dos cabeçalhos `  pontos  caminho  [tipo/status]`."""
    return [m.group(1) for m in re.finditer(r"^\s*\d+\.\d+  (.+?)  \[", saida, re.MULTILINE)]


# ------------------------------------------------------------ texto e termos


def test_radical_une_variacoes_morfologicas():
    assert cb.tokens("modificação")[0] == cb.tokens("modificações")[0]
    assert cb.tokens("configurado")[0] == cb.tokens("configurar")[0]
    assert cb.tokens("Busca")[0] == cb.tokens("buscando")[0]


def test_stopwords_e_acentos_somem():
    assert cb.tokens("a latência do Noah") == [cb.radical("latencia"), "noah"]


def test_sinonimos_entram_com_peso_menor():
    pesos = cb.termos_consulta("modifica")
    assert pesos[cb.radical("modifica")] == 1.0
    assert pesos[cb.radical("edita")] == cb.PESO_SINONIMO


# ------------------------------------------------------------------ ranking


def test_sinonimo_encontra_nota_que_nao_tem_o_termo_literal(cofre):
    base, escrever = cofre
    escrever("05 - Padrões/Aprendizado - x.md", _nota(corpo="# X\n\nComo editar o arquivo com segurança.\n"))

    saida = cb.buscar(base, "modificar arquivo")

    assert "Aprendizado - x.md" in saida


def test_titulo_pesa_mais_que_corpo(cofre):
    base, escrever = cofre
    escrever("a/Aprendizado - latência.md", _nota(corpo="# T\n\nNotas gerais sobre o sistema.\n"))
    escrever("a/Aprendizado - outro.md", _nota(corpo="# T\n\nTexto que cita latência uma vez.\n"))

    assert _rels(cb.buscar(base, "latência"))[0] == "a/Aprendizado - latência.md"


def test_bm25_premia_termo_raro(cofre):
    base, escrever = cofre
    for i in range(4):
        escrever(f"a/Comum {i}.md", _nota(corpo="# T\n\nnoah noah noah\n"))
    escrever("a/Rara.md", _nota(corpo="# T\n\nnoah e o microfone\n"))

    assert _rels(cb.buscar(base, "noah microfone"))[0] == "a/Rara.md"


def test_secao_estado_atual_pesa_mais_que_historico(cofre):
    base, escrever = cofre
    escrever("a/Atual.md", _nota(corpo="# T\n\n## Estado atual\n\nwhisper ativo\n"))
    escrever("a/Antiga.md", _nota(corpo="# T\n\n## Histórico\n\nwhisper ativo\n"))

    assert _rels(cb.buscar(base, "whisper"))[0] == "a/Atual.md"


# ------------------------------------------------------------------ trechos


def test_trechos_passam_de_quatro_linhas_e_tem_contexto(cofre):
    base, escrever = cofre
    corpo = "# T\n\n" + "\n".join(f"linha {i} fala de benchmark" if i % 2 == 0 else f"vizinha {i}" for i in range(14))
    escrever("a/Bench.md", _nota(corpo=corpo + "\n"))

    saida = cb.buscar(base, "benchmark")
    foco = [l for l in saida.splitlines() if l.startswith("    > ")]
    contexto = [l for l in saida.splitlines() if l.startswith("      L")]

    assert len(foco) == 7  # todas as 7 pertinentes (limite padrão 8 > 4 da CLI)
    assert contexto and "vizinha" in contexto[0]


def test_trechos_indicam_linhas_excedentes_e_numeram_como_no_arquivo(cofre):
    base, escrever = cofre
    corpo = "# T\n\n" + "\n".join("ollama aqui" for _ in range(12))
    escrever("a/Muitas.md", _nota(corpo=corpo + "\n"))

    saida = cb.buscar(base, "ollama", orcamento=20_000)

    assert "(+4 linha(s) pertinentes nesta nota)" in saida
    # frontmatter (4 linhas) + "# T" + linha vazia -> primeira "ollama" é L7 do arquivo
    assert "> L7 [T] ollama aqui" in saida


# ------------------------------------------------------------------ filtros


def test_filtros_espelham_a_cli(cofre):
    base, escrever = cofre
    escrever("02 - Projetos/Projeto - Alvo.md", _nota(corpo="# P\n\nmarcador\n"))
    escrever(f"{cb.TEMPLATES}/Template.md", _nota(corpo="marcador\n"))
    escrever(f"{cb.LOGS}/Log.md", _nota(corpo="marcador\n"))
    escrever(f"{cb.SAIDAS}/Saida.md", _nota(corpo="marcador\n"))
    escrever(".oculta/Nota.md", _nota(corpo="marcador\n"))
    escrever("a/Arquivada.md", _nota(status="arquivado", corpo="marcador\n"))
    escrever("a/Obsoleta.md", _nota(status="obsoleto", corpo="marcador\n"))
    fora = escrever("../fora/Fora.md", _nota(corpo="marcador\n"))
    os.symlink(fora, base / "a" / "Link.md")
    os.symlink(fora.parent, base / "pasta-link")

    assert _rels(cb.buscar(base, "marcador")) == ["02 - Projetos/Projeto - Alvo.md"]


def test_filtro_projeto_por_metadado_ou_nome(cofre):
    base, escrever = cofre
    escrever("a/Da meta.md", _nota(projeto="Noah", corpo="termo\n"))
    escrever("02 - Projetos/Projeto - Noah.md", _nota(corpo="termo\n"))
    escrever("a/Outro.md", _nota(projeto="Outro", corpo="termo\n"))

    assert sorted(_rels(cb.buscar(base, "termo", projeto="noah"))) == [
        "02 - Projetos/Projeto - Noah.md",
        "a/Da meta.md",
    ]


def test_cofre_sem_protocolo_ou_symlink_e_invalido(tmp_path):
    with pytest.raises(cb.CofreInvalido):
        cb.carregar(tmp_path)
    real = tmp_path / "real"
    (real / "00 - Regras para Agentes").mkdir(parents=True)
    (real / cb.PROTOCOLO).write_text(PROTOCOLO, encoding="utf-8")
    os.symlink(real, tmp_path / "link")
    with pytest.raises(cb.CofreInvalido):
        cb.carregar(tmp_path / "link")


def test_frontmatter_malformado_nao_derruba(cofre):
    base, escrever = cofre
    escrever("a/Quebrada.md", "---\ntipo: x\nsem fim de frontmatter\npalavra\n")

    assert "a/Quebrada.md" in cb.buscar(base, "palavra")


# --------------------------------------------------------------- orçamento


def test_orcamento_mantem_prefixo_da_relevancia(cofre):
    base, escrever = cofre
    for i in range(6):
        escrever(f"a/N{i}.md", _nota(corpo="# T\n\n" + ("alvo " * (6 - i)) + "x" * 300 + "\n"))

    saida = cb.buscar(base, "alvo", orcamento=900, max_notas=5)

    assert len(saida) <= 900
    assert _rels(saida) == [f"a/N{i}.md" for i in range(len(_rels(saida)))]
    assert "omitida(s)" in saida


def test_sem_resultado_devolve_vazio(cofre):
    base, _ = cofre
    assert cb.buscar(base, "inexistentexyz") == ""


def test_busca_nao_grava_nada(cofre):
    base, escrever = cofre
    escrever("a/N.md", _nota(corpo="conteúdo alvo\n"))
    antes = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in base.rglob("*")}

    cb.buscar(base, "alvo")

    depois = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in base.rglob("*")}
    assert antes == depois


# ------------------------------------------------------- integração consultar


class _Proc:
    def __init__(self, stdout):
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


@pytest.fixture
def cli_falsa(tmp_path, monkeypatch):
    script = tmp_path / "cerebro.py"
    script.write_text("# dummy\n", encoding="utf-8")
    monkeypatch.setattr(config, "CEREBRO_SCRIPT", script)
    chamadas = []

    def run(argv, **kwargs):
        chamadas.append(argv)
        return _Proc("  1.00  da CLI\n-- trechos de 1 nota(s).")

    monkeypatch.setattr(cerebro.subprocess, "run", run)
    return chamadas


def test_consultar_usa_bm25_por_padrao_sem_chamar_cli(cofre, cli_falsa, monkeypatch):
    base, escrever = cofre
    escrever("a/N.md", _nota(corpo="conteúdo alvo\n"))
    monkeypatch.setattr(config, "CEREBRO_DIR", base)
    monkeypatch.setattr(config, "CEREBRO_BUSCA", "bm25")

    saida = cerebro.consultar("alvo")

    assert "ranking BM25 local" in saida and "a/N.md" in saida
    assert cli_falsa == []


def test_consultar_bm25_sem_resultado(cofre, cli_falsa, monkeypatch):
    base, _ = cofre
    monkeypatch.setattr(config, "CEREBRO_DIR", base)
    monkeypatch.setattr(config, "CEREBRO_BUSCA", "bm25")

    assert "Nenhuma nota pertinente" in cerebro.consultar("inexistentexyz")
    assert cli_falsa == []


def test_consultar_cai_na_cli_quando_cofre_invalido(tmp_path, cli_falsa, monkeypatch):
    monkeypatch.setattr(config, "CEREBRO_DIR", tmp_path)  # sem protocolo
    monkeypatch.setattr(config, "CEREBRO_BUSCA", "bm25")

    assert "da CLI" in cerebro.consultar("alvo")
    assert len(cli_falsa) == 1


def test_modo_cli_preserva_caminho_antigo(cofre, cli_falsa, monkeypatch):
    base, escrever = cofre
    escrever("a/N.md", _nota(corpo="conteúdo alvo\n"))
    monkeypatch.setattr(config, "CEREBRO_DIR", base)
    monkeypatch.setattr(config, "CEREBRO_BUSCA", "cli")

    assert "da CLI" in cerebro.consultar("alvo", projeto="Noah")
    assert "buscar" in cli_falsa[0] and "alvo" in cli_falsa[0]
    assert "--projeto" in cli_falsa[0] and "Noah" in cli_falsa[0]


def test_orcamento_e_dividido_entre_notas(cofre):
    # A nota mais relevante tem muitas linhas longas; ainda assim as outras
    # aparecem (a cota encolhe os trechos da primeira em vez de excluí-las).
    base, escrever = cofre
    escrever("a/Grande.md", _nota(corpo="# Grande\n\n" + "\n".join(f"alvo alvo {'x' * 200} {i}" for i in range(20)) + "\n"))
    escrever("a/Media.md", _nota(corpo="# M\n\nalvo uma vez\n"))
    escrever("a/Pequena.md", _nota(corpo="# P\n\noutro alvo\n"))

    saida = cb.buscar(base, "alvo", orcamento=2_000)

    assert len(saida) <= 2_000
    assert _rels(saida)[0] == "a/Grande.md"
    assert set(_rels(saida)) == {"a/Grande.md", "a/Media.md", "a/Pequena.md"}
