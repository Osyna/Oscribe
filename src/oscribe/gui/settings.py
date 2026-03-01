from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("oscribe")

from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from oscribe.audio.capture import AudioCapture
from oscribe.audio.transcriber import WHISPER_MODELS
from oscribe.config import Config

# ── palette ──────────────────────────────────────────────────────

BG = "#0A0A0A"
FG = "#FFFFFF"
MUTED = "#666666"
BORDER = "#2A2A2A"
CONTROL_BG = "#111111"


# ── shared stylesheet fragments ─────────────────────────────────

_COMBO_STYLE = f"""
QComboBox {{
    background: {CONTROL_BG};
    color: {FG};
    border: 1px solid {BORDER};
    padding: 6px 10px;
    font-size: 13px;
    min-height: 18px;
}}
QComboBox:hover {{
    border-color: {MUTED};
}}
QComboBox:focus {{
    border-color: {FG};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {FG};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {CONTROL_BG};
    color: {FG};
    border: 1px solid {BORDER};
    selection-background-color: #222222;
    selection-color: {FG};
    outline: none;
    padding: 0;
    margin: 0;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 10px;
    min-height: 22px;
    background: {CONTROL_BG};
    color: {FG};
}}
QComboBox QAbstractItemView::item:selected {{
    background: #222222;
}}
QComboBox QListView {{
    background: {CONTROL_BG};
    border: 1px solid {BORDER};
    padding: 0;
    margin: 0;
}}
QComboBox QScrollBar:vertical {{
    background: {CONTROL_BG};
    width: 6px;
    margin: 0;
    padding: 0;
}}
QComboBox QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 20px;
}}
QComboBox QScrollBar::add-line:vertical,
QComboBox QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


class _StyledComboBox(QComboBox):
    """QComboBox subclass that forces the popup frame background to black."""

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.findChild(QWidget, "QComboBoxPrivateContainer")
        if popup is not None:
            popup.setStyleSheet(f"background: {CONTROL_BG}; border: 1px solid {BORDER}; padding: 0; margin: 0;")
        frame = self.view().parentWidget()
        if frame is not None:
            frame.setStyleSheet(f"background: {CONTROL_BG}; border: 1px solid {BORDER}; padding: 0; margin: 0;")


class ValueStepper(QWidget):
    """Minimal [ - ]  value  [ + ] stepper widget."""

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        value: float = 3.0,
        minimum: float = 1.0,
        maximum: float = 10.0,
        step: float = 0.5,
        suffix: str = "s",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self._min = minimum
        self._max = maximum
        self._step = step
        self._suffix = suffix
        self.setFixedSize(140, 34)

        _btn = (
            f"background: {CONTROL_BG}; color: {FG}; border: 1px solid {BORDER}; "
            f"font-size: 16px; font-weight: 400;"
        )
        _btn_hover = f"background: #1A1A1A; border-color: {MUTED};"

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._minus = QPushButton("\u2212")  # minus sign
        self._minus.setFixedSize(34, 34)
        self._minus.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minus.setStyleSheet(
            f"QPushButton {{ {_btn} }} QPushButton:hover {{ {_btn_hover} }}"
        )
        self._minus.clicked.connect(self._dec)
        row.addWidget(self._minus)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"background: {CONTROL_BG}; color: {FG}; "
            f"border-top: 1px solid {BORDER}; border-bottom: 1px solid {BORDER}; "
            f"border-left: none; border-right: none; "
            f"font-size: 13px; padding: 0 4px;"
        )
        row.addWidget(self._label, 1)

        self._plus = QPushButton("+")
        self._plus.setFixedSize(34, 34)
        self._plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus.setStyleSheet(
            f"QPushButton {{ {_btn} }} QPushButton:hover {{ {_btn_hover} }}"
        )
        self._plus.clicked.connect(self._inc)
        row.addWidget(self._plus)

        self._refresh()

    def value(self) -> float:
        return self._value

    def setValue(self, v: float) -> None:
        self._value = max(self._min, min(self._max, v))
        self._refresh()

    def _inc(self) -> None:
        self.setValue(round(self._value + self._step, 1))
        self.valueChanged.emit(self._value)

    def _dec(self) -> None:
        self.setValue(round(self._value - self._step, 1))
        self.valueChanged.emit(self._value)

    def _refresh(self) -> None:
        self._label.setText(f"{self._value:.1f}{self._suffix}")
        self._minus.setEnabled(self._value > self._min)
        self._plus.setEnabled(self._value < self._max)


# ── custom toggle switch ─────────────────────────────────────────

class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False
        self._thumb_x = 2.0

        self._anim = QPropertyAnimation(self, b"thumbX")
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool) -> None:
        if self._checked == on:
            return
        self._checked = on
        end = 24.0 if on else 2.0
        self._anim.stop()
        self._anim.setStartValue(self._thumb_x)
        self._anim.setEndValue(end)
        self._anim.start()
        self.toggled.emit(on)

    @pyqtProperty(float)
    def thumbX(self) -> float:
        return self._thumb_x

    @thumbX.setter
    def thumbX(self, val: float) -> None:
        self._thumb_x = val
        self.update()

    def mousePressEvent(self, ev: object) -> None:
        self.setChecked(not self._checked)

    def paintEvent(self, ev: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Track
        track_color = QColor(FG) if self._checked else QColor(BORDER)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(track_color if self._checked else QColor(CONTROL_BG))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

        # Thumb — square
        thumb_color = QColor(BG) if self._checked else QColor(FG)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(thumb_color)
        p.drawRect(int(self._thumb_x), 2, 18, 18)

        p.end()


# ── helpers ──────────────────────────────────────────────────────

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {MUTED}; font-size: 10px; letter-spacing: 3px; "
        f"padding: 0; margin: 0; border: none; background: transparent;"
    )
    return lbl


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {FG}; font-size: 13px; "
        f"padding: 0; margin: 0; border: none; background: transparent;"
    )
    return lbl


def _hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {MUTED}; font-size: 11px; "
        f"padding: 0; margin: 0; border: none; background: transparent;"
    )
    return lbl


def _separator() -> QWidget:
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {BORDER};")
    return line


# ── settings window ──────────────────────────────────────────────

class SettingsWindow(QWidget):
    config_saved = pyqtSignal(object)
    cache_cleared = pyqtSignal()

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("oscribe")
        self.setFixedWidth(400)
        self.config_path = config_path

        self.setStyleSheet(f"""
            QWidget {{
                background: {BG};
                color: {FG};
                font-family: system-ui, -apple-system, sans-serif;
            }}
        """)

        root = QVBoxLayout()
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(0)

        # ── title ────────────────────────────────────────────────
        title = QLabel("SETTINGS")
        title.setStyleSheet(
            f"color: {FG}; font-size: 11px; letter-spacing: 6px; "
            f"font-weight: 500; border: none; background: transparent; padding: 0; margin: 0;"
        )
        root.addWidget(title)
        root.addSpacing(24)
        root.addWidget(_separator())

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

        # ── audio section ────────────────────────────────────────
        root.addSpacing(20)
        root.addWidget(_section_label("Audio"))
        root.addSpacing(12)

        self.device_combo = _StyledComboBox()
        self.device_combo.setStyleSheet(_COMBO_STYLE)
        self.device_combo.setFixedWidth(180)
        self._populate_devices()
        root.addLayout(self._row("Microphone", self.device_combo))

        root.addSpacing(12)

        self.lang_combo = _StyledComboBox()
        self.lang_combo.setStyleSheet(_COMBO_STYLE)
        self.lang_combo.setFixedWidth(140)
        self._populate_languages()
        root.addLayout(self._row("Language", self.lang_combo))

        root.addSpacing(20)
        root.addWidget(_separator())

        # ── output section ───────────────────────────────────────
        root.addSpacing(20)
        root.addWidget(_section_label("Output"))
        root.addSpacing(12)

        # Toggle row: "Paste method" with descriptive state label
        self.output_toggle = ToggleSwitch()
        self.output_label = QLabel("Copy to clipboard")
        self.output_label.setStyleSheet(
            f"color: {MUTED}; font-size: 12px; border: none; background: transparent; padding: 0; margin: 0;"
        )
        self.output_toggle.toggled.connect(self._on_output_toggle)
        out_row = QHBoxLayout()
        out_row.setContentsMargins(0, 0, 0, 0)
        out_row.addWidget(_field_label("Auto-type"))
        out_row.addStretch()
        out_row.addWidget(self.output_label)
        out_row.addSpacing(10)
        out_row.addWidget(self.output_toggle)
        root.addLayout(out_row)

        root.addSpacing(4)
        hint = _hint_label("When on, text is typed into the focused window")
        root.addWidget(hint)

        root.addSpacing(12)

        # Live typing toggle (only active when auto-type is on)
        self.streaming_toggle = ToggleSwitch()
        self.streaming_label = QLabel("Off")
        self.streaming_label.setStyleSheet(
            f"color: {MUTED}; font-size: 12px; border: none; background: transparent; padding: 0; margin: 0;"
        )
        self.streaming_toggle.toggled.connect(self._on_streaming_toggle)
        stream_row = QHBoxLayout()
        stream_row.setContentsMargins(0, 0, 0, 0)
        stream_row.addWidget(_field_label("Live typing (alpha)"))
        stream_row.addStretch()
        stream_row.addWidget(self.streaming_label)
        stream_row.addSpacing(10)
        stream_row.addWidget(self.streaming_toggle)
        root.addLayout(stream_row)

        root.addSpacing(4)
        self.streaming_hint = _hint_label("Text appears as you speak (requires auto-type)")
        root.addWidget(self.streaming_hint)

        root.addSpacing(12)

        self.position_combo = _StyledComboBox()
        self.position_combo.setStyleSheet(_COMBO_STYLE)
        self.position_combo.setFixedWidth(160)
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
        root.addLayout(self._row("Overlay position", self.position_combo))

        root.addSpacing(20)
        root.addWidget(_separator())

        # ── timing section ───────────────────────────────────────
        root.addSpacing(20)
        root.addWidget(_section_label("Timing"))
        root.addSpacing(12)

        self.silence_stepper = ValueStepper(
            value=3.0, minimum=1.0, maximum=10.0, step=0.5, suffix="s",
        )
        root.addLayout(self._row("Silence timeout", self.silence_stepper))

        root.addSpacing(20)
        root.addWidget(_separator())

        # ── feedback section ─────────────────────────────────────
        root.addSpacing(20)
        root.addWidget(_section_label("Feedback"))
        root.addSpacing(12)

        self.sound_toggle = ToggleSwitch()
        sound_row = QHBoxLayout()
        sound_row.setContentsMargins(0, 0, 0, 0)
        sound_row.addWidget(_field_label("Sound effects"))
        sound_row.addStretch()
        sound_row.addWidget(self.sound_toggle)
        root.addLayout(sound_row)

        root.addSpacing(4)
        root.addWidget(_hint_label("Play tones on record, process, and done"))

        root.addSpacing(12)

        self.punctuation_toggle = ToggleSwitch()
        punct_row = QHBoxLayout()
        punct_row.setContentsMargins(0, 0, 0, 0)
        punct_row.addWidget(_field_label("Punctuation hints"))
        punct_row.addStretch()
        punct_row.addWidget(self.punctuation_toggle)
        root.addLayout(punct_row)

        root.addSpacing(4)
        root.addWidget(_hint_label("Nudge Whisper to add natural punctuation"))

        root.addSpacing(20)
        root.addWidget(_separator())

        # ── storage section ─────────────────────────────────────
        root.addSpacing(20)
        root.addWidget(_section_label("Storage"))
        root.addSpacing(12)

        self._cache_size_label = QLabel("")
        self._cache_size_label.setStyleSheet(
            f"color: {MUTED}; font-size: 12px; border: none; "
            f"background: transparent; padding: 0; margin: 0;"
        )

        cache_row = QHBoxLayout()
        cache_row.setContentsMargins(0, 0, 0, 0)
        cache_row.addWidget(_field_label("Downloaded models"))
        cache_row.addStretch()
        cache_row.addWidget(self._cache_size_label)
        root.addLayout(cache_row)

        root.addSpacing(8)

        self._clear_cache_btn = QPushButton("Clear model cache")
        self._clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_cache_btn.setFixedHeight(32)
        self._clear_cache_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #CC4444;
                border: 1px solid #CC4444;
                padding: 4px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: #1A0000;
                border-color: #FF5555;
                color: #FF5555;
            }}
        """)
        self._clear_cache_btn.clicked.connect(self._clear_model_cache)
        root.addWidget(self._clear_cache_btn)

        root.addSpacing(4)
        root.addWidget(_hint_label("Remove all cached Whisper models from disk"))

        root.addSpacing(28)
        root.addWidget(_separator())
        root.addSpacing(20)

        # ── save button ──────────────────────────────────────────
        save_btn = QWidget()
        save_btn.setFixedHeight(40)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QWidget {{
                background: {FG};
                color: {BG};
            }}
            QWidget:hover {{
                background: #DDDDDD;
            }}
        """)
        save_layout = QVBoxLayout(save_btn)
        save_layout.setContentsMargins(0, 0, 0, 0)
        save_text = QLabel("APPLY")
        save_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        save_text.setStyleSheet(
            f"color: {BG}; font-size: 11px; letter-spacing: 4px; "
            f"font-weight: 600; border: none; background: transparent;"
        )
        save_layout.addWidget(save_text)
        save_btn.mousePressEvent = lambda ev: self._save()
        root.addWidget(save_btn)

        root.addStretch()
        self.setLayout(root)
        self._load_current()

    def _row(self, label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_field_label(label))
        row.addStretch()
        row.addWidget(widget)
        return row

    def _on_output_toggle(self, on: bool) -> None:
        self.output_label.setText("Type into window" if on else "Copy to clipboard")
        # Gray out streaming toggle when auto-type is off
        self.streaming_toggle.setEnabled(on)
        if not on:
            self.streaming_toggle.setChecked(False)

    def _on_streaming_toggle(self, on: bool) -> None:
        self.streaming_label.setText("On" if on else "Off")

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
        idx = self.model_combo.findData(cfg.model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        idx = self.lang_combo.findData(cfg.language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        if cfg.device_index is None:
            self.device_combo.setCurrentIndex(0)
        else:
            idx = self.device_combo.findData(cfg.device_index)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        self.output_toggle.setChecked(cfg.output_mode == "type")
        idx = self.position_combo.findData(cfg.window_position)
        if idx >= 0:
            self.position_combo.setCurrentIndex(idx)
        self.silence_stepper.setValue(cfg.silence_timeout)
        self.sound_toggle.setChecked(cfg.sound_enabled)
        self.streaming_toggle.setChecked(cfg.streaming)
        self.streaming_toggle.setEnabled(cfg.output_mode == "type")
        self.punctuation_toggle.setChecked(cfg.punctuation_hints)
        self._update_cache_size()

    def _save(self) -> None:
        cfg = Config(
            device_index=self.device_combo.currentData(),
            language=self.lang_combo.currentData(),
            output_mode="type" if self.output_toggle.isChecked() else "clipboard",
            window_position=self.position_combo.currentData(),
            silence_timeout=self.silence_stepper.value(),
            sound_enabled=self.sound_toggle.isChecked(),
            streaming=self.streaming_toggle.isChecked(),
            punctuation_hints=self.punctuation_toggle.isChecked(),
            model=self.model_combo.currentData(),
        )
        try:
            cfg.save(self.config_path)
            self.config_saved.emit(cfg)
            self.hide()
        except Exception as exc:
            logger.error("Settings save error: %s", exc)
            QMessageBox.critical(self, "Error", f"Failed to save settings:\n{exc}")

    def _update_cache_size(self) -> None:
        try:
            from huggingface_hub import scan_cache_dir
            from faster_whisper.utils import _MODELS
            whisper_repos = set(_MODELS.values())
            info = scan_cache_dir()
            total = sum(r.size_on_disk for r in info.repos if r.repo_id in whisper_repos)
            count = sum(1 for r in info.repos if r.repo_id in whisper_repos)
            if total > 0:
                if total >= 1e9:
                    size_str = f"{total / 1e9:.1f} GB"
                else:
                    size_str = f"{total / 1e6:.0f} MB"
                self._cache_size_label.setText(f"{count} model{'s' if count != 1 else ''}, {size_str}")
            else:
                self._cache_size_label.setText("No models cached")
        except Exception:
            self._cache_size_label.setText("")

    def _clear_model_cache(self) -> None:
        try:
            from huggingface_hub import scan_cache_dir
            from faster_whisper.utils import _MODELS
            whisper_repos = set(_MODELS.values())
            info = scan_cache_dir()

            revisions = []
            total = 0
            count = 0
            for repo in info.repos:
                if repo.repo_id in whisper_repos:
                    count += 1
                    total += repo.size_on_disk
                    for rev in repo.revisions:
                        revisions.append(rev.commit_hash)

            if not revisions:
                QMessageBox.information(self, "oscribe", "No cached models to remove.")
                return

            if total >= 1e9:
                size_str = f"{total / 1e9:.1f} GB"
            else:
                size_str = f"{total / 1e6:.0f} MB"

            reply = QMessageBox.question(
                self,
                "oscribe",
                f"Delete {count} cached model{'s' if count != 1 else ''} ({size_str})?\n\n"
                "The active model will be re-downloaded on next use.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            strategy = info.delete_revisions(*revisions)
            strategy.execute()
            logger.info("Cleared %d model(s) (%s) from cache", count, size_str)

            self._update_cache_size()
            self.cache_cleared.emit()

        except Exception as exc:
            logger.error("Cache clear error: %s", exc)
            QMessageBox.critical(self, "Error", f"Failed to clear cache:\n{exc}")
