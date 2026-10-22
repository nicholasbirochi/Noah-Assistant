"""Servidor da central (central/servidor.py) numa porta efêmera, com lista,
respostas e dispensadas falsas: nada de conversa real nem CLI."""

import http.client
import json
import threading

import pytest

from central import servidor as central_servidor
from central.fontes import Dispensadas, Pendencia
from central.conversa import Conversas
from central.resposta import Respostas
from central.servidor import ServidorCentral

ITENS = [
    Pendencia("claude", "s1", "Conversa", "proj", "2026-10-19T10:00", "Posso seguir?", "v1", cwd="/tmp"),
    Pendencia("noah", "p-1", "Lembretes", "Noah", "", "2 vencidos", "p-1", pode_responder=False),
]


@pytest.fixture
def servidor_factory(tmp_path):
    criados = []

    def criar(*, token=None, presenca=None, sinal=None, turno=None,
              host="127.0.0.1", hosts_adicionais=()):
        respondidas = []

        def executor(p, texto):
            respondidas.append((p.chave, texto))
            return "ok"

        srv = ServidorCentral(
            (host, 0), token=token, hosts_adicionais=hosts_adicionais,
            listar=lambda: (list(ITENS), ["Codex"]),
            respostas=Respostas(executor),
            dispensadas=Dispensadas(tmp_path / "dispensadas.json"),
            presenca=presenca or (lambda: {"ligada": False, "variavel": "NOAH_PRESENCE_ENABLED",
                                           "itens": [], "falhas": []}),
            sinal=sinal or (lambda: {"janela_s": 600, "cerebro": {}, "auxiliares": {}, "falhas": []}),
            atividade=lambda: {"ollama": True, "modelos": [], "rotas": {}, "cerebro": {"pastas": []},
                               "eventos": [{"quando": 1.0, "tipo": "auxiliar", "de": "agente",
                                            "para": "qwen2.5-coder:7b", "texto": "tarefa mecanica"}],
                               "falhas": []},
            conversas=Conversas(turno or (lambda h: "oi"), info=lambda: {"provedor": "ollama", "modelo": "m"}),
        )
        srv.respondidas = respondidas
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
    h = {"Host": f"127.0.0.1:{porta}"}
    if corpo is not None:
        bruto = json.dumps(corpo).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn.request(metodo, caminho, body=bruto, headers=h)
    resp = conn.getresponse()
    dados = resp.read()
    conn.close()
    try:
        dados = json.loads(dados)
    except ValueError:
        pass
    return resp.status, dict(resp.getheaders()), dados


def test_lista_pendencias(servidor_factory):
    srv = servidor_factory()
    status, _, dados = _req(srv, "GET", "/central/api/pendencias")
    assert status == 200
    assert [i["chave"] for i in dados["itens"]] == ["claude:s1", "noah:p-1"]
    assert dados["falhas"] == ["Codex"] and dados["respondendo"] == []
    assert all("cwd" not in i and i["respondendo"] is False for i in dados["itens"])


def test_pagina_sem_token_com_cabecalhos(servidor_factory):
    srv = servidor_factory(token="segredo")
    status, h, corpo = _req(srv, "GET", "/central/")
    assert status == 200 and b"Pend" in corpo
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff" and h["Cache-Control"] == "no-store"
    for caminho in ("/central/app.js", "/central/manifest.webmanifest", "/central/icone.svg",
                    "/central/icone-180.png", "/central/icone-512.png"):
        assert _req(srv, "GET", caminho)[0] == 200
    assert _req(srv, "GET", "/central/icone-180.png")[2].startswith(b"\x89PNG")
    status, h, _ = _req(srv, "GET", "/")
    assert status == 302 and h["Location"] == "/central/"


def test_token(servidor_factory):
    srv = servidor_factory(token="segredo")
    assert _req(srv, "GET", "/central/api/pendencias")[0] == 401
    assert _req(srv, "GET", "/central/api/pendencias", headers={"Authorization": "Bearer errado"})[0] == 401
    assert _req(srv, "GET", "/central/api/pendencias", headers={"Authorization": "Bearer segredo"})[0] == 200
    assert _req(srv, "POST", "/central/api/dispensar", {"fonte": "claude", "id": "s1"})[0] == 401
    assert _req(srv, "GET", "/central/api/presenca")[0] == 401
    assert _req(srv, "GET", "/central/api/presenca", headers={"Authorization": "Bearer segredo"})[0] == 200


def test_host_e_origem(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "GET", "/central/", headers={"Host": "evil.example"})[0] == 403
    assert _req(srv, "GET", "/central/api/pendencias", headers={"Host": "evil.example"})[0] == 403
    assert _req(srv, "GET", "/central/api/presenca", headers={"Host": "evil.example"})[0] == 403
    assert _req(srv, "GET", "/central/api/presenca", headers={"Origin": "https://evil.example"})[0] == 403
    corpo = {"fonte": "claude", "id": "s1", "texto": "oi"}
    assert _req(srv, "POST", "/central/api/responder", corpo, headers={"Origin": "https://evil.example"})[0] == 403
    porta = srv.server_address[1]
    status, _, _ = _req(srv, "POST", "/central/api/dispensar", {"fonte": "claude", "id": "s1"},
                        headers={"Origin": f"http://127.0.0.1:{porta}"})
    assert status == 200


@pytest.mark.parametrize("nome", ["localhost", "127.0.0.1", "Meu-Mac.local"])
def test_escuta_em_todas_interfaces_com_hosts_explicitos_exige_token(servidor_factory, nome):
    srv = servidor_factory(token="segredo", host="0.0.0.0",
                           hosts_adicionais=("localhost", "127.0.0.1", "meu-mac.local"))
    headers = {"Host": f"{nome}:{srv.server_address[1]}"}
    assert _req(srv, "GET", "/central/api/pendencias", headers=headers)[0] == 401
    headers["Authorization"] = "Bearer segredo"
    assert _req(srv, "GET", "/central/api/pendencias", headers=headers)[0] == 200


def test_hosts_adicionais_nao_liberam_host_ou_origem_arbitrarios(servidor_factory):
    srv = servidor_factory(token="segredo", host="0.0.0.0", hosts_adicionais=("meu-mac.local",))
    porta = srv.server_address[1]
    headers = {"Host": f"Meu-Mac.local:{porta}", "Authorization": "Bearer segredo"}
    headers["Origin"] = f"http://MEU-MAC.LOCAL:{porta}"
    assert _req(srv, "GET", "/central/api/pendencias", headers=headers)[0] == 200
    headers["Origin"] = "https://evil.example"
    assert _req(srv, "GET", "/central/api/pendencias", headers=headers)[0] == 403
    headers.pop("Origin")
    headers["Host"] = f"meu-mac.local.evil.example:{porta}"
    assert _req(srv, "GET", "/central/api/pendencias", headers=headers)[0] == 403


def test_main_carrega_hosts_explicitos_do_ambiente(monkeypatch):
    from unittest.mock import Mock

    fabrica = Mock()
    fabrica.return_value.server_address = ("0.0.0.0", 8769)
    fabrica.return_value.serve_forever.side_effect = KeyboardInterrupt
    monkeypatch.setattr(central_servidor, "ServidorCentral", fabrica)
    monkeypatch.setenv("NOAH_CENTRAL_HOSTS", "localhost,meu-mac.local")
    monkeypatch.delenv("NOAH_CENTRAL_VOZ", raising=False)
    assert central_servidor.main(["--host", "0.0.0.0", "--token", "teste"]) == 0
    fabrica.assert_called_once_with(("0.0.0.0", 8769), token="teste",
                                   hosts_adicionais=("localhost", "meu-mac.local"))
    fabrica.return_value.server_close.assert_called_once()


def test_post_exige_json_e_limita_corpo(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "POST", "/central/api/responder", bruto=b"fonte=claude",
                headers={"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    grande = b'{"x":"' + b"a" * (central_servidor.LIMITE_CORPO + 1) + b'"}'
    assert _req(srv, "POST", "/central/api/responder", bruto=grande,
                headers={"Content-Type": "application/json"})[0] == 413
    assert _req(srv, "POST", "/central/api/responder", bruto=b"[1]",
                headers={"Content-Type": "application/json"})[0] == 400


def test_responder(servidor_factory):
    srv = servidor_factory()
    status, _, dados = _req(srv, "POST", "/central/api/responder", {"fonte": "claude", "id": "s1", "texto": "pode"})
    assert status == 202 and dados["job"]["chave"] == "claude:s1"
    assert _req(srv, "POST", "/central/api/responder", {"fonte": "claude", "id": "nao-listado", "texto": "x"})[0] == 404
    assert _req(srv, "POST", "/central/api/responder", {"fonte": "noah", "id": "p-1", "texto": "x"})[0] == 400
    assert _req(srv, "POST", "/central/api/responder", {"fonte": "claude", "id": "s1"})[0] == 400
    longo = {"fonte": "claude", "id": "s1", "texto": "x" * 4001}
    assert _req(srv, "POST", "/central/api/responder", longo)[0] == 413


def test_dispensar_grava_a_versao(servidor_factory, tmp_path):
    srv = servidor_factory()
    status, _, dados = _req(srv, "POST", "/central/api/dispensar", {"fonte": "claude", "id": "s1"})
    assert status == 200 and dados == {"dispensada": "claude:s1"}
    assert Dispensadas(tmp_path / "dispensadas.json").carregar() == {"claude:s1": "v1"}


def test_rota_inexistente(servidor_factory):
    srv = servidor_factory()
    assert _req(srv, "GET", "/central/api/nada")[0] == 404
    assert _req(srv, "POST", "/central/api/nada", {})[0] == 404


def test_fora_do_loopback_exige_token(capsys, monkeypatch):
    monkeypatch.delenv("NOAH_CENTRAL_TOKEN", raising=False)
    with pytest.raises(ValueError, match="exige token"):
        ServidorCentral(("0.0.0.0", 0))
    assert central_servidor.main(["--host", "0.0.0.0", "--porta", "0"]) == 2
    assert "exige token" in capsys.readouterr().err


# -- app Noah: abas e presença ------------------------------------------------------


def test_app_noah_tem_duas_abas_e_manifesto_noah(servidor_factory):
    srv = servidor_factory()
    pagina = _req(srv, "GET", "/central/")[2].decode()
    assert "<title>Noah</title>" in pagina
    assert 'id="aba-pendencias"' in pagina and 'id="aba-presenca"' in pagina
    assert 'aria-labelledby="aba-presenca" hidden' in pagina
    manifesto = _req(srv, "GET", "/central/manifest.webmanifest")[2]
    assert manifesto["name"] == manifesto["short_name"] == "Noah"
    assert {"icone-180.png", "icone-512.png"} <= {i["src"] for i in manifesto["icons"]}


def test_app_js_so_insere_texto_por_textcontent(servidor_factory):
    js = _req(servidor_factory(), "GET", "/central/app.js")[2].decode()
    assert ".innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js


def test_presenca_desligada_nao_traz_numeros(servidor_factory):
    srv = servidor_factory()
    status, h, dados = _req(srv, "GET", "/central/api/presenca")
    assert status == 200 and h["Cache-Control"] == "no-store"
    assert dados["ligada"] is False and dados["itens"] == [] and dados["falhas"] == []
    assert dados["variavel"] == "NOAH_PRESENCE_ENABLED" and "gerado_em" in dados


def test_presenca_ligada_lista_fonte_porque_acao(servidor_factory):
    item = {"source": "Lembretes", "why": "2 vencidos", "action": "Abra os lembretes"}
    srv = servidor_factory(presenca=lambda: {"ligada": True, "variavel": "NOAH_PRESENCE_ENABLED",
                                             "itens": [item], "falhas": []})
    dados = _req(srv, "GET", "/central/api/presenca")[2]
    assert dados["ligada"] is True and dados["itens"] == [item]


def test_ler_presenca_desligada_nao_le_fontes(monkeypatch):
    from assistant import presence

    monkeypatch.setattr(presence, "is_enabled", lambda: False)
    monkeypatch.setattr(presence, "build_presence_items", lambda: pytest.fail("leu fontes desligada"))
    assert central_servidor.ler_presenca() == {
        "ligada": False, "variavel": presence.ENABLED_ENV_VAR, "itens": [], "falhas": []}


def test_ler_presenca_ligada_e_falha_vira_aviso(monkeypatch):
    from assistant import presence

    monkeypatch.setattr(presence, "is_enabled", lambda: True)
    monkeypatch.setattr(presence, "build_presence_items",
                        lambda: [presence.PresenceItem("Agenda", "reunião às 15h", "Revise a pauta")])
    estado = central_servidor.ler_presenca()
    assert estado["ligada"] is True and estado["falhas"] == []
    assert estado["itens"] == [{"source": "Agenda", "why": "reunião às 15h", "action": "Revise a pauta"}]

    def quebra():
        raise RuntimeError("fonte ilegível")

    monkeypatch.setattr(presence, "build_presence_items", quebra)
    estado = central_servidor.ler_presenca()
    assert estado["itens"] == [] and estado["falhas"] == ["Presença"]


def test_ler_presenca_respeita_a_variavel(monkeypatch):
    from assistant import presence

    monkeypatch.setattr(presence, "build_presence_items", lambda: [])
    monkeypatch.setenv(presence.ENABLED_ENV_VAR, "false")
    assert central_servidor.ler_presenca()["ligada"] is False
    monkeypatch.setenv(presence.ENABLED_ENV_VAR, "true")
    assert central_servidor.ler_presenca() == {
        "ligada": True, "variavel": presence.ENABLED_ENV_VAR, "itens": [], "falhas": []}


def test_sinal_do_cerebro_exige_token_e_traz_gerado_em(servidor_factory):
    sinal = {"janela_s": 600, "cerebro": {"claude": {"consultas": 2, "registros": 1, "ultima": 1.0}},
             "auxiliares": {"codex": {"delegacoes": 1, "ultima": 2.0}}, "falhas": []}
    srv = servidor_factory(token="t", sinal=lambda: sinal)
    status, _, _ = _req(srv, "GET", "/central/api/cerebro")
    assert status == 401
    status, _, dados = _req(srv, "GET", "/central/api/cerebro", headers={"Authorization": "Bearer t"})
    assert status == 200
    assert dados["cerebro"]["claude"]["consultas"] == 2
    assert dados["auxiliares"]["codex"]["delegacoes"] == 1
    assert isinstance(dados["gerado_em"], float)


def test_atividade_junta_turnos_do_noah(servidor_factory):
    def turno(historico):
        historico.append({"role": "tool", "content": "nota", "tool_name": "consult_cerebro"})
        return "achei no cofre"

    srv = servidor_factory(turno=turno)
    status, _, dados = _req(srv, "POST", "/central/api/conversa", {"mensagem": "o que diz o cérebro?"})
    assert status == 200
    assert dados["resposta"] == "achei no cofre" and dados["ferramentas"] == ["consult_cerebro"]
    assert dados["modelo"] == "m" and dados["sessao"]

    status, _, dados = _req(srv, "GET", "/central/api/atividade")
    assert status == 200
    assert [e["tipo"] for e in dados["eventos"]] == ["noah", "auxiliar"]
    assert dados["eventos"][0]["para"] == "cerebro"
    assert dados["noah"]["respondendo_desde"] is None and len(dados["noah"]["turnos"]) == 1


def test_conversa_valida_e_exige_token(servidor_factory):
    srv = servidor_factory(token="segredo")
    assert _req(srv, "POST", "/central/api/conversa", {"mensagem": "oi"})[0] == 401
    assert _req(srv, "GET", "/central/api/atividade")[0] == 401
    auth = {"Authorization": "Bearer segredo"}
    assert _req(srv, "POST", "/central/api/conversa", {"mensagem": "  "}, headers=auth)[0] == 400
    assert _req(srv, "POST", "/central/api/conversa", {"mensagem": "x" * 4001}, headers=auth)[0] == 413
    assert _req(srv, "POST", "/central/api/conversa", {"mensagem": "oi", "sessao": 3}, headers=auth)[0] == 400
    status, _, dados = _req(srv, "POST", "/central/api/conversa", {"mensagem": "oi"}, headers=auth)
    assert status == 200 and dados["resposta"] == "oi"
    assert _req(srv, "POST", "/central/api/conversa/cancelar", {"request_id": "x"})[0] == 401
    status, _, dados = _req(
        srv, "POST", "/central/api/conversa/cancelar", {"request_id": "cancelado-antes"}, headers=auth
    )
    assert status == 200 and dados == {"ok": True}
    status, _, dados = _req(
        srv, "POST", "/central/api/conversa",
        {"mensagem": "não iniciar", "request_id": "cancelado-antes"}, headers=auth,
    )
    assert status == 409 and dados["erro"] == "pedido cancelado"
