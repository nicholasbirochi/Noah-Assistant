"""XTTS-v2 voice cloning backend (github.com/idiap/coqui-ai-TTS, the
maintained fork -- the original coqui-ai/TTS is abandoned and doesn't run
on Python 3.12). Clones a voice from a short reference clip instead of
using one of macOS's built-in `say` voices; see tts.py for how this fits
into the overall speak() fallback chain.

Real, measured findings on this machine (M5, 24GB RAM, MPS available) that
shape the design here, not assumptions:
- Confirmed live with a real reference clip: loading takes ~13s, and
  generation runs at roughly real-time to faster (7.8s for a 7s reply,
  21.3s for a 29.7s reply -- 0.72x). Needs FFmpeg installed on the system
  (`brew install ffmpeg`) -- torchaudio's decoder loads its shared
  libraries at runtime; without it, synthesis fails with a clear
  "Could not load libtorchcodec" error.
- One earlier, isolated run -- before the real reference clip existed, using
  one of the model's own built-in preset voices -- took 15-17 minutes to
  load, for a reason never identified and never reproduced since. As a
  precaution the model still loads exactly ONCE per process on a background
  thread rather than being reloaded per-conversation (like stt.py does):
  preload_in_background() is meant to be called once, as early as possible
  (Noah startup, not first speak()), so even a repeat of that slow case
  would overlap with the user just having Noah on rather than blocking
  their first activation.
- That same earlier (pre-real-clip) comparison measured CPU as faster than
  MPS for this specific model (3.4s vs 11.4s to generate the same short
  sentence) -- MPS being "available" doesn't mean every op in this model
  has an efficient MPS kernel; per-op CPU fallback overhead can lose to
  just using CPU outright. device is hardcoded to "cpu" below for that
  reason, not auto-detected.

The native client buffers a complete reply before playback. On this Mac,
repeated short inference_stream blocks took 9.6s for 4.4s of audio, versus
4.8s with stream_chunk_size=0 (same seed and text, 2026-10-21). Completing
sentences avoids repeatedly decoding a growing waveform; the transport
still uses framed PCM and supports cancellation between blocks.

NEVER CALL preload_in_background() FROM THE MAIN Noah PROCESS: found
live that doing so made torchcodec dlopen the Homebrew-installed FFmpeg
into the same process that already has faster-whisper's own bundled
FFmpeg (via PyAV) loaded -- macOS logged a real ObjC class collision
(AVFFrameReceiver/AVFAudioReceiver defined in both libavdevice copies),
and wake-word/clap detection stopped firing entirely, silently, right
after. This module is only ever imported by xtts_worker.py now, a
genuinely separate OS process spawned by xtts_client.py -- see that
module's docstring. Safe there; never safe alongside PvRecorder.
"""

from __future__ import annotations

import os
import sys
import threading

_model = None
_model_lock = threading.Lock()
_load_started = False

# int16, mono -- XTTS-v2's own native output rate (confirmed live via the
# loaded model's synthesizer.output_sample_rate), not a guess. Whatever
# plays these chunks back (voice/tts.py, via ffplay) must be told
# this exact rate or the audio will sound pitched/sped up or down.
STREAM_SAMPLE_RATE = 24000

# (gpt_cond_latent, speaker_embedding) for the one reference clip this
# whole module clones from -- computed once (a real, measured ~0.2-0.4s,
# not free) and reused for every synthesize_stream() call rather than
# recomputed from the reference wav on every single reply.
_conditioning_cache = None


def has_reference_audio() -> bool:
    from config import TTS_XTTS_SPEAKER_WAV_PATH  # live lookup -- monkeypatchable in tests

    return TTS_XTTS_SPEAKER_WAV_PATH.exists()


def is_ready() -> bool:
    with _model_lock:
        return _model is not None


def preload_in_background() -> None:
    """Starts loading the model on a background thread, at most once per
    process. No-ops if there's no reference clip yet -- no point paying the
    15+ minute cost (and the model's real memory footprint) for a voice
    that can't clone anything. Safe to call repeatedly (e.g. once per
    wake-word session) -- only the first call actually starts a thread."""
    global _load_started

    if not has_reference_audio():
        return

    with _model_lock:
        if _load_started:
            return
        _load_started = True

    threading.Thread(target=_load, daemon=True, name="xtts-preload").start()


def _build_model():
    """Split out from _load() purely so tests can make this step fail
    without needing to fight a real (or really-absent) TTS import."""
    # Explicit paths bypass ModelManager's automatic model download.
    from pathlib import Path

    pasta = Path(os.environ.get(
        "NOAH_XTTS_MODEL_DIR",
        str(Path.home() / "Library/Application Support/tts/tts_models--multilingual--multi-dataset--xtts_v2"),
    ))
    if not all((pasta / nome).is_file() for nome in ("model.pth", "config.json", "vocab.json", "speakers_xtts.pth")):
        raise RuntimeError("Voz clonada não instalada localmente; nenhum download foi iniciado")
    from TTS.api import TTS
    from TTS.utils.synthesizer import Synthesizer

    model = TTS()
    model.synthesizer = Synthesizer(model_dir=str(pasta), use_cuda=False)
    model.config = model.synthesizer.tts_config
    return model.to("cpu")


def _load() -> None:
    global _model

    try:
        model = _build_model()
    except Exception as exc:
        # Runs on a daemon thread -- an uncaught exception here would just
        # print a traceback nobody's watching and silently leave is_ready()
        # False forever. tts.py already falls back to the say-based voice
        # whenever that's the case, so this is a degrade, not a crash --
        # but it should say why, not fail silently.
        print(
            f"[xtts] falha ao carregar o modelo ({exc}) -- dependências de "
            "voice-cloning instaladas? `pip install -e '.[voice-cloning]'`. "
            "Usando a voz padrão (say) por enquanto.",
            file=sys.stderr,
        )
        return

    with _model_lock:
        _model = model


def synthesize_to_file(text: str, out_path: str) -> None:
    """Raises RuntimeError if the model isn't loaded yet or there's no
    reference clip -- callers (tts.py) must check is_ready() /
    has_reference_audio() first and fall back to the fast voice instead of
    calling this speculatively."""
    from config import TTS_XTTS_LANGUAGE, TTS_XTTS_SPEAKER_WAV_PATH

    with _model_lock:
        model = _model
    if model is None:
        raise RuntimeError("modelo XTTS ainda não carregado")

    model.tts_to_file(
        text=text,
        speaker_wav=str(TTS_XTTS_SPEAKER_WAV_PATH),
        language=TTS_XTTS_LANGUAGE,
        file_path=out_path,
    )


def _get_conditioning_latents():
    """Computed once and cached at module scope -- every synthesize_stream()
    call after the first reuses it instead of recomputing from the
    reference wav each time. Raises RuntimeError if the model isn't loaded
    yet, same contract as the rest of this module."""
    global _conditioning_cache

    if _conditioning_cache is not None:
        return _conditioning_cache

    from config import TTS_XTTS_SPEAKER_WAV_PATH

    with _model_lock:
        model = _model
    if model is None:
        raise RuntimeError("modelo XTTS ainda não carregado")

    _conditioning_cache = model.synthesizer.tts_model.get_conditioning_latents(
        audio_path=str(TTS_XTTS_SPEAKER_WAV_PATH)
    )
    return _conditioning_cache


def _to_pcm16_bytes(wav_chunk) -> bytes:
    import numpy as np

    array = wav_chunk.detach().cpu().numpy() if hasattr(wav_chunk, "detach") else np.asarray(wav_chunk)
    clipped = np.clip(array, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


def synthesize_stream(text: str):
    """Yield complete sentence waveforms as PCM16, without repeatedly
    running the vocoder over the same growing prefix. Sentence splitting
    also keeps long replies within XTTS's tokenizer limit. The native
    player validates and buffers the reply before starting playback.
    """
    from config import TTS_XTTS_LANGUAGE

    with _model_lock:
        model = _model
    if model is None:
        raise RuntimeError("modelo XTTS ainda não carregado")

    gpt_cond_latent, speaker_embedding = _get_conditioning_latents()
    for wav_chunk in model.synthesizer.tts_model.inference_stream(
        text, TTS_XTTS_LANGUAGE, gpt_cond_latent, speaker_embedding,
        stream_chunk_size=0, enable_text_splitting=True,
    ):
        yield _to_pcm16_bytes(wav_chunk)
