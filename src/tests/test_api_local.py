"""API local F7 (api_local.py) com um turno falso: servidor real em porta
efêmera no 127.0.0.1, sem Ollama nem modelo."""

import http.client
import json
import threading

import pytest

import api_local
from api_local import ServidorNoah


class TurnoFalso:
    def __init__(self, falhar=False):
        self.historicos: list[list] = []
        self.falhar = falhar

    def __call__(self, messages):
        if self.falhar:
            raise ConnectionError("ollama fora do ar")
        self.historicos.append([m["content"] for m in messages])
        resposta = f"eco {len(messages)}: {messages[-1]['content']}"
        messages.append({"role": "assistant", "content": resposta})
        return resposta


@pytest.fixture
def servidor_factory():
    criados = []

    def criar(**kwargs):
        kwargs.setdefault("turno", TurnoFalso())
        kwargs.setdefault("info", lambda: {"provider": "falso", "modelo": "m"})
        srv = ServidorNoah(("127.0.0.1", 0), **kwargs)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        criados.append(srv)
        return srv

    yield criar
    for srv in criados:
        srv.shutdown()
        srv.server_close()


def _req(srv, metodo, caminho, corpo=None, headers=None, bruto=None):
    porta = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    h = {"Content-Type": "application/json"} if corpo is not None or bruto is not None else {}
    h.update(headers or {})
    dados = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else None)
    conn.request(metodo, caminho, body=dados, headers=h)
    resp = conn.getresponse()
    texto = resp.read()
    conn.close()
    return resp.status, (json.loads(texto) if texto else None)


def test_saude(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "GET", "/saude") == (200, {"status": "ok", "provider": "falso", "modelo": "m"})


def test_conversa_mantem_o_historico_da_sessao(servidor_factory):
    turno = TurnoFalso()
    srv = servidor_factory(turno=turno)
    status, r1 = _req(srv, "POST", "/conversa", {"mensagem": "  oi  "})
    assert status == 200 and r1["resposta"] == "eco 1: oi"
    status, r2 = _req(srv, "POST", "/conversa", {"mensagem": "e aí?", "sessao": r1["sessao"]})
    assert status == 200 and r2["sessao"] == r1["sessao"]
    assert turno.historicos[-1] == ["oi", "eco 1: oi", "e aí?"]
    # sessão desconhecida vira sessão nova, sem herdar nada
    _, r3 = _req(srv, "POST", "/conversa", {"mensagem": "x", "sessao": "inventada"})
    assert r3["sessao"] not in (r1["sessao"], "inventada") and turno.historicos[-1] == ["x"]


def test_apagar_sessao(servidor_factory):
    srv = servidor_factory()
    _, r = _req(srv, "POST", "/conversa", {"mensagem": "oi"})
    assert _req(srv, "DELETE", f"/sessoes/{r['sessao']}")[0] == 204
    assert _req(srv, "DELETE", f"/sessoes/{r['sessao']}")[0] == 404


@pytest.mark.parametrize("corpo,status", [
    ({}, 400),
    ({"mensagem": "   "}, 400),
    ({"mensagem": 3}, 400),
    ({"mensagem": "oi", "sessao": 7}, 400),
    ({"mensagem": "x" * (api_local.LIMITE_MENSAGEM + 1)}, 413),
])
def test_valida_o_corpo(servidor_factory, corpo, status):
    turno = TurnoFalso()
    srv = servidor_factory(turno=turno)
    assert _req(srv, "POST", "/conversa", corpo)[0] == status
    assert turno.historicos == []


def test_json_invalido_e_tipo_errado(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "POST", "/conversa", bruto=b"{quebrado")[0] == 400
    assert _req(srv, "POST", "/conversa", bruto=b"[1]")[0] == 400
    # formulário simples de outra página (sem preflight de CORS) é recusado
    status, _ = _req(srv, "POST", "/conversa", bruto=b"mensagem=oi",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 415


def test_corpo_grande_demais(servidor_factory):
    srv = servidor_factory()
    status, corpo = _req(srv, "POST", "/conversa", bruto=b"x" * (api_local.LIMITE_CORPO + 1))
    assert status == 413 and "corpo" in corpo["erro"]


def test_host_estranho_e_recusado(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "GET", "/saude", headers={"Host": "ataque.exemplo:80"})[0] == 403


def test_token_obrigatorio_quando_configurado(servidor_factory):
    srv = servidor_factory(token="segredo-de-teste")
    assert _req(srv, "GET", "/saude")[0] == 401
    assert _req(srv, "GET", "/saude", headers={"Authorization": "Bearer errado"})[0] == 401
    assert _req(srv, "GET", "/saude", headers={"Authorization": "Bearer segredo-de-teste"})[0] == 200


def test_fora_do_loopback_sem_token_e_recusado():
    with pytest.raises(ValueError, match="exige token"):
        ServidorNoah(("0.0.0.0", 0))


def test_falha_do_modelo_vira_502_e_nao_suja_o_historico(servidor_factory):
    turno = TurnoFalso()
    srv = servidor_factory(turno=turno)
    _, r = _req(srv, "POST", "/conversa", {"mensagem": "primeira"})
    turno.falhar = True
    status, corpo = _req(srv, "POST", "/conversa", {"mensagem": "vai falhar", "sessao": r["sessao"]})
    assert status == 502 and "ConnectionError" in corpo["erro"] and "ollama" not in corpo["erro"]
    turno.falhar = False
    _req(srv, "POST", "/conversa", {"mensagem": "de novo", "sessao": r["sessao"]})
    assert turno.historicos[-1] == ["primeira", "eco 1: primeira", "de novo"]


def test_rota_inexistente(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "GET", "/nada")[0] == 404
    assert _req(srv, "POST", "/nada", {"mensagem": "x"})[0] == 404


def test_sessoes_respeitam_o_teto():
    s = api_local.Sessoes(maximo=2)
    a, _ = s.obter(None)
    s.obter(None)
    s.obter(a)          # "a" vira a mais recente
    s.obter(None)       # sai a do meio, não "a"
    assert len(s) == 2 and s.obter(a)[0] == a


def test_e_loopback():
    assert api_local.e_loopback("127.0.0.1") and api_local.e_loopback("::1")
    assert api_local.e_loopback("localhost")
    assert not api_local.e_loopback("0.0.0.0") and not api_local.e_loopback("192.168.0.5")
