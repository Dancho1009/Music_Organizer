from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .common import atomic_write_json, fingerprint, is_within, path_key, utc_now
from .journal import Journal
from .lyrics import classify_lrc
from .planner import load_plan, save_plan


class LyricsDeletionError(RuntimeError):
    pass


EventCallback = Callable[[dict[str, Any]], None]


def _emit(callback: EventCallback | None, event: str, **data: Any) -> None:
    if callback:
        callback({"event": event, **data})


def _journal_path(plan_id: str, data_root: str | Path) -> Path:
    return Path(data_root) / "journals" / f"{plan_id}.lyrics-delete.jsonl"


def _journal_state(entries: list[dict[str, Any]]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    committed: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}
    for entry in entries:
        source = entry.get("source")
        if not source:
            continue
        key = path_key(source)
        if entry.get("state") == "committed":
            committed.add(key)
            pending.pop(key, None)
        elif entry.get("state") == "intent" and key not in committed:
            pending[key] = entry
    return committed, pending


def _candidate(
    plan: Any,
    track: Any,
    committed: set[str],
    pending: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    deletion = track.lyrics.get("deletion")
    source = track.lyrics.get("source")
    if not isinstance(deletion, dict) or deletion.get("requested") is not True or not source:
        return None

    source = os.path.abspath(str(source))
    source_key = path_key(source)
    if source_key in committed:
        return {"track_id": track.track_id, "source": source, "state": "deleted", "ok": True}

    if not is_within(source, plan.config["source"]):
        return {
            "track_id": track.track_id,
            "source": source,
            "state": "blocked",
            "ok": False,
            "reason": "歌词文件不在当前源目录内。",
        }

    if not os.path.isfile(source):
        if source_key in pending:
            return {
                "track_id": track.track_id,
                "source": source,
                "state": "reconciled",
                "ok": True,
                "reason": "删除日志存在，但文件已不存在，按已完成处理。",
            }
        return {
            "track_id": track.track_id,
            "source": source,
            "state": "blocked",
            "ok": False,
            "reason": "歌词文件已不存在，无法确认删除对象。",
        }

    expected = deletion.get("fingerprint")
    current = fingerprint(source, include_hash=True)
    if not isinstance(expected, dict) or current != expected:
        return {
            "track_id": track.track_id,
            "source": source,
            "state": "blocked",
            "ok": False,
            "reason": "歌词文件内容或文件状态已变化，拒绝删除。",
            "expected": expected,
            "current": current,
        }

    current_status = str(classify_lrc(source)["status"])
    if current_status in {"actual", "suspect", "malformed"}:
        return {
            "track_id": track.track_id,
            "source": source,
            "state": "blocked",
            "ok": False,
            "reason": (
                "文件重新检测为实际歌词，拒绝删除。"
                if current_status == "actual"
                else "文件重新检测为可疑或格式异常，拒绝删除。"
            ),
            "lyrics_status": current_status,
        }

    return {
        "track_id": track.track_id,
        "source": source,
        "state": "pending",
        "ok": True,
        "lyrics_status": current_status,
        "fingerprint": current,
    }


def _preview(plan_path: str | Path, data_root: str | Path) -> tuple[Any, Journal, list[dict[str, Any]]]:
    plan = load_plan(plan_path)
    if plan.status != "verified":
        raise LyricsDeletionError(f"Lyrics deletion requires a verified plan, current status: {plan.status}")
    journal = Journal(plan.execution.get("lyrics_deletion_journal_path") or _journal_path(plan.plan_id, data_root))
    committed, pending = _journal_state(journal.entries())
    candidates = [
        item
        for track in plan.tracks
        if (item := _candidate(plan, track, committed, pending)) is not None
    ]
    return plan, journal, candidates


def delete_planned_lyrics(
    plan_path: str | Path,
    data_root: str | Path,
    apply: bool = False,
    report_path: str | Path | None = None,
    on_event: EventCallback | None = None,
) -> dict[str, Any]:
    plan_path = Path(plan_path)
    plan, journal, candidates = _preview(plan_path, data_root)
    pending_by_source: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if item["state"] in {"pending", "reconciled"}:
            pending_by_source.setdefault(path_key(item["source"]), item)
    pending = list(pending_by_source.values())
    blocked = [item for item in candidates if not item["ok"]]
    result: dict[str, Any] = {
        "plan_id": plan.plan_id,
        "created_at": utc_now(),
        "applied": apply,
        "ok": not blocked,
        "count": len(pending),
        "deleted": [],
        "blocked": blocked,
        "candidates": candidates,
        "journal_path": str(journal.path),
    }
    if report_path and (not apply or blocked):
        atomic_write_json(report_path, result)
        result["report_path"] = str(Path(report_path))
    if blocked or not apply:
        return result

    plan.execution["lyrics_deletion_journal_path"] = str(journal.path)
    for index, item in enumerate(pending, start=1):
        operation_id = f"lyrics_delete_{uuid4().hex}"
        journal.append(
            {
                "event": "deletion_intent",
                "state": "intent",
                "operation_id": operation_id,
                "plan_id": plan.plan_id,
                "track_id": item["track_id"],
                "source": item["source"],
                "fingerprint": item.get("fingerprint"),
            }
        )
        _emit(on_event, "lyrics_deletion_started", index=index, total=len(pending), source=item["source"])
        try:
            if item["state"] == "pending":
                os.unlink(item["source"])
            journal.append(
                {
                    "event": "deletion_committed",
                    "state": "committed",
                    "operation_id": operation_id,
                    "plan_id": plan.plan_id,
                    "track_id": item["track_id"],
                    "source": item["source"],
                    "fingerprint": item.get("fingerprint"),
                    "outcome": "deleted" if item["state"] == "pending" else "reconciled",
                }
            )
            for track in plan.tracks:
                if path_key(track.lyrics.get("source", "")) == path_key(item["source"]):
                    track.lyrics.setdefault("deletion", {})["state"] = "deleted"
            result["deleted"].append(item["source"])
            _emit(on_event, "lyrics_deletion_committed", index=index, total=len(pending), source=item["source"])
            save_plan(plan, plan_path)
        except Exception as exc:
            journal.append(
                {
                    "event": "deletion_failed",
                    "state": "failed",
                    "operation_id": operation_id,
                    "plan_id": plan.plan_id,
                    "track_id": item["track_id"],
                    "source": item["source"],
                    "error": str(exc),
                }
            )
            result["ok"] = False
            result.setdefault("errors", []).append({"source": item["source"], "error": str(exc)})
            _emit(on_event, "lyrics_deletion_failed", source=item["source"], error=str(exc))
            break

    plan.execution["lyrics_deletion"] = {
        "ok": result["ok"],
        "deleted": len(result["deleted"]),
        "completed_at": utc_now(),
        "report_path": str(Path(report_path)) if report_path else None,
    }
    save_plan(plan, plan_path)
    if report_path:
        result["report_path"] = str(Path(report_path))
        atomic_write_json(report_path, result)
    return result
