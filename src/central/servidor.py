"""Servidor do app Noah: central de pendências + presença (stdlib, porta 8769).
Decisão em docs/ADR-0002.

Mesmas travas de src/api_local.py: escuta só no 127.0.0.1 por padrão; fora do
loopback, só com token (``Authorization: Bearer``); ``Host`` conferido; POST só
com ``application/json`` e corpo limitado; sem CORS, e um POST com ``Origin``
de outro site é recusado. A página e o manifesto abrem sem token porque não têm
dado nenhum; a lista e as ações sempre exigem o token, quando ele existe.

  GET  /central/                         -> página (PWA)
  GET  /central/api/pendencias           -> {itens, respondendo, falhas, gerado_em}
  GET  /central/api/presenca             -> {ligada, variavel, itens, falhas, gerado_em}
  GET  /central/api/cerebro              -> {janela_s, cerebro, auxiliares, falhas, gerado_em}
  GET  /central/api/atividade            -> {ollama, modelos, rotas, cerebro, eventos, noah, falhas, gerado_em}
  GET  /central/api/voz                  -> estado da voz clonada
  POST /central/api/voz                  {texto} -> PCM em blocos
  POST /central/api/responder            {fonte, id, texto} -> 202 {job}
  POST /central/api/dispensar            {fonte, id} -> 200 (guarda a versão atual)
  POST /central/api/conversa             {mensagem, sessao?, request_id?} -> {sessao, resposta, ferramentas, modelo}
  POST /central/api/conversa/cancelar    {request_id} -> {ok}
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import sys
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from central import fontes, sinal_cerebro
from central import atividade as atividade_mod
from central.conversa import ConversaRecusada, Conversas
from central.resposta import MAX_TEXTO, RespostaRecusada, Respostas

PORTA_PADRAO = 8769
LIMITE_CORPO = 64 * 1024

_PWA = Path(__file__).with_name("pwa")
ESTATICOS = {
    "/central/": ("index.html", "text/html; charset=utf-8"),
    "/central/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/central/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/central/icone.svg": ("icone.svg", "image/svg+xml"),
    # O iOS não aceita SVG como ícone da tela de início: PNG gerado do icone.svg.
    "/central/icone-180.png": ("icone-180.png", "image/png"),
    "/central/icone-512.png": ("icone-512.png", "image/png"),
}

CABECALHOS_ESTATICOS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "img-src 'self'; connect-src 'self'; manifest-src 'self'; form-action 'none'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

Listar = Callable[[], tuple[list[fontes.Pendencia], list[str]]]
Presenca = Callable[[], dict]
Sinal = Callable[[], dict]
Atividade = Callable[[], dict]


def ler_presenca() -> dict:
    """Aba Presença (docs/ADR-0001), só leitura. Desligada, não conta nada: a
    página diz como ligar em vez de mostrar números. Uma fonte ilegível já é
    pulada por build_presence_items(); se a leitura toda falhar, sai em
    ``falhas`` e a lista fica vazia -- nunca um número chutado."""
    from assistant import presence

    estado = {"ligada": presence.is_enabled(), "variavel": presence.ENABLED_ENV_VAR, "itens": [], "falhas": []}
    if not estado["ligada"]:
        return estado
    try:
        estado["itens"] = [asdict(i) for i in presence.build_presence_items()]
    except Exception:
        estado["falhas"] = ["Presença"]
    return estado


def e_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ServidorCentral(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, endereco, *, token: str | None = None, listar: Listar | None = None,
                 respostas: Respostas | None = None, dispensadas: fontes.Dispensadas | None = None,
                 presenca: Presenca | None = None, sinal: Sinal | None = None,
                 atividade: Atividade | None = None, conversas: Conversas | None = None):
        host = endereco[0]
        if not e_loopback(host) and not token:
            raise ValueError(f"recusado: escutar em {host} (fora do loopback) exige token")
        super().__init__(endereco, _Handler)
        self.token = token
        self.dispensadas = dispensadas or fontes.Dispensadas()
        self.listar = listar or (lambda: fontes.listar(dispensadas=self.dispensadas.carregar()))
        self.respostas = respostas or Respostas()
        self.presenca = presenca or ler_presenca
        self.sinal = sinal or sinal_cerebro.ler_sinal
        self.atividade = atividade or atividade_mod.ler_atividade
        self.conversas = conversas or Conversas()

    def hosts_aceitos(self) -> set[str]:
        host, porta = self.server_address[:2]
        nomes = {host, "localhost", "127.0.0.1"} if e_loopback(host) else {host}
        return {f"{n}:{porta}" for n in nomes} | nomes

    def achar(self, fonte: str, ident: str) -> fontes.Pendencia | None:
        """Só o que a própria central lista agora pode ser respondido ou dispensado."""
        itens, _ = self.listar()
        return next((p for p in itens if p.fonte == fonte and p.id == ident), None)


class _Handler(BaseHTTPRequestHandler):
    server: ServidorCentral

    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- assinatura da stdlib
        pass  # não registra o conteúdo das conversas

    # -- roteamento ---------------------------------------------------------

    def do_GET(self) -> None:
        caminho = urlsplit(self.path).path
        if caminho in ("/", "/central"):
            if self._autorizado(exigir_token=False):
                self.send_response(302)
                self.send_header("Location", "/central/")
                self.send_header("Content-Length", "0")
                self.end_headers()
            return
        if caminho in ESTATICOS:
            if self._autorizado(exigir_token=False):
                nome, tipo = ESTATICOS[caminho]
                self._estatico((_PWA / nome).read_bytes(), tipo)
            return
        if not self._autorizado():
            return
        if caminho == "/central/api/pendencias":
            self._pendencias()
        elif caminho == "/central/api/presenca":
            self._json(200, {**self.server.presenca(), "gerado_em": time.time()})
        elif caminho == "/central/api/cerebro":
            self._json(200, {**self.server.sinal(), "gerado_em": time.time()})
        elif caminho == "/central/api/atividade":
            self._atividade()
        elif caminho == "/central/api/voz":
            from central import voz

            self._json(200, voz.estado())
        else:
            self._erro(404, "rota inexistente")

    def do_POST(self) -> None:
        if not self._autorizado():
            return
        caminho = urlsplit(self.path).path
        if caminho == "/central/api/responder":
            self._responder()
        elif caminho == "/central/api/dispensar":
            self._dispensar()
        elif caminho == "/central/api/conversa":
            self._conversa()
        elif caminho == "/central/api/conversa/cancelar":
            self._cancelar_conversa()
        elif caminho == "/central/api/voz":
            self._voz()
        else:
            self._erro(404, "rota inexistente")

    # -- regras -------------------------------------------------------------

    def _autorizado(self, *, exigir_token: bool = True) -> bool:
        if self.headers.get("Host", "") not in self.server.hosts_aceitos():
            self._erro(403, "host não permitido")
            return False
        origem = self.headers.get("Origin")
        if origem is not None and urlsplit(origem).netloc not in self.server.hosts_aceitos():
            self._erro(403, "origem não permitida")
            return False
        token = self.server.token
        if token and exigir_token:
            enviado = self.headers.get("Authorization", "")
            if not hmac.compare_digest(enviado.encode(), f"Bearer {token}".encode()):
                self._erro(401, "token ausente ou inválido")
                return False
        return True

    def _ler_json(self) -> dict | None:
        tipo = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if tipo != "application/json":
            self._erro(415, "use Content-Type: application/json")
            return None
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            tamanho = -1
        if tamanho < 0 or tamanho > LIMITE_CORPO:
            self._erro(413, f"corpo acima de {LIMITE_CORPO} bytes ou sem Content-Length")
            return None
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._erro(400, "JSON inválido")
            return None
        if not isinstance(dados, dict):
            self._erro(400, "o corpo deve ser um objeto JSON")
            return None
        return dados

    def _alvo(self, dados: dict) -> fontes.Pendencia | None:
        fonte, ident = dados.get("fonte"), dados.get("id")
        if not isinstance(fonte, str) or not isinstance(ident, str):
            self._erro(400, "campos 'fonte' e 'id' (texto) são obrigatórios")
            return None
        alvo = self.server.achar(fonte, ident)
        if alvo is None:
            self._erro(404, "pendência não encontrada (já respondida ou fora da lista)")
        return alvo

    # -- ações --------------------------------------------------------------

    def _pendencias(self) -> None:
        itens, falhas = self.server.listar()
        ocupadas = self.server.respostas.ocupadas()
        lista = []
        for p in itens:
            dados = p.para_json()
            dados["respondendo"] = p.chave in ocupadas
            lista.append(dados)
        self._json(200, {
            "itens": lista,
            "respondendo": self.server.respostas.lista(),
            "falhas": falhas,
            "gerado_em": time.time(),
        })

    def _responder(self) -> None:
        dados = self._ler_json()
        if dados is None:
            return
        texto = dados.get("texto")
        if not isinstance(texto, str):
            self._erro(400, "campo 'texto' é obrigatório")
            return
        if len(texto) > MAX_TEXTO:
            self._erro(413, f"resposta acima de {MAX_TEXTO} caracteres")
            return
        alvo = self._alvo(dados)
        if alvo is None:
            return
        try:
            job = self.server.respostas.iniciar(alvo, texto)
        except RespostaRecusada as exc:
            self._erro(exc.status, exc.mensagem)
            return
        self._json(202, {"job": job.para_json()})

    def _dispensar(self) -> None:
        dados = self._ler_json()
        if dados is None:
            return
        alvo = self._alvo(dados)
        if alvo is None:
            return
        self.server.dispensadas.marcar(alvo.chave, alvo.versao)
        self._json(200, {"dispensada": alvo.chave})

    def _atividade(self) -> None:
        """Modelos, Cérebro e o feed: o que veio dos arquivos (atividade.py) mais
        o que só a central sabe -- respostas enviadas aos agentes e turnos do
        Noah nesta execução."""
        dados = self.server.atividade()
        noah = self.server.conversas.estado()
        eventos = list(dados.get("eventos", []))
        for job in self.server.respostas.lista():
            eventos.append({"quando": job["inicio"], "tipo": "resposta", "de": "central", "para": job["fonte"],
                            "texto": f"resposta para {job['titulo']} ({job['estado']})"})
        for turno in noah["turnos"]:
            usou = ", ".join(turno["ferramentas"])
            eventos.append({"quando": turno["quando"], "tipo": "noah", "de": "noah",
                            "para": "cerebro" if "consult_cerebro" in turno["ferramentas"] else "noah",
                            "texto": "Noah respondeu" + (f" usando {usou}" if usou else "")})
        eventos.sort(key=lambda e: e["quando"], reverse=True)
        self._json(200, {**dados, "eventos": eventos[:atividade_mod.MAX_EVENTOS], "noah": noah,
                         "gerado_em": time.time()})

    def _conversa(self) -> None:
        dados = self._ler_json()
        if dados is None:
            return
        try:
            corpo = self.server.conversas.conversar(
                dados.get("mensagem"), dados.get("sessao"), dados.get("request_id")
            )
        except ConversaRecusada as exc:
            self._erro(exc.status, exc.mensagem)
            return
        self._json(200, corpo)

    def _cancelar_conversa(self) -> None:
        dados = self._ler_json()
        if dados is None:
            return
        try:
            corpo = self.server.conversas.cancelar(dados.get("request_id"))
        except ConversaRecusada as exc:
            self._erro(exc.status, exc.mensagem)
            return
        self._json(200, corpo)

    def _voz(self) -> None:
        from central import voz

        voz.transmitir(self)

    # -- respostas ----------------------------------------------------------

    def _json(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _estatico(self, conteudo: bytes, tipo: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(conteudo)))
        for nome, valor in CABECALHOS_ESTATICOS.items():
            self.send_header(nome, valor)
        self.end_headers()
        self.wfile.write(conteudo)

    def _erro(self, status: int, detalhe: str) -> None:
        self._json(status, {"erro": detalhe})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="App Noah: central de pendências (Claude Code, Codex e Noah) e presença.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--porta", type=int, default=int(os.environ.get("NOAH_CENTRAL_PORT", PORTA_PADRAO)))
    parser.add_argument("--token", default=os.environ.get("NOAH_CENTRAL_TOKEN") or None)
    args = parser.parse_args(argv)
    if os.environ.get("NOAH_CENTRAL_VOZ") == "1":
        from voice import xtts_client

        xtts_client.ensure_worker_started()
    try:
        servidor = ServidorCentral((args.host, args.porta), token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    host, porta = servidor.server_address[:2]
    print(f"App Noah em http://{host}:{porta}/central/ (token: {'sim' if args.token else 'não'}). Ctrl+C encerra.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
