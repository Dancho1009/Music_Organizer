from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .common import utc_now
from .filesystem import link_file, move_file
from .journal import Journal
from .models import AssetPlan, MigrationPlan
from .planner import load_plan, save_plan, update_plan_status


class PlanExecutionError(RuntimeError):
    pass


EventCallback = Callable[[dict[str, Any]], None]


def _emit(callback: EventCallback | None, event: str, **data: Any) -> None:
    if callback:
        callback({"event": event, **data})


def _journal_path(plan: MigrationPlan, data_root: str | Path) -> Path:
    return Path(data_root) / "journals" / f"{plan.plan_id}.jsonl"


def _actionable_assets(plan: MigrationPlan) -> list[tuple[str, AssetPlan]]:
    result: list[tuple[str, AssetPlan]] = []
    for track in plan.tracks:
        for asset in track.assets:
            if asset.action in {"move", "link"} and asset.status == "planned":
                result.append((track.track_id, asset))
    return result


def apply_plan(
    plan_path: str | Path,
    data_root: str | Path,
    on_event: EventCallback | None = None,
) -> MigrationPlan:
    plan_path = Path(plan_path)
    plan = load_plan(plan_path)
    if plan.status != "ready":
        raise PlanExecutionError(f"Plan is not ready to apply: {plan.status}")

    actions = _actionable_assets(plan)
    already_completed = sum(
        1 for track in plan.tracks for asset in track.assets if asset.status == "completed"
    )
    journal = Journal(plan.execution.get("journal_path") or _journal_path(plan, data_root))
    total_assets = already_completed + len(actions)
    plan.execution = {
        "journal_path": str(journal.path),
        "started_at": utc_now(),
        "total_assets": total_assets,
        "completed_assets": already_completed,
    }
    update_plan_status(plan_path, plan, "applying")
    _emit(on_event, "apply_started", plan_id=plan.plan_id, total=total_assets)

    try:
        for index, (track_id, asset) in enumerate(actions, start=already_completed + 1):
            operation_id = f"op_{uuid4().hex}"
            _emit(
                on_event,
                "operation_started",
                operation_id=operation_id,
                index=index,
                total=total_assets,
                track_id=track_id,
                kind=asset.kind,
                source=asset.source,
                destination=asset.destination,
            )
            journal.append(
                {
                    "event": "operation_intent",
                    "state": "intent",
                    "at": utc_now(),
                    "operation_id": operation_id,
                    "plan_id": plan.plan_id,
                    "track_id": track_id,
                    "kind": asset.kind,
                    "action": asset.action,
                    "source": asset.source,
                    "destination": asset.destination,
                    "fingerprint": asset.fingerprint,
                }
            )
            if asset.action == "move":
                completed = move_file(
                    asset.source,
                    asset.destination,
                    asset.fingerprint,
                    f"{plan.plan_id}-{index}",
                )
            else:
                completed = link_file(asset.source, asset.destination, asset.fingerprint)

            entry = {
                "event": "operation_committed",
                "state": "committed",
                "at": utc_now(),
                "operation_id": operation_id,
                "plan_id": plan.plan_id,
                "track_id": track_id,
                "kind": asset.kind,
                "action": asset.action,
                "source": asset.source,
                "destination": asset.destination,
                "result": completed,
            }
            journal.append(entry)
            asset.execution = completed
            asset.status = "completed"
            plan.execution["completed_assets"] = index
            save_plan(plan, plan_path)
            _emit(
                on_event,
                "operation_committed",
                index=index,
                total=total_assets,
                **{key: value for key, value in entry.items() if key != "event"},
            )

        plan.execution["finished_at"] = utc_now()
        update_plan_status(plan_path, plan, "applied")
        _emit(on_event, "apply_finished", plan_id=plan.plan_id, total=total_assets)
        return plan
    except Exception as exc:
        plan.execution["failed_at"] = utc_now()
        plan.execution["error"] = str(exc)
        committed = int(plan.execution.get("completed_assets", 0))
        update_plan_status(plan_path, plan, "rollback_required" if committed else "failed")
        _emit(on_event, "operation_failed", plan_id=plan.plan_id, error=str(exc))
        if committed:
            try:
                from .rollback import rollback_plan

                rollback_plan(plan_path, data_root, on_event)
                raise PlanExecutionError(f"{exc}；已自动回滚已完成的文件操作。") from exc
            except PlanExecutionError:
                raise
            except Exception as rollback_exc:
                raise PlanExecutionError(f"{exc}；自动回滚失败：{rollback_exc}") from rollback_exc
        raise PlanExecutionError(str(exc)) from exc


def recoverable_plan(plan_path: str | Path) -> dict[str, Any]:
    plan = load_plan(plan_path)
    journal_location = plan.execution.get("journal_path")
    entries = Journal(journal_location).entries() if journal_location else []
    committed_entries = [entry for entry in entries if entry.get("state") == "committed"]
    committed_ids = {entry.get("operation_id") for entry in committed_entries}
    pending_entries = [
        entry
        for entry in entries
        if entry.get("state") == "intent" and entry.get("operation_id") not in committed_ids
    ]
    rollback_location = plan.execution.get("rollback_journal_path")
    if not rollback_location and journal_location:
        rollback_location = str(Path(journal_location).with_name(f"{plan.plan_id}.rollback.jsonl"))
    rollback_entries = Journal(rollback_location).entries() if rollback_location and os.path.isfile(rollback_location) else []
    rolled_back_ids = {
        entry.get("source_operation_id")
        for entry in rollback_entries
        if entry.get("state") == "committed"
    }
    consistency: list[dict[str, Any]] = []
    from .common import sha256_file

    for entry in committed_entries:
        if entry.get("operation_id") in rolled_back_ids:
            continue
        destination = entry["destination"]
        source = entry["source"]
        action = entry["action"]
        expected_hash = entry.get("result", {}).get("sha256")
        destination_ok = bool(
            expected_hash and os.path.isfile(destination) and sha256_file(destination) == expected_hash
        )
        source_ok = not os.path.exists(source) if action == "move" else os.path.isfile(source)
        consistency.append(
            {
                "operation_id": entry.get("operation_id"),
                "destination_ok": destination_ok,
                "source_ok": source_ok,
                "ok": destination_ok and source_ok,
            }
        )
    pending_consistency: list[dict[str, Any]] = []
    for entry in pending_entries:
        source = entry["source"]
        destination = entry["destination"]
        source_ok = os.path.isfile(source)
        destination_ok = not os.path.exists(destination)
        pending_consistency.append(
            {
                "operation_id": entry.get("operation_id"),
                "source_untouched": source_ok,
                "destination_absent": destination_ok,
                "ok": source_ok and destination_ok,
            }
        )
    incomplete = [
        {"track_id": track.track_id, "source": asset.source, "destination": asset.destination}
        for track in plan.tracks
        for asset in track.assets
        if asset.status == "planned" and asset.action in {"move", "link"}
    ]
    return {
        "plan_id": plan.plan_id,
        "status": plan.status,
        "journal_path": plan.execution.get("journal_path"),
        "completed_assets": len(committed_entries),
        "incomplete_assets": incomplete,
        "can_resume": plan.status in {"applying", "failed", "rollback_required"}
        and all(item["ok"] for item in consistency)
        and all(item["ok"] for item in pending_consistency),
        "consistency": consistency,
        "pending_consistency": pending_consistency,
        "can_rollback": bool(committed_entries)
        and all(item["ok"] for item in consistency),
    }


def resume_plan(
    plan_path: str | Path,
    data_root: str | Path,
    on_event: EventCallback | None = None,
) -> MigrationPlan:
    plan_path = Path(plan_path)
    recovery = recoverable_plan(plan_path)
    if not recovery["can_resume"]:
        raise PlanExecutionError("The interrupted plan no longer matches its journal and cannot be resumed.")
    plan = load_plan(plan_path)
    journal = Journal(plan.execution["journal_path"])
    committed = {
        (entry["source"], entry["destination"]): entry
        for entry in journal.entries()
        if entry.get("state") == "committed"
    }
    for track in plan.tracks:
        for asset in track.assets:
            entry = committed.get((asset.source, asset.destination))
            if entry:
                asset.status = "completed"
                asset.execution = entry.get("result")
    plan.status = "ready"
    save_plan(plan, plan_path)
    _emit(on_event, "resume_started", plan_id=plan.plan_id)
    return apply_plan(plan_path, data_root, on_event)
