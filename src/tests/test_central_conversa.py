"""Conversa da aba Central (central/conversa.py) com turno falso: sem modelo."""

import threading

import pytest

from central.conversa import ConversaRecusada, Conversas

INFO = {"provedor": "ollama", "modelo": "qwen2.5:7b"}


def _conversas(turno):
    return Conversas(turno, info=lambda: INFO)


def test_mantem_historico_da_sessao():
    vistos = []

    def turno(historico):
        vistos.append(len(historico))
        return f"resposta {len(historico)}"

    c = _conversas(turno)
    primeira = c.conversar("oi")
    segunda = c.conversar("e agora?", primeira["sessao"])
    assert segunda["sessao"] == primeira["sessao"]
    assert vistos == [1, 2]  # o turno falso não acrescenta a resposta; o real acrescenta
    assert primeira["modelo"] == "qwen2.5:7b" and primeira["ferramentas"] == []


def test_registra_so_as_ferramentas_deste_turno():
    def turno(historico):
        historico.append({"role": "tool", "content": "x", "tool_name": "consult_cerebro"})
        historico.append({"role": "tool", "content": "y", "tool_name": "consult_cerebro"})
        historico.append({"role": "tool", "content": "z", "tool_name": "get_weather"})
        return "ok"

    c = _conversas(turno)
    assert c.conversar("oi")["ferramentas"] == ["consult_cerebro", "get_weather"]
    assert c.estado()["turnos"][0]["ferramentas"] == ["consult_cerebro", "get_weather"]
    assert "content" not in str(c.estado()["turnos"])


def test_falha_do_modelo_desfaz_a_mensagem():
    historicos = []

    def turno(historico):
        historicos.append(historico)
        raise RuntimeError("ollama caiu")

    c = _conversas(turno)
    with pytest.raises(ConversaRecusada) as erro:
        c.conversar("oi")
    assert erro.value.status == 502 and "RuntimeError" in erro.value.mensagem
    assert historicos[0] == [] and c.estado()["respondendo_desde"] is None


def test_segundo_turno_simultaneo_recebe_409():
    liberar, entrou = threading.Event(), threading.Event()

    def turno(historico):
        entrou.set()
        liberar.wait(5)
        return "ok"

    c = _conversas(turno)
    t = threading.Thread(target=c.conversar, args=("primeira",))
    t.start()
    entrou.wait(5)
    assert c.estado()["respondendo_desde"] is not None
    with pytest.raises(ConversaRecusada) as erro:
        c.conversar("segunda")
    assert erro.value.status == 409
    liberar.set()
    t.join(5)


def test_teto_de_sessoes_esquece_a_mais_antiga():
    c = Conversas(lambda h: "ok", info=lambda: INFO, max_sessoes=2)
    a = c.conversar("a")["sessao"]
    c.conversar("b")
    c.conversar("c")
    assert c.conversar("de novo", a)["sessao"] != a
