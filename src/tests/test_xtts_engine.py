import threading
import time

import pytest

import config
from voice import xtts_engine


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    # _model/_load_started/_conditioning_cache are module-level singletons
    # by design (the real model loads, and its reference clip's
    # conditioning latents compute, exactly once per process) -- reset
    # them around every test so tests don't leak state into each other.
    monkeypatch.setattr(xtts_engine, "_model", None)
    monkeypatch.setattr(xtts_engine, "_load_started", False)
    monkeypatch.setattr(xtts_engine, "_conditioning_cache", None)


def test_has_reference_audio_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "missing.wav")

    assert xtts_engine.has_reference_audio() is False


def test_has_reference_audio_true_when_file_exists(tmp_path, monkeypatch):
    path = tmp_path / "reference.wav"
    path.write_bytes(b"fake wav")
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", path)

    assert xtts_engine.has_reference_audio() is True


def test_is_ready_false_before_any_load():
    assert xtts_engine.is_ready() is False


def test_is_ready_true_once_model_is_set(monkeypatch):
    monkeypatch.setattr(xtts_engine, "_model", object())

    assert xtts_engine.is_ready() is True


def test_preload_in_background_noop_when_no_reference_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "missing.wav")
    load_calls = []
    monkeypatch.setattr(xtts_engine, "_load", lambda: load_calls.append(1))

    xtts_engine.preload_in_background()
    time.sleep(0.05)  # give a thread a chance to start, if one wrongly did

    assert load_calls == []
    assert xtts_engine.is_ready() is False


def test_preload_in_background_starts_load_thread_when_reference_exists(tmp_path, monkeypatch):
    path = tmp_path / "reference.wav"
    path.write_bytes(b"fake wav")
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", path)

    started = threading.Event()
    monkeypatch.setattr(xtts_engine, "_load", lambda: started.set())

    xtts_engine.preload_in_background()
    assert started.wait(timeout=2), "background load never started"


def test_preload_in_background_only_starts_once(tmp_path, monkeypatch):
    path = tmp_path / "reference.wav"
    path.write_bytes(b"fake wav")
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", path)

    call_count = []
    done = threading.Event()

    def fake_load():
        call_count.append(1)
        done.set()

    monkeypatch.setattr(xtts_engine, "_load", fake_load)

    xtts_engine.preload_in_background()
    assert done.wait(timeout=2)
    xtts_engine.preload_in_background()  # second call -- must not start another thread
    xtts_engine.preload_in_background()

    assert len(call_count) == 1


def test_load_degrades_gracefully_when_model_build_fails(monkeypatch, capsys):
    # e.g. voice-cloning extras not installed, or the download failed --
    # must never crash the background thread silently; is_ready() should
    # just stay False so tts.py keeps using the say-based fallback.
    def _raise():
        raise ModuleNotFoundError("No module named 'TTS'")

    monkeypatch.setattr(xtts_engine, "_build_model", _raise)

    xtts_engine._load()

    assert xtts_engine.is_ready() is False
    assert "falha ao carregar o modelo" in capsys.readouterr().err


def test_synthesize_to_file_raises_when_model_not_loaded():
    with pytest.raises(RuntimeError):
        xtts_engine.synthesize_to_file("olá", "/tmp/out.wav")


def test_synthesize_to_file_delegates_to_loaded_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "reference.wav")
    monkeypatch.setattr(config, "TTS_XTTS_LANGUAGE", "pt")

    calls = []

    class FakeModel:
        def tts_to_file(self, *, text, speaker_wav, language, file_path):
            calls.append((text, speaker_wav, language, file_path))

    monkeypatch.setattr(xtts_engine, "_model", FakeModel())

    xtts_engine.synthesize_to_file("olá", "/tmp/out.wav")

    assert calls == [("olá", str(tmp_path / "reference.wav"), "pt", "/tmp/out.wav")]


# ---- synthesize_stream ----


class FakeTokenizer:
    char_limits = {"pt": 203}


class FakeTtsModel:
    tokenizer = FakeTokenizer()

    def __init__(self, chunks, latents=("cond_latent", "spk_emb")):
        self.chunks = chunks
        self.latents = latents
        self.conditioning_calls: list[str] = []
        self.inference_calls: list[tuple] = []

    def get_conditioning_latents(self, audio_path):
        self.conditioning_calls.append(audio_path)
        return self.latents

    def inference_stream(self, text, language, gpt_cond_latent, speaker_embedding, **options):
        # XTTS's own splitting needs spaCy, which this project doesn't install.
        assert options == {"stream_chunk_size": 0, "enable_text_splitting": False}
        self.inference_calls.append((text, language, gpt_cond_latent, speaker_embedding))
        yield from self.chunks


class FakeSynthesizer:
    def __init__(self, tts_model):
        self.tts_model = tts_model


class FakeModel:
    def __init__(self, tts_model):
        self.synthesizer = FakeSynthesizer(tts_model)


def test_synthesize_stream_raises_when_model_not_loaded():
    with pytest.raises(RuntimeError):
        list(xtts_engine.synthesize_stream("olá"))


def _expected_pcm16_bytes(values):
    import numpy as np

    clipped = np.clip(np.array(values, dtype=np.float64), -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


def test_synthesize_stream_yields_pcm16_bytes_per_chunk(monkeypatch, tmp_path):
    import numpy as np

    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "reference.wav")
    monkeypatch.setattr(config, "TTS_XTTS_LANGUAGE", "pt")
    tts_model = FakeTtsModel(chunks=[np.array([0.5, -0.5]), np.array([1.0, -1.0])])
    monkeypatch.setattr(xtts_engine, "_model", FakeModel(tts_model))

    chunks = list(xtts_engine.synthesize_stream("olá"))

    assert chunks == [_expected_pcm16_bytes([0.5, -0.5]), _expected_pcm16_bytes([1.0, -1.0])]


def test_synthesize_stream_passes_configured_language_and_text(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "reference.wav")
    monkeypatch.setattr(config, "TTS_XTTS_LANGUAGE", "pt")
    tts_model = FakeTtsModel(chunks=[])
    monkeypatch.setattr(xtts_engine, "_model", FakeModel(tts_model))

    list(xtts_engine.synthesize_stream("bom dia"))

    assert tts_model.inference_calls == [("bom dia", "pt", "cond_latent", "spk_emb")]


def test_synthesize_stream_computes_conditioning_latents_from_reference_wav(monkeypatch, tmp_path):
    reference = tmp_path / "reference.wav"
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", reference)
    tts_model = FakeTtsModel(chunks=[])
    monkeypatch.setattr(xtts_engine, "_model", FakeModel(tts_model))

    list(xtts_engine.synthesize_stream("olá"))

    assert tts_model.conditioning_calls == [str(reference)]


def test_synthesize_stream_reuses_cached_conditioning_latents_across_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "reference.wav")
    tts_model = FakeTtsModel(chunks=[])
    monkeypatch.setattr(xtts_engine, "_model", FakeModel(tts_model))

    list(xtts_engine.synthesize_stream("primeira"))
    list(xtts_engine.synthesize_stream("segunda"))

    assert len(tts_model.conditioning_calls) == 1  # not recomputed the second time


def test_synthesize_stream_splits_a_reply_that_reaches_the_character_limit(monkeypatch, tmp_path):
    import numpy as np

    monkeypatch.setattr(config, "TTS_XTTS_SPEAKER_WAV_PATH", tmp_path / "reference.wav")
    monkeypatch.setattr(config, "TTS_XTTS_LANGUAGE", "pt")
    tts_model = FakeTtsModel(chunks=[np.array([0.5])])
    monkeypatch.setattr(xtts_engine, "_model", FakeModel(tts_model))
    texto = " ".join(f"Esta é a frase número {n} da resposta do Noah." for n in range(12))

    chunks = list(xtts_engine.synthesize_stream(texto))

    pedacos = [chamada[0] for chamada in tts_model.inference_calls]
    assert len(pedacos) > 1
    assert all(len(pedaco) <= 203 for pedaco in pedacos)
    assert " ".join(pedacos) == texto
    assert len(chunks) == len(pedacos)


# ---- _frases ----


@pytest.mark.parametrize(
    ("texto", "limite", "esperado"),
    [
        # Below the limit, several sentences stay together.
        ("Bom dia. Tudo certo?", 203, ["Bom dia. Tudo certo?"]),
        # Exactly at the limit is still within what XTTS accepts.
        ("a" * 30, 30, ["a" * 30]),
        # Whole sentences are joined up to the limit.
        (
            "Primeira frase curta. Segunda frase. Terceira frase aqui.",
            40,
            ["Primeira frase curta. Segunda frase.", "Terceira frase aqui."],
        ),
        # A long sentence is cut at a comma in the second half of the limit.
        (
            "um dois tres quatro, cinco seis sete oito nove dez",
            30,
            ["um dois tres quatro,", "cinco seis sete oito nove dez"],
        ),
        # An early comma would leave a tiny fragment, so a space wins.
        (
            "um, dois tres quatro cinco seis sete oito nove",
            30,
            ["um, dois tres quatro cinco", "seis sete oito nove"],
        ),
        # A decimal comma is not a clause.
        (
            "o valor total ficou em 1234,56 reais neste mes corrente",
            30,
            ["o valor total ficou em", "1234,56 reais neste mes", "corrente"],
        ),
        # With no separator at all, the cut stays within the limit.
        ("a" * 70, 30, ["a" * 30, "a" * 30, "a" * 10]),
    ],
)
def test_frases_splits_within_the_limit(texto, limite, esperado):
    assert xtts_engine._frases(texto, limite) == esperado


def test_to_pcm16_bytes_clips_out_of_range_values():
    import numpy as np

    result = xtts_engine._to_pcm16_bytes(np.array([2.0, -2.0]))

    assert result == _expected_pcm16_bytes([1.0, -1.0])
