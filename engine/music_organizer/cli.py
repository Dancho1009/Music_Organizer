from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .cleanup import cleanup_plan
from .executor import apply_plan, recoverable_plan, resume_plan
from .lyrics_deletion import delete_planned_lyrics
from .planner import build_plan, load_plan, save_plan
from .rollback import rollback_plan
from .verifier import verify_plan


def _write(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _decisions(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(value)
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("Decisions must be a JSON object.")
    return data


def _track_ids(value: str | None) -> set[str] | None:
    if not value:
        return None
    data = json.loads(value)
    if isinstance(data, list):
        return {str(item) for item in data}
    if isinstance(data, str):
        return {part.strip() for part in data.split(",") if part.strip()}
    raise ValueError("track-ids must be a JSON array or a comma separated string.")


def _data_root(value: str) -> Path:
    root = Path(value).resolve()
    (root / "plans").mkdir(parents=True, exist_ok=True)
    (root / "journals").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music-organizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--source", required=True)
    plan.add_argument("--flac-destination")
    plan.add_argument("--mp3-destination")
    plan.add_argument("--mode", choices=["move", "link"], default="move")
    plan.add_argument("--decisions")
    plan.add_argument("--data-root", required=True)
    plan.add_argument("--output")
    plan.add_argument("--parent-plan")
    plan.add_argument("--lyrics-cleanup-only", action="store_true")

    for name in ("apply", "rollback", "verify", "recover", "resume"):
        item = subparsers.add_parser(name)
        item.add_argument("--plan", required=True)
        item.add_argument("--data-root", required=True)
        if name == "apply":
            item.add_argument("--track-ids")

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--plan", required=True)
    cleanup.add_argument("--data-root", required=True)
    cleanup.add_argument("--apply", action="store_true")
    cleanup.add_argument("--include-root", action="store_true")
    delete_lyrics = subparsers.add_parser("delete-lyrics")
    delete_lyrics.add_argument("--plan", required=True)
    delete_lyrics.add_argument("--data-root", required=True)
    delete_lyrics.add_argument("--apply", action="store_true")
    history = subparsers.add_parser("history")
    history.add_argument("--data-root", required=True)
    return parser


def run(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            root = _data_root(args.data_root)
            parent = load_plan(args.parent_plan) if args.parent_plan else None
            plan = build_plan(
                args.source,
                args.flac_destination,
                args.mp3_destination,
                args.mode,
                _decisions(args.decisions),
                parent_plan_id=parent.plan_id if parent else None,
                plan_version=parent.plan_version + 1 if parent else 1,
                on_event=_write,
                lyrics_cleanup_only=args.lyrics_cleanup_only,
                data_root=str(root),
            )
            output = Path(args.output) if args.output else root / "plans" / f"{plan.plan_id}.json"
            save_plan(plan, output)
            _write({"event": "plan_created", "plan_path": str(output), "plan": plan.to_dict()})
            return 0
        if args.command == "apply":
            plan = apply_plan(
                args.plan,
                _data_root(args.data_root),
                _write,
                track_ids=_track_ids(args.track_ids),
            )
            _write({"event": "result", "plan": plan.to_dict()})
            return 0
        if args.command == "rollback":
            _write({"event": "result", "result": rollback_plan(args.plan, _data_root(args.data_root), _write)})
            return 0
        if args.command == "verify":
            root = _data_root(args.data_root)
            current = load_plan(args.plan)
            result = verify_plan(args.plan, root / "reports" / f"{current.plan_id}.verify.json", _write)
            _write({"event": "result", "result": result})
            return 0 if result["ok"] else 2
        if args.command == "recover":
            _write({"event": "result", "result": recoverable_plan(args.plan)})
            return 0
        if args.command == "resume":
            plan = resume_plan(args.plan, _data_root(args.data_root), _write)
            _write({"event": "result", "plan": plan.to_dict()})
            return 0
        if args.command == "cleanup":
            root = _data_root(args.data_root)
            current = load_plan(args.plan)
            result = cleanup_plan(
                args.plan,
                apply=args.apply,
                include_root=args.include_root,
                report_path=root / "reports" / f"{current.plan_id}.cleanup.json",
            )
            _write({"event": "result", "result": result})
            return 0
        if args.command == "delete-lyrics":
            root = _data_root(args.data_root)
            current = load_plan(args.plan)
            result = delete_planned_lyrics(
                args.plan,
                root,
                apply=args.apply,
                report_path=root / "reports" / f"{current.plan_id}.lyrics-delete.json",
                on_event=_write,
            )
            _write({"event": "result", "result": {**result, "plan": load_plan(args.plan).to_dict()}})
            return 0
        if args.command == "history":
            root = _data_root(args.data_root)
            plans = []
            for location in sorted((root / "plans").glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
                current = load_plan(location)
                item: dict[str, Any] = {
                    "plan_id": current.plan_id,
                    "plan_version": current.plan_version,
                    "parent_plan_id": current.parent_plan_id,
                    "status": current.status,
                    "created_at": current.created_at,
                    "plan_path": str(location),
                    "summary": current.summary,
                }
                if current.status in {"applying", "failed", "rollback_required", "rolling_back", "rollback_failed"}:
                    item["recovery"] = recoverable_plan(location)
                plans.append(item)
            _write({"event": "result", "result": {"plans": plans}})
            return 0
    except Exception as exc:
        _write({"event": "error", "error": str(exc), "command": args.command})
        return 1
    raise AssertionError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(run())
