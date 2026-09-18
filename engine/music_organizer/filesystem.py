from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from .common import fingerprint, fingerprint_matches, same_filesystem, sha256_file


class FileOperationError(RuntimeError):
    pass


def _ensure_source_matches(source: str, expected: dict[str, Any]) -> None:
    if not os.path.isfile(source):
        raise FileOperationError(f"Source file is missing: {source}")
    if not fingerprint_matches(source, expected):
        raise FileOperationError(f"Source file changed after planning: {source}")


def _ensure_free(destination: str) -> None:
    if os.path.exists(destination):
        raise FileOperationError(f"Destination is occupied: {destination}")


def _copy_with_hash(source: str, temporary: str) -> tuple[int, str]:
    digest = __import__("hashlib").sha256()
    total = 0
    with open(source, "rb") as read_handle, open(temporary, "xb") as write_handle:
        while block := read_handle.read(1024 * 1024):
            write_handle.write(block)
            digest.update(block)
            total += len(block)
        write_handle.flush()
        os.fsync(write_handle.fileno())
    return total, digest.hexdigest()


def move_file(source: str, destination: str, expected: dict[str, Any], operation_id: str) -> dict[str, Any]:
    _ensure_source_matches(source, expected)
    _ensure_free(destination)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)

    if same_filesystem(source, destination):
        try:
            os.rename(source, destination)
            try:
                result = fingerprint(destination, include_hash=True)
                return {"method": "rename", **result}
            except Exception:
                if os.path.exists(destination) and not os.path.exists(source):
                    os.rename(destination, source)
                raise
        except OSError:
            # A mounted share may report a compatible device id yet refuse rename.
            if not os.path.isfile(source) or os.path.exists(destination):
                raise

    temporary = os.path.join(
        os.path.dirname(destination), f".{Path(destination).name}.{operation_id}.{uuid.uuid4().hex}.partial"
    )
    placed = False
    copied_hash: str | None = None
    try:
        copied_size, copied_hash = _copy_with_hash(source, temporary)
        if copied_size != expected["size"] or sha256_file(temporary) != copied_hash:
            raise FileOperationError(f"Copied file verification failed: {destination}")
        _ensure_source_matches(source, expected)
        _ensure_free(destination)
        os.rename(temporary, destination)
        placed = True
        final = fingerprint(destination, include_hash=True)
        if final["sha256"] != copied_hash or final["size"] != copied_size:
            raise FileOperationError(f"Final destination verification failed: {destination}")
        os.unlink(source)
        return {"method": "copy_delete", **final}
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        if placed and os.path.isfile(source) and os.path.isfile(destination):
            try:
                if copied_hash and sha256_file(destination) == copied_hash:
                    os.unlink(destination)
            except OSError as cleanup_error:
                raise FileOperationError(
                    f"Transfer failed and the verified destination could not be removed: {destination}"
                ) from cleanup_error
        raise


def link_file(source: str, destination: str, expected: dict[str, Any]) -> dict[str, Any]:
    _ensure_source_matches(source, expected)
    _ensure_free(destination)
    if not same_filesystem(source, destination):
        raise FileOperationError("Hard links are not available across volumes or network mounts.")
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination)
    return {"method": "link", **fingerprint(destination, include_hash=True)}


def reverse_move(source: str, destination: str, expected_sha256: str) -> dict[str, Any]:
    if not os.path.isfile(destination):
        raise FileOperationError(f"Rollback destination is missing: {destination}")
    if sha256_file(destination) != expected_sha256:
        raise FileOperationError(f"Rollback destination changed: {destination}")
    if os.path.exists(source):
        raise FileOperationError(f"Rollback source is occupied: {source}")
    expected = fingerprint(destination)
    return move_file(destination, source, expected, f"rollback-{uuid.uuid4().hex}")


def remove_link(destination: str, source: str) -> None:
    if not os.path.exists(destination):
        return
    if not os.path.samefile(destination, source):
        raise FileOperationError(f"Rollback link target changed: {destination}")
    os.unlink(destination)
