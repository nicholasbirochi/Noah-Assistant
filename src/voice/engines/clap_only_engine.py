"""Audio framing for clap-only activation; no spoken-keyword detector."""

from __future__ import annotations


class ClapOnlyEngine:
    frame_length = 1280
    sample_rate = 16000

    def process(self, frame: list[int]) -> bool:
        return False

    def close(self) -> None:
        pass
