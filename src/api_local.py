"""API local do Noah (F7, primeira versão): HTTP + JSON só com a biblioteca
padrão, sem FastAPI/uvicorn (dependência ainda não autorizada).

Expõe o mesmo turno de conversa do modo texto (`llm_client.send_turn`, com as
mesmas ferramentas e as mesmas travas), para que outro cliente -- um atalho,
uma página, depois o iPhone pela VPN -- converse com o Noah sem o terminal.

Endpoints:
  GET    /saude              -> {"status": "ok", "provider", "modelo"}
  POST   /conversa           {"mensagem", "sessao"?} -> {"sessao", "resposta"}
  DELETE /sessoes/<id>       -> 204 (esquece o histórico daquela sessão)

Segurança, por padrão:
- escuta só em 127.0.0.1; um endereço fora do loopback é recusado sem token;
- com token (NOAH_API_TOKEN ou --token), toda rota exige
  `Authorization: Bearer <token>`;
- POST exige `Content-Type: application/json` (um formulário de outra página
  não passa sem preflight de CORS, que esta API nunca libera) e o `Host` precisa
  ser o próprio endereço local (barra DNS rebinding);
- corpo limitado a 64 KB; histórico em memória, com teto de sessões e turnos.

Um turno de cada vez (trava global): o modelo local roda numa máquina de 24 GB
e duas gerações em paralelo só disputariam memória.

Uso:
  .venv/bin/python src/api_local.py [--porta 8768] [--host 127.0.0.1] [--token X]
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import secrets
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

# 8765 é o HUD, 8766 o XTTS e 8767 o portal; 8768 fica livre para esta API.
PORTA_PADRAO = 8768
LIMITE_CORPO = 64 * 1024
LIMITE_MENSAGEM = 4000
MAX_SESSOES = 32
MAX_MENSAGENS_POR_SESSAO = 200

Turno = Callable[[list], str]


def _turno_padrao(messages: list) -> str:
    # Import tardio: subir o módulo (e os testes) não carrega ollama/ferramentas.
    from assistant.llm_client import send_turn

    return send_turn(messages)


def _info_modelo() -> dict:
    import config

    modelo = config.MLX_MODEL if config.LLM_PROVIDER == "mlx" else config.LOCAL_MODEL
    return {"provider": config.LLM_PROVIDER, "modelo": modelo}


def e_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Sessoes:
    """Históricos em memória, do mais antigo ao mais recente; o mais antigo sai
    quando passa do teto. Nada vai para disco."""

    def __init__(self, maximo: int = MAX_SESSOES):
        self._maximo = maximo
        self._dados: OrderedDict[str, list] = OrderedDict()

    def obter(self, sessao: str | None) -> tuple[str, list]:
        if sessao and sessao in self._dados:
            self._dados.move_to_end(sessao)
            return sessao, self._dados[sessao]
        novo = secrets.token_urlsafe(12)
        self._dados[novo] = []
        while len(self._dados) > self._maximo:
            self._dados.popitem(last=False)
        return novo, self._dados[novo]

    def remover(self, sessao: str) -> bool:
        return self._dados.pop(sessao, None) is not None

    def __len__(self) -> int:
        return len(self._dados)


class ServidorNoah(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, endereco, *, turno: Turno = _turno_padrao, token: str | None = None,
                 info: Callable[[], dict] = _info_modelo):
        host = endereco[0]
        if not e_loopback(host) and not token:
            raise ValueError(f"recusado: escutar em {host} (fora do loopback) exige token")
        super().__init__(endereco, _Handler)
        self.turno = turno
        self.token = token
        self.info = info
        self.sessoes = Sessoes()
        self.trava_turno = threading.Lock()
        self.trava_sessoes = threading.Lock()

    def hosts_aceitos(self) -> set[str]:
        host, porta = self.server_address[:2]
        nomes = {host, "localhost", "127.0.0.1"} if e_loopback(host) else {host}
        return {f"{n}:{porta}" for n in nomes} | nomes


class _Handler(BaseHTTPRequestHandler):
    server: ServidorNoah

    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- assinatura da stdlib
        pass  # não registra o conteúdo das conversas

    # -- roteamento ---------------------------------------------------------

    def do_GET(self) -> None:
        if not self._autorizado():
            return
        if self.path == "/saude":
            self._json(200, {"status": "ok", **self.server.info()})
        else:
            self._erro(404, "rota inexistente")

    def do_POST(self) -> None:
        if not self._autorizado():
            return
        if self.path == "/conversa":
            self._conversa()
        else:
            self._erro(404, "rota inexistente")

    def do_DELETE(self) -> None:
        if not self._autorizado():
            return
        prefixo = "/sessoes/"
        if self.path.startswith(prefixo) and len(self.path) > len(prefixo):
            with self.server.trava_sessoes:
                existia = self.server.sessoes.remover(self.path[len(prefixo):])
            if existia:
                self.send_response(204)
                self.end_headers()
            else:
                self._erro(404, "sessão inexistente")
        else:
            self._erro(404, "rota inexistente")

    # -- regras -------------------------------------------------------------

    def _autorizado(self) -> bool:
        if self.headers.get("Host", "") not in self.server.hosts_aceitos():
            self._erro(403, "host não permitido")
            return False
        token = self.server.token
        if token:
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

    def _conversa(self) -> None:
        dados = self._ler_json()
        if dados is None:
            return
        mensagem = dados.get("mensagem")
        if not isinstance(mensagem, str) or not mensagem.strip():
            self._erro(400, "campo 'mensagem' (texto) é obrigatório")
            return
        if len(mensagem) > LIMITE_MENSAGEM:
            self._erro(413, f"mensagem acima de {LIMITE_MENSAGEM} caracteres")
            return
        sessao_pedida = dados.get("sessao")
        if sessao_pedida is not None and not isinstance(sessao_pedida, str):
            self._erro(400, "campo 'sessao' deve ser texto")
            return

        with self.server.trava_turno:
            with self.server.trava_sessoes:
                sessao, historico = self.server.sessoes.obter(sessao_pedida)
            if len(historico) >= MAX_MENSAGENS_POR_SESSAO:
                self._erro(409, "sessão longa demais; apague-a e comece outra")
                return
            tamanho_antes = len(historico)
            historico.append({"role": "user", "content": mensagem.strip()})
            try:
                resposta = self.server.turno(historico)
            except Exception as exc:  # o histórico volta ao estado anterior ao turno
                del historico[tamanho_antes:]
                self._erro(502, f"falha no modelo local: {type(exc).__name__}")
                return
        self._json(200, {"sessao": sessao, "resposta": resposta})

    # -- respostas ----------------------------------------------------------

    def _json(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _erro(self, status: int, detalhe: str) -> None:
        self._json(status, {"erro": detalhe})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="API local do Noah (F7, stdlib).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--porta", type=int, default=int(os.environ.get("NOAH_API_PORT", PORTA_PADRAO)))
    parser.add_argument("--token", default=os.environ.get("NOAH_API_TOKEN") or None)
    args = parser.parse_args(argv)
    try:
        servidor = ServidorNoah((args.host, args.porta), token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    host, porta = servidor.server_address[:2]
    print(f"Noah API em http://{host}:{porta} (token: {'sim' if args.token else 'não'}). Ctrl+C encerra.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
