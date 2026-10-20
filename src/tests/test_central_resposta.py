"""Resposta pela central (central/resposta.py): argumentos das CLIs, ambiente do
filho e as travas de concorrência, com um executor falso (nenhuma CLI roda)."""

import subprocess
import threading
import time

import pytest

from central import resposta
from central.fontes import Pendencia
from central.resposta import RespostaRecusada, Respostas


def _p(fonte="claude", ident="s1", *, pode=True, cwd="/tmp"):
    return Pendencia(fonte, ident, "Título", "proj", "q", "msg", "v", pode_responder=pode, cwd=cwd)


def _esperar(condicao, limite=2.0):
    fim = time.time() + limite
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return False


def test_comando_claude_so_leitura():
    cmd = resposta.comando(_p("claude", "abc"), "/bin/claude")
    assert cmd[:4] == ["/bin/claude", "-p", "--resume", "abc"]
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob"
    assert "--strict-mcp-config" in cmd
    assert not any("skip-permissions" in a or a == "--dangerously-skip-permissions" for a in cmd)


def test_comando_codex_so_leitura_e_texto_pelo_stdin():
    cmd = resposta.comando(_p("codex", "t1"), "/bin/codex")
    assert cmd[:3] == ["/bin/codex", "exec", "resume"]
    assert 'sandbox_mode="read-only"' in cmd and 'approval_policy="never"' in cmd
    assert cmd[-2:] == ["t1", "-"]
    assert not any("bypass" in a or "full-auto" in a for a in cmd)


def test_comando_noah_recusa():
    with pytest.raises(RespostaRecusada) as exc:
        resposta.comando(_p("noah"), "/bin/x")
    assert exc.value.status == 400


def test_ambiente_filho_tira_variaveis_do_claude_pai():
    env = resposta.ambiente_filho({
        "PATH": "/bin", "HOME": "/h", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "x",
        "CLAUDE_AGENT_SDK_VERSION": "1", "CLAUDE_PID": "9", "CLAUDE_EFFORT": "high", "CLAUDE_CONFIG_DIR": "/c",
    })
    assert env == {"PATH": "/bin", "HOME": "/h", "CLAUDE_CONFIG_DIR": "/c"}


def test_binario_prefere_variavel(monkeypatch):
    monkeypatch.setenv("NOAH_CLAUDE_BIN", "/opt/claude")
    assert resposta.binario("claude") == "/opt/claude"


def test_binario_prefere_cli_do_app_ao_path(monkeypatch, tmp_path):
    monkeypatch.delenv("NOAH_CODEX_BIN", raising=False)
    monkeypatch.setattr(resposta.shutil, "which", lambda nome: "/usr/local/bin/codex-antigo")
    do_app = tmp_path / "codex"
    monkeypatch.setitem(resposta.CLI_DO_APP, "codex", do_app)
    assert resposta.binario("codex") == "/usr/local/bin/codex-antigo"
    do_app.write_text("#!/bin/sh\n")
    do_app.chmod(0o755)
    assert resposta.binario("codex") == str(do_app)
    monkeypatch.setenv("NOAH_CODEX_BIN", "/opt/codex")
    assert resposta.binario("codex") == "/opt/codex"


def test_executar_sem_cli_ou_sem_pasta(monkeypatch, tmp_path):
    monkeypatch.setattr(resposta, "binario", lambda nome: None)
    with pytest.raises(RuntimeError, match="não encontrada"):
        resposta.executar(_p(cwd=str(tmp_path)), "oi")
    monkeypatch.setattr(resposta, "binario", lambda nome: "/bin/claude")
    with pytest.raises(RuntimeError, match="não existe mais"):
        resposta.executar(_p(cwd=str(tmp_path / "sumiu")), "oi")


def test_executar_passa_texto_pelo_stdin_e_trata_erro(monkeypatch, tmp_path):
    chamadas = []

    def falso_run(cmd, **kw):
        chamadas.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, chamadas_rc.pop(0), stdout=" ok \n", stderr="linha\nfalhou")

    chamadas_rc = [0, 1]
    monkeypatch.setattr(resposta, "binario", lambda nome: "/bin/claude")
    monkeypatch.setattr(resposta.subprocess, "run", falso_run)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert resposta.executar(_p(cwd=str(tmp_path)), "--não-é-flag") == "ok"
    cmd, kw = chamadas[0]
    assert kw["input"] == "--não-é-flag" and "--não-é-flag" not in cmd
    assert kw["cwd"] == str(tmp_path) and "CLAUDECODE" not in kw["env"]
    with pytest.raises(RuntimeError, match="código 1") as exc:
        resposta.executar(_p(cwd=str(tmp_path)), "oi")
    assert "falhou" in str(exc.value)


def test_iniciar_valida_texto_e_fonte():
    r = Respostas(lambda p, t: "")
    casos = [(_p(pode=False), "oi", 400), (_p(), "   ", 400), (_p(), "x" * (resposta.MAX_TEXTO + 1), 413)]
    for p, texto, status in casos:
        with pytest.raises(RespostaRecusada) as exc:
            r.iniciar(p, texto)
        assert exc.value.status == status


def test_iniciar_trava_conversa_e_limite():
    liberar = threading.Event()

    def executor(p, texto):
        liberar.wait(2)
        return "feito"

    r = Respostas(executor, max_simultaneas=2)
    job = r.iniciar(_p(ident="a"), "oi")
    with pytest.raises(RespostaRecusada) as exc:
        r.iniciar(_p(ident="a"), "de novo")
    assert exc.value.status == 409
    r.iniciar(_p(ident="b"), "oi")
    with pytest.raises(RespostaRecusada) as exc:
        r.iniciar(_p(ident="c"), "oi")
    assert exc.value.status == 429
    assert r.ocupadas() == {"claude:a", "claude:b"}

    liberar.set()
    assert _esperar(lambda: not r.ocupadas())
    estado = {j["id"]: j for j in r.lista()}[job.id]
    assert estado["estado"] == "concluido" and estado["detalhe"] == "feito" and estado["fim"]


def test_erro_do_executor_vira_estado():
    def executor(p, texto):
        raise RuntimeError("A CLI terminou com código 2.")

    r = Respostas(executor)
    job = r.iniciar(_p(), "oi")
    assert _esperar(lambda: r.lista()[0]["estado"] != "rodando")
    [estado] = r.lista()
    assert estado["id"] == job.id and estado["estado"] == "erro" and "código 2" in estado["detalhe"]
