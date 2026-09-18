from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .common import utc_now
from .filesystem import remove_link, reverse_move
from .journal import Journal
from .planner import load_plan, save_plan, update_plan_status


class RollbackError(RuntimeError):
    pass


EventCallback = Callable[[dict[str, Any]], None]


def _emit(callback: EventCallback | None, event: str, **data: Any) -> None:
    if callback:
        callback({"event": event, **data})


def rollback_plan(
    plan_path: str | Path,
    data_root: str | Path,
    on_event: EventCallback | None = None,
) -> dict[str, Any]:
    plan_path = Path(plan_path)
    plan = load_plan(plan_path)
    journal_location = plan.execution.get("journal_path") or str(
        Path(data_root) / "journals" / f"{plan.plan_id}.jsonl"
    )
    entries = [entry for entry in Journal(journal_location).entries() if entry.get("state") == "committed"]
    if not entries:
        raise RollbackError("No completed operations are available for rollback.")

    rollback_journal = Journal(Path(data_root) / "journals" / f"{plan.plan_id}.rollback.jsonl")
    rolled_back_operation_ids = {
        entry.get("source_operation_id")
        for entry in rollback_journal.entries()
        if entry.get("state") == "committed"
    }
    pending_entries = [
        entry for entry in reversed(entries) if entry.get("operation_id") not in rolled_back_operation_ids
    ]
    plan.execution["rollback_started_at"] = utc_now()
    plan.execution["rollback_journal_path"] = str(rollback_journal.path)
    update_plan_status(plan_path, plan, "rolling_back")
    _emit(on_event, "rollback_started", plan_id=plan.plan_id, total=len(pending_entries))
    completed = 0
    try:
        for index, entry in enumerate(pending_entries, start=1):
            action = entry["action"]
            rollback_operation_id = f"rollback_{entry.get('operation_id', index)}"
            rollback_journal.append(
                {
                    "event": "rollback_intent",
                    "state": "intent",
                    "at": utc_now(),
                    "operation_id": rollback_operation_id,
                    "source_operation_id": entry.get("operation_id"),
                    "action": action,
                    "source": entry["source"],
                    "destination": entry["destination"],
                }
            )
            if action == "move":
                reverse_move(entry["source"], entry["destination"], entry["result"]["sha256"])
            elif action == "link":
                remove_link(entry["destination"], entry["source"])
            else:
                raise RollbackError(f"Unsupported journal action: {action}")
            rollback_journal.append(
                {
                    "event": "rollback_committed",
                    "state": "committed",
                    "at": utc_now(),
                    "operation_id": rollback_operation_id,
                    "source_operation_id": entry.get("operation_id"),
                    "action": action,
                    "source": entry["source"],
                    "destination": entry["destination"],
                }
            )
            completed = index
            _emit(
                on_event,
                "rollback_asset_completed",
                index=index,
                total=len(pending_entries),
                **{key: value for key, value in entry.items() if key != "event"},
            )

        for track in plan.tracks:
            for asset in track.assets:
                if asset.status == "completed":
                    asset.status = "rolled_back"
        plan.execution["rollback_finished_at"] = utc_now()
        plan.execution["rollback_completed_assets"] = completed
        update_plan_status(plan_path, plan, "rolled_back")
        _emit(on_event, "rollback_finished", plan_id=plan.plan_id, total=completed)
        return {"plan_id": plan.plan_id, "rolled_back_assets": completed, "status": plan.status}
    except Exception as exc:
        plan.execution["rollback_failed_at"] = utc_now()
        plan.execution["rollback_error"] = str(exc)
        plan.execution["rollback_completed_assets"] = completed
        update_plan_status(plan_path, plan, "rollback_failed")
        _emit(on_event, "rollback_failed", plan_id=plan.plan_id, error=str(exc))
        raise RollbackError(str(exc)) from exc
