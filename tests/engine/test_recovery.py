from __future__ import annotations

from pathlib import Path

from music_organizer.common import fast_fingerprint, utc_now
from music_organizer.executor import apply_plan, recoverable_plan, resume_plan
from music_organizer.filesystem import move_file, reverse_move
from music_organizer.journal import Journal
from music_organizer.models import AssetPlan, MigrationPlan, TrackPlan
from music_organizer.planner import load_plan, save_plan
from music_organizer.rollback import rollback_plan


def _two_asset_plan(tmp_path: Path) -> tuple[MigrationPlan, Path, Path, list[AssetPlan]]:
    sources = [tmp_path / "source" / "first.bin", tmp_path / "source" / "second.bin"]
    destinations = [tmp_path / "library" / "first.bin", tmp_path / "library" / "second.bin"]
    sources[0].parent.mkdir()
    sources[0].write_bytes(b"first asset")
    sources[1].write_bytes(b"second asset")
    assets = [
        AssetPlan("audio", str(source), str(destination), fast_fingerprint(source), "move")
        for source, destination in zip(sources, destinations, strict=True)
    ]
    track = TrackPlan(
        "trk_recovery",
        str(sources[0]),
        "first.bin",
        "flac",
        {},
        {},
        {"status": "ignored"},
        assets,
    )
    plan = MigrationPlan(config={}, tracks=[track], status="ready")
    plan_path = tmp_path / "plan.json"
    data_root = tmp_path / "state"
    save_plan(plan, plan_path)
    return plan, plan_path, data_root, assets


def test_resume_reconciles_committed_journal_before_continuing(tmp_path: Path) -> None:
    plan, plan_path, data_root, assets = _two_asset_plan(tmp_path)
    journal = Journal(data_root / "journals" / f"{plan.plan_id}.jsonl")
    operation_id = "op_interrupted"
    journal.append(
        {
            "event": "operation_intent",
            "state": "intent",
            "operation_id": operation_id,
            "plan_id": plan.plan_id,
            "track_id": plan.tracks[0].track_id,
            "kind": assets[0].kind,
            "action": assets[0].action,
            "source": assets[0].source,
            "destination": assets[0].destination,
        }
    )
    result = move_file(
        assets[0].source,
        assets[0].destination,
        assets[0].fingerprint,
        operation_id,
    )
    journal.append(
        {
            "event": "operation_committed",
            "state": "committed",
            "operation_id": operation_id,
            "plan_id": plan.plan_id,
            "track_id": plan.tracks[0].track_id,
            "kind": assets[0].kind,
            "action": assets[0].action,
            "source": assets[0].source,
            "destination": assets[0].destination,
            "result": result,
        }
    )
    plan.status = "applying"
    plan.execution = {
        "journal_path": str(journal.path),
        "started_at": utc_now(),
        "total_assets": 2,
        "completed_assets": 0,
    }
    save_plan(plan, plan_path)

    recovery = recoverable_plan(plan_path)
    assert recovery["can_resume"]
    assert recovery["completed_assets"] == 1

    resumed = resume_plan(plan_path, data_root)
    assert resumed.status == "applied"
    assert all(asset.status == "completed" for asset in resumed.tracks[0].assets)
    assert all(Path(asset.destination).is_file() for asset in resumed.tracks[0].assets)
    assert all(not Path(asset.source).exists() for asset in resumed.tracks[0].assets)


def test_rollback_retry_skips_operations_already_reversed(tmp_path: Path) -> None:
    plan, plan_path, data_root, _ = _two_asset_plan(tmp_path)
    applied = apply_plan(plan_path, data_root)
    apply_entries = [
        entry
        for entry in Journal(applied.execution["journal_path"]).entries()
        if entry.get("state") == "committed"
    ]
    last_entry = apply_entries[-1]
    reverse_move(last_entry["source"], last_entry["destination"], last_entry["result"]["sha256"])

    rollback_journal = Journal(data_root / "journals" / f"{plan.plan_id}.rollback.jsonl")
    rollback_journal.append(
        {
            "event": "rollback_committed",
            "state": "committed",
            "operation_id": f"rollback_{last_entry['operation_id']}",
            "source_operation_id": last_entry["operation_id"],
            "action": last_entry["action"],
            "source": last_entry["source"],
            "destination": last_entry["destination"],
        }
    )
    interrupted = load_plan(plan_path)
    interrupted.status = "rollback_failed"
    interrupted.execution["rollback_journal_path"] = str(rollback_journal.path)
    save_plan(interrupted, plan_path)

    result = rollback_plan(plan_path, data_root)
    reloaded = load_plan(plan_path)
    assert result["rolled_back_assets"] == 1
    assert reloaded.status == "rolled_back"
    assert all(Path(asset.source).is_file() for asset in reloaded.tracks[0].assets)
    assert all(not Path(asset.destination).exists() for asset in reloaded.tracks[0].assets)


def test_recovery_refuses_changed_pending_operation(tmp_path: Path) -> None:
    plan, plan_path, data_root, assets = _two_asset_plan(tmp_path)
    journal = Journal(data_root / "journals" / f"{plan.plan_id}.jsonl")
    journal.append(
        {
            "event": "operation_intent",
            "state": "intent",
            "operation_id": "op_pending",
            "plan_id": plan.plan_id,
            "track_id": plan.tracks[0].track_id,
            "kind": assets[0].kind,
            "action": assets[0].action,
            "source": assets[0].source,
            "destination": assets[0].destination,
        }
    )
    Path(assets[0].source).unlink()
    plan.status = "applying"
    plan.execution = {"journal_path": str(journal.path)}
    save_plan(plan, plan_path)

    recovery = recoverable_plan(plan_path)
    assert not recovery["can_resume"]
    assert recovery["pending_consistency"] == [
        {
            "operation_id": "op_pending",
            "source_untouched": False,
            "destination_absent": True,
            "ok": False,
        }
    ]
