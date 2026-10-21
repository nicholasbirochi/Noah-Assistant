"""Conversa com o Noah pela aba Central do app (mesmo turno do modo texto).

Mesmo turno de ``assistant.llm_client.send_turn``, com as mesmas ferramentas e
as mesmas travas (escrita só com confirmação do Nicholas). O histórico fica em
memória, com teto de sessões e de mensagens; nada vai para disco.

Cada turno registra quais ferramentas o Noah chamou (``consult_cerebro`` etc.),
lidas das mensagens ``role == "tool"`` que o próprio turno acrescentou: é daí
que sai a seta "Noah -> Cérebro" do Fluxo, só quando aconteceu de verdade.

Um turno por vez: o modelo local roda numa máquina de 24 GB e duas gerações em
paralelo só disputariam memória; o segundo pedido recebe 409 na hora em vez de
ficar na fila.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict, deque
from typing import Callable

LIMITE_MENSAGEM = 4000
MAX_SESSOES = 16
MAX_MENSAGENS_POR_SESSAO = 200
MAX_EVENTOS = 20

Turno = Callable[[list], str]


class ConversaRecusada(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def _turno_padrao(messages: list) -> str:
    # Import tardio: subir a central (e os testes) não carrega ollama/ferramentas.
    from assistant.llm_client import send_turn

    return send_turn(messages)


def info_modelo() -> dict:
    import config

    modelo = config.MLX_MODEL if config.LLM_PROVIDER == "mlx" else config.LOCAL_MODEL
    return {"provedor": config.LLM_PROVIDER, "modelo": modelo}


class Conversas:
    def __init__(self, turno: Turno = _turno_padrao, *, info: Callable[[], dict] = info_modelo,
                 max_sessoes: int = MAX_SESSOES):
        self._turno = turno
        self._info = info
        self._max = max_sessoes
        self._sessoes: OrderedDict[str, list] = OrderedDict()
        self._eventos: deque[dict] = deque(maxlen=MAX_EVENTOS)
        self._trava_turno = threading.Lock()
        self._trava = threading.Lock()
        self._respondendo_desde: float | None = None

    def _historico(self, sessao: str | None) -> tuple[str, list]:
        with self._trava:
            if sessao and sessao in self._sessoes:
                self._sessoes.move_to_end(sessao)
                return sessao, self._sessoes[sessao]
            novo = secrets.token_urlsafe(12)
            self._sessoes[novo] = []
            while len(self._sessoes) > self._max:
                self._sessoes.popitem(last=False)
            return novo, self._sessoes[novo]

    def conversar(self, mensagem: object, sessao: object = None) -> dict:
        if not isinstance(mensagem, str) or not mensagem.strip():
            raise ConversaRecusada(400, "campo 'mensagem' (texto) é obrigatório")
        if len(mensagem) > LIMITE_MENSAGEM:
            raise ConversaRecusada(413, f"mensagem acima de {LIMITE_MENSAGEM} caracteres")
        if sessao is not None and not isinstance(sessao, str):
            raise ConversaRecusada(400, "campo 'sessao' deve ser texto")
        if not self._trava_turno.acquire(blocking=False):
            raise ConversaRecusada(409, "o Noah ainda está respondendo a outra mensagem")
        try:
            ident, historico = self._historico(sessao)
            if len(historico) >= MAX_MENSAGENS_POR_SESSAO:
                raise ConversaRecusada(409, "conversa longa demais; comece uma nova")
            antes = len(historico)
            historico.append({"role": "user", "content": mensagem.strip()})
            self._respondendo_desde = time.time()
            try:
                resposta = self._turno(historico)
            except Exception as exc:
                del historico[antes:]
                raise ConversaRecusada(502, f"falha no modelo local: {type(exc).__name__}") from exc
            finally:
                self._respondendo_desde = None
            ferramentas = list(dict.fromkeys(
                m["tool_name"] for m in historico[antes:]
                if m.get("role") == "tool" and isinstance(m.get("tool_name"), str)
            ))
            self._eventos.appendleft({"quando": time.time(), "ferramentas": ferramentas})
            return {"sessao": ident, "resposta": resposta, "ferramentas": ferramentas, **self._info()}
        finally:
            self._trava_turno.release()

    def estado(self) -> dict:
        """Para o Fluxo e o feed: se há turno rodando e os últimos turnos (sem o texto)."""
        return {
            "respondendo_desde": self._respondendo_desde,
            "turnos": list(self._eventos),
            **self._info(),
        }
