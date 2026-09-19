from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .common import atomic_write_json, sha256_file, utc_now
from .planner import load_plan, save_plan


class VerificationError(RuntimeError):
    pass


def _asset_check(track_id: str, asset: Any) -> dict[str, Any]:
    if asset.action == "skip":
        destination_exists = os.path.isfile(asset.destination)
        source_exists = os.path.isfile(asset.source)
        return {
            "track_id": track_id,
            "kind": asset.kind,
            "source": asset.source,
            "destination": asset.destination,
            "action": asset.action,
            "destination_exists": destination_exists,
            "size_matches": destination_exists,
            "hash_matches": destination_exists,
            "source_state_matches": source_exists,
            "ok": destination_exists and source_exists,
        }

    destination_exists = os.path.isfile(asset.destination)
    expected_size = asset.fingerprint.get("size")
    actual_size = os.path.getsize(asset.destination) if destination_exists else None
    size_matches = bool(destination_exists and actual_size == expected_size)
    expected_hash = (asset.execution or {}).get("sha256")
    if asset.action == "reuse" and os.path.isfile(asset.source):
        expected_hash = sha256_file(asset.source)
    actual_hash = sha256_file(asset.destination) if destination_exists and size_matches else None
    hash_matches = bool(expected_hash and actual_hash == expected_hash)
    source_state_matches = (
        not os.path.exists(asset.source) if asset.action == "move" else os.path.isfile(asset.source)
    )
    return {
        "track_id": track_id,
        "kind": asset.kind,
        "source": asset.source,
        "destination": asset.destination,
        "action": asset.action,
        "destination_exists": destination_exists,
        "expected_size": expected_size,
        "actual_size": actual_size,
        "size_matches": size_matches,
        "hash_matches": hash_matches,
        "source_state_matches": source_state_matches,
        "ok": bool(destination_exists and size_matches and hash_matches and source_state_matches),
    }


def verify_plan(
    plan_path: str | Path,
    report_path: str | Path | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    plan_path = Path(plan_path)
    plan = load_plan(plan_path)
    cleanup_only = bool(plan.config.get("lyrics_cleanup_only"))
    allowed_statuses = {"applied", "partially_applied", "verified", "verify_failed"}
    if cleanup_only:
        allowed_statuses.add("ready")
    if plan.status not in allowed_statuses:
        raise VerificationError(f"Plan cannot be verified from status: {plan.status}")

    plan.status = "verifying"
    save_plan(plan, plan_path)
    checks: list[dict[str, Any]] = []
    track_checks: list[dict[str, Any]] = []
    pending_assets: list[dict[str, Any]] = []
    try:
        included_tracks = [track for track in plan.tracks if track.status != "excluded"]
        for current_index, track in enumerate(included_tracks, start=1):
            if track.status == "excluded":
                continue
            # Assets awaiting a later partial apply are reported as pending, not passed.
            pending = [
                {
                    "track_id": track.track_id,
                    "kind": asset.kind,
                    "source": asset.source,
                    "destination": asset.destination,
                }
                for asset in track.assets
                if asset.status == "planned" and asset.action in {"move", "link"}
            ]
            pending_assets.extend(pending)
            current = [
                _asset_check(track.track_id, asset)
                for asset in track.assets
                if asset.status != "planned"
            ]
            checks.extend(current)
            audio = next((asset for asset in track.assets if asset.kind == "audio"), None)
            lyrics = next((asset for asset in track.assets if asset.kind == "lrc"), None)
            pair_ok = True
            if lyrics:
                pair_ok = bool(
                    audio
                    and Path(audio.destination).parent == Path(lyrics.destination).parent
                    and Path(audio.destination).stem.casefold() == Path(lyrics.destination).stem.casefold()
                )
            track_checks.append(
                {
                    "track_id": track.track_id,
                    "relative_source": track.relative_source,
                    "lyrics_pair_matches": pair_ok,
                    "pending": len(pending),
                    "complete": not pending,
                    "ok": pair_ok and all(item["ok"] for item in current),
                }
            )
            if on_event:
                on_event(
                    {
                        "event": "verify_progress",
                        "current": current_index,
                        "total": len(included_tracks),
                        "track_id": track.track_id,
                    }
                )

        passed = sum(1 for item in checks if item["ok"])
        counts = Counter(item["kind"] for item in checks if item["ok"])
        totals = Counter(item["kind"] for item in checks)
        result: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "verified_at": utc_now(),
            "checks": checks,
            "track_checks": track_checks,
            "passed": passed,
            "pending": len(pending_assets),
            "pending_assets": pending_assets,
            "failed": len(checks) - passed + sum(1 for item in track_checks if not item["ok"]),
            "by_kind": {
                kind: {"passed": counts[kind], "total": totals[kind]}
                for kind in sorted(totals)
            },
        }
        result["ok"] = result["failed"] == 0
        result["complete"] = not pending_assets
        if report_path:
            atomic_write_json(report_path, result)
            result["report_path"] = str(Path(report_path))
        plan.execution["verification"] = {
            "ok": result["ok"],
            "passed": result["passed"],
            "failed": result["failed"],
            "verified_at": result["verified_at"],
            "report_path": result.get("report_path"),
        }
        if result["ok"] and result["complete"]:
            plan.status = "verified"
        elif result["ok"]:
            plan.status = "partially_applied"
        else:
            plan.status = "verify_failed"
        save_plan(plan, plan_path)
        result["plan_status"] = plan.status
        if on_event:
            on_event({"event": "verify_complete", "passed": result["ok"]})
        return result
    except Exception:
        plan.status = "verify_failed"
        save_plan(plan, plan_path)
        raise
