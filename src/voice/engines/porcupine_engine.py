"""Optional adapter -- kept for anyone who wants Porcupine's custom
wake-word training tools. Requires a local Noah keyword model and AccessKey."""

from __future__ import annotations

from pathlib import Path

import pvporcupine

from config import NOAH_PORCUPINE_MODEL_PATH, PICOVOICE_ACCESS_KEY


class PorcupineEngine:
    def __init__(self) -> None:
        if not PICOVOICE_ACCESS_KEY:
            raise RuntimeError(
                "PICOVOICE_ACCESS_KEY não configurada. Preencha o arquivo .env, "
                "ou use WAKE_WORD_ENGINE=clap (padrao, sem chave)."
            )
        path = Path(NOAH_PORCUPINE_MODEL_PATH).expanduser()
        if not path.is_file():
            raise FileNotFoundError("Configure NOAH_PORCUPINE_MODEL_PATH com um modelo Noah local.")
        self._porcupine = pvporcupine.create(access_key=PICOVOICE_ACCESS_KEY, keyword_paths=[str(path)])

    @property
    def frame_length(self) -> int:
        return self._porcupine.frame_length

    @property
    def sample_rate(self) -> int:
        return self._porcupine.sample_rate

    def process(self, frame: list[int]) -> bool:
        return self._porcupine.process(frame) >= 0

    def close(self) -> None:
        self._porcupine.delete()
