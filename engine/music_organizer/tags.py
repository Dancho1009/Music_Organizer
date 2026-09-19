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


def _all(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return " / ".join(parts) if parts else None
    return str(value)


def read_tags(path: str) -> dict[str, str | float | None]:
    audio = MutagenFile(path, easy=False)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path}")

    title = album = albumartist = artist = None
    if isinstance(audio, FLAC):
        title = _first(audio.get("title"))
        album = _first(audio.get("album"))
        albumartist = _all(audio.get("albumartist") or audio.get("album artist"))
        artist = _all(audio.get("artist"))
    elif isinstance(audio, MP3) and audio.tags:
        title = str(audio.tags["TIT2"]) if audio.tags.get("TIT2") else None
        album = str(audio.tags["TALB"]) if audio.tags.get("TALB") else None
        albumartist = str(audio.tags["TPE2"]) if audio.tags.get("TPE2") else None
        artist = str(audio.tags["TPE1"]) if audio.tags.get("TPE1") else None

    tags = getattr(audio, "tags", None)
    if tags is not None:
        title = title or _first(tags.get("title"))
        album = album or _first(tags.get("album"))
        albumartist = albumartist or _all(tags.get("albumartist") or tags.get("album artist"))
        artist = artist or _all(tags.get("artist"))

    duration = getattr(getattr(audio, "info", None), "length", None)
    return {"title": title, "album": album, "albumartist": albumartist, "artist": artist, "duration_seconds": duration}
