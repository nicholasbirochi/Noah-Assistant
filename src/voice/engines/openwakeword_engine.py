"""Optional spoken activation using an explicitly supplied local Noah model."""

from __future__ import annotations

from pathlib import Path

import numpy as np

FRAME_LENGTH = 1280  # 80ms @ 16kHz, per openWakeWord's documented frame requirement
SAMPLE_RATE = 16000
DEFAULT_THRESHOLD = 0.5


class OpenWakeWordEngine:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD, model_path: Path | None = None) -> None:
        from config import NOAH_WAKE_WORD_MODEL_PATH

        path = model_path if model_path is not None else NOAH_WAKE_WORD_MODEL_PATH
        if not path.is_file():
            raise FileNotFoundError(
                "Detector Noah local ausente. Configure NOAH_WAKE_WORD_MODEL_PATH "
                "ou use WAKE_WORD_ENGINE=clap."
            )
        from openwakeword.model import Model

        self._model = Model(wakeword_models=[str(path)], inference_framework="onnx")
        self._threshold = threshold

    @property
    def frame_length(self) -> int:
        return FRAME_LENGTH

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    def process(self, frame: list[int]) -> bool:
        scores = self._model.predict(np.array(frame, dtype=np.int16))
        return any(score >= self._threshold for score in scores.values())

    def close(self) -> None:
        pass
