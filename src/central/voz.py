"""Authenticated Central proxy for the existing local cloned voice.

PCM stays in memory. The loopback worker is never exposed on the LAN; the
Central applies its normal Host, Origin, bearer and JSON size checks first.
"""

from __future__ import annotations

import struct
import threading

from voice import xtts_client

_trava = threading.Lock()


def estado() -> dict:
    return {"pronta": xtts_client.is_ready(), "voz": "clonada", "sample_rate": 24000}


def transmitir(handler) -> None:
    corpo = handler._ler_json()
    if corpo is None:
        return
    texto = corpo.get("texto")
    if not isinstance(texto, str) or not texto.strip() or len(texto) > 1500:
        handler._erro(400, "Informe texto entre 1 e 1500 caracteres")
        return
    if not xtts_client.is_ready():
        handler._erro(503, "A voz clonada ainda não está pronta no Mac")
        return
    if not _trava.acquire(blocking=False):
        handler._erro(409, "A voz está atendendo outra fala")
        return
    fluxo = None
    iniciou = False
    try:
        fluxo = xtts_client.synthesize_stream(texto.strip())
        primeiro = next(fluxo, b"")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/vnd.noah.pcm")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        iniciou = True
        for parte in _com_primeiro(primeiro, fluxo):
            handler.wfile.write(struct.pack(">I", len(parte)))
            handler.wfile.write(parte)
            handler.wfile.flush()
        handler.wfile.write(struct.pack(">I", 0))
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception:
        if not iniciou:
            handler._erro(503, "Não foi possível gerar a voz clonada agora")
    finally:
        try:
            if fluxo is not None:
                fluxo.close()
        finally:
            _trava.release()


def _com_primeiro(primeiro, fluxo):
    if primeiro:
        yield primeiro
    yield from fluxo
