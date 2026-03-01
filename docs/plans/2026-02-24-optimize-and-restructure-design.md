# Dictate — Optimization & Restructure Design

**Date:** 2026-02-24
**Goal:** Make the live transcriber easily installable and very fast.

## Decision: Approach B — faster-whisper + Package Restructure

Replace HuggingFace transformers with `faster-whisper` (CTranslate2 backend) for 3-4x faster
transcription, and restructure into a proper installable Python package.

## Frontends Kept

- **GUI service** (`service.py`) — primary, system tray + ZMQ IPC + overlay window
- **CLI** (`cli.py`) — lightweight push-to-talk fallback
- **Removed:** Textual TUI (`tui/app.py`)

## Package Structure

```
TTS/
├── pyproject.toml
├── config.yaml
├── src/
│   └── dictate/
│       ├── __init__.py
│       ├── __main__.py        # python -m dictate → launches service
│       ├── cli.py             # dictate-cli entry point
│       ├── service.py         # dictate entry point (GUI)
│       ├── trigger.py         # dictate-trigger entry point
│       ├── config.py          # Shared config loader
│       ├── audio/
│       │   ├── __init__.py
│       │   ├── capture.py
│       │   └── transcriber.py
│       └── gui/
│           ├── __init__.py
│           ├── window.py
│           └── settings.py
```

## Dependencies

**Before (10):** accelerate, librosa, numpy, pyperclip, pyqt6, pyzmq, sounddevice, textual, torch, transformers

**After (6):** faster-whisper, numpy, pyperclip, pyqt6, pyzmq, sounddevice

- `torch`, `transformers`, `accelerate` → replaced by `faster-whisper`
- `librosa` → resampling handled internally by faster-whisper
- `textual` → TUI dropped

## Transcriber Rewrite

- `WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")`
- `model.transcribe(audio, language="en")` returns segments iterator
- No processor/generate/batch_decode dance
- Built-in Silero VAD available
- Int8 quantization option for CPU

## Audio Capture Changes

- Drop librosa resampling from `read()` — faster-whisper resamples internally
- Keep energy-based speech detection for UI visualization
- Simplify the generator to yield raw chunks

## Entry Points

```
dictate          → GUI service (system tray + overlay)
dictate-trigger  → ZMQ toggle trigger
dictate-cli      → CLI push-to-talk mode
```

## Installation

```bash
uv pip install .   # or: pip install .
dictate            # launches GUI service
```
