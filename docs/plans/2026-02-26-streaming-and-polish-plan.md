# Streaming & Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add opt-in streaming transcription, per-language punctuation hints, and robustness fixes to the dictate app.

**Architecture:** Streaming uses local agreement — transcribe accumulated audio every ~1s, emit only text that consecutive runs agree on. Punctuation hints use Whisper's `initial_prompt` parameter. Robustness covers logging, IPC guard, XDG socket, clipboard safety, startup validation, and settings error feedback.

**Tech Stack:** Python 3.10+, faster-whisper, PyQt6, PyZMQ, sounddevice

**Note:** This project has no test suite. Verification is manual — run the app and test each feature. Each task includes a "Verify" step describing what to check.

---

### Task 1: Replace print() with logging module

All files currently use `print()`. Switch to `logging.getLogger("dictate")` with INFO default level.

**Files:**
- Modify: `src/dictate/service.py` (all print calls)
- Modify: `src/dictate/desktop.py` (all print calls)
- Modify: `src/dictate/audio/capture.py:51` (status print)
- Modify: `src/dictate/audio/transcriber.py` (already has logger — just use it consistently)
- Modify: `src/dictate/gui/settings.py:512` (save error print)

**Step 1: Add logger and replace prints in service.py**

At top of `service.py`, after imports add:
```python
import logging

logger = logging.getLogger("dictate")
```

Replace every `print(...)` with the appropriate log level:
- `print(f"Toggle received...")` → `logger.info(...)`
- `print("Loading model...")` → `logger.info(...)`
- `print("Model loaded.")` → `logger.info(...)`
- `print("Recording cancelled...")` → `logger.info(...)`
- `print(f"Audio: {len(audio)}...")` → `logger.debug(...)`
- `print("No audio chunks captured.")` → `logger.debug(...)`
- `print(f"Clipboard error: {exc}")` → `logger.error(...)`
- `print("IPC socket already in use.")` → `logger.error(...)` (in _IPCWorker)
- `print(f"IPC error: {exc}")` → `logger.error(...)`

Add logging setup in `main()`:
```python
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    svc = DictateService()
    svc.run()
```

**Step 2: Replace prints in desktop.py**

At top, after imports:
```python
import logging

logger = logging.getLogger("dictate")
```

Replace:
- `print(f"Desktop: {self.display}...")` → `logger.info(...)`
- `print(f"Desktop: paste {combo}...")` → `logger.debug(...)`
- `print("Desktop: clipboard_write failed")` → `logger.warning(...)`
- `print(f"Desktop: all paste methods failed")` → `logger.warning(...)`

**Step 3: Replace prints in capture.py**

At top:
```python
import logging

logger = logging.getLogger("dictate")
```

Replace:
- `print(status, flush=True)` → `logger.warning("Audio callback: %s", status)`
- `print(f"Warning querying device: {exc}")` → `logger.warning("Device query fallback: %s", exc)`

**Step 4: Replace print in settings.py**

At top:
```python
import logging

logger = logging.getLogger("dictate")
```

Replace:
- `print(f"Settings save error: {exc}")` → `logger.error("Settings save error: %s", exc)`

**Step 5: Remove `on_text` callback from Transcriber**

The `on_text` callback in `Transcriber` duplicates what logging does. Remove it:
- In `transcriber.py`: Remove `on_text` parameter and all `if self.on_text:` blocks. Use `logger.info(...)` instead.
- In `service.py`: Change `Transcriber(language=self.cfg.language, on_text=print)` to `Transcriber(language=self.cfg.language)`

**Step 6: Commit**

```bash
git add src/dictate/service.py src/dictate/desktop.py src/dictate/audio/capture.py src/dictate/audio/transcriber.py src/dictate/gui/settings.py
git commit -m "refactor: replace print() with logging module"
```

**Verify:** Run `dictate` — should see timestamped log output in terminal. All functionality unchanged.

---

### Task 2: IPC guard — prevent duplicate instances

**Files:**
- Modify: `src/dictate/service.py:42-48` (_IPCWorker.run)

**Step 1: Exit on bind failure**

Replace the `_IPCWorker.run` method:

```python
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
```

Note: Use `os._exit(1)` not `sys.exit(1)` because this runs in a QThread — `sys.exit` only raises `SystemExit` in the calling thread.

**Step 2: Commit**

```bash
git add src/dictate/service.py
git commit -m "fix: exit on duplicate instance instead of silently continuing"
```

**Verify:** Run `dictate` twice. Second instance should log error and exit immediately.

---

### Task 3: XDG-compliant IPC socket path

**Files:**
- Modify: `src/dictate/service.py:34` (IPC_ADDRESS)
- Modify: `src/dictate/trigger.py:5` (IPC_ADDRESS)

**Step 1: Create shared IPC address helper**

In `service.py`, replace the constant:

```python
def _ipc_address() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return f"ipc://{runtime}/dictate.ipc"
    return "ipc:///tmp/dictate_service.ipc"

IPC_ADDRESS = _ipc_address()
```

Add `import os` at top if not already there.

**Step 2: Update trigger.py**

Replace `IPC_ADDRESS` in trigger.py with the same logic:

```python
import os

import zmq


def _ipc_address() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return f"ipc://{runtime}/dictate.ipc"
    return "ipc:///tmp/dictate_service.ipc"

IPC_ADDRESS = _ipc_address()
```

**Step 3: Commit**

```bash
git add src/dictate/service.py src/dictate/trigger.py
git commit -m "fix: use XDG_RUNTIME_DIR for IPC socket path"
```

**Verify:** Run `echo $XDG_RUNTIME_DIR` (should be `/run/user/1000`). Start `dictate`, then `dictate-trigger`. Check `ls /run/user/1000/dictate.ipc` exists.

---

### Task 4: Clipboard restore in try/finally

**Files:**
- Modify: `src/dictate/desktop.py:369-400` (type_into_window)

**Step 1: Wrap clipboard operations in try/finally**

Replace the "Set clipboard → paste → restore" section in `type_into_window`:

```python
        # Set clipboard → paste → restore
        try:
            if not self.clipboard_write(text):
                logger.warning("Desktop: clipboard_write failed")
                return
            time.sleep(0.05)

            if not self.simulate_paste(window_id):
                logger.warning("Desktop: all paste methods failed")
        finally:
            time.sleep(0.15)
            self.clipboard_restore(saved)
```

This guarantees `clipboard_restore` runs even if `simulate_paste` throws.

**Step 2: Commit**

```bash
git add src/dictate/desktop.py
git commit -m "fix: guarantee clipboard restore with try/finally"
```

**Verify:** Dictation should work as before. Copy something to clipboard, dictate, verify clipboard is restored.

---

### Task 5: Startup validation warning

**Files:**
- Modify: `src/dictate/desktop.py:148-151` (DesktopHelper.__init__)

**Step 1: Add warning after tool detection**

After the existing print/log line in `__init__`, add:

```python
        if not self._paste_tools:
            logger.warning(
                "No paste tool available — install ydotool, wtype, or xdotool. "
                "Auto-type mode will not work."
            )
```

**Step 2: Commit**

```bash
git add src/dictate/desktop.py
git commit -m "fix: warn at startup if no paste tool available"
```

**Verify:** Rename wtype temporarily (`sudo mv /usr/bin/wtype /usr/bin/wtype.bak`), start dictate, see warning. Rename back after.

---

### Task 6: Settings save error feedback in GUI

**Files:**
- Modify: `src/dictate/gui/settings.py:507-512` (_save method)

**Step 1: Show QMessageBox on save failure**

Add import at top of settings.py:
```python
from PyQt6.QtWidgets import QMessageBox
```

(Add `QMessageBox` to the existing `from PyQt6.QtWidgets import ...` line.)

Replace the except block in `_save`:

```python
        except Exception as exc:
            logger.error("Settings save error: %s", exc)
            QMessageBox.critical(self, "Error", f"Failed to save settings:\n{exc}")
```

**Step 2: Commit**

```bash
git add src/dictate/gui/settings.py
git commit -m "fix: show error dialog on settings save failure"
```

**Verify:** Make config file read-only (`chmod 444 src/config.yaml`), open settings, click APPLY — should show error dialog. Restore: `chmod 644 src/config.yaml`.

---

### Task 7: Add new config fields

**Files:**
- Modify: `src/dictate/config.py` (add fields, update load/save)
- Modify: `src/config.yaml` (add defaults)

**Step 1: Add streaming and punctuation_hints to Config dataclass**

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
```

**Step 2: Update load() to read new fields**

Add to the `cls(...)` call in `load()`:
```python
                streaming=bool(data.get("streaming", False)),
                punctuation_hints=bool(data.get("punctuation_hints", True)),
```

**Step 3: Update save() to write new fields**

Add to the `data = {...}` dict in `save()`:
```python
            "streaming": self.streaming,
            "punctuation_hints": self.punctuation_hints,
```

**Step 4: Update src/config.yaml**

Add new fields:
```yaml
streaming: false
punctuation_hints: true
```

**Step 5: Commit**

```bash
git add src/dictate/config.py src/config.yaml
git commit -m "feat: add streaming and punctuation_hints config fields"
```

**Verify:** `python3 -c "from dictate.config import Config; c = Config(); print(c.streaming, c.punctuation_hints)"` — should print `False True`.

---

### Task 8: Add punctuation hint prompts to Transcriber

**Files:**
- Modify: `src/dictate/audio/transcriber.py`

**Step 1: Add PUNCTUATION_PROMPTS dict**

After the imports, add:

```python
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
```

**Step 2: Add punctuation_hints flag to Transcriber.__init__**

```python
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
```

**Step 3: Pass initial_prompt in transcribe()**

In the `self._model.transcribe(...)` call, add the `initial_prompt` parameter:

```python
            initial_prompt=(
                PUNCTUATION_PROMPTS.get(self.language)
                if self.punctuation_hints else None
            ),
```

Add it after `language=self.language,` in the transcribe call.

**Step 4: Update service.py to pass punctuation_hints**

In `DictateService.__init__`:
```python
        self.transcriber = Transcriber(
            language=self.cfg.language,
            punctuation_hints=self.cfg.punctuation_hints,
        )
```

In `_on_config_changed`:
```python
    def _on_config_changed(self, cfg: Config) -> None:
        self.cfg = cfg
        self.transcriber.language = cfg.language
        self.transcriber.punctuation_hints = cfg.punctuation_hints
        self.capture = AudioCapture(device=cfg.device_index)
```

**Step 5: Commit**

```bash
git add src/dictate/audio/transcriber.py src/dictate/service.py
git commit -m "feat: add per-language punctuation hints via initial_prompt"
```

**Verify:** Run dictate with `punctuation_hints: true`, dictate "hello how are you" — should get punctuation. Toggle off in config, repeat — should get raw output.

---

### Task 9: Add settings UI toggles for Live typing and Punctuation hints

**Files:**
- Modify: `src/dictate/gui/settings.py`

**Step 1: Add Live typing toggle after Auto-type toggle**

After the existing auto-type hint label (line ~369), add the streaming toggle:

```python
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
        stream_row.addWidget(_field_label("Live typing"))
        stream_row.addStretch()
        stream_row.addWidget(self.streaming_label)
        stream_row.addSpacing(10)
        stream_row.addWidget(self.streaming_toggle)
        root.addLayout(stream_row)

        root.addSpacing(4)
        self.streaming_hint = _hint_label("Text appears as you speak (requires auto-type)")
        root.addWidget(self.streaming_hint)
```

**Step 2: Add Punctuation hints toggle**

After the streaming hint, add:

```python
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
```

**Step 3: Add toggle handlers**

```python
    def _on_streaming_toggle(self, on: bool) -> None:
        self.streaming_label.setText("On" if on else "Off")

    def _on_output_toggle(self, on: bool) -> None:
        self.output_label.setText("Type into window" if on else "Copy to clipboard")
        # Gray out streaming toggle when auto-type is off
        self.streaming_toggle.setEnabled(on)
        if not on:
            self.streaming_toggle.setChecked(False)
```

(Replace existing `_on_output_toggle` and add `_on_streaming_toggle`.)

**Step 4: Update _load_current to load new fields**

Add at the end of `_load_current`:
```python
        self.streaming_toggle.setChecked(cfg.streaming)
        self.streaming_toggle.setEnabled(cfg.output_mode == "type")
        self.punctuation_toggle.setChecked(cfg.punctuation_hints)
```

**Step 5: Update _save to include new fields**

In `_save`, add to the `Config(...)` constructor:
```python
            streaming=self.streaming_toggle.isChecked(),
            punctuation_hints=self.punctuation_toggle.isChecked(),
```

**Step 6: Commit**

```bash
git add src/dictate/gui/settings.py
git commit -m "feat: add Live typing and Punctuation hints toggles to settings"
```

**Verify:** Open settings. See new toggles. Disable auto-type — streaming toggle should gray out. Toggle punctuation hints. Click APPLY, reopen settings — values should persist.

---

### Task 10: Add transcribe_streaming method to Transcriber

**Files:**
- Modify: `src/dictate/audio/transcriber.py`

**Step 1: Add transcribe_streaming method**

Add after the existing `transcribe()` method:

```python
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
```

**Step 2: Commit**

```bash
git add src/dictate/audio/transcriber.py
git commit -m "feat: add transcribe_streaming with local agreement algorithm"
```

**Verify:** Quick Python test:
```python
t = Transcriber()
t.load_model()
# Simulate two runs with overlapping text
confirmed, full = t.transcribe_streaming(audio_1s, prev_text="")
# confirmed should be "", full should be the transcription
confirmed2, full2 = t.transcribe_streaming(audio_2s, prev_text=full)
# confirmed2 should be the common prefix words
```

---

### Task 11: Streaming orchestration in service.py

This is the largest task. The service needs a streaming mode that:
- Accumulates audio in a buffer while recording
- Every ~1s, runs `transcribe_streaming()` on accumulated audio
- Types confirmed text immediately
- On stop, does a final pass to flush remaining text

**Files:**
- Modify: `src/dictate/service.py`

**Step 1: Add streaming state fields**

In `DictateService.__init__`, after the existing state fields:

```python
        # Streaming state
        self._stream_buffer: list[np.ndarray] = []
        self._stream_prev_text: str = ""
        self._stream_confirmed_len: int = 0  # chars already typed
        self._stream_timer = QTimer()
        self._stream_timer.setInterval(1000)
        self._stream_timer.timeout.connect(self._stream_tick)
        self._streaming_active = False
```

**Step 2: Add _stream_tick method**

This runs every ~1s during streaming recording:

```python
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
```

**Step 3: Add queue import**

At the top of service.py, add:
```python
import queue
```

**Step 4: Modify _start_recording for streaming**

In `_start_recording`, after `self._silence_timer.start()`, add streaming setup:

```python
        # Start streaming if enabled
        if self.cfg.streaming and self.cfg.output_mode == "type":
            self._streaming_active = True
            self._stream_buffer = []
            self._stream_prev_text = ""
            self._stream_confirmed_len = 0
            self._stream_timer.start()
            logger.info("Streaming transcription active")
```

**Step 5: Modify _stop_recording for streaming**

In `_stop_recording`, before the `threading.Thread(target=self._process_audio)` line, stop streaming:

```python
        # Stop streaming timer
        if self._streaming_active:
            self._streaming_active = False
            self._stream_timer.stop()
```

**Step 6: Modify _process_audio for streaming final pass**

In `_process_audio`, after the existing audio concatenation, add streaming final flush logic:

```python
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
                time.sleep(0.15)

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
```

**Step 7: Modify _cancel_recording to clean up streaming state**

In `_cancel_recording`, add streaming cleanup:

```python
    def _cancel_recording(self) -> None:
        if not self.is_recording:
            return
        logger.info("Recording cancelled (no speech detected).")
        self.is_recording = False
        self._streaming_active = False
        self._stream_timer.stop()
        self._silence_timer.stop()
        self.window.set_energy(0.0)
        self.capture.stop()
        self.capture.read()  # drain
        self._stream_buffer = []
        self._stream_confirmed_len = 0
        self._stream_prev_text = ""
        self.window.hide()
```

**Step 8: Update _on_config_changed**

Ensure streaming state is updated when config changes:

```python
    def _on_config_changed(self, cfg: Config) -> None:
        self.cfg = cfg
        self.transcriber.language = cfg.language
        self.transcriber.punctuation_hints = cfg.punctuation_hints
        self.capture = AudioCapture(device=cfg.device_index)
```

**Step 9: Commit**

```bash
git add src/dictate/service.py
git commit -m "feat: add streaming transcription with local agreement"
```

**Verify:**
1. Set `streaming: true` and `output_mode: type` in config
2. Run `dictate`, open a text editor, trigger recording
3. Speak a sentence — text should start appearing while you speak
4. After silence timeout, remaining text should be flushed
5. Set `streaming: false` — should work as before (batch mode)

---

### Task 12: Final integration test and commit

**Files:** None — manual verification only.

**Step 1: Test batch mode (default)**

- Config: `streaming: false`, `output_mode: type`, `punctuation_hints: true`
- Trigger recording, say "Hello, how are you?"
- Text should appear after silence, with punctuation

**Step 2: Test streaming mode**

- Config: `streaming: true`, `output_mode: type`, `punctuation_hints: true`
- Trigger recording, say a longer sentence
- Text should appear incrementally while speaking
- After silence, remaining text flushes

**Step 3: Test clipboard mode**

- Config: `output_mode: clipboard`
- Trigger recording, speak, stop
- Ctrl+V should paste the text

**Step 4: Test settings UI**

- Open settings, verify all new toggles appear
- Toggle auto-type off → streaming toggle should gray out
- Toggle punctuation hints on/off
- Click APPLY, reopen — values persist

**Step 5: Test robustness**

- Start two instances → second should exit with error
- Check IPC socket is in `$XDG_RUNTIME_DIR`
- Check log output has timestamps and levels

**Step 6: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: integration test fixups"
```
