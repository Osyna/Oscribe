# Dictate — Restructure & Optimize Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure "live-transcriber" into an installable `dictate` package using `faster-whisper` for 3-4x faster transcription.

**Architecture:** Proper Python package under `src/dictate/` with entry points. Replace HuggingFace transformers with faster-whisper (CTranslate2). Drop librosa, textual, accelerate, torch, transformers. Keep GUI service + CLI frontends.

**Tech Stack:** faster-whisper, sounddevice, numpy, PyQt6, pyzmq, pyperclip, pyyaml

**Design doc:** `docs/plans/2026-02-24-optimize-and-restructure-design.md`

---

### Task 1: Create package skeleton with __init__.py files

**Files:**
- Create: `src/dictate/__init__.py`
- Create: `src/dictate/audio/__init__.py`
- Create: `src/dictate/gui/__init__.py`

**Step 1: Create the package directories and init files**

```bash
mkdir -p src/dictate/audio src/dictate/gui
```

`src/dictate/__init__.py`:
```python
"""Dictate — fast speech-to-text with system tray integration."""
```

`src/dictate/audio/__init__.py`:
```python
```

`src/dictate/gui/__init__.py`:
```python
```

**Step 2: Verify the directory structure**

Run: `find src/dictate -type f | sort`
Expected:
```
src/dictate/__init__.py
src/dictate/audio/__init__.py
src/dictate/gui/__init__.py
```

**Step 3: Commit**

```bash
git add src/dictate/
git commit -m "feat: create dictate package skeleton"
```

---

### Task 2: Rewrite pyproject.toml with trimmed deps and entry points

**Files:**
- Modify: `pyproject.toml`

**Step 1: Rewrite pyproject.toml**

```toml
[project]
name = "dictate"
version = "0.1.0"
description = "Fast speech-to-text with system tray integration"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "faster-whisper>=1.1.0",
    "numpy>=2.0.0",
    "pyperclip>=1.9.0",
    "pyqt6>=6.7.0",
    "pyzmq>=26.0.0",
    "pyyaml>=6.0",
    "sounddevice>=0.5.0",
]

[project.scripts]
dictate = "dictate.service:main"
dictate-trigger = "dictate.trigger:main"
dictate-cli = "dictate.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dictate"]
```

**Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "feat: rewrite pyproject.toml with dictate entry points and trimmed deps"
```

---

### Task 3: Create shared config loader

**Files:**
- Create: `src/dictate/config.py`

**Step 1: Write config.py**

This extracts config loading that was duplicated in `main.py` and `service.py`.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


@dataclass
class Config:
    device_index: int | None = None
    language: str = "en"
    output_mode: str = "clipboard"
    silence_timeout: float = 3.0
    window_position: str = "bottom_center"

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or _DEFAULT_CONFIG_PATH
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls(
                device_index=data.get("device_index"),
                language=data.get("language", "en"),
                output_mode=data.get("output_mode", "clipboard"),
                silence_timeout=float(data.get("silence_timeout", 3.0)),
                window_position=data.get("window_position", "bottom_center"),
            )
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or _DEFAULT_CONFIG_PATH
        data = {
            "device_index": self.device_index,
            "language": self.language,
            "output_mode": self.output_mode,
            "silence_timeout": self.silence_timeout,
            "window_position": self.window_position,
        }
        with open(path, "w") as f:
            yaml.dump(data, f)
```

**Step 2: Commit**

```bash
git add src/dictate/config.py
git commit -m "feat: add shared Config dataclass with load/save"
```

---

### Task 4: Rewrite audio/capture.py — drop librosa resampling

**Files:**
- Create: `src/dictate/audio/capture.py` (rewrite from `src/audio/capture.py`)

**Step 1: Write the new capture.py**

Key changes from old version:
- No librosa import — faster-whisper handles resampling
- `read()` yields raw float32 chunks as-is (no resampling)
- Keep energy tracking for UI visualization
- Type hints on all public APIs

```python
from __future__ import annotations

import queue
import time

import numpy as np
import sounddevice as sd


class AudioCapture:

    @staticmethod
    def list_devices() -> list[dict]:
        return sd.query_devices()  # type: ignore[return-value]

    def __init__(
        self,
        device: int | None = None,
        block_duration_ms: int = 30,
        silence_threshold: float = 0.001,
    ) -> None:
        self.device = device
        self.block_duration_ms = block_duration_ms
        self.silence_threshold = silence_threshold

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self.running = False

        # Actual sample rate of the device (set in start())
        self.sample_rate: int = 16_000

        # Silence / speech tracking (read by service for UI + auto-stop)
        self.current_energy: float = 0.0
        self.last_sound_time: float = 0.0
        self.speech_detected: bool = False

    # -- stream callback (runs in audio thread) -------------------------

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(status, flush=True)
        self._queue.put(indata.copy())

        energy = float(np.mean(indata**2))
        self.current_energy = energy
        if energy > self.silence_threshold:
            self.last_sound_time = time.time()
            self.speech_detected = True

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        self.running = True

        # Query actual device sample rate
        try:
            if self.device is not None:
                info = sd.query_devices(self.device, "input")
            else:
                info = sd.query_devices(kind="input")
            self.sample_rate = int(info["default_samplerate"])
        except Exception as exc:
            print(f"Warning querying device: {exc}")
            self.sample_rate = 16_000

        block_size = int(self.sample_rate * self.block_duration_ms / 1000)

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=block_size,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self.running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self) -> list[np.ndarray]:
        """Drain the queue and return all buffered chunks."""
        chunks: list[np.ndarray] = []
        while True:
            try:
                chunk = self._queue.get(timeout=0.05)
                if chunk.ndim > 1:
                    chunk = chunk.flatten()
                chunks.append(chunk)
            except queue.Empty:
                if not self.running:
                    break
                # One more pass to catch stragglers
                if self._queue.empty():
                    break
        return chunks
```

Note: `read()` changed from a generator to returning `list[np.ndarray]` — simpler for the callers who always drain everything anyway.

**Step 2: Commit**

```bash
git add src/dictate/audio/capture.py
git commit -m "feat: rewrite AudioCapture — drop librosa, simplify read()"
```

---

### Task 5: Rewrite audio/transcriber.py — use faster-whisper

**Files:**
- Create: `src/dictate/audio/transcriber.py` (rewrite from `src/audio/transcriber.py`)

**Step 1: Write the new transcriber.py**

Key changes:
- `faster_whisper.WhisperModel` replaces transformers `AutoModelForSpeechSeq2Seq` + `AutoProcessor`
- Single `model.transcribe(audio_array)` call instead of processor→generate→decode pipeline
- VAD filter enabled by default for better accuracy
- `compute_type="float16"` on CUDA, `"int8"` on CPU for speed

```python
from __future__ import annotations

from typing import Callable

import numpy as np


class Transcriber:

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        language: str = "en",
        on_text: Callable[[str], object] | None = None,
    ) -> None:
        self.model_size = model_size
        self.language = language
        self.on_text = on_text
        self._model = None

    # -- model lifecycle ------------------------------------------------

    def load_model(self) -> None:
        if self._model is not None:
            return

        if self.on_text:
            self.on_text("Loading model (faster-whisper)...")

        from faster_whisper import WhisperModel

        # Auto-detect: float16 on CUDA, int8 on CPU
        import ctranslate2

        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
        )

        if self.on_text:
            self.on_text(f"Model loaded on {device} ({compute_type}).")

    # -- transcription --------------------------------------------------

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        """Transcribe a complete audio signal. Returns stripped text or empty string."""
        self.load_model()
        if self._model is None:
            return ""

        if self.on_text:
            self.on_text(f"Transcribing ({self.language})...")

        # Flatten to mono if needed
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        # Quick silence check
        energy = float(np.mean(audio**2))
        if energy < 1e-6:
            return ""

        try:
            segments, _info = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            if self.on_text:
                self.on_text(f"Transcription error: {exc}")
            return ""

        if text and self.on_text:
            self.on_text(text)
        return text
```

**Step 2: Commit**

```bash
git add src/dictate/audio/transcriber.py
git commit -m "feat: rewrite Transcriber with faster-whisper backend"
```

---

### Task 6: Rewrite gui/window.py and gui/settings.py

**Files:**
- Create: `src/dictate/gui/window.py` (copy from `src/gui/window.py` — no logic changes)
- Create: `src/dictate/gui/settings.py` (adapt from `src/gui/settings.py` to use Config dataclass)

**Step 1: Copy window.py as-is**

The overlay window has no dependency on transformers/librosa — copy `src/gui/window.py` verbatim to `src/dictate/gui/window.py`. No changes needed.

**Step 2: Rewrite settings.py to use Config dataclass**

```python
from __future__ import annotations

from pathlib import Path

import yaml
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dictate.audio.capture import AudioCapture
from dictate.config import Config


class SettingsWindow(QWidget):
    config_saved = pyqtSignal(object)  # emits Config

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("Dictate Settings")
        self.resize(400, 200)
        self.config_path = config_path

        layout = QVBoxLayout()
        form = QFormLayout()

        # Audio device
        self.device_combo = QComboBox()
        self._populate_devices()
        form.addRow("Microphone:", self.device_combo)

        # Language
        self.lang_combo = QComboBox()
        self._populate_languages()
        form.addRow("Language:", self.lang_combo)

        # Output mode
        self.output_combo = QComboBox()
        self.output_combo.addItem("Clipboard", "clipboard")
        self.output_combo.addItem("Type into active window", "type")
        form.addRow("Output:", self.output_combo)

        # Window position
        self.position_combo = QComboBox()
        for label, value in [
            ("Bottom Center", "bottom_center"),
            ("Bottom Left", "bottom_left"),
            ("Bottom Right", "bottom_right"),
            ("Top Center", "top_center"),
            ("Top Left", "top_left"),
            ("Top Right", "top_right"),
            ("Center", "center"),
        ]:
            self.position_combo.addItem(label, value)
        form.addRow("Position:", self.position_combo)

        # Silence timeout
        self.silence_spin = QDoubleSpinBox()
        self.silence_spin.setRange(1.0, 10.0)
        self.silence_spin.setSingleStep(0.5)
        self.silence_spin.setValue(3.0)
        self.silence_spin.setSuffix(" sec")
        form.addRow("Silence timeout:", self.silence_spin)

        layout.addLayout(form)

        save_btn = QPushButton("Save && Apply")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        self.setLayout(layout)
        self._load_current()

    def _populate_devices(self) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("System Default", None)
        for i, dev in enumerate(AudioCapture.list_devices()):
            if dev["max_input_channels"] > 0:
                self.device_combo.addItem(dev["name"], i)

    def _populate_languages(self) -> None:
        for name, code in {
            "English": "en", "French": "fr", "German": "de",
            "Spanish": "es", "Italian": "it", "Portuguese": "pt",
            "Dutch": "nl", "Polish": "pl", "Russian": "ru",
            "Japanese": "ja", "Chinese": "zh",
        }.items():
            self.lang_combo.addItem(name, code)

    def _load_current(self) -> None:
        cfg = Config.load(self.config_path)
        idx = self.lang_combo.findData(cfg.language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        if cfg.device_index is None:
            self.device_combo.setCurrentIndex(0)
        else:
            idx = self.device_combo.findData(cfg.device_index)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        idx = self.output_combo.findData(cfg.output_mode)
        if idx >= 0:
            self.output_combo.setCurrentIndex(idx)
        idx = self.position_combo.findData(cfg.window_position)
        if idx >= 0:
            self.position_combo.setCurrentIndex(idx)
        self.silence_spin.setValue(cfg.silence_timeout)

    def _save(self) -> None:
        cfg = Config(
            device_index=self.device_combo.currentData(),
            language=self.lang_combo.currentData(),
            output_mode=self.output_combo.currentData(),
            window_position=self.position_combo.currentData(),
            silence_timeout=self.silence_spin.value(),
        )
        try:
            cfg.save(self.config_path)
            self.config_saved.emit(cfg)
            QMessageBox.information(self, "Success", "Configuration saved!")
            self.hide()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save: {exc}")
```

**Step 3: Commit**

```bash
git add src/dictate/gui/
git commit -m "feat: add gui window and settings using Config dataclass"
```

---

### Task 7: Rewrite service.py — main GUI entry point

**Files:**
- Create: `src/dictate/service.py` (rewrite from `src/service.py`)

**Step 1: Write the new service.py**

Key changes from old version:
- Proper imports from `dictate.*` (no sys.path hacks)
- Uses `Config` dataclass instead of raw dict
- Uses new `Transcriber.transcribe()` API
- Uses new `AudioCapture.read()` that returns `list[np.ndarray]`
- `on_config_changed` receives `Config` object

```python
from __future__ import annotations

import json
import math
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pyperclip
import zmq
from PyQt6.QtCore import (
    Q_ARG,
    QMetaObject,
    QObject,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from dictate.audio.capture import AudioCapture
from dictate.audio.transcriber import Transcriber
from dictate.config import Config
from dictate.gui.settings import SettingsWindow
from dictate.gui.window import RecordingWindow

IPC_ADDRESS = "ipc:///tmp/dictate_service.ipc"

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


class _IPCWorker(QObject):
    toggle_received = pyqtSignal()

    def run(self) -> None:
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REP)
        try:
            sock.bind(IPC_ADDRESS)
        except zmq.error.ZMQError:
            print("IPC socket already in use.")
        while True:
            try:
                msg = sock.recv_string()
                if msg == "TOGGLE":
                    self.toggle_received.emit()
                    sock.send_string("OK")
                else:
                    sock.send_string("UNKNOWN")
            except Exception as exc:
                print(f"IPC error: {exc}")


class DictateService:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.cfg = Config.load(CONFIG_PATH)

        # Audio + transcription
        self.capture = AudioCapture(device=self.cfg.device_index)
        self.transcriber = Transcriber(language=self.cfg.language, on_text=print)

        # GUI
        self.window = RecordingWindow()
        self.window.stop_signal.connect(self._stop_recording)

        self.settings_window = SettingsWindow(CONFIG_PATH)
        self.settings_window.config_saved.connect(self._on_config_changed)

        self._setup_tray()

        # Preload model
        print("Loading model...")
        self.transcriber.load_model()
        print("Model loaded.")

        # Output helpers
        self._paste_tool: str | None = None
        for tool in ("ydotool", "wtype", "xdotool"):
            if shutil.which(tool):
                self._paste_tool = tool
                break

        # State
        self.is_recording = False
        self._saved_window_addr: str | None = None

        # Silence timer
        self._silence_timer = QTimer()
        self._silence_timer.setInterval(50)
        self._silence_timer.timeout.connect(self._check_silence)

        # IPC
        self._ipc_worker = _IPCWorker()
        self._ipc_thread = QThread()
        self._ipc_worker.moveToThread(self._ipc_thread)
        self._ipc_worker.toggle_received.connect(self._handle_toggle)
        self._ipc_thread.started.connect(self._ipc_worker.run)
        self._ipc_thread.start()

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self.app)
        icon = QIcon.fromTheme("microphone")
        if icon.isNull():
            from PyQt6.QtGui import QColor, QPainter, QPixmap

            px = QPixmap(64, 64)
            px.fill(QColor("transparent"))
            p = QPainter(px)
            p.setBrush(QColor("red"))
            p.setPen(QColor("white"))
            p.drawEllipse(2, 2, 60, 60)
            p.end()
            icon = QIcon(px)
        self._tray.setIcon(icon)
        menu = QMenu()
        settings_act = QAction("Settings", self.app)
        settings_act.triggered.connect(self._show_settings)
        menu.addAction(settings_act)
        quit_act = QAction("Quit", self.app)
        quit_act.triggered.connect(self.app.quit)
        menu.addAction(quit_act)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _show_settings(self) -> None:
        self.settings_window.show()
        self.settings_window.activateWindow()
        self.settings_window.raise_()

    def _on_config_changed(self, cfg: Config) -> None:
        self.cfg = cfg
        self.transcriber.language = cfg.language
        self.capture = AudioCapture(device=cfg.device_index)

    # -- silence detection ----------------------------------------------

    def _check_silence(self) -> None:
        if not self.is_recording:
            return
        raw = self.capture.current_energy
        vis = (math.log10(raw) + 4) / 3.0 if raw > 1e-10 else 0.0
        self.window.set_energy(min(1.0, max(0.0, vis)))

        if not self.capture.speech_detected:
            if time.time() - self.capture.last_sound_time >= self.cfg.silence_timeout:
                self._cancel_recording()
                return

        if self.capture.speech_detected and self.capture.last_sound_time:
            if time.time() - self.capture.last_sound_time >= self.cfg.silence_timeout:
                self._stop_recording()

    # -- recording lifecycle --------------------------------------------

    def _handle_toggle(self) -> None:
        if self.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _capture_active_window(self) -> None:
        try:
            r = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, text=True, timeout=1,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                self._saved_window_addr = data.get("address")
        except Exception:
            self._saved_window_addr = None

    def _start_recording(self) -> None:
        if self.is_recording:
            return
        if self.cfg.output_mode == "type":
            self._capture_active_window()
        self.is_recording = True
        self.window.position(self.cfg.window_position)
        self.window.set_state("recording")
        self.window.show()
        if self.cfg.output_mode != "type":
            self.window.activateWindow()
        self.window.raise_()
        self.capture.start()
        self.capture.last_sound_time = time.time()
        self.capture.speech_detected = False
        self._silence_timer.start()

    def _cancel_recording(self) -> None:
        if not self.is_recording:
            return
        self.is_recording = False
        self._silence_timer.stop()
        self.window.set_energy(0.0)
        self.capture.stop()
        self.capture.read()  # drain
        self.window.hide()

    def _stop_recording(self) -> None:
        if not self.is_recording:
            return
        self.is_recording = False
        self._silence_timer.stop()
        self.window.set_energy(0.0)
        self.capture.stop()
        self.window.set_state("analysing")
        threading.Thread(target=self._process_audio, daemon=True).start()

    def _process_audio(self) -> None:
        chunks = self.capture.read()
        text = ""
        if chunks:
            audio = np.concatenate(chunks)
            text = self.transcriber.transcribe(audio, sample_rate=self.capture.sample_rate)
        if text:
            self._deliver_text(text)
            QMetaObject.invokeMethod(
                self.window, "set_state",
                Qt.ConnectionType.QueuedConnection, Q_ARG(str, "done"),
            )
            time.sleep(1.0)
        QMetaObject.invokeMethod(
            self.window, "hide", Qt.ConnectionType.QueuedConnection,
        )

    # -- text delivery --------------------------------------------------

    def _deliver_text(self, text: str) -> None:
        if self.cfg.output_mode == "type":
            self._type_into_window(text)
        else:
            try:
                pyperclip.copy(text)
            except Exception as exc:
                print(f"Clipboard error: {exc}")

    def _type_into_window(self, text: str) -> None:
        if self._saved_window_addr:
            try:
                subprocess.run(
                    ["hyprctl", "dispatch", "focuswindow", f"address:{self._saved_window_addr}"],
                    capture_output=True, text=True, timeout=1,
                )
                time.sleep(0.3)
            except Exception:
                pass
        else:
            time.sleep(0.15)

        # Save clipboard
        saved: bytes | None = None
        try:
            r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=2)
            if r.returncode == 0:
                saved = r.stdout
        except Exception:
            pass

        # Set clipboard to text
        try:
            proc = subprocess.Popen(["wl-copy", "--"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"), timeout=2)
        except Exception:
            return

        # Paste
        if self._paste_tool == "ydotool":
            subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], timeout=2)
        elif self._paste_tool == "wtype":
            subprocess.run(
                ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"],
                capture_output=True, text=True, timeout=2,
            )
        elif self._paste_tool == "xdotool":
            subprocess.run(["xdotool", "key", "ctrl+v"], timeout=2)
        else:
            return

        # Restore clipboard
        time.sleep(0.15)
        try:
            if saved is not None:
                proc = subprocess.Popen(["wl-copy", "--"], stdin=subprocess.PIPE)
                proc.communicate(input=saved, timeout=2)
            else:
                subprocess.run(["wl-copy", "--clear"], capture_output=True, timeout=2)
        except Exception:
            pass

    # -- run ------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        sys.exit(self.app.exec())


def main() -> None:
    svc = DictateService()
    svc.run()
```

**Step 2: Commit**

```bash
git add src/dictate/service.py
git commit -m "feat: rewrite service.py with proper imports and Config dataclass"
```

---

### Task 8: Rewrite trigger.py

**Files:**
- Create: `src/dictate/trigger.py`

**Step 1: Write trigger.py**

```python
from __future__ import annotations

import zmq

IPC_ADDRESS = "ipc:///tmp/dictate_service.ipc"


def main() -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.connect(IPC_ADDRESS)
    sock.setsockopt(zmq.RCVTIMEO, 2000)

    sock.send_string("TOGGLE")
    try:
        reply = sock.recv_string()
        print(f"Service replied: {reply}")
    except zmq.error.Again:
        print("Service timed out. Is dictate running?")

    sock.close()
    ctx.term()


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add src/dictate/trigger.py
git commit -m "feat: rewrite trigger.py with updated IPC address"
```

---

### Task 9: Rewrite cli.py — lightweight push-to-talk CLI

**Files:**
- Create: `src/dictate/cli.py`

**Step 1: Write cli.py**

```python
from __future__ import annotations

import sys

import numpy as np
from rich.console import Console

from dictate.audio.capture import AudioCapture
from dictate.audio.transcriber import Transcriber
from dictate.config import Config

console = Console()


def main() -> None:
    cfg = Config.load()
    console.print("[bold green]Dictate CLI (push-to-talk)[/]")
    console.print("Press Ctrl+C to quit.\n")

    # Device selection
    devices = AudioCapture.list_devices()
    input_devs: list[tuple[int | None, dict]] = [(None, {"name": "System Default"})]
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            input_devs.append((i, dev))

    console.print("[yellow]Input devices:[/]")
    for idx, (_, dev) in enumerate(input_devs):
        console.print(f"  {idx}. {dev['name']}")

    while True:
        try:
            choice = input("Select microphone [0]: ").strip() or "0"
            ci = int(choice)
            if 0 <= ci < len(input_devs):
                selected = input_devs[ci][0]
                console.print(f"[green]Selected: {input_devs[ci][1]['name']}[/]\n")
                break
            console.print("[red]Invalid.[/]")
        except ValueError:
            console.print("[red]Invalid.[/]")

    capture = AudioCapture(device=selected)
    transcriber = Transcriber(language=cfg.language, on_text=lambda t: console.print(t))

    console.print("[yellow]Loading model...[/]")
    transcriber.load_model()

    try:
        while True:
            console.print("\n[bold white on blue] Ready [/] Press Enter to START (Ctrl+C to quit)")
            try:
                input()
            except EOFError:
                break

            capture.start()
            capture.last_sound_time = __import__("time").time()
            capture.speech_detected = False
            console.print("[bold red] REC [/] Press Enter to STOP")

            try:
                input()
            except EOFError:
                break

            capture.stop()
            chunks = capture.read()

            if chunks:
                audio = np.concatenate(chunks)
                duration = len(audio) / capture.sample_rate
                console.print(f"[dim]Captured {duration:.1f}s audio.[/]")
                text = transcriber.transcribe(audio, sample_rate=capture.sample_rate)
                if text:
                    console.print(f"[bold cyan]{text}[/]")
                else:
                    console.print("[dim]No speech detected.[/]")
            else:
                console.print("[dim]No audio captured.[/]")

    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()
        console.print("[bold green]Done.[/]")


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add src/dictate/cli.py
git commit -m "feat: rewrite CLI with proper package imports"
```

---

### Task 10: Add __main__.py

**Files:**
- Create: `src/dictate/__main__.py`

**Step 1: Write __main__.py**

```python
from dictate.service import main

main()
```

**Step 2: Commit**

```bash
git add src/dictate/__main__.py
git commit -m "feat: add __main__.py for python -m dictate"
```

---

### Task 11: Update .gitignore and clean up old files

**Files:**
- Modify: `.gitignore`
- Delete: `src/main.py`, `src/service.py`, `src/trigger.py`, `src/audio/`, `src/gui/`, `src/tui/`
- Delete: `test_nemo.py`, `test_tray.py`, `debug_components.py`, `debug_manual_processor.py`

**Step 1: Remove old source tree and debug files**

```bash
rm -rf src/main.py src/service.py src/trigger.py src/audio/ src/gui/ src/tui/
rm -f test_nemo.py test_tray.py debug_components.py debug_manual_processor.py
```

**Step 2: Update .gitignore**

Add `docs/plans/` is fine to keep tracked. Ensure `.venv` and standard Python ignores are present (already are).

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove old source tree and debug scripts"
```

---

### Task 12: Install and smoke test

**Step 1: Recreate venv and install**

```bash
rm -rf .venv
uv venv --python 3.10
uv pip install -e .
```

**Step 2: Verify entry points exist**

```bash
which dictate && which dictate-trigger && which dictate-cli
```

Expected: three paths in `.venv/bin/`

**Step 3: Verify imports work**

```bash
python -c "from dictate.config import Config; print(Config.load())"
python -c "from dictate.audio.capture import AudioCapture; print('OK')"
python -c "from dictate.audio.transcriber import Transcriber; print('OK')"
```

**Step 4: Quick CLI test**

```bash
dictate-cli
```

Expected: shows device list, loads model, enters push-to-talk loop.

**Step 5: Commit any fixes if needed**

---
