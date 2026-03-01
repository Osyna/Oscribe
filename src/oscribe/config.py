from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "oscribe" / "config.yaml"


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
                sound_enabled=bool(data.get("sound_enabled", True)),
                streaming=bool(data.get("streaming", False)),
                punctuation_hints=bool(data.get("punctuation_hints", True)),
                model=data.get("model", "large-v3-turbo"),
            )
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or _DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "device_index": self.device_index,
            "language": self.language,
            "output_mode": self.output_mode,
            "silence_timeout": self.silence_timeout,
            "window_position": self.window_position,
            "sound_enabled": self.sound_enabled,
            "streaming": self.streaming,
            "punctuation_hints": self.punctuation_hints,
            "model": self.model,
        }
        with open(path, "w") as f:
            yaml.dump(data, f)
