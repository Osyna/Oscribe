# Model Selection with Download Progress

## Problem

The Whisper model is hardcoded to `large-v3-turbo`. Users should be able to
choose their model in settings, trading accuracy for speed/VRAM. Changing the
model requires downloading it, which needs a progress indicator.

## Design decisions

- **Model catalog**: 10 models (tiny through large-v3-turbo, plus distil
  variants) with size and speed hints shown in the dropdown.
- **Trigger**: Download starts on APPLY, not on dropdown change.
- **Progress**: Modal `QDialog` with determinate `QProgressBar` (0–100%).
- **Download**: Call `huggingface_hub.snapshot_download()` directly with a
  custom `tqdm` subclass that emits Qt signals. Pass the resulting local path
  to `WhisperModel` to skip re-downloading.
- **Language change**: Runtime-only parameter, no download needed.

## Model catalog

```python
WHISPER_MODELS = {
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

Excludes `.en` base variants (redundant with language parameter), `large-v1/v2`
(superseded), and aliases (`large`, `turbo`).

## Architecture

### Config

Add `model: str = "large-v3-turbo"` to `Config` dataclass.

### Settings UI

New **Model** section at the top (before Audio) with a `_StyledComboBox`.
Each entry shows: `large-v3-turbo (~1.6 GB, fast + accurate)`.

### Download flow (on APPLY when model changed)

```
Settings APPLY
  → config_saved signal
  → service._on_config_changed() detects model change
  → Opens ModelDownloadDialog (modal QDialog)
    ├── QProgressBar (0–100%)
    ├── Model name label
    └── Cancel button
  → QThread runs:
    1. huggingface_hub.snapshot_download(repo_id, tqdm_class=SignalTqdm)
    2. WhisperModel(local_path, device, compute_type)
  → On success: swap transcriber._model, close dialog
  → On cancel/error: keep old model, revert config.model
```

### SignalTqdm

Custom `tqdm` subclass that emits a Qt signal on each `update()` call:

```python
class SignalTqdm(tqdm):
    def __init__(self, *args, signal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._signal = signal

    def update(self, n=1):
        super().update(n)
        if self._signal and self.total:
            self._signal.emit(int(self.n / self.total * 100))
```

### Transcriber changes

- Constructor accepts `model_size` from config (already does).
- New `download_model(progress_callback) -> str`: downloads model, returns
  local path.
- `load_model(model_path=None)`: if `model_path` given, skips download.
- Model swap: set `_model = None`, call `load_model(new_path)`.

### Error handling

- **Network failure**: Dialog shows error, keeps old model.
- **User cancels**: Keeps old model, reverts `config.model`.
- **Already cached**: `snapshot_download` returns instantly (no download needed),
  dialog flashes briefly then closes.

## Out of scope

- Model deletion/cache management.
- Custom HuggingFace model IDs.
- Per-model quality benchmarks.
