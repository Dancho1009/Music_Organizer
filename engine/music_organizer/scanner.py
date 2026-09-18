from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .common import AUDIO_EXTENSIONS


@dataclass
class ScannedAudio:
    audio: str
    relative_audio: str
    lrc: str | None
    lrc_candidates: list[str]
    cover: str | None


def scan_source(source: str | Path) -> list[ScannedAudio]:
    root = Path(source)
    result: list[ScannedAudio] = []
    for directory, _, names in os.walk(root):
        folder = Path(directory)
        lrc_by_stem: dict[str, Path] = {}
        lrc_candidates: list[Path] = []
        cover: Path | None = None
        audio_names: list[str] = []
        for name in names:
            path = folder / name
            suffix = path.suffix.lower()
            if suffix == ".lrc":
                lrc_by_stem[path.stem.casefold()] = path
                lrc_candidates.append(path)
            elif suffix in AUDIO_EXTENSIONS:
                audio_names.append(name)
            elif name.casefold() == "cover.ico":
                cover = path

        for name in sorted(audio_names, key=str.casefold):
            audio = folder / name
            result.append(
                ScannedAudio(
                    audio=str(audio),
                    relative_audio=os.path.relpath(audio, root),
                    lrc=str(lrc_by_stem[audio.stem.casefold()])
                    if audio.stem.casefold() in lrc_by_stem
                    else None,
                    lrc_candidates=[str(item) for item in lrc_candidates],
                    cover=str(cover) if cover else None,
                )
            )
    return result

