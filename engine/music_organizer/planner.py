from __future__ import annotations

import hashlib
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .common import (
    AUDIO_EXTENSIONS,
    atomic_write_json,
    fingerprint,
    fast_fingerprint,
    is_within,
    main_artist,
    path_key,
    read_json,
    safe_component,
    same_file,
    same_filesystem,
    utc_now,
)
from .lyrics import classify_lrc
from .models import AssetPlan, MigrationPlan, TrackPlan
from .scanner import ScannedAudio, scan_source
from .tags import read_tags


def _track_id(relative_audio: str) -> str:
    digest = hashlib.sha1(relative_audio.encode("utf-8")).hexdigest()[:16]
    return f"trk_{digest}"


def _issue(code: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **extra}


def _decision_for(decisions: dict[str, Any], track_id: str) -> dict[str, Any]:
    value = decisions.get(track_id, {})
    return value if isinstance(value, dict) else {}


def _lyrics_for_track(
    item: ScannedAudio,
    source_root: str,
    decision: dict[str, Any],
) -> tuple[str | None, dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    selected = item.lrc
    match_type = "exact" if selected else "missing"

    manual_path = decision.get("lyrics_path")
    if manual_path:
        candidate = os.path.abspath(str(manual_path))
        if not candidate.lower().endswith(".lrc") or not os.path.isfile(candidate):
            issues.append(_issue("invalid_manual_lrc", "blocked", "人工歌词文件不存在或不是 LRC。"))
            return None, {"status": "manual_review", "match_type": "manual"}, issues
        if not is_within(candidate, source_root):
            issues.append(_issue("manual_lrc_outside_source", "blocked", "人工歌词必须来自当前源目录。"))
            return None, {"status": "manual_review", "match_type": "manual"}, issues
        selected = candidate
        match_type = "manual"

    if decision.get("lyrics_action") == "ignore":
        return None, {"status": "ignored", "match_type": "ignored"}, issues

    if not selected:
        issues.append(
            _issue(
                "missing_lrc",
                "blocked",
                "未找到同目录、同 stem 的 LRC。",
                candidates=item.lrc_candidates,
            )
        )
        return None, {"status": "missing", "match_type": "missing"}, issues

    info = classify_lrc(selected)
    override = decision.get("lyrics_status")
    if override in {"actual", "metadata_only", "empty"}:
        info["status"] = override
        info["overridden"] = True
    info["match_type"] = match_type
    info["source"] = selected

    if decision.get("lyrics_action") == "delete":
        if info["status"] == "actual":
            issues.append(
                _issue(
                    "delete_actual_lyric_rejected",
                    "blocked",
                    "当前文件重新确认是实际歌词，不能标记为删除。",
                )
            )
            return None, info, issues
        if info["status"] in {"suspect", "malformed"}:
            issues.append(
                _issue(
                    "delete_uncertain_lyric_rejected",
                    "blocked",
                    "歌词内容或格式无法确认，不能自动标记为删除。",
                    lyrics_status=info["status"],
                    confidence=info.get("confidence"),
                )
            )
            return None, info, issues
        info["deletion"] = {
            "requested": True,
            "state": "pending",
            "fingerprint": fingerprint(selected, include_hash=True),
        }
        return None, info, issues

    if info["status"] != "actual":
        issues.append(
            _issue(
                "lyrics_requires_review",
                "manual_review",
                "歌词不是已确认的实际歌词，需要人工确认或忽略。",
                lyrics_status=info["status"],
                confidence=info.get("confidence"),
                reasons=info.get("reasons", []),
            )
        )
    return selected, info, issues


def _destination_for(
    audio_path: str,
    tags: dict[str, str | None],
    flac_dest: str | None,
    mp3_dest: str | None,
) -> tuple[str, dict[str, str], list[dict[str, Any]]]:
    suffix = Path(audio_path).suffix.lower()
    issues: list[dict[str, Any]] = []
    album = tags.get("album")
    if not album:
        issues.append(_issue("missing_album", "blocked", "缺少 album 标签。"))
    album_dir = safe_component(album, "未知专辑")

    artist_value = tags.get("albumartist") or tags.get("artist")
    if not artist_value:
        issues.append(_issue("missing_artist", "blocked", "音频缺少 albumartist 与 artist 标签。"))
    artist_dir = main_artist(artist_value)
    destination_root = flac_dest if suffix == ".flac" else mp3_dest
    destination_dir = os.path.join(destination_root or "", artist_dir, album_dir)
    resolved = {
        "main_artist": artist_dir,
        "album": album_dir,
        "main_artist_source": "albumartist" if tags.get("albumartist") else "artist",
    }
    return destination_dir, resolved, issues


def _check_existing_asset(asset: AssetPlan, is_cover: bool) -> dict[str, Any] | None:
    if not os.path.exists(asset.destination):
        return None
    if same_file(asset.source, asset.destination):
        asset.action = "reuse"
        asset.status = "reuse"
        return None
    if is_cover:
        asset.action = "skip"
        asset.status = "skipped"
        asset.note = "目标已有不同封面，保留目标封面。"
        return _issue("different_cover", "warning", "目标已有不同 cover.ico，未覆盖。")
    return _issue(
        "different_destination_file",
        "blocked",
        "目标路径已有不同文件，禁止覆盖。",
        destination=asset.destination,
    )


def _set_track_status(track: TrackPlan) -> None:
    if track.status == "excluded":
        return
    severities = {item["severity"] for item in track.issues}
    if "blocked" in severities:
        track.status = "blocked"
    elif "manual_review" in severities:
        track.status = "manual_review"
    elif "warning" in severities:
        track.status = "warning"
    elif any(asset.status == "reuse" for asset in track.assets):
        track.status = "reuse"
    else:
        track.status = "ready"


def _add_internal_collisions(tracks: list[TrackPlan]) -> None:
    destinations: dict[str, list[tuple[TrackPlan, AssetPlan]]] = defaultdict(list)
    for track in tracks:
        for asset in track.assets:
            if asset.action != "skip":
                destinations[path_key(asset.destination)].append((track, asset))

    for location, entries in destinations.items():
        sources = {path_key(asset.source) for _, asset in entries}
        kinds = {asset.kind for _, asset in entries}
        if len(entries) > 1 and (len(sources) > 1 or kinds != {"cover"}):
            for track, _ in entries:
                track.issues.append(
                    _issue(
                        "internal_destination_collision",
                        "blocked",
                        "本次计划有多个不同文件写入同一目标路径。",
                        destination=location,
                    )
                )


def _deduplicate_shared_covers(tracks: list[TrackPlan]) -> None:
    seen: set[tuple[str, str]] = set()
    for track in tracks:
        unique_assets: list[AssetPlan] = []
        for asset in track.assets:
            key = (path_key(asset.source), path_key(asset.destination))
            if asset.kind == "cover" and key in seen:
                continue
            unique_assets.append(asset)
            if asset.kind == "cover":
                seen.add(key)
        track.assets = unique_assets


def _add_source_collisions(tracks: list[TrackPlan], mode: str) -> None:
    if mode != "move":
        return
    sources: dict[str, list[tuple[TrackPlan, AssetPlan]]] = defaultdict(list)
    for track in tracks:
        for asset in track.assets:
            if asset.action == "move":
                sources[path_key(asset.source)].append((track, asset))
    for entries in sources.values():
        destinations = {path_key(asset.destination) for _, asset in entries}
        if len(destinations) > 1:
            for track, asset in entries:
                track.issues.append(
                    _issue(
                        "source_asset_multiple_destinations",
                        "blocked",
                        "同一源文件将被移动到多个目标，无法安全执行。",
                        source=asset.source,
                    )
                )


def _summarize(tracks: list[TrackPlan]) -> dict[str, int]:
    summary: Counter[str] = Counter(track.status for track in tracks)
    summary["tracks"] = len(tracks)
    summary["assets"] = sum(len(track.assets) for track in tracks)
    return dict(summary)


def build_plan(
    source: str,
    flac_dest: str | None,
    mp3_dest: str | None,
    mode: str = "move",
    decisions: dict[str, Any] | None = None,
    parent_plan_id: str | None = None,
    plan_version: int = 1,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    lyrics_cleanup_only: bool = False,
) -> MigrationPlan:
    if mode not in {"move", "link"}:
        raise ValueError("mode must be 'move' or 'link'")
    source = os.path.abspath(source)
    flac_dest = os.path.abspath(flac_dest) if flac_dest else None
    mp3_dest = os.path.abspath(mp3_dest) if mp3_dest else None
    if not os.path.isdir(source):
        raise ValueError(f"Source directory does not exist: {source}")
    if not lyrics_cleanup_only and not flac_dest and not mp3_dest:
        raise ValueError("Select at least one destination directory.")
    if not lyrics_cleanup_only and flac_dest and not os.path.isdir(flac_dest):
        raise ValueError(f"FLAC destination directory does not exist: {flac_dest}")
    if not lyrics_cleanup_only and mp3_dest and not os.path.isdir(mp3_dest):
        raise ValueError(f"MP3 destination directory does not exist: {mp3_dest}")
    if lyrics_cleanup_only:
        flac_dest = None
        mp3_dest = None
    decisions = decisions or {}
    tracks: list[TrackPlan] = []
    scanned = scan_source(source)
    if on_event:
        on_event({"event": "scan_started", "total": len(scanned)})

    for current_index, item in enumerate(scanned, start=1):
        if on_event:
            on_event(
                {
                    "event": "scan_progress",
                    "current": current_index,
                    "total": len(scanned),
                    "file": item.audio,
                }
        )
        audio_path = item.audio
        suffix = Path(audio_path).suffix.lower()
        decision = _decision_for(decisions, _track_id(item.relative_audio))
        if lyrics_cleanup_only and not item.lrc and not decision.get("lyrics_path"):
            continue
        if not lyrics_cleanup_only and ((suffix == ".flac" and not flac_dest) or (suffix == ".mp3" and not mp3_dest)):
            continue
        track_id = _track_id(item.relative_audio)
        issues: list[dict[str, Any]] = []
        if lyrics_cleanup_only:
            tags = {}
            destination_dir = ""
            resolved = {"main_artist": "", "album": "", "main_artist_source": ""}
        else:
            try:
                tags = read_tags(audio_path)
            except Exception as exc:
                tags = {"album": None, "albumartist": None, "artist": None}
                issues.append(_issue("tag_read_failed", "blocked", f"无法读取音频标签：{exc}"))

            destination_dir, resolved, destination_issues = _destination_for(
                audio_path, tags, flac_dest, mp3_dest
            )
            issues.extend(destination_issues)
        if decision.get("exclude") is True:
            tracks.append(
                TrackPlan(
                    track_id=track_id,
                    source_audio=audio_path,
                    relative_source=item.relative_audio,
                    audio_format=Path(audio_path).suffix.lower().removeprefix("."),
                    tags=tags,
                    resolved=resolved,
                    lyrics={"status": "ignored", "match_type": "excluded"},
                    assets=[],
                    issues=[],
                    status="excluded",
                )
            )
            continue
        lrc_path, lyrics, lyric_issues = _lyrics_for_track(item, source, decision)
        issues.extend(lyric_issues)

        assets: list[AssetPlan] = []
        if not lyrics_cleanup_only:
            audio_destination = os.path.join(destination_dir, os.path.basename(audio_path))
            assets.append(
                AssetPlan(
                    kind="audio",
                    source=audio_path,
                    destination=audio_destination,
                    fingerprint=fast_fingerprint(audio_path),
                    action=mode,
                )
            )
            if lrc_path and lyrics["status"] == "actual":
                assets.append(
                    AssetPlan(
                        kind="lrc",
                        source=lrc_path,
                        destination=os.path.join(destination_dir, f"{Path(audio_path).stem}.lrc"),
                        fingerprint=fast_fingerprint(lrc_path),
                        action=mode,
                    )
                )
            if item.cover:
                assets.append(
                    AssetPlan(
                        kind="cover",
                        source=item.cover,
                        destination=os.path.join(destination_dir, "cover.ico"),
                        fingerprint=fast_fingerprint(item.cover),
                        action=mode,
                    )
                )

        for asset in assets:
            existing_issue = _check_existing_asset(asset, asset.kind == "cover")
            if existing_issue:
                issues.append(existing_issue)
            if mode == "link" and asset.action == "link" and not same_filesystem(asset.source, asset.destination):
                issues.append(
                    _issue(
                        "hardlink_cross_filesystem",
                        "blocked",
                        "硬链接只能用于同一文件系统；跨卷或网络目标请使用移动模式。",
                    )
                )

        track = TrackPlan(
            track_id=track_id,
            source_audio=audio_path,
            relative_source=item.relative_audio,
            audio_format=Path(audio_path).suffix.lower().removeprefix("."),
            tags=tags,
            resolved=resolved,
            lyrics=lyrics,
            assets=assets,
            issues=issues,
        )
        _set_track_status(track)
        tracks.append(track)
        if on_event:
            for issue in track.issues:
                on_event(
                    {
                        "event": "issue_found",
                        "track_id": track.track_id,
                        "issue_type": issue["code"],
                        "severity": issue["severity"],
                    }
                )

    _deduplicate_shared_covers(tracks)
    _add_internal_collisions(tracks)
    _add_source_collisions(tracks, mode)
    for track in tracks:
        _set_track_status(track)

    plan = MigrationPlan(
        config={
            "source": source,
            "flac_destination": flac_dest,
            "mp3_destination": mp3_dest,
            "mode": mode,
            "created_with": "music-organizer-engine",
            "lyrics_cleanup_only": lyrics_cleanup_only,
        },
        tracks=tracks,
        decisions=decisions,
        parent_plan_id=parent_plan_id,
        plan_version=plan_version,
        status="ready" if all(track.status in {"ready", "warning", "reuse", "excluded"} for track in tracks) else "blocked",
    )
    plan.summary = _summarize(tracks)
    if on_event:
        on_event({"event": "plan_ready", "plan_id": plan.plan_id, "status": plan.status})
    return plan


def save_plan(plan: MigrationPlan, path: str | Path) -> None:
    atomic_write_json(path, plan.to_dict())


def load_plan(path: str | Path) -> MigrationPlan:
    return MigrationPlan.from_dict(read_json(path))


def update_plan_status(plan_path: str | Path, plan: MigrationPlan, status: str) -> None:
    plan.status = status
    if status == "applying" and not plan.frozen_at:
        plan.frozen_at = utc_now()
    save_plan(plan, plan_path)
