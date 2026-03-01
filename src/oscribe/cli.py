from __future__ import annotations

import time

import numpy as np
from rich.console import Console

from oscribe.audio.capture import AudioCapture
from oscribe.audio.transcriber import Transcriber
from oscribe.config import Config

console = Console()


def main() -> None:
    cfg = Config.load()
    console.print("[bold green]Oscribe CLI (push-to-talk)[/]")
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
    transcriber = Transcriber(language=cfg.language)

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
            capture.last_sound_time = time.time()
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
