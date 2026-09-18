from __future__ import annotations

from pathlib import Path

from music_organizer.common import fingerprint
from music_organizer.lyrics_deletion import delete_planned_lyrics
from music_organizer.models import MigrationPlan, TrackPlan
from music_organizer.planner import load_plan, save_plan


def _plan_for_lrc(tmp_path: Path, content: str) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    lrc = source_root / "song.lrc"
    lrc.write_text(content, encoding="utf-8")
    track = TrackPlan(
        track_id="trk_lyrics_delete",
        source_audio=str(source_root / "song.mp3"),
        relative_source="song.mp3",
        audio_format="mp3",
        tags={},
        resolved={},
        lyrics={
            "status": "metadata_only",
            "source": str(lrc),
            "deletion": {
                "requested": True,
                "state": "pending",
                "fingerprint": fingerprint(lrc, include_hash=True),
            },
        },
        assets=[],
    )
    plan = MigrationPlan(config={"source": str(source_root)}, tracks=[track], status="verified")
    plan_path = tmp_path / "plan.json"
    data_root = tmp_path / "state"
    save_plan(plan, plan_path)
    return plan_path, data_root, lrc


def test_lyrics_deletion_requires_preview_then_removes_and_logs(tmp_path: Path) -> None:
    plan_path, data_root, lrc = _plan_for_lrc(tmp_path, "[00:01.00]作词：甲\n")

    preview = delete_planned_lyrics(plan_path, data_root)
    assert preview["ok"]
    assert preview["count"] == 1
    assert lrc.exists()

    result = delete_planned_lyrics(plan_path, data_root, apply=True)
    assert result["ok"]
    assert result["deleted"] == [str(lrc)]
    assert not lrc.exists()
    assert load_plan(plan_path).tracks[0].lyrics["deletion"]["state"] == "deleted"
    journal_text = Path(result["journal_path"]).read_text(encoding="utf-8")
    assert "deletion_intent" in journal_text
    assert "deletion_committed" in journal_text


def test_lyrics_deletion_refuses_changed_file(tmp_path: Path) -> None:
    plan_path, data_root, lrc = _plan_for_lrc(tmp_path, "[00:01.00]作词：甲\n")
    lrc.write_text("[00:01.00]第一句歌词\n[00:02.00]第二句歌词\n", encoding="utf-8")

    result = delete_planned_lyrics(plan_path, data_root, apply=True)

    assert not result["ok"]
    assert result["blocked"][0]["reason"] == "歌词文件内容或文件状态已变化，拒绝删除。"
    assert lrc.exists()


def test_lyrics_deletion_refuses_file_reclassified_as_actual(tmp_path: Path) -> None:
    plan_path, data_root, lrc = _plan_for_lrc(tmp_path, "[00:01.00]作词：甲\n")
    lrc.write_text("[00:01.00]第一句歌词\n[00:02.00]第二句歌词\n", encoding="utf-8")
    plan = load_plan(plan_path)
    plan.tracks[0].lyrics["deletion"]["fingerprint"] = fingerprint(lrc, include_hash=True)
    save_plan(plan, plan_path)

    result = delete_planned_lyrics(plan_path, data_root)

    assert not result["ok"]
    assert result["blocked"][0]["reason"] == "文件重新检测为实际歌词，拒绝删除。"
    assert lrc.exists()


def test_lyrics_deletion_refuses_file_reclassified_as_uncertain(tmp_path: Path) -> None:
    plan_path, data_root, lrc = _plan_for_lrc(tmp_path, "[00:01.00]作词：甲\n")
    lrc.write_text("[00:01.00]只有一句歌词\n", encoding="utf-8")
    plan = load_plan(plan_path)
    plan.tracks[0].lyrics["deletion"]["fingerprint"] = fingerprint(lrc, include_hash=True)
    save_plan(plan, plan_path)

    result = delete_planned_lyrics(plan_path, data_root)

    assert not result["ok"]
    assert result["blocked"][0]["reason"] == "文件重新检测为可疑或格式异常，拒绝删除。"
    assert lrc.exists()


def test_lyrics_deletion_deduplicates_shared_lrc_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    lrc = source / "shared.lrc"
    lrc.write_text("[00:01.00]作词：甲\n", encoding="utf-8")
    shared_fingerprint = fingerprint(lrc, include_hash=True)
    tracks = []
    for track_id in ("trk_flac", "trk_mp3"):
        tracks.append(
            TrackPlan(
                track_id=track_id,
                source_audio=str(source / f"{track_id}.audio"),
                relative_source=f"{track_id}.audio",
                audio_format="mp3",
                tags={},
                resolved={},
                lyrics={
                    "status": "metadata_only",
                    "source": str(lrc),
                    "deletion": {
                        "requested": True,
                        "state": "pending",
                        "fingerprint": shared_fingerprint,
                    },
                },
                assets=[],
            )
        )
    plan = MigrationPlan(config={"source": str(source)}, tracks=tracks, status="verified")
    plan_path = tmp_path / "plan.json"
    data_root = tmp_path / "state"
    save_plan(plan, plan_path)

    result = delete_planned_lyrics(plan_path, data_root, apply=True)

    assert result["ok"] is True
    assert result["deleted"] == [str(lrc)]
    assert not lrc.exists()
    assert all(track.lyrics["deletion"]["state"] == "deleted" for track in load_plan(plan_path).tracks)
