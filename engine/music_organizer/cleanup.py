from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .common import AUDIO_EXTENSIONS, atomic_write_json, utc_now
from .planner import load_plan, save_plan


class CleanupError(RuntimeError):
    pass


def scan_remaining_files(source: str | Path) -> dict[str, Any]:
    root = Path(source).resolve()
    if not root.is_dir():
        raise ValueError(f"Source directory does not exist: {root}")
    files = {"audio": [], "lrc": [], "cover": [], "other": []}
    for directory, _, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            suffix = path.suffix.lower()
            if suffix in AUDIO_EXTENSIONS:
                files["audio"].append(str(path))
            elif suffix == ".lrc":
                files["lrc"].append(str(path))
            elif name.casefold() == "cover.ico":
                files["cover"].append(str(path))
            else:
                files["other"].append(str(path))
    return {"source": str(root), "files": files, "counts": {key: len(value) for key, value in files.items()}}


def preview_empty_directories(source: str | Path, include_root: bool = False) -> list[str]:
    root = Path(source).resolve()
    if not root.is_dir():
        raise ValueError(f"Source directory does not exist: {root}")
    removable: set[Path] = set()
    ordered: list[str] = []
    for directory, child_names, file_names in os.walk(root, topdown=False):
        path = Path(directory)
        child_paths = [path / name for name in child_names]
        if not file_names and all(child in removable for child in child_paths):
            removable.add(path)
            if path != root or include_root:
                ordered.append(str(path))
    return ordered


def remove_empty_directories(source: str | Path, include_root: bool = False) -> dict[str, Any]:
    root = Path(source).resolve()
    deleted: list[str] = []
    for directory, _, _ in os.walk(root, topdown=False):
        path = Path(directory)
        if path == root and not include_root:
            continue
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            deleted.append(str(path))
    return {"source": str(root), "deleted_directories": deleted, "count": len(deleted)}


def cleanup_plan(
    plan_path: str | Path,
    apply: bool = False,
    include_root: bool = False,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    plan_path = Path(plan_path)
    plan = load_plan(plan_path)
    if plan.status != "verified":
        raise CleanupError(f"Cleanup requires a verified plan, current status: {plan.status}")
    source = plan.config["source"]
    remaining = scan_remaining_files(source)
    candidates = preview_empty_directories(source, include_root=include_root)
    deleted: list[str] = []
    if apply:
        deleted = remove_empty_directories(source, include_root=include_root)["deleted_directories"]
    result = {
        "plan_id": plan.plan_id,
        "created_at": utc_now(),
        "applied": apply,
        "remaining": remaining,
        "empty_directories": candidates,
        "deleted_directories": deleted,
        "count": len(deleted if apply else candidates),
    }
    if report_path:
        atomic_write_json(report_path, result)
        result["report_path"] = str(Path(report_path))
    if apply:
        plan.execution["cleanup"] = {
            "cleaned_at": result["created_at"],
            "deleted_directories": len(deleted),
            "report_path": result.get("report_path"),
        }
        plan.status = "cleaned"
        save_plan(plan, plan_path)
    return result
