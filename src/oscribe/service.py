from __future__ import annotations

import logging
import math
import os
import signal
import sys
import queue
import threading
import time
from pathlib import Path

logger = logging.getLogger("oscribe")

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
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from oscribe.audio.capture import AudioCapture
from oscribe.audio import sounds
from oscribe.audio.transcriber import Transcriber
from oscribe.config import Config, _DEFAULT_CONFIG_PATH
from oscribe.desktop import DesktopHelper
from oscribe.gui.icon import create_tray_icon
from oscribe.gui.download import ModelDownloadDialog
from oscribe.gui.settings import SettingsWindow
from oscribe.gui.window import RecordingWindow

def _ipc_address() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return f"ipc://{runtime}/oscribe.ipc"
    return "ipc:///tmp/oscribe_service.ipc"

IPC_ADDRESS = _ipc_address()

CONFIG_PATH = _DEFAULT_CONFIG_PATH


class _IPCWorker(QObject):
    toggle_received = pyqtSignal()

    def run(self) -> None:
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REP)
        try:
            sock.bind(IPC_ADDRESS)
        except zmq.error.ZMQError:
            logger.error("IPC socket already in use — is another instance running?")
            import os
            os._exit(1)
        while True:
            try:
                msg = sock.recv_string()
                if msg == "TOGGLE":
                    self.toggle_received.emit()
                    sock.send_string("OK")
                else:
                    sock.send_string("UNKNOWN")
            except Exception as exc:
                logger.error("IPC error: %s", exc)


class OscribeService:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.cfg = Config.load(CONFIG_PATH)

        # Desktop integration (clipboard, paste, window focus)
        self.desktop = DesktopHelper()

        # Audio + transcription
        self.capture = AudioCapture(device=self.cfg.device_index)
        self.transcriber = Transcriber(
            model_size=self.cfg.model,
            language=self.cfg.language,
            punctuation_hints=self.cfg.punctuation_hints,
        )

        # GUI
        self.window = RecordingWindow()
        self.window.stop_signal.connect(self._stop_recording)

        self.settings_window = SettingsWindow(CONFIG_PATH)
        self.settings_window.config_saved.connect(self._on_config_changed)
        self.settings_window.cache_cleared.connect(self._on_cache_cleared)

        self._setup_tray()

        # Preload model (show progress dialog if download needed)
        self._preload_model()

        # State
        self.is_recording = False
        self._saved_window_id: str | None = None
        self._needs_model_reload = False

        # Streaming state
        self._stream_buffer: list[np.ndarray] = []
        self._stream_prev_text: str = ""
        self._stream_confirmed_len: int = 0  # chars already typed
        self._stream_timer = QTimer()
        self._stream_timer.setInterval(1000)
        self._stream_timer.timeout.connect(self._stream_tick)
        self._streaming_active = False

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
        self._tray.setIcon(create_tray_icon())
        menu = QMenu()
        # Disable compositor transparency on Wayland
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        menu.setWindowOpacity(1.0)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0A0A0A;
                color: #FFFFFF;
                border: 1px solid #2A2A2A;
                padding: 4px 0;
            }
            QMenu::item {
                background-color: #0A0A0A;
                padding: 8px 24px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: #1A1A1A;
            }
            QMenu::separator {
                height: 1px;
                background: #2A2A2A;
                margin: 4px 0;
            }
        """)
        settings_act = QAction("Settings", self.app)
        settings_act.triggered.connect(self._show_settings)
        menu.addAction(settings_act)
        menu.addSeparator()
        quit_act = QAction("Quit", self.app)
        quit_act.triggered.connect(self.app.quit)
        menu.addAction(quit_act)
        self._tray.setContextMenu(menu)
        self._tray.show()

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

    def _show_settings(self) -> None:
        self.settings_window.show()
        self.settings_window.activateWindow()
        self.settings_window.raise_()

    def _on_config_changed(self, cfg: Config) -> None:
        old_model = self.cfg.model
        self.cfg = cfg
        self.transcriber.language = cfg.language
        self.transcriber.punctuation_hints = cfg.punctuation_hints
        self.capture = AudioCapture(device=cfg.device_index)

        if cfg.model != old_model or self._needs_model_reload:
            self._needs_model_reload = False
            self._switch_model(cfg.model, old_model)

    def _switch_model(self, model_name: str, old_model: str) -> None:
        """Download (if needed) and load a new Whisper model."""
        self.transcriber.unload_model()
        self.transcriber.model_size = model_name

        dlg = ModelDownloadDialog(self.transcriber)
        dlg.start()

        if not dlg.succeeded():
            # Revert to previous model
            logger.warning("Model switch cancelled, reverting to previous model")
            self.transcriber.model_size = old_model
            self.cfg.model = old_model
            self.transcriber.load_model()

    def _on_cache_cleared(self) -> None:
        """Handle model cache being cleared from settings."""
        logger.info("Model cache cleared, unloading current model")
        self.transcriber.unload_model()
        self._needs_model_reload = True

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
        logger.info("Toggle received (recording=%s)", self.is_recording)
        if self.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self.is_recording:
            return
        if self.cfg.sound_enabled:
            sounds.play_start()
        if self.cfg.output_mode == "type":
            self._saved_window_id = self.desktop.capture_active_window()
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

        # Start streaming if enabled
        if self.cfg.streaming and self.cfg.output_mode == "type":
            self._streaming_active = True
            self._stream_buffer = []
            self._stream_prev_text = ""
            self._stream_confirmed_len = 0
            self._stream_timer.start()
            logger.info("Streaming transcription active")

    def _cancel_recording(self) -> None:
        if not self.is_recording:
            return
        logger.info("Recording cancelled (no speech detected).")
        self.is_recording = False
        self._silence_timer.stop()
        if self._streaming_active:
            self._streaming_active = False
            self._stream_timer.stop()
        self.window.set_energy(0.0)
        self.capture.stop()
        self.capture.read()  # drain
        self.window.hide()

    def _stop_recording(self) -> None:
        if not self.is_recording:
            return
        self.is_recording = False
        self._silence_timer.stop()
        # Stop streaming timer
        if self._streaming_active:
            self._streaming_active = False
            self._stream_timer.stop()
        self.window.set_energy(0.0)
        self.capture.stop()
        if self.cfg.sound_enabled:
            sounds.play_analysing()
        self.window.set_state("analysing")
        threading.Thread(target=self._process_audio, daemon=True).start()

    def _process_audio(self) -> None:
        chunks = self.capture.read()

        # In streaming mode, merge remaining capture chunks into stream buffer
        if self._stream_buffer:
            chunks = self._stream_buffer + chunks
            self._stream_buffer = []

        text = ""
        if chunks:
            audio = np.concatenate(chunks)
            logger.debug(
                "Audio: %d samples @ %dHz (%.1fs)",
                len(audio), self.capture.sample_rate,
                len(audio) / self.capture.sample_rate,
            )
            text = self.transcriber.transcribe(audio, sample_rate=self.capture.sample_rate)
        else:
            logger.debug("No audio chunks captured.")

        if text:
            if self.cfg.output_mode == "type":
                # Hide overlay BEFORE typing so it doesn't steal focus
                QMetaObject.invokeMethod(
                    self.window, "hide", Qt.ConnectionType.QueuedConnection,
                )
                time.sleep(0.08)  # let compositor process the unmap

            # In streaming mode, only type the remaining unconfirmed text
            if self._stream_confirmed_len > 0:
                remaining = text[self._stream_confirmed_len:]
                self._stream_confirmed_len = 0
                self._stream_prev_text = ""
                if remaining.strip():
                    self._deliver_text(remaining.strip())
            else:
                self._deliver_text(text)

            if self.cfg.sound_enabled:
                sounds.play_done()
            if self.cfg.output_mode != "type":
                QMetaObject.invokeMethod(
                    self.window, "set_state",
                    Qt.ConnectionType.QueuedConnection, Q_ARG(str, "done"),
                )
                time.sleep(0.5)
        QMetaObject.invokeMethod(
            self.window, "hide", Qt.ConnectionType.QueuedConnection,
        )

    # -- streaming transcription ----------------------------------------

    def _stream_tick(self) -> None:
        """Periodic streaming transcription while recording."""
        if not self._streaming_active:
            return

        # Drain current audio chunks into buffer
        while True:
            try:
                chunk = self.capture._queue.get_nowait()
                if chunk.ndim > 1:
                    chunk = chunk.flatten()
                self._stream_buffer.append(chunk)
            except queue.Empty:
                break

        if not self._stream_buffer:
            return

        audio = np.concatenate(self._stream_buffer)
        if len(audio) < self.capture.sample_rate:
            return  # need at least 1s of audio

        # Run in thread to not block UI
        threading.Thread(
            target=self._stream_transcribe,
            args=(audio.copy(), self.capture.sample_rate),
            daemon=True,
        ).start()

    def _stream_transcribe(self, audio: np.ndarray, sample_rate: int) -> None:
        """Background thread: transcribe and type confirmed text."""
        confirmed, full = self.transcriber.transcribe_streaming(
            audio, sample_rate=sample_rate, prev_text=self._stream_prev_text,
        )
        self._stream_prev_text = full

        # Type only the newly confirmed portion
        if confirmed and len(confirmed) > self._stream_confirmed_len:
            new_text = confirmed[self._stream_confirmed_len:]
            # Add trailing space so next chunk appends cleanly
            if not new_text.endswith(" "):
                new_text += " "
            self._stream_confirmed_len = len(confirmed)
            logger.debug("Streaming: typing confirmed %r", new_text)
            self.desktop.type_into_window(new_text, self._saved_window_id)

    # -- text delivery --------------------------------------------------

    def _deliver_text(self, text: str) -> None:
        if self.cfg.output_mode == "type":
            self.desktop.type_into_window(text, self._saved_window_id)
        else:
            try:
                pyperclip.copy(text)
            except Exception as exc:
                logger.error("Clipboard error: %s", exc)

    # -- run ------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        sys.exit(self.app.exec())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    svc = OscribeService()
    svc.run()
