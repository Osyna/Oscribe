from __future__ import annotations

import logging
import os
import typing

import numpy as np
from tqdm.auto import tqdm as _tqdm_base

logger = logging.getLogger(__name__)

PUNCTUATION_PROMPTS: dict[str, str] = {
    "en": "Hello, how are you? I'm doing well. Let me explain the situation.",
    "fr": "Bonjour, comment allez-vous ? Je vais bien. Laissez-moi vous expliquer.",
    "de": "Hallo, wie geht es Ihnen? Mir geht es gut. Lassen Sie mich das erklären.",
    "es": "Hola, ¿cómo estás? Estoy bien. Déjame explicarte la situación.",
    "it": "Ciao, come stai? Sto bene. Lasciami spiegare la situazione.",
    "pt": "Olá, como vai? Estou bem. Deixe-me explicar a situação.",
    "nl": "Hallo, hoe gaat het? Het gaat goed. Laat me de situatie uitleggen.",
    "pl": "Cześć, jak się masz? Dobrze. Pozwól, że wyjaśnię sytuację.",
    "ru": "Привет, как дела? У меня всё хорошо. Позвольте мне объяснить ситуацию.",
    "ja": "こんにちは、お元気ですか？元気です。状況を説明させてください。",
    "zh": "你好，你好吗？我很好。让我解释一下情况。",
}

WHISPER_MODELS: dict[str, tuple[str, str]] = {
    "tiny":              ("~75 MB",  "fastest"),
    "base":              ("~150 MB", "fast"),
    "small":             ("~500 MB", "balanced"),
    "distil-small.en":   ("~250 MB", "fast, English only"),
    "medium":            ("~1.5 GB", "accurate"),
    "distil-medium.en":  ("~750 MB", "balanced, English only"),
    "large-v3":          ("~3 GB",   "most accurate"),
    "distil-large-v2":   ("~1.5 GB", "fast + accurate"),
    "distil-large-v3":   ("~1.5 GB", "fast + accurate"),
    "large-v3-turbo":    ("~1.6 GB", "fast + accurate"),
}


def _detect_device() -> tuple[str, str]:
    """Pick the best device and compute type for inference.

    CTranslate2 uses "cuda" for both NVIDIA (CUDA) and AMD (ROCm) GPUs.
    The ROCm build reports GPUs via get_cuda_device_count() and supports
    the same compute types.

    Set OSCRIBE_FORCE_CPU=1 to skip GPU detection entirely (useful when
    the GPU driver causes crashes or hangs).

    Returns (device, compute_type):
      - GPU available (NVIDIA or AMD ROCm) -> ("cuda", best_type)
      - CPU fallback                       -> ("cpu", "int8")
    """
    if os.environ.get("OSCRIBE_FORCE_CPU"):
        logger.info("OSCRIBE_FORCE_CPU set — forcing CPU mode.")
        return "cpu", "int8"

    try:
        import ctranslate2

        gpu_count = ctranslate2.get_cuda_device_count()
        if gpu_count > 0:
            supported = ctranslate2.get_supported_compute_types("cuda")
            logger.info(
                "GPU detected: %d device(s), compute types: %s",
                gpu_count,
                ", ".join(sorted(supported)),
            )
            for preferred in ("float16", "int8_float16", "int8"):
                if preferred in supported:
                    return "cuda", preferred
            return "cuda", "default"
    except Exception as exc:
        logger.debug("GPU detection failed: %s", exc)

    return "cpu", "int8"


class _disabled_tqdm(_tqdm_base):
    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        kwargs["disable"] = True
        super().__init__(*args, **kwargs)


def _make_progress_tqdm(
    callback: typing.Callable[[int], None],
) -> type:
    """Create a tqdm subclass that reports progress via callback."""

    class _ProgressTqdm(_tqdm_base):
        def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
            super().__init__(*args, **kwargs)

        def update(self, n: int = 1) -> bool | None:
            result = super().update(n)
            if self.total and self.total > 0:
                callback(int(self.n / self.total * 100))
            return result

    return _ProgressTqdm


class Transcriber:

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        language: str = "en",
        punctuation_hints: bool = True,
    ) -> None:
        self.model_size = model_size
        self.language = language
        self.punctuation_hints = punctuation_hints
        self._model = None
        self._device: str = "cpu"

    # -- model lifecycle ------------------------------------------------

    def load_model(self, model_path: str | None = None) -> None:
        if self._model is not None:
            return

        device, compute_type = _detect_device()
        self._device = device

        logger.info("Loading model (%s, %s)...", device, compute_type)

        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            model_path or self.model_size,
            device=device,
            compute_type=compute_type,
        )

        logger.info("Model loaded (%s).", device)

    def _reload_on_cpu(self) -> None:
        """Fallback: reload model on CPU after a CUDA error."""
        logger.warning("Reloading model on CPU as fallback...")
        self._model = None
        self._device = "cpu"

        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type="int8",
        )
        logger.info("Model reloaded (cpu, int8).")

    def unload_model(self) -> None:
        """Release the current model from memory."""
        self._model = None

    def download_model(
        self,
        progress_callback: typing.Callable[[int], None] | None = None,
    ) -> str:
        """Download the model and return its local path.

        Args:
            progress_callback: Called with percentage (0-100) during download.

        Returns:
            Local filesystem path to the downloaded model.
        """
        import huggingface_hub
        from faster_whisper.utils import _MODELS

        repo_id = _MODELS.get(self.model_size, self.model_size)

        tqdm_cls = _make_progress_tqdm(progress_callback) if progress_callback else _disabled_tqdm

        return huggingface_hub.snapshot_download(
            repo_id,
            allow_patterns=[
                "config.json",
                "preprocessor_config.json",
                "model.bin",
                "tokenizer.json",
                "vocabulary.*",
            ],
            tqdm_class=tqdm_cls,
        )

    # -- transcription --------------------------------------------------

    def _run_transcribe(self, audio: np.ndarray) -> str:
        """Run faster-whisper transcription. Raises on CUDA/runtime errors."""
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            initial_prompt=(
                PUNCTUATION_PROMPTS.get(self.language)
                if self.punctuation_hints else None
            ),
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        """Transcribe a complete audio signal. Returns stripped text or empty string."""
        self.load_model()
        if self._model is None:
            return ""

        logger.info("Transcribing (%s)...", self.language)

        # Flatten to mono if needed
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        # Ensure float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Resample to 16kHz if needed (whisper expects 16kHz)
        if sample_rate != 16_000:
            samples = int(len(audio) * 16_000 / sample_rate)
            from numpy import interp, linspace
            audio = interp(
                linspace(0, len(audio), samples, endpoint=False),
                np.arange(len(audio)),
                audio,
            ).astype(np.float32)

        # Quick silence check
        energy = float(np.mean(audio**2))
        if energy < 1e-6:
            return ""

        try:
            text = self._run_transcribe(audio)
        except Exception as exc:
            if self._device == "cuda":
                logger.error("CUDA transcription failed: %s", exc)
                logger.info("Falling back to CPU...")
                try:
                    self._reload_on_cpu()
                    text = self._run_transcribe(audio)
                except Exception as cpu_exc:
                    logger.error("CPU transcription also failed: %s", cpu_exc)
                    return ""
            else:
                logger.error("Transcription error: %s", exc)
                return ""

        if text:
            logger.info(text)
        return text

    def transcribe_streaming(
        self,
        audio: np.ndarray,
        sample_rate: int = 16_000,
        prev_text: str = "",
    ) -> tuple[str, str]:
        """Incremental transcription using local agreement.

        Args:
            audio: Full accumulated audio so far.
            sample_rate: Sample rate of the audio.
            prev_text: Full transcription text from the previous call.

        Returns:
            (confirmed_new, full_text):
                confirmed_new: Text that both this and previous run agree on,
                    minus what was already confirmed. Empty string on first call.
                full_text: The complete transcription of the current audio.
        """
        full_text = self.transcribe(audio, sample_rate=sample_rate)
        if not full_text:
            return "", prev_text

        if not prev_text:
            # First run — nothing to compare against yet
            return "", full_text

        # Find the longest common prefix (word-level)
        prev_words = prev_text.split()
        curr_words = full_text.split()

        common_len = 0
        for pw, cw in zip(prev_words, curr_words):
            if pw == cw:
                common_len += 1
            else:
                break

        if common_len == 0:
            return "", full_text

        confirmed = " ".join(curr_words[:common_len])
        return confirmed, full_text
