from __future__ import annotations

from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp3 import MP3

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}

MAGIC_EXTENSIONS = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF8", ".gif"),
    (b"BM", ".bmp"),
)


def _extension_for(mime: object, data: bytes) -> str:
    normalized = str(mime or "").strip().lower()
    if normalized in MIME_EXTENSIONS:
        return MIME_EXTENSIONS[normalized]
    for magic, suffix in MAGIC_EXTENSIONS:
        if data.startswith(magic):
            return suffix
    return ".jpg"


def embedded_cover(audio_path: str | Path) -> tuple[bytes, str] | None:
    """Return (raw image bytes, file extension) for the audio's embedded cover."""
    try:
        audio = MutagenFile(str(audio_path), easy=False)
        if audio is None:
            return None
        if isinstance(audio, FLAC):
            pictures = getattr(audio, "pictures", None) or []
            if not pictures:
                return None
            picture = pictures[0]
            return picture.data, _extension_for(getattr(picture, "mime", None), picture.data)
        if isinstance(audio, MP3) and audio.tags is not None:
            for key in audio.tags.keys():
                if str(key).startswith("APIC"):
                    frame = audio.tags[key]
                    return frame.data, _extension_for(getattr(frame, "mime", None), frame.data)
        return None
    except Exception:
        # A damaged or unreadable file simply has no extractable cover.
        return None
