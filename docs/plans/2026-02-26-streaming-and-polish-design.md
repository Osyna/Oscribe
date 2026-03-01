# Streaming Transcription, Punctuation Hints & Robustness Polish

**Date:** 2026-02-26
**Status:** Approved

## Context

Dictate is a fast speech-to-text app for Linux (Wayland/X11). Primary use case: quick notes and messages into text fields. Runs on NVIDIA GPU with faster-whisper.

Current pain points: latency after speaking (full batch transcription), no punctuation control, and several robustness gaps.

## Scope

Three improvement areas:

1. **Streaming transcription** (opt-in, disabled by default)
2. **Whisper punctuation hints** (opt-in, enabled by default)
3. **Robustness & polish** (6 targeted fixes)

## 1. Streaming Transcription

### Config

New fields:
- `streaming: false` — live typing as you speak (off by default)
- Toggle in settings: "Live typing" — grayed out when auto-type is off

### Algorithm: Local Agreement

Instead of batch transcription after recording stops, transcribe incrementally every ~1s:

1. Audio accumulates in a buffer (existing AudioCapture queue)
2. Every ~1s, accumulated audio so far is sent to `model.transcribe()`
3. Compare new transcription with previous run
4. Emit only text that consecutive runs agree on (the "confirmed" prefix)
5. On recording stop, final transcription pass flushes remaining text

Example:
```
t=1.0s: transcribe("Hey can")         → first run, nothing confirmed
t=2.0s: transcribe("Hey can you send") → confirmed "Hey can " → type it
t=3.0s: transcribe("Hey can you send me the") → confirmed "you send " → type it
stop:   final pass → "me the report" → type it
```

### Architecture

Add to `Transcriber`:
```python
def transcribe_streaming(self, audio, prev_text) -> tuple[str, str]:
    """Returns (confirmed_new_text, full_text_so_far)."""
```

Service orchestration:
- Background thread accumulates audio chunks, calls `transcribe_streaming()` on ~1s timer
- Confirmed text delivered immediately via `desktop.type_into_window()`
- Overlay stays in "recording" state (no "analysing" spinner) during streaming
- `silence_timeout` still applies to auto-stop
- On stop: final batch transcription of full audio, emit remaining unconfirmed text

### Constraints
- Streaming only works with `output_mode == "type"` (nothing to stream into clipboard)
- Settings UI grays out streaming toggle when auto-type is off
- GPU usage is higher (repeated inference on growing audio window)

## 2. Whisper Punctuation Hints

### Config

New field:
- `punctuation_hints: true` — enable initial_prompt hints (on by default)
- Toggle in settings: "Punctuation hints"

### Implementation

Set `initial_prompt` parameter on all `model.transcribe()` calls with a well-punctuated sentence per language. This nudges Whisper to output natural punctuation.

Example prompts:
- **en:** `"Hello, how are you? I'm doing well. Let me explain the situation."`
- **fr:** `"Bonjour, comment allez-vous ? Je vais bien. Laissez-moi vous expliquer."`
- **de:** `"Hallo, wie geht es Ihnen? Mir geht es gut. Lassen Sie mich erklären."`
- (one per supported language)

Applied in both batch and streaming modes. When disabled, no `initial_prompt` is passed (current behavior).

## 3. Robustness & Polish

### 3.1 IPC Guard
- On `sock.bind()` failure in `_IPCWorker.run()`, log error and `sys.exit(1)`
- Prevents silent zombie second instance

### 3.2 Clipboard Restore in try/finally
- In `DesktopHelper.type_into_window()`, wrap clipboard-write/paste/restore in `try/finally`
- Guarantees clipboard restoration even on exception

### 3.3 XDG-Compliant Socket Path
- `ipc://{XDG_RUNTIME_DIR}/dictate.ipc` instead of `ipc:///tmp/dictate_service.ipc`
- Falls back to `/tmp/` if env var not set
- More secure (runtime dir is per-user, mode 0700)

### 3.4 Startup Validation
- If no paste tool available and `output_mode == "type"`, log a warning at startup
- Don't crash — clipboard mode still works

### 3.5 Logging
- Replace all `print()` with `logging` module
- Logger: `logging.getLogger("dictate")`
- Levels: DEBUG (detection/timing), INFO (state changes), WARNING (fallbacks), ERROR (failures)
- Default level: INFO

### 3.6 Settings Save Feedback
- Show `QMessageBox.critical()` on config save failure instead of silent print

## Files Touched

| File | Changes |
|------|---------|
| `config.py` | Add `streaming`, `punctuation_hints` fields |
| `service.py` | Streaming orchestration, logging, IPC guard, XDG socket |
| `audio/transcriber.py` | `transcribe_streaming()`, initial_prompt per language |
| `gui/settings.py` | "Live typing" and "Punctuation hints" toggles |
| `desktop.py` | try/finally clipboard, logging |
| `trigger.py` | XDG socket path |

## Not In Scope

- Text post-processing module (spoken punctuation rules, voice commands)
- Continuous dictation mode (no auto-stop)
- Multi-language switching without settings
