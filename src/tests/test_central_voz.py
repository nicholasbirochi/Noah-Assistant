import io
import struct

from central import voz


class Handler:
    def __init__(self, body):
        self.body = body
        self.wfile = io.BytesIO()
        self.headers = {}
        self.status = None

    def _ler_json(self):
        return self.body

    def _erro(self, status, mensagem):
        self.status = status

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


def test_not_ready_returns_503_without_generating(monkeypatch):
    monkeypatch.setattr(voz.xtts_client, 'is_ready', lambda: False)
    h = Handler({'texto': 'Olá'})
    voz.transmitir(h)
    assert h.status == 503
    assert not h.wfile.getvalue()


def test_rejects_invalid_or_oversized_text():
    for value in [None, '', '  ', 'a' * 1501, 4]:
        h = Handler({'texto': value})
        voz.transmitir(h)
        assert h.status == 400


def test_stream_framing_and_generator_cleanup(monkeypatch):
    closed = []
    def synth(text):
        assert text == 'Olá'
        try:
            yield b'\x01\x00'
            yield b'\x02\x00'
        finally:
            closed.append(True)
    monkeypatch.setattr(voz.xtts_client, 'is_ready', lambda: True)
    monkeypatch.setattr(voz.xtts_client, 'synthesize_stream', synth)
    h = Handler({'texto': ' Olá '})
    voz.transmitir(h)
    assert h.status == 200
    assert h.headers['Content-Type'] == 'application/vnd.noah.pcm'
    assert h.wfile.getvalue() == struct.pack('>I', 2) + b'\x01\x00' + struct.pack('>I', 2) + b'\x02\x00' + bytes(4)
    assert closed == [True]
    assert voz._trava.acquire(blocking=False)
    voz._trava.release()


def test_missing_local_model_never_imports_or_downloads_tts(tmp_path, monkeypatch):
    from voice import xtts_engine
    monkeypatch.setenv('NOAH_XTTS_MODEL_DIR', str(tmp_path))
    import pytest
    with pytest.raises(RuntimeError, match='nenhum download'):
        xtts_engine._build_model()
