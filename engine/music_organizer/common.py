from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = {".flac", ".mp3"}
WINDOWS_INVALID_CHARS = re.compile(r'[<>:"/\\\\|?*]')
EXPLICIT_ARTIST_SEPARATOR = re.compile(
    r"\s*(?:/|;|；|&|\bfeat\.?\b|\bft\.?\b)\s*", re.IGNORECASE
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def safe_component(value: str | None, fallback: str) -> str:
    cleaned = WINDOWS_INVALID_CHARS.sub("_", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(" .")
    return cleaned or fallback


def main_artist(value: str | None) -> str:
    if not value or not value.strip():
        return "未知艺术家"
    first = EXPLICIT_ARTIST_SEPARATOR.split(value.strip(), maxsplit=1)[0].strip()
    return safe_component(first, "未知艺术家")


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def fast_fingerprint(path: str | Path) -> dict[str, Any]:
    stat = os.stat(path)
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def fingerprint(path: str | Path, include_hash: bool = False) -> dict[str, Any]:
    result = fast_fingerprint(path)
    if include_hash:
        result["sha256"] = sha256_file(path)
    return result


def fingerprint_matches(path: str | Path, expected: dict[str, Any]) -> bool:
    try:
        current = fast_fingerprint(path)
    except OSError:
        return False
    return current["size"] == expected["size"] and current["mtime_ns"] == expected["mtime_ns"]


def same_file(left: str | Path, right: str | Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def existing_parent(path: str | Path) -> Path:
    candidate = Path(path)
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def same_filesystem(source: str | Path, destination: str | Path) -> bool:
    try:
        return os.stat(source).st_dev == os.stat(existing_parent(destination)).st_dev
    except OSError:
        return False


def is_within(path: str | Path, root: str | Path) -> bool:
    try:
        return os.path.commonpath([path_key(path), path_key(root)]) == path_key(root)
    except ValueError:
        return False


def read_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: str | Path, data: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

