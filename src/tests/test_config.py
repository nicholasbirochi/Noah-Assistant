"""Regression coverage for the DATA_DIR vs. LOCAL_STATE_DIR split -- the
whole project lives inside an actively-synced OneDrive folder, so anything
that must never leave this machine (site-adapter login sessions, and any
future evidence with incidental PII) has to live outside PROJECT_ROOT
entirely, not just be .gitignore'd. See config.py's LOCAL_STATE_DIR
comment for the full story."""

from pathlib import Path
import runpy

import pytest

import config


def test_local_state_dir_is_not_inside_project_root():
    assert config.PROJECT_ROOT not in config.LOCAL_STATE_DIR.parents
    assert config.LOCAL_STATE_DIR != config.PROJECT_ROOT


def test_sites_state_dir_lives_under_local_state_dir_not_data_dir():
    assert config.LOCAL_STATE_DIR in config.SITES_STATE_DIR.parents
    assert config.DATA_DIR not in config.SITES_STATE_DIR.parents


def test_sites_evidence_dir_lives_under_sites_state_dir():
    assert config.SITES_STATE_DIR in config.SITES_EVIDENCE_DIR.parents


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for name in ("NOAH_LOCAL_STATE_DIR", "NOAH_MODEL_CODING", "WAKE_WORD_ENGINE"):
        monkeypatch.delenv(name, raising=False)
    return lambda: runpy.run_path(config.__file__)


@pytest.mark.parametrize("value", [None, "local-model", ""])
def test_noah_environment_configuration(monkeypatch, isolated_config, value):
    if value is not None:
        monkeypatch.setenv("NOAH_MODEL_CODING", value)
    assert isolated_config()["CODING_MODEL"] == value


def test_noah_defaults_use_only_noah_paths(isolated_config, tmp_path):
    values = isolated_config()
    state = tmp_path / "Library" / "Application Support" / "Noah"
    assert values["LOCAL_STATE_DIR"] == state
    assert values["TTS_XTTS_SPEAKER_WAV_PATH"] == state / "voice" / "noah_reference.wav"
    assert values["WAKE_WORD_ENGINE"] == "clap"


def test_indexer_excludes_its_actual_project_directory():
    assert config.PROJECT_ROOT in config.EXCLUDED_INDEX_PATHS


def test_noah_stop_phrases():
    assert config.STOP_PHRASES == ("tchau noah", "tchau, noah", "obrigado noah", "encerrar")
