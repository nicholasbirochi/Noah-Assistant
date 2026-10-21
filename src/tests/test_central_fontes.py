"""Leitores da central de pendências (central/fontes.py) com transcripts falsos
em pasta temporária: nada de ~/.claude nem ~/.codex de verdade."""

import json

from central import fontes
from central.fontes import Dispensadas, Pendencia


def _escrever(caminho, linhas):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # Compacto, como o Claude Code e o Codex gravam.
    texto = "\n".join(json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in linhas)
    caminho.write_text(texto + "\n", encoding="utf-8")
    return caminho


def _user(texto, ts="2026-10-19T10:00:00Z", **extra):
    return {"type": "user", "timestamp": ts, "cwd": "/tmp/proj", "message": {"role": "user", "content": texto}, **extra}


def _assistant(blocos, *, stop="end_turn", ts="2026-10-19T10:01:00Z", mid="m1", **extra):
    return {
        "type": "assistant", "timestamp": ts, "cwd": "/tmp/proj",
        "message": {"id": mid, "role": "assistant", "stop_reason": stop, "content": blocos}, **extra,
    }


def _texto(t):
    return {"type": "text", "text": t}


# -- Claude -------------------------------------------------------------------


def test_claude_pendente_com_titulo(tmp_path):
    _escrever(tmp_path / "proj" / "s1.jsonl", [
        {"type": "custom-title", "customTitle": "Meu título"},
        {**_user("oi"), "entrypoint": "claude-desktop"},
        _assistant([_texto("Pronto. Posso seguir?")]),
    ])
    itens = fontes.pendencias_claude(tmp_path)
    assert len(itens) == 1
    p = itens[0]
    assert (p.fonte, p.id, p.titulo, p.projeto) == ("claude", "s1", "Meu título", "proj")
    assert p.mensagem == "Pronto. Posso seguir?"
    assert p.pergunta is True and p.para_json()["pergunta"] is True
    assert p.simples is True and p.para_json()["simples"] is True
    assert p.cwd == "/tmp/proj"
    assert "cwd" not in p.para_json() and p.para_json()["chave"] == "claude:s1"


def test_claude_junta_blocos_da_mesma_mensagem(tmp_path):
    _escrever(tmp_path / "p" / "s.jsonl", [
        _user("oi"),
        _assistant([_texto("parte 1")], stop=None),
        _assistant([_texto("parte 2")]),
    ])
    assert fontes.pendencias_claude(tmp_path)[0].mensagem == "parte 1\n\nparte 2"


def test_claude_resposta_pronta_nao_e_pergunta(tmp_path):
    _escrever(tmp_path / "p" / "s.jsonl", [
        _user("oi"),
        _assistant([_texto("Feito: testes passaram e o README foi atualizado.")]),
    ])
    [p] = fontes.pendencias_claude(tmp_path)
    assert p.pergunta is False and p.pode_responder is True
    assert p.simples is False


def test_e_pergunta_olha_o_fim_sem_codigo_nem_link():
    assert fontes.e_pergunta("Relatório.\n\nQuer que eu abra o PR?")
    assert fontes.e_pergunta("Tudo certo. Me avise se precisar de ajuste.")
    assert fontes.e_pergunta("Done. Let me know if you want the tests too.")
    assert fontes.e_pergunta("Ficou assim. Você prefere a versão curta")
    assert not fontes.e_pergunta("Pronto. Commit feito e testes verdes.")
    assert not fontes.e_pergunta("Veja https://exemplo.com/busca?q=1 para detalhes.")
    assert not fontes.e_pergunta("Regex nova:\n```\n^a?b$\n```\nUsei `x?` no padrão.")
    assert not fontes.e_pergunta("")
    # Pergunta lá no começo de um relatório longo não conta: vale o fim.
    assert not fontes.e_pergunta("Posso seguir? " + "linha do relatório. " * 40 + "Fim.")


def test_e_simples_so_sim_ou_nao_curta():
    # Aceitar só onde um "sim" responde.
    assert fontes.e_simples("Fiz o commit. Posso fazer o push?")
    assert fontes.e_simples("Relatório.\n\nQuer que eu abra o PR?")
    assert fontes.e_simples("Tudo certo. Should I proceed with the merge?")
    assert fontes.e_simples("Posso seguir ou prefere revisar antes?")
    assert fontes.e_simples("Aguardo seu ok para o push.")
    assert fontes.e_simples("Ficou bom? Posso mandar para revisão?")
    # Pergunta aberta, menu de opções, várias perguntas ou longa: resposta escrita.
    assert not fontes.e_simples("Qual nome você prefere para a branch?")
    assert not fontes.e_simples("Como você quer organizar as pastas?")
    assert not fontes.e_simples("E o que acha disso?")
    assert not fontes.e_simples("Opções:\n1. Postgres\n2. SQLite\n3. Arquivo\nPosso usar a 1?")
    assert not fontes.e_simples("Posso seguir? Quer A? Ou B? Ou C?")
    assert not fontes.e_simples("Posso " + "mesmo " * 40 + "seguir?")
    # Sem pergunta, ou "?" só em código e link: nada a aceitar.
    assert not fontes.e_simples("Pronto. Commit feito e testes verdes.")
    assert not fontes.e_simples("Veja `x?` e https://exemplo.com/?q=1")
    assert not fontes.e_simples("")


def test_claude_titulo_ia_quando_nao_ha_titulo_proprio(tmp_path):
    _escrever(tmp_path / "p" / "s.jsonl", [{"type": "ai-title", "aiTitle": "Título IA"}, _user("oi"), _assistant([_texto("ok")])])
    assert fontes.pendencias_claude(tmp_path)[0].titulo == "Título IA"


def test_claude_fica_de_fora(tmp_path):
    casos = {
        "vez_do_agente": [_assistant([_texto("ok")]), _user("e agora?")],
        "tool_use": [_user("oi"), _assistant([_texto("vou ler"), {"type": "tool_use", "id": "t"}], stop="tool_use")],
        "sem_fim_de_turno": [_user("oi"), _assistant([_texto("...")], stop=None)],
        "sem_texto": [_user("oi"), _assistant([{"type": "thinking", "thinking": "x"}])],
        "sdk": [{**_user("oi"), "entrypoint": "sdk-cli"}, _assistant([_texto("ok")])],
    }
    for nome, linhas in casos.items():
        _escrever(tmp_path / "p" / f"{nome}.jsonl", linhas)
    assert fontes.pendencias_claude(tmp_path) == []


def test_claude_ignora_subagente_no_fim(tmp_path):
    _escrever(tmp_path / "p" / "s.jsonl", [
        _user("oi"),
        _assistant([_texto("resposta principal")]),
        _assistant([_texto("do subagente")], mid="m2", isSidechain=True),
    ])
    assert fontes.pendencias_claude(tmp_path)[0].mensagem == "resposta principal"


def test_claude_respeita_janela_de_dias(tmp_path):
    arquivo = _escrever(tmp_path / "p" / "s.jsonl", [_user("oi"), _assistant([_texto("ok")])])
    agora = arquivo.stat().st_mtime + 10 * 86400
    assert fontes.pendencias_claude(tmp_path, dias=3, agora=agora) == []
    assert len(fontes.pendencias_claude(tmp_path, dias=30, agora=agora)) == 1


def test_claude_linha_corrompida_nao_quebra(tmp_path):
    arquivo = _escrever(tmp_path / "p" / "s.jsonl", [_user("oi"), _assistant([_texto("ok")])])
    with arquivo.open("a") as f:
        f.write("{isto não é json\n")
    assert len(fontes.pendencias_claude(tmp_path)) == 1


# -- Codex --------------------------------------------------------------------


def _rollout(raiz, ident, *, source="vscode", eventos=None, nome=None):
    linhas = [{"type": "session_meta", "payload": {"id": ident, "source": source, "cwd": "/tmp/repo"}}]
    linhas += eventos if eventos is not None else [
        {"type": "event_msg", "timestamp": "2026-10-19T09:00:00Z", "payload": {"type": "task_started"}},
        {"type": "event_msg", "timestamp": "2026-10-19T09:05:00Z",
         "payload": {"type": "task_complete", "last_agent_message": "Feito. Quer que eu rode os testes?"}},
    ]
    return _escrever(raiz / "sessions" / "2026" / "10" / "19" / (nome or f"rollout-x-{ident}.jsonl"), linhas)


def test_codex_pendente_com_titulo(tmp_path):
    _rollout(tmp_path, "t1")
    _escrever(tmp_path / "session_index.jsonl", [
        {"id": "t1", "thread_name": "antigo"}, {"id": "t1", "thread_name": "Título novo"},
    ])
    itens = fontes.pendencias_codex(tmp_path)
    assert len(itens) == 1
    p = itens[0]
    assert (p.fonte, p.id, p.titulo, p.projeto, p.cwd) == ("codex", "t1", "Título novo", "repo", "/tmp/repo")
    assert p.mensagem.startswith("Feito.")
    assert p.pergunta is True
    assert p.simples is fontes.e_simples(p.mensagem)
    assert p.versao == "2026-10-19T09:05:00Z"


def test_codex_fica_de_fora(tmp_path):
    _rollout(tmp_path, "exec", source="exec")
    _rollout(tmp_path, "sub", source={"subagent": {"other": "guardian"}})
    _rollout(tmp_path, "rodando", eventos=[
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "velha"}},
        {"type": "event_msg", "payload": {"type": "task_started"}},
    ])
    _rollout(tmp_path, "abortado", eventos=[{"type": "event_msg", "payload": {"type": "turn_aborted"}}])
    _rollout(tmp_path, "vazio", eventos=[{"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": None}}])
    _escrever(tmp_path / "sessions" / "2026" / "10" / "19" / "rollout-ruim.jsonl", [{"type": "outra"}])
    assert fontes.pendencias_codex(tmp_path) == []


def test_codex_sem_pasta_devolve_vazio(tmp_path):
    assert fontes.pendencias_codex(tmp_path / "nada") == []
    assert fontes.pendencias_claude(tmp_path / "nada") == []


# -- lista, dispensadas e texto ---------------------------------------------------


def _p(fonte, ident, quando, versao=None):
    return Pendencia(fonte, ident, f"T {ident}", "proj", quando, "msg", versao or quando)


def test_listar_ordena_e_dispensa_so_a_versao(tmp_path, monkeypatch):
    monkeypatch.setattr(fontes, "pendencias_claude", lambda *a, **k: [_p("claude", "a", "2026-10-19T08:00")])
    monkeypatch.setattr(fontes, "pendencias_codex", lambda *a, **k: [_p("codex", "b", "2026-10-19T09:00")])
    monkeypatch.setattr(fontes, "pendencias_noah", lambda: [_p("noah", "n", "")])
    itens, falhas = fontes.listar()
    assert [i.chave for i in itens] == ["codex:b", "claude:a", "noah:n"] and falhas == []

    itens, _ = fontes.listar(dispensadas={"codex:b": "2026-10-19T09:00", "claude:a": "versão antiga"})
    assert [i.chave for i in itens] == ["claude:a", "noah:n"]


def test_listar_fonte_quebrada_vira_falha(monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("formato novo")

    monkeypatch.setattr(fontes, "pendencias_claude", lambda *a, **k: [_p("claude", "a", "x")])
    monkeypatch.setattr(fontes, "pendencias_codex", quebra)
    itens, falhas = fontes.listar(incluir_noah=False)
    assert [i.chave for i in itens] == ["claude:a"] and falhas == ["Codex"]


def test_dispensadas_persistem_e_arquivo_ruim_vale_vazio(tmp_path):
    d = Dispensadas(tmp_path / "c" / "d.json")
    assert d.carregar() == {}
    d.marcar("claude:a", "v1")
    d.marcar("claude:a", "v2")
    assert Dispensadas(tmp_path / "c" / "d.json").carregar() == {"claude:a": "v2"}
    (tmp_path / "c" / "d.json").write_text("[1, 2]")
    assert d.carregar() == {}


def test_noah_desligado_nao_lista(monkeypatch):
    from assistant import presence

    monkeypatch.setattr(presence, "is_enabled", lambda: False)
    assert fontes.pendencias_noah() == []


def test_noah_ligado_vira_item_so_leitura(monkeypatch):
    from assistant import presence

    monkeypatch.setattr(presence, "is_enabled", lambda: True)
    monkeypatch.setattr(presence, "build_presence_items",
                        lambda: [presence.PresenceItem(source="Lembretes", why="2 vencidos", action="Abrir lembretes")])
    [p] = fontes.pendencias_noah()
    assert p.fonte == "noah" and p.pode_responder is False and "Abrir lembretes" in p.mensagem
    assert p.pergunta is True and p.simples is False


def test_formatar_texto():
    assert fontes.formatar_texto([], []) == "Nada esperando resposta."
    p = Pendencia("codex", "b", "Título", "repo", "q", "linha 1\nlinha 2\nlinha 3\nlinha 4", "v")
    saida = fontes.formatar_texto([p], ["Claude"])
    assert saida.startswith("[Codex] Título (repo)\n    linha 1")
    assert "linha 4" not in saida
    assert saida.endswith("Fonte com problema (pulada): Claude")
