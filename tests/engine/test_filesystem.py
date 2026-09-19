from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from music_organizer.common import fast_fingerprint, sha256_file
from music_organizer.filesystem import FileOperationError, link_file, move_file


def test_cross_volume_move_keeps_content_and_removes_source() -> None:
    # Destination must live on a different volume than TEMP; derive it from the
    # repository location so the test survives the checkout being moved.
    repo_drive = Path(__file__).resolve().drive
    with tempfile.TemporaryDirectory(dir=os.environ["TEMP"]) as source_dir, tempfile.TemporaryDirectory(
        dir=f"{repo_drive}\\"
    ) as destination_dir:
        source = Path(source_dir) / "source.bin"
        destination = Path(destination_dir) / "nested" / "target.bin"
        source.write_bytes((b"cross-volume-content\n" * 200_000))
        original_hash = sha256_file(source)

        result = move_file(str(source), str(destination), fast_fingerprint(source), "pytest-cross")

        assert result["method"] == "copy_delete"
        assert not source.exists()
        assert destination.exists()
        assert sha256_file(destination) == original_hash


def test_network_mount_copy_branch_is_hash_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"network branch" * 4096)
    original_hash = sha256_file(source)
    monkeypatch.setattr("music_organizer.filesystem.same_filesystem", lambda *_: False)

    result = move_file(str(source), str(destination), fast_fingerprint(source), "pytest-network")

    assert result["method"] == "copy_delete"
    assert not source.exists()
    assert sha256_file(destination) == original_hash


def test_hard_link_rejects_cross_volume_or_network_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"content")
    monkeypatch.setattr("music_organizer.filesystem.same_filesystem", lambda *_: False)

    with pytest.raises(FileOperationError, match="Hard links"):
        link_file(str(source), str(tmp_path / "target.bin"), fast_fingerprint(source))
