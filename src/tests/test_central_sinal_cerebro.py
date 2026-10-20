"""Sinal ao vivo do Cérebro (central/sinal_cerebro.py) com transcripts falsos em
pasta temporária: nada de ~/.claude, ~/.codex nem do estado real do Noah."""

import json
from datetime import datetime, timezone

from central import sinal_cerebro

AGORA = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc).timestamp()
CEREBRO = 'python3 "/Users/x/Documents/Cérebro/.cerebro/cerebro.py"'


def _ts(segundos_atras):
    return datetime.fromtimestamp(AGORA - segundos_atras, timezone.utc).isoformat().replace("+00:00", "Z")


def _escrever(caminho, linhas):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in linhas) + "\n", encoding="utf-8")
    return caminho


def _bash_claude(comando, atras=30, ident="t"):
    return {"type": "assistant", "timestamp": _ts(atras), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": ident, "name": "Bash", "input": {"command": comando, "description": "x"}},
    ]}}


def _resultado_claude(ident, texto, atras=29):
    return {"type": "user", "timestamp": _ts(atras), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": ident, "content": [{"type": "text", "text": texto}]},
    ]}}


# Saída no formato do buscar --trechos (notas falsas).
SAIDA_BUSCAR = """== 02 - Projetos/Projeto - Exemplo.md
trecho falso
== 03 - Graphify e Mapas de Projeto/Mapas/Mapa - Exemplo.md
outro trecho
-- trechos de 2 nota(s)"""


def _texto_claude(texto, atras=30):
    return {"type": "assistant", "timestamp": _ts(atras),
            "message": {"role": "assistant", "content": [{"type": "text", "text": texto}]}}


def _chamada_codex(argumentos, atras=30, tipo="function_call", ident="c"):
    return {"type": "response_item", "timestamp": _ts(atras),
            "payload": {"type": tipo, "name": "exec_command", "arguments": json.dumps(argumentos), "call_id": ident}}


def _saida_codex(ident, texto, atras=29, tipo="function_call_output"):
    return {"type": "response_item", "timestamp": _ts(atras),
            "payload": {"type": tipo, "call_id": ident, "output": json.dumps({"output": texto})}}


def _codex(tmp_path, linhas):
    return _escrever(tmp_path / "sessions" / "2026" / "10" / "20" / "rollout-a.jsonl", linhas)


# -- Claude -----------------------------------------------------------------------


def test_claude_conta_consulta_registro_e_delegacao(tmp_path):
    _escrever(tmp_path / "proj" / "s.jsonl", [
        _bash_claude(f"{CEREBRO} buscar noah fluxo --trechos", atras=300),
        _bash_claude(f"{CEREBRO} contexto --projeto Noah", atras=200),
        _bash_claude(f"{CEREBRO} gravar --nota x", atras=100),
        _bash_claude("python3 .cerebro/auxiliares.py --tipo mecanica 'ajuste'", atras=50),
    ])
    cerebro, aux = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert (cerebro["consultas"], cerebro["registros"]) == (2, 1)
    assert cerebro["ultima"] == AGORA - 100
    assert aux == {"delegacoes": 1, "ultima": AGORA - 50}


def test_claude_texto_e_mencao_nao_contam(tmp_path):
    _escrever(tmp_path / "proj" / "s.jsonl", [
        _texto_claude(f"Rode {CEREBRO} buscar noah para ver."),
        _bash_claude("grep -n 'cerebro.py buscar' readme.md"),  # cita, não executa
        _bash_claude(f"{CEREBRO} hash nota.md"),  # subcomando que não é consulta nem registro
        {"type": "user", "timestamp": _ts(30), "message": {"role": "user", "content": f"{CEREBRO} buscar x"}},
    ])
    cerebro, aux = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert (cerebro["consultas"], cerebro["registros"], cerebro["ultima"]) == (0, 0, None)
    assert aux["delegacoes"] == 0


def test_claude_fora_da_janela_nao_conta(tmp_path):
    _escrever(tmp_path / "proj" / "s.jsonl", [
        _bash_claude(f"{CEREBRO} buscar velho", atras=sinal_cerebro.JANELA_S + 5),
        _bash_claude(f"{CEREBRO} buscar novo", atras=5),
    ])
    cerebro, _ = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert cerebro["consultas"] == 1


def test_claude_inclui_subagentes(tmp_path):
    _escrever(tmp_path / "proj" / "sess" / "subagents" / "agent-1.jsonl", [_bash_claude(f"{CEREBRO} buscar x")])
    cerebro, _ = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert cerebro["consultas"] == 1


def test_arquivo_antigo_nem_e_aberto(tmp_path):
    import os

    caminho = _escrever(tmp_path / "proj" / "s.jsonl", [_bash_claude(f"{CEREBRO} buscar x", atras=5)])
    os.utime(caminho, (AGORA - 3600, AGORA - 3600))
    cerebro, _ = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert cerebro["consultas"] == 0


def test_claude_partes_da_consulta_e_do_registro(tmp_path):
    _escrever(tmp_path / "proj" / "s.jsonl", [
        _bash_claude(f"{CEREBRO} buscar noah --trechos", atras=60, ident="b1"),
        _resultado_claude("b1", SAIDA_BUSCAR, atras=59),
        _bash_claude(f"{CEREBRO} contexto --projeto Noah", atras=50, ident="b2"),
        _resultado_claude("b2", "Projeto: 02 - Projetos/Projeto - Exemplo.md", atras=49),
        _bash_claude(f'{CEREBRO} gravar --destino "06 - Logs de Tarefas/2026/log.md" --novo', atras=40, ident="g1"),
        _resultado_claude("g1", "gravado", atras=39),
    ])
    cerebro, _ = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert (cerebro["consultas"], cerebro["registros"]) == (2, 1)
    assert cerebro["partes"] == {"02": 2, "03": 1, "06": 1}


def test_claude_partes_so_de_resposta_do_cerebro(tmp_path):
    _escrever(tmp_path / "proj" / "s.jsonl", [
        _bash_claude("cat '05 - Padrões e Preferências/x.md'", ident="o1"),  # outra ferramenta
        _resultado_claude("o1", "05 - Padrões e Preferências/x.md"),
        _bash_claude(f"{CEREBRO} buscar y", ident="b1"),
        _resultado_claude("b1", "nada em 01 - Índices sem barra"),  # sem caminho de nota
        _resultado_claude("b9", "== 07 - Templates/a.md"),  # resposta de chamada desconhecida
    ])
    cerebro, _ = sinal_cerebro.contar_claude(tmp_path, agora=AGORA)
    assert cerebro["consultas"] == 1
    assert cerebro["partes"] == {}


def test_pastas_citadas():
    assert sinal_cerebro.pastas_citadas(SAIDA_BUSCAR) == ["02", "03"]
    assert sinal_cerebro.pastas_citadas("x/08 - Outra/a.md 1002 - Y/b.md") == []
    assert sinal_cerebro.pastas_citadas(None) == []


# -- Codex ------------------------------------------------------------------------


def test_codex_conta_argv_e_texto(tmp_path):
    _codex(tmp_path, [
        _chamada_codex({"cmd": f"{CEREBRO} buscar noah"}),
        _chamada_codex({"command": ["python3", "/x/.cerebro/cerebro.py", "gravar", "--nota", "y"]}),
        _chamada_codex({"command": ["bash", "-lc", "python3 auxiliares.py --tipo codigo t"]}, tipo="local_shell_call"),
        {"type": "response_item", "timestamp": _ts(30), "payload": {"type": "message", "role": "assistant",
                                                                    "content": [{"type": "output_text", "text": f"{CEREBRO} buscar"}]}},
    ])
    cerebro, aux = sinal_cerebro.contar_codex(tmp_path, agora=AGORA)
    assert (cerebro["consultas"], cerebro["registros"]) == (1, 1)
    assert aux["delegacoes"] == 1


def test_codex_partes_pela_saida_com_mesmo_call_id(tmp_path):
    _codex(tmp_path, [
        _chamada_codex({"cmd": f"{CEREBRO} buscar noah --trechos"}, ident="c1"),
        _saida_codex("outro", "== 07 - Templates/Modelo.md"),  # saída de outra chamada
        _saida_codex("c1", SAIDA_BUSCAR),
        _chamada_codex({"cmd": "ls '04 - Decisões Técnicas/'"}, ident="c2"),  # não é o Cérebro
        _saida_codex("c2", "04 - Decisões Técnicas/ADR.md"),
    ])
    cerebro, _ = sinal_cerebro.contar_codex(tmp_path, agora=AGORA)
    assert cerebro["consultas"] == 1
    assert cerebro["partes"] == {"02": 1, "03": 1}


def test_codex_sem_pasta_e_zero(tmp_path):
    cerebro, aux = sinal_cerebro.contar_codex(tmp_path, agora=AGORA)
    assert cerebro["consultas"] == 0 and aux["delegacoes"] == 0


# -- Noah -------------------------------------------------------------------------


def test_noah_registra_so_o_horario_e_conta_na_janela(tmp_path):
    arquivo = tmp_path / "central" / "atividade_cerebro.jsonl"
    sinal_cerebro.registrar_consulta_noah(arquivo, agora=AGORA - sinal_cerebro.JANELA_S - 10)
    sinal_cerebro.registrar_consulta_noah(arquivo, agora=AGORA - 20)
    sinal_cerebro.registrar_consulta_noah(arquivo, agora=AGORA - 10)
    assert all(set(json.loads(l)) == {"t"} for l in arquivo.read_text().splitlines())
    assert sinal_cerebro.contar_noah(arquivo, agora=AGORA) == {"consultas": 2, "registros": 0, "ultima": AGORA - 10,
                                                                "partes": {}}


def test_noah_registra_so_os_codigos_das_pastas(tmp_path):
    arquivo = tmp_path / "atividade.jsonl"
    sinal_cerebro.registrar_consulta_noah(arquivo, agora=AGORA - 20, partes=["02", "03", "02"])
    sinal_cerebro.registrar_consulta_noah(arquivo, agora=AGORA - 10, partes=["02", "termo secreto", "9"])
    linhas = [json.loads(l) for l in arquivo.read_text().splitlines()]
    assert [l["p"] for l in linhas] == [["02", "03"], ["02"]]
    assert sinal_cerebro.contar_noah(arquivo, agora=AGORA)["partes"] == {"02": 2, "03": 1}


def test_noah_arquivo_fica_pequeno(tmp_path):
    arquivo = tmp_path / "atividade.jsonl"
    for i in range(sinal_cerebro.MAX_EVENTOS_NOAH * 3):
        sinal_cerebro.registrar_consulta_noah(arquivo, agora=AGORA - 1000 + i)
    assert len(arquivo.read_text().splitlines()) <= sinal_cerebro.MAX_EVENTOS_NOAH * 2


def test_noah_registro_nunca_levanta(tmp_path):
    bloqueio = tmp_path / "arquivo"
    bloqueio.write_text("x")
    sinal_cerebro.registrar_consulta_noah(bloqueio / "dentro" / "a.jsonl")  # pai é arquivo: falha engolida


def test_consultar_anota_a_consulta(monkeypatch, tmp_path):
    import subprocess

    from assistant import cerebro

    anotadas = []
    monkeypatch.setattr(cerebro, "registrar_consulta_noah", lambda **k: anotadas.append(list(k["partes"])))
    monkeypatch.setattr(cerebro, "_run", lambda *a, **k: subprocess.CompletedProcess(a, 0, SAIDA_BUSCAR, ""))
    assert cerebro.consultar("noah").startswith("== 02 - Projetos")
    assert cerebro.consultar("   ") .startswith("Preciso")  # sem termos não chega ao Cérebro
    monkeypatch.setattr(cerebro, "_run", lambda *a, **k: subprocess.CompletedProcess(a, 2, SAIDA_BUSCAR, "erro"))
    cerebro.consultar("noah")  # falhou: conta a consulta, mas sem pastas
    assert anotadas == [["02", "03"], []]


# -- resumo -----------------------------------------------------------------------


def test_ler_sinal_junta_as_fontes(tmp_path):
    _escrever(tmp_path / "claude" / "p" / "s.jsonl", [_bash_claude(f"{CEREBRO} buscar x")])
    _codex(tmp_path / "codex", [_chamada_codex({"cmd": "python3 auxiliares.py --tipo analise t"})])
    sinal = sinal_cerebro.ler_sinal(raiz_claude=tmp_path / "claude", raiz_codex=tmp_path / "codex",
                                    arquivo_noah=tmp_path / "noah.jsonl", agora=AGORA, usar_cache=False)
    assert sinal["janela_s"] == sinal_cerebro.JANELA_S
    assert sinal["cerebro"]["claude"]["consultas"] == 1
    assert sinal["cerebro"]["codex"]["consultas"] == 0
    assert sinal["cerebro"]["noah"] == {"consultas": 0, "registros": 0, "ultima": None, "partes": {}}
    assert sinal["auxiliares"]["codex"]["delegacoes"] == 1
    assert sinal["falhas"] == []


def test_ler_sinal_fonte_que_falha_vira_aviso(tmp_path, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(sinal_cerebro, "contar_codex", quebra)
    sinal = sinal_cerebro.ler_sinal(raiz_claude=tmp_path, raiz_codex=tmp_path, arquivo_noah=tmp_path / "n",
                                    agora=AGORA, usar_cache=False)
    assert sinal["falhas"] == ["Codex"]
    assert sinal["cerebro"]["codex"]["consultas"] == 0


def test_ler_sinal_usa_cache_curto(tmp_path, monkeypatch):
    monkeypatch.setattr(sinal_cerebro, "_cache", None)
    chamadas = []
    original = sinal_cerebro.contar_noah
    monkeypatch.setattr(sinal_cerebro, "contar_noah", lambda *a, **k: (chamadas.append(1), original(*a, **k))[1])
    kw = dict(raiz_claude=tmp_path, raiz_codex=tmp_path, arquivo_noah=tmp_path / "n")
    sinal_cerebro.ler_sinal(agora=AGORA, **kw)
    sinal_cerebro.ler_sinal(agora=AGORA + 1, **kw)
    sinal_cerebro.ler_sinal(agora=AGORA + sinal_cerebro.CACHE_S + 1, **kw)
    assert len(chamadas) == 2
