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


def test_cancelamento_antes_do_post_impede_iniciar_turno():
    chamados = []
    c = _conversas(lambda h: chamados.append(True) or "não deveria rodar")

    assert c.cancelar("antes") == {"ok": True}
    with pytest.raises(ConversaRecusada) as erro:
        c.conversar("texto", request_id="antes")
    assert erro.value.status == 409
    assert chamados == []


def test_request_id_repetido_nao_repete_acao():
    chamados = []
    c = _conversas(lambda h: chamados.append(True) or "ok")
    c.conversar("ação", request_id="unico")
    with pytest.raises(ConversaRecusada) as erro:
        c.conversar("ação", request_id="unico")
    assert erro.value.status == 409
    assert chamados == [True]


def test_novo_pedido_aguarda_inferencia_cancelada_e_preserva_fala():
    iniciou, liberar, segundo = threading.Event(), threading.Event(), threading.Event()

    def turno(historico):
        fala = historico[-1]["content"]
        if fala == "antiga":
            iniciou.set()
            liberar.wait(5)
            return "resposta antiga"
        if fala == "nova":
            segundo.set()
            return "resposta nova"
        return "resposta inicial"

    c = _conversas(turno)
    sessao = c.conversar("início")["sessao"]
    erros = []
    antiga = threading.Thread(target=lambda: _capturar_erro(
        erros, c.conversar, "antiga", sessao, "request-antiga"
    ))
    antiga.start()
    assert iniciou.wait(5)
    c.cancelar("request-antiga")

    resultado = []
    nova = threading.Thread(target=lambda: resultado.append(
        c.conversar("nova", sessao, "request-nova")
    ))
    nova.start()
    assert not segundo.wait(0.05), "não deve iniciar uma segunda inferência em paralelo"
    liberar.set()
    antiga.join(5)
    nova.join(5)

    assert not antiga.is_alive() and not nova.is_alive()
    assert [e.status for e in erros] == [409]
    assert resultado[0]["resposta"] == "resposta nova"
    assert segundo.is_set()
    assert [m["content"] for m in c._sessoes[sessao] if m["role"] == "user"] == ["início", "nova"]


def _capturar_erro(erros, func, *args):
    try:
        func(*args)
    except ConversaRecusada as exc:
        erros.append(exc)


def test_teto_de_sessoes_esquece_a_mais_antiga():
    c = Conversas(lambda h: "ok", info=lambda: INFO, max_sessoes=2)
    a = c.conversar("a")["sessao"]
    c.conversar("b")
    c.conversar("c")
    assert c.conversar("de novo", a)["sessao"] != a
