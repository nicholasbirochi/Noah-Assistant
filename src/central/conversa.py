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
MAX_PEDIDOS = 512
TEMPO_PEDIDO_S = 3600
TEMPO_FILA_S = 180

Turno = Callable[[list], str]


class ConversaRecusada(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def _turno_padrao(messages: list, cancelado: Callable[[], bool] | None = None) -> str:
    # Import tardio: subir a central (e os testes) não carrega ollama/ferramentas.
    from assistant.llm_client import send_turn

    return send_turn(messages, should_cancel=cancelado)


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
        self._pedido_ativo: str | None = None
        # request_id -> (status, timestamp). Unknown cancellations are kept
        # briefly so a cancel arriving just before its conversation POST wins.
        self._pedidos: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def _limpar_pedidos(self, agora: float) -> None:
        expirados = [ident for ident, (status, quando) in self._pedidos.items()
                     if status != "ativo" and agora - quando > TEMPO_PEDIDO_S]
        for ident in expirados:
            self._pedidos.pop(ident, None)
        while len(self._pedidos) > MAX_PEDIDOS:
            ident = next((i for i, (status, _) in self._pedidos.items() if status != "ativo"), None)
            if ident is None:
                break
            self._pedidos.pop(ident, None)

    def _cancelado(self, request_id: str | None) -> bool:
        if request_id is None:
            return False
        with self._trava:
            registro = self._pedidos.get(request_id)
            return bool(registro and registro[0] == "cancelado")

    def cancelar(self, request_id: object) -> dict:
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
            raise ConversaRecusada(400, "campo 'request_id' (texto de até 128 caracteres) é obrigatório")
        ident = request_id.strip()
        agora = time.time()
        with self._trava:
            self._limpar_pedidos(agora)
            anterior = self._pedidos.get(ident)
            if anterior is None or anterior[0] != "concluido":
                self._pedidos[ident] = ("cancelado", agora)
                self._pedidos.move_to_end(ident)
            self._limpar_pedidos(agora)
        return {"ok": True}

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

    def conversar(self, mensagem: object, sessao: object = None, request_id: object = None) -> dict:
        if not isinstance(mensagem, str) or not mensagem.strip():
            raise ConversaRecusada(400, "campo 'mensagem' (texto) é obrigatório")
        if len(mensagem) > LIMITE_MENSAGEM:
            raise ConversaRecusada(413, f"mensagem acima de {LIMITE_MENSAGEM} caracteres")
        if sessao is not None and not isinstance(sessao, str):
            raise ConversaRecusada(400, "campo 'sessao' deve ser texto")
        if request_id is not None and (
            not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128
        ):
            raise ConversaRecusada(400, "campo 'request_id' deve ser texto de até 128 caracteres")
        pedido = request_id.strip() if isinstance(request_id, str) else None
        if pedido is not None:
            with self._trava:
                self._limpar_pedidos(time.time())
                registro = self._pedidos.get(pedido)
                if registro and registro[0] == "cancelado":
                    raise ConversaRecusada(409, "pedido cancelado")
                if registro:
                    raise ConversaRecusada(409, "pedido já recebido; use um novo request_id")
                if len(self._pedidos) >= MAX_PEDIDOS:
                    raise ConversaRecusada(429, "muitos pedidos recentes; tente novamente em instantes")
                self._pedidos[pedido] = ("ativo", time.time())
                self._pedidos.move_to_end(pedido)
                self._limpar_pedidos(time.time())
        adquirido = self._trava_turno.acquire(blocking=False)
        if not adquirido:
            with self._trava:
                anterior = self._pedido_ativo
            if pedido is None or not self._cancelado(anterior):
                self._remover_pedido_ativo(pedido)
                raise ConversaRecusada(409, "o Noah ainda está respondendo a outra mensagem")
            # Preserve the next utterance while the canceled provider call closes.
            # A bound also covers custom providers which do not support cancellation.
            limite = time.monotonic() + TEMPO_FILA_S
            while not adquirido:
                if self._cancelado(pedido):
                    raise ConversaRecusada(409, "pedido cancelado enquanto aguardava")
                if time.monotonic() >= limite:
                    self._remover_pedido_ativo(pedido)
                    raise ConversaRecusada(503, "o modelo demorou a liberar a conversa; tente novamente")
                adquirido = self._trava_turno.acquire(timeout=0.1)
        with self._trava:
            self._pedido_ativo = pedido
        try:
            if self._cancelado(pedido):
                raise ConversaRecusada(409, "pedido cancelado")
            ident, historico = self._historico(sessao)
            if len(historico) >= MAX_MENSAGENS_POR_SESSAO:
                raise ConversaRecusada(409, "conversa longa demais; comece uma nova")
            antes = len(historico)
            historico.append({"role": "user", "content": mensagem.strip()})
            self._respondendo_desde = time.time()
            try:
                if self._turno is _turno_padrao:
                    resposta = self._turno(historico, lambda: self._cancelado(pedido))
                else:
                    resposta = self._turno(historico)
                if self._cancelado(pedido):
                    del historico[antes:]
                    raise ConversaRecusada(409, "pedido cancelado")
            except ConversaRecusada:
                del historico[antes:]
                raise
            except Exception as exc:
                del historico[antes:]
                if self._cancelado(pedido):
                    raise ConversaRecusada(409, "pedido cancelado") from exc
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
            with self._trava:
                self._pedido_ativo = None
            self._trava_turno.release()
            if pedido is not None:
                with self._trava:
                    registro = self._pedidos.get(pedido)
                    if registro and registro[0] != "cancelado":
                        self._pedidos[pedido] = ("concluido", time.time())
                    self._limpar_pedidos(time.time())

    def _remover_pedido_ativo(self, request_id: str | None) -> None:
        if request_id is None:
            return
        with self._trava:
            registro = self._pedidos.get(request_id)
            if registro and registro[0] == "ativo":
                self._pedidos.pop(request_id, None)

    def estado(self) -> dict:
        """Para o Fluxo e o feed: se há turno rodando e os últimos turnos (sem o texto)."""
        return {
            "respondendo_desde": self._respondendo_desde,
            "turnos": list(self._eventos),
            **self._info(),
        }
