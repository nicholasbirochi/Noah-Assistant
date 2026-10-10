import sys
from types import SimpleNamespace

import pytest

import config
from voice import wake_word
from voice.engines.openwakeword_engine import OpenWakeWordEngine


def test_clap_only_engine_never_reports_a_spoken_keyword(monkeypatch):
    monkeypatch.setattr(config, "WAKE_WORD_ENGINE", "clap")
    monkeypatch.setattr(config, "CLAP_ACTIVATION_ENABLED", True)
    engine = wake_word.get_wake_word_engine()
    assert engine.sample_rate == 16000
    assert engine.frame_length == 1280
    assert engine.process([0] * engine.frame_length) is False
    engine.close()


def test_clap_only_engine_rejects_disabled_activation(monkeypatch):
    monkeypatch.setattr(config, "WAKE_WORD_ENGINE", "clap")
    monkeypatch.setattr(config, "CLAP_ACTIVATION_ENABLED", False)
    with pytest.raises(ValueError, match="Noah"):
        wake_word.get_wake_word_engine()


def test_missing_noah_model_does_not_download_or_use_another_model(tmp_path):
    with pytest.raises(FileNotFoundError, match="Noah"):
        OpenWakeWordEngine(model_path=tmp_path / "noah.onnx")


def test_openwakeword_loads_only_the_supplied_local_model(monkeypatch, tmp_path):
    path = tmp_path / "noah.onnx"
    path.touch()
    calls = []
    model = SimpleNamespace(predict=lambda frame: {"noah": 0.8})
    monkeypatch.setitem(sys.modules, "openwakeword.model", SimpleNamespace(
        Model=lambda **kwargs: calls.append(kwargs) or model,
    ))
    engine = OpenWakeWordEngine(model_path=path)
    assert calls == [{"wakeword_models": [str(path)], "inference_framework": "onnx"}]
    assert engine.process([0] * engine.frame_length) is True
    engine.close()


def test_porcupine_requires_a_local_noah_model(monkeypatch, tmp_path):
    from voice.engines import porcupine_engine

    monkeypatch.setattr(porcupine_engine, "PICOVOICE_ACCESS_KEY", "synthetic-key")
    monkeypatch.setattr(porcupine_engine, "NOAH_PORCUPINE_MODEL_PATH", str(tmp_path / "noah.ppn"))
    with pytest.raises(FileNotFoundError, match="Noah"):
        porcupine_engine.PorcupineEngine()
