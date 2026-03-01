# Model Selection with Download Progress — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users choose their Whisper model in settings, with a modal progress dialog during download.

**Architecture:** Pre-download models via `huggingface_hub.snapshot_download()` with a custom tqdm subclass that emits Qt signals. Pass the local path to `WhisperModel` to skip re-downloading. Model selection is a new combo box in the settings UI. The service detects model changes on config save and orchestrates the download→load→swap flow.

**Tech Stack:** PyQt6 (QDialog, QProgressBar, QThread), huggingface_hub, faster-whisper, tqdm

**Design doc:** `docs/plans/2026-02-26-model-selection-design.md`

---

### Task 1: Add `model` field to Config

**Files:**
- Modify: `src/oscribe/config.py:12-53`

**Step 1: Add field to dataclass**

In `src/oscribe/config.py`, add `model: str = "large-v3-turbo"` to the `Config` dataclass (after `punctuation_hints`):

```python
@dataclass
class Config:
    device_index: int | None = None
    language: str = "en"
    output_mode: str = "clipboard"
    silence_timeout: float = 3.0
    window_position: str = "bottom_center"
    sound_enabled: bool = True
    streaming: bool = False
    punctuation_hints: bool = True
    model: str = "large-v3-turbo"
```

**Step 2: Add to load()**

Add this line in the `cls(...)` call in `load()`, after the `punctuation_hints` line:

```python
model=data.get("model", "large-v3-turbo"),
```

**Step 3: Add to save()**

Add this line in the `data` dict in `save()`, after the `punctuation_hints` line:

```python
"model": self.model,
```

**Step 4: Verify**

Run: `uv run python -c "from oscribe.config import Config; c = Config(); print(c.model)"`
Expected: `large-v3-turbo`

**Step 5: Commit**

```bash
git add src/oscribe/config.py
git commit -m "feat: add model field to Config"
```

---

### Task 2: Add model catalog to transcriber

**Files:**
- Modify: `src/oscribe/audio/transcriber.py:1-10`

**Step 1: Add WHISPER_MODELS dict**

Add this after the `PUNCTUATION_PROMPTS` dict (after line 21), before `_detect_device()`:

```python
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
```

**Step 2: Verify**

Run: `uv run python -c "from oscribe.audio.transcriber import WHISPER_MODELS; print(list(WHISPER_MODELS.keys()))"`
Expected: list of 10 model names

**Step 3: Commit**

```bash
git add src/oscribe/audio/transcriber.py
git commit -m "feat: add WHISPER_MODELS catalog with size and speed hints"
```

---

### Task 3: Add download_model method to Transcriber

**Files:**
- Modify: `src/oscribe/audio/transcriber.py`

This task adds a `download_model()` method that calls `huggingface_hub.snapshot_download()` with a custom tqdm class for progress reporting. It also modifies `load_model()` to accept an optional `model_path` parameter.

**Step 1: Add download_model method**

Add this method to the `Transcriber` class, after the existing `load_model()` method (after line 73):

```python
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
```

**Step 2: Add helper classes at module level**

Add these before the `Transcriber` class:

```python
import typing

from tqdm.auto import tqdm as _tqdm_base


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
```

**Step 3: Modify load_model to accept model_path**

Change the `load_model` method to accept an optional path:

```python
def load_model(self, model_path: str | None = None) -> None:
    if self._model is not None:
        return

    device, compute_type = _detect_device()

    logger.info("Loading model (%s, %s)...", device, compute_type)

    from faster_whisper import WhisperModel

    self._model = WhisperModel(
        model_path or self.model_size,
        device=device,
        compute_type=compute_type,
    )

    logger.info("Model loaded (%s).", device)
```

**Step 4: Add unload_model method**

Add after `load_model`:

```python
def unload_model(self) -> None:
    """Release the current model from memory."""
    self._model = None
```

**Step 5: Verify**

Run: `uv run python -c "from oscribe.audio.transcriber import Transcriber; t = Transcriber(); print(hasattr(t, 'download_model'))"`
Expected: `True`

**Step 6: Commit**

```bash
git add src/oscribe/audio/transcriber.py
git commit -m "feat: add download_model with progress callback and model lifecycle methods"
```

---

### Task 4: Add model dropdown to settings UI

**Files:**
- Modify: `src/oscribe/gui/settings.py`

**Step 1: Add import**

Add to the imports at the top of `settings.py`:

```python
from oscribe.audio.transcriber import WHISPER_MODELS
```

**Step 2: Add Model section**

In `SettingsWindow.__init__`, after the title and first separator (after line 326 `root.addWidget(_separator())`), add a new Model section *before* the Audio section:

```python
# ── model section ─────────────────────────────────────────
root.addSpacing(20)
root.addWidget(_section_label("Model"))
root.addSpacing(12)

self.model_combo = _StyledComboBox()
self.model_combo.setStyleSheet(_COMBO_STYLE)
self.model_combo.setFixedWidth(300)
for name, (size, speed) in WHISPER_MODELS.items():
    self.model_combo.addItem(f"{name}  ({size}, {speed})", name)
root.addLayout(self._row("Whisper model", self.model_combo))

root.addSpacing(4)
root.addWidget(_hint_label("Larger models are more accurate but slower"))

root.addSpacing(20)
root.addWidget(_separator())
```

**Step 3: Load current model in _load_current**

Add to `_load_current()`, after `cfg = Config.load(...)`:

```python
idx = self.model_combo.findData(cfg.model)
if idx >= 0:
    self.model_combo.setCurrentIndex(idx)
```

**Step 4: Save model in _save**

Add `model=self.model_combo.currentData(),` to the `Config(...)` constructor call in `_save()`.

**Step 5: Verify**

Run: `uv run python -c "from oscribe.gui.settings import SettingsWindow; print('OK')"`
Expected: `OK` (import succeeds)

**Step 6: Commit**

```bash
git add src/oscribe/gui/settings.py
git commit -m "feat: add model dropdown to settings UI"
```

---

### Task 5: Create ModelDownloadDialog

**Files:**
- Create: `src/oscribe/gui/download.py`

**Step 1: Create the dialog**

Create `src/oscribe/gui/download.py`:

```python
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from oscribe.audio.transcriber import Transcriber

logger = logging.getLogger("oscribe")

BG = "#0A0A0A"
FG = "#FFFFFF"
MUTED = "#666666"
BORDER = "#2A2A2A"


class _DownloadWorker(QThread):
    """Downloads and loads a Whisper model in a background thread."""

    progress = pyqtSignal(int)
    finished = pyqtSignal(str)   # local model path
    error = pyqtSignal(str)

    def __init__(self, transcriber: Transcriber) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._cancelled = False

    def run(self) -> None:
        try:
            path = self._transcriber.download_model(
                progress_callback=self._on_progress,
            )
            if self._cancelled:
                return
            self._transcriber.load_model(model_path=path)
            self.finished.emit(path)
        except Exception as exc:
            if not self._cancelled:
                logger.error("Model download failed: %s", exc)
                self.error.emit(str(exc))

    def _on_progress(self, pct: int) -> None:
        if not self._cancelled:
            self.progress.emit(pct)

    def cancel(self) -> None:
        self._cancelled = True


class ModelDownloadDialog(QDialog):
    """Modal dialog showing model download + load progress."""

    model_ready = pyqtSignal()

    def __init__(
        self,
        transcriber: Transcriber,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("oscribe")
        self.setFixedSize(360, 150)
        self.setModal(True)
        self._transcriber = transcriber
        self._worker: _DownloadWorker | None = None
        self._success = False

        self.setStyleSheet(f"""
            QDialog {{
                background: {BG};
                color: {FG};
                font-family: system-ui, -apple-system, sans-serif;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._title = QLabel(f"Downloading {transcriber.model_size}...")
        self._title.setStyleSheet(
            f"color: {FG}; font-size: 13px; font-weight: 500;"
        )
        layout.addWidget(self._title)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {BORDER};
                border: 1px solid {BORDER};
                height: 8px;
                text-align: center;
                color: transparent;
            }}
            QProgressBar::chunk {{
                background: {FG};
            }}
        """)
        layout.addWidget(self._bar)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {MUTED}; font-size: 11px;"
        )
        layout.addWidget(self._status)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedWidth(80)
        self._cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {MUTED};
                border: 1px solid {BORDER};
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                color: {FG};
                border-color: {MUTED};
            }}
        """)
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel_btn)

    def start(self) -> None:
        """Start the download and show the dialog."""
        self._worker = _DownloadWorker(self._transcriber)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self.exec()

    def succeeded(self) -> bool:
        return self._success

    def _on_progress(self, pct: int) -> None:
        self._bar.setValue(pct)
        self._status.setText(f"{pct}%")

    def _on_finished(self, path: str) -> None:
        self._bar.setValue(100)
        self._title.setText("Loading model...")
        self._status.setText("Initializing...")
        self._success = True
        self.model_ready.emit()
        self.accept()

    def _on_error(self, msg: str) -> None:
        self._title.setText("Download failed")
        self._status.setText(msg)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._cancel_btn.setText("Close")

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self.reject()
```

**Step 2: Verify**

Run: `uv run python -c "from oscribe.gui.download import ModelDownloadDialog; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/oscribe/gui/download.py
git commit -m "feat: add ModelDownloadDialog with progress bar"
```

---

### Task 6: Wire model change in service

**Files:**
- Modify: `src/oscribe/service.py`

**Step 1: Add import**

Add to the imports in `service.py`:

```python
from oscribe.gui.download import ModelDownloadDialog
```

**Step 2: Pass model to Transcriber constructor**

In `OscribeService.__init__` (line 86-89), add `model_size` to the Transcriber constructor:

```python
self.transcriber = Transcriber(
    model_size=self.cfg.model,
    language=self.cfg.language,
    punctuation_hints=self.cfg.punctuation_hints,
)
```

**Step 3: Update _on_config_changed**

Replace `_on_config_changed` (lines 176-180) with:

```python
def _on_config_changed(self, cfg: Config) -> None:
    old_model = self.cfg.model
    self.cfg = cfg
    self.transcriber.language = cfg.language
    self.transcriber.punctuation_hints = cfg.punctuation_hints
    self.capture = AudioCapture(device=cfg.device_index)

    if cfg.model != old_model:
        self._switch_model(cfg.model)

def _switch_model(self, model_name: str) -> None:
    """Download (if needed) and load a new Whisper model."""
    self.transcriber.unload_model()
    self.transcriber.model_size = model_name

    dlg = ModelDownloadDialog(self.transcriber)
    dlg.start()

    if not dlg.succeeded():
        # Revert to previous model
        logger.warning("Model switch cancelled, reverting to previous model")
        self.transcriber.model_size = self.cfg.model
        self.transcriber.load_model()
```

**Step 4: Verify**

Run the full app: `uv run oscribe &`
Open settings, change the model, click APPLY.
Expected: Modal dialog appears with progress bar. On completion, dialog closes.

**Step 5: Commit**

```bash
git add src/oscribe/service.py
git commit -m "feat: wire model change with download dialog in service"
```

---

### Task 7: Handle startup with configured model

**Files:**
- Modify: `src/oscribe/service.py`

The startup preload (lines 100-103) should use the configured model. Since we already pass `model_size=self.cfg.model` in Task 6, the existing `self.transcriber.load_model()` will download+load the right model. But on first run (no cache), the startup will block with no progress. Let's show the download dialog on startup too if the model isn't cached.

**Step 1: Replace startup preload**

Replace lines 100-103:

```python
# Preload model
logger.info("Loading model...")
self.transcriber.load_model()
logger.info("Model loaded.")
```

With:

```python
# Preload model (show progress dialog if download needed)
self._preload_model()
```

**Step 2: Add _preload_model method**

Add after `_setup_tray`:

```python
def _preload_model(self) -> None:
    """Load model at startup, showing download dialog if needed."""
    try:
        import huggingface_hub
        from faster_whisper.utils import _MODELS
        repo_id = _MODELS.get(self.cfg.model, self.cfg.model)
        # Check if already cached (no download needed)
        huggingface_hub.snapshot_download(
            repo_id,
            local_files_only=True,
            allow_patterns=["config.json", "model.bin", "tokenizer.json",
                            "preprocessor_config.json", "vocabulary.*"],
        )
        # Cached — load directly
        logger.info("Loading model (cached)...")
        self.transcriber.load_model()
        logger.info("Model loaded.")
    except Exception:
        # Not cached — show download dialog
        logger.info("Model not cached, downloading...")
        dlg = ModelDownloadDialog(self.transcriber)
        dlg.start()
        if not dlg.succeeded():
            logger.error("Initial model download failed or cancelled")
            sys.exit(1)
        logger.info("Model loaded.")
```

**Step 3: Verify**

Clear model cache and run: `uv run oscribe`
Expected: Download dialog appears on first startup with progress.

Run again (model cached): `uv run oscribe`
Expected: Starts immediately, no dialog.

**Step 4: Commit**

```bash
git add src/oscribe/service.py
git commit -m "feat: show download dialog on startup if model not cached"
```

---

### Task 8: Manual integration test

**No files modified.** This is a verification-only task.

**Step 1: Fresh start test**

1. Run `uv run oscribe`
2. Open settings from tray icon
3. Verify model dropdown shows `large-v3-turbo (~1.6 GB, fast + accurate)` selected
4. Change model to `tiny (~75 MB, fastest)`
5. Click APPLY
6. Verify: modal dialog appears, progress bar fills, dialog closes
7. Record a short phrase and verify transcription still works

**Step 2: Cancel test**

1. Open settings, change model to `large-v3 (~3 GB, most accurate)`
2. Click APPLY
3. Click Cancel during download
4. Verify: dialog closes, app continues working with previous model

**Step 3: Already-cached test**

1. Open settings, switch to `tiny` (already downloaded from step 1)
2. Click APPLY
3. Verify: dialog appears briefly then closes (no download needed)

**Step 4: Config persistence test**

1. Set model to `small`, click APPLY
2. Quit and restart app
3. Open settings
4. Verify: `small` is selected in dropdown

**Step 5: Commit (if any fixes needed)**

Fix any issues found, commit with descriptive message.
