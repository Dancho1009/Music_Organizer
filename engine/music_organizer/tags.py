from __future__ import annotations

from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp3 import MP3


def _first(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else None
    return str(value)


def read_tags(path: str) -> dict[str, str | None]:
    audio = MutagenFile(path, easy=False)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path}")

    album = albumartist = artist = None
    if isinstance(audio, FLAC):
        album = _first(audio.get("album"))
        albumartist = _first(audio.get("albumartist") or audio.get("album artist"))
        artist = _first(audio.get("artist"))
    elif isinstance(audio, MP3) and audio.tags:
        album = str(audio.tags["TALB"]) if audio.tags.get("TALB") else None
        albumartist = str(audio.tags["TPE2"]) if audio.tags.get("TPE2") else None
        artist = str(audio.tags["TPE1"]) if audio.tags.get("TPE1") else None

    tags = getattr(audio, "tags", None)
    if tags is not None:
        album = album or _first(tags.get("album"))
        albumartist = albumartist or _first(tags.get("albumartist") or tags.get("album artist"))
        artist = artist or _first(tags.get("artist"))

    return {"album": album, "albumartist": albumartist, "artist": artist}

