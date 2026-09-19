from __future__ import annotations

from pathlib import Path
import pytest


from music_organizer.common import fast_fingerprint
from music_organizer.cleanup import CleanupError, cleanup_plan
from music_organizer.executor import PlanExecutionError, apply_plan
from music_organizer.models import AssetPlan, MigrationPlan, TrackPlan
from music_organizer.planner import build_plan, load_plan, save_plan
from music_organizer.rollback import rollback_plan
from music_organizer.scanner import ScannedAudio
from music_organizer.verifier import verify_plan


def test_planner_routes_flac_and_only_exact_actual_lrc(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    audio = source_root / "track.flac"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[00:01.00]first lyric\n[00:02.00]second lyric\n", encoding="utf-8")
    (tmp_path / "flac").mkdir()
    (tmp_path / "mp3").mkdir()
    scanned = ScannedAudio(
        audio=str(audio),
        relative_audio="track.flac",
        lrc=str(lrc),
        lrc_candidates=[],
    )
    monkeypatch.setattr("music_organizer.planner.scan_source", lambda _: [scanned])
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album: One", "albumartist": "Album Artist", "artist": "Artist A / Artist B"},
    )

    plan = build_plan(str(source_root), str(tmp_path / "flac"), str(tmp_path / "mp3"))

    assert plan.status == "ready"
    track = plan.tracks[0]
    assert track.resolved["main_artist"] == "Artist A _ Artist B"
    assert track.resolved["main_artist_source"] == "artist"
    assert Path(track.assets[0].destination).parent == tmp_path / "flac" / "Artist A _ Artist B" / "Album_ One"
    assert [asset.kind for asset in track.assets] == ["audio", "lrc"]


def test_planner_blocks_hard_links_across_filesystems(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    flac_root = tmp_path / "flac"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    flac_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[00:01.00]first lyric\n[00:02.00]second lyric\n", encoding="utf-8")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [ScannedAudio(str(audio), "track.mp3", str(lrc), [])],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": None, "artist": "Artist"},
    )
    monkeypatch.setattr("music_organizer.planner.same_filesystem", lambda *_: False)

    plan = build_plan(str(source_root), str(flac_root), str(mp3_root), mode="link")

    assert plan.status == "blocked"
    assert any(issue["code"] == "hardlink_cross_filesystem" for issue in plan.tracks[0].issues)


def test_planner_routes_mp3_by_main_artist_and_album(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[00:01.00]first lyric\n[00:02.00]second lyric\n", encoding="utf-8")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [ScannedAudio(str(audio), "track.mp3", str(lrc), [])],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Album Artist", "artist": "Artist A feat. Artist B"},
    )

    plan = build_plan(str(source_root), None, str(mp3_root))

    assert plan.status == "ready"
    assert Path(plan.tracks[0].assets[0].destination).parent == mp3_root / "Artist A feat. Artist B" / "Album"


def test_planner_falls_back_to_albumartist_when_artist_missing(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [ScannedAudio(str(audio), "track.mp3", None, [])],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Album Artist", "artist": None},
    )

    plan = build_plan(str(source_root), None, str(mp3_root))

    assert plan.tracks[0].resolved["main_artist"] == "Album Artist"
    assert plan.tracks[0].resolved["main_artist_source"] == "albumartist"


def test_lyrics_quality_issues_do_not_block_migration_plan(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[ti:Other Song]\n[ar:Wrong Artist]\n[00:01.00]only one line\n", encoding="utf-8")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [ScannedAudio(str(audio), "track.mp3", str(lrc), [])],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist", "title": "Song", "duration_seconds": 180.0},
    )

    plan = build_plan(str(source_root), None, str(mp3_root))

    assert plan.status == "ready"
    assert all(issue.get("affects_plan") is False for issue in plan.tracks[0].issues)
    assert [asset.kind for asset in plan.tracks[0].assets] == ["audio"]

def test_missing_lyrics_does_not_block_migration_plan(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [ScannedAudio(str(audio), "track.mp3", None, [])],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist"},
    )

    plan = build_plan(str(source_root), None, str(mp3_root))

    assert plan.status == "ready"
    assert any(issue["code"] == "missing_lrc" and issue.get("affects_plan") is False for issue in plan.tracks[0].issues)
    assert [asset.kind for asset in plan.tracks[0].assets] == ["audio"]


def test_destination_conflict_still_blocks_migration_plan(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    (mp3_root / "Artist" / "Album").mkdir(parents=True)
    audio = source_root / "track.mp3"
    audio.write_bytes(b"audio")
    (mp3_root / "Artist" / "Album" / "track.mp3").write_bytes(b"different")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [ScannedAudio(str(audio), "track.mp3", None, [])],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist"},
    )

    plan = build_plan(str(source_root), None, str(mp3_root))

    assert plan.status == "blocked"
    assert any(issue["code"] == "different_destination_file" for issue in plan.tracks[0].issues)


def test_planner_marks_abnormal_lyrics_for_deletion_without_migrating_lrc(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[00:01.00]作词：甲\n[00:02.00]作曲：乙\n", encoding="utf-8")
    scanned = ScannedAudio(str(audio), "track.mp3", str(lrc), [])
    monkeypatch.setattr("music_organizer.planner.scan_source", lambda _: [scanned])
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist"},
    )

    initial = build_plan(str(source_root), None, str(mp3_root))
    track_id = initial.tracks[0].track_id
    plan = build_plan(
        str(source_root),
        None,
        str(mp3_root),
        decisions={track_id: {"lyrics_action": "delete"}},
    )

    assert plan.status == "ready"
    assert [asset.kind for asset in plan.tracks[0].assets] == ["audio"]
    assert plan.tracks[0].lyrics["deletion"]["requested"] is True


def test_planner_rejects_deletion_of_uncertain_lyrics(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    mp3_root.mkdir()
    audio = source_root / "track.mp3"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[00:01.00]只有一句歌词\n", encoding="utf-8")
    scanned = ScannedAudio(str(audio), "track.mp3", str(lrc), [])
    monkeypatch.setattr("music_organizer.planner.scan_source", lambda _: [scanned])
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist"},
    )

    initial = build_plan(str(source_root), None, str(mp3_root))
    track_id = initial.tracks[0].track_id
    plan = build_plan(
        str(source_root),
        None,
        str(mp3_root),
        decisions={track_id: {"lyrics_action": "delete"}},
    )

    assert plan.status == "blocked"
    assert plan.tracks[0].lyrics.get("deletion") is None
    assert any(issue["code"] == "delete_uncertain_lyric_rejected" for issue in plan.tracks[0].issues)


def test_lyrics_cleanup_plan_requires_only_source_and_can_verify_without_migration(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    audio = source_root / "track.mp3"
    lrc = source_root / "track.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("[00:01.00]作词：甲\n[00:02.00]作曲：乙\n", encoding="utf-8")
    scanned = ScannedAudio(str(audio), "track.mp3", str(lrc), [])
    monkeypatch.setattr("music_organizer.planner.scan_source", lambda _: [scanned])

    initial = build_plan(str(source_root), None, None, lyrics_cleanup_only=True)
    track_id = initial.tracks[0].track_id
    plan = build_plan(
        str(source_root),
        None,
        None,
        decisions={track_id: {"lyrics_action": "delete"}},
        lyrics_cleanup_only=True,
    )
    plan_path = tmp_path / "lyrics-cleanup-plan.json"
    save_plan(plan, plan_path)

    verification = verify_plan(plan_path)

    assert plan.status == "ready"
    assert plan.config["lyrics_cleanup_only"] is True
    assert plan.config["flac_destination"] is None
    assert plan.config["mp3_destination"] is None
    assert plan.tracks[0].assets == []
    assert verification["ok"] is True
    assert load_plan(plan_path).status == "verified"


def test_planner_allows_one_destination_and_skips_unselected_format(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    flac_root = tmp_path / "flac"
    source_root.mkdir()
    flac_root.mkdir()
    flac = source_root / "selected.flac"
    mp3 = source_root / "unselected.mp3"
    flac_lrc = source_root / "selected.lrc"
    flac.write_bytes(b"flac")
    mp3.write_bytes(b"mp3")
    flac_lrc.write_text("[00:01.00]first lyric\n[00:02.00]second lyric\n", encoding="utf-8")
    monkeypatch.setattr(
        "music_organizer.planner.scan_source",
        lambda _: [
            ScannedAudio(str(flac), "selected.flac", str(flac_lrc), []),
            ScannedAudio(str(mp3), "unselected.mp3", None, []),
        ],
    )
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist"},
    )

    plan = build_plan(str(source_root), str(flac_root), None)

    assert plan.status == "ready"
    assert [track.relative_source for track in plan.tracks] == ["selected.flac"]
    assert plan.tracks[0].assets[0].destination.startswith(str(flac_root))


def test_embedded_cover_is_extracted_per_song(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    flac_root = tmp_path / "flac"
    mp3_root = tmp_path / "mp3"
    source_root.mkdir()
    flac_root.mkdir()
    mp3_root.mkdir()
    scanned = []
    for number in (1, 2):
        audio = source_root / f"track{number}.flac"
        lyrics = source_root / f"track{number}.lrc"
        audio.write_bytes(f"audio-{number}".encode())
        lyrics.write_text("[00:01.00]first lyric\n[00:02.00]second lyric\n", encoding="utf-8")
        scanned.append(ScannedAudio(str(audio), audio.name, str(lyrics), []))
    monkeypatch.setattr("music_organizer.planner.scan_source", lambda _: scanned)
    monkeypatch.setattr(
        "music_organizer.planner.read_tags",
        lambda _: {"album": "Album", "albumartist": "Artist", "artist": "Artist"},
    )

    # Both songs carry their own embedded JPEG cover; nothing shared on disk.
    monkeypatch.setattr("music_organizer.planner.embedded_cover", lambda _: (b"\xff\xd8\xff-jpeg", ".jpg"))

    plan = build_plan(str(source_root), str(flac_root), str(mp3_root), data_root=str(tmp_path / "state"))

    cover_assets = [asset for track in plan.tracks for asset in track.assets if asset.kind == "cover"]
    assert plan.status == "ready"
    assert len(cover_assets) == 2
    # Original format is preserved and the cover is named after its own song.
    assert {Path(asset.destination).name for asset in cover_assets} == {"track1.jpg", "track2.jpg"}
    assert all(asset.action == "move" for asset in cover_assets)


def test_partial_apply_only_moves_selected_tracks(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    data_root = tmp_path / "state"
    tracks = []
    for name in ("a", "b"):
        source = tmp_path / f"{name}.bin"
        source.write_bytes(f"payload-{name}".encode())
        destination = tmp_path / "library" / f"{name}.bin"
        asset = AssetPlan(
            kind="audio",
            source=str(source),
            destination=str(destination),
            fingerprint=fast_fingerprint(source),
            action="move",
        )
        tracks.append(
            TrackPlan(
                track_id=f"trk_{name}",
                source_audio=str(source),
                relative_source=f"{name}.bin",
                audio_format="flac",
                tags={},
                resolved={},
                lyrics={"status": "ignored"},
                assets=[asset],
            )
        )
    # One track is blocked, so the whole plan is blocked and full apply would refuse.
    tracks[1].status = "blocked"
    plan = MigrationPlan(config={}, tracks=tracks, status="blocked")
    save_plan(plan, plan_path)

    partial = apply_plan(plan_path, data_root, track_ids={"trk_a"})

    assert partial.status == "partially_applied"
    assert (tmp_path / "library" / "a.bin").exists()
    assert not (tmp_path / "library" / "b.bin").exists()
    reloaded = load_plan(plan_path)
    statuses = {track.track_id: track.assets[0].status for track in reloaded.tracks}
    assert statuses == {"trk_a": "completed", "trk_b": "planned"}


def test_partial_apply_refuses_blocked_tracks(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    data_root = tmp_path / "state"
    source = tmp_path / "a.bin"
    source.write_bytes(b"payload")
    asset = AssetPlan(
        kind="audio",
        source=str(source),
        destination=str(tmp_path / "library" / "a.bin"),
        fingerprint=fast_fingerprint(source),
        action="move",
    )
    track = TrackPlan(
        track_id="trk_a",
        source_audio=str(source),
        relative_source="a.bin",
        audio_format="flac",
        tags={},
        resolved={},
        lyrics={"status": "ignored"},
        assets=[asset],
        status="blocked",
    )
    plan = MigrationPlan(config={}, tracks=[track], status="blocked")
    save_plan(plan, plan_path)


def test_apply_verify_and_rollback_are_journal_backed(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "library" / "target.bin"
    source.write_bytes(b"journal lifecycle" * 1024)
    asset = AssetPlan(
        kind="audio",
        source=str(source),
        destination=str(destination),
        fingerprint=fast_fingerprint(source),
        action="move",
    )
    track = TrackPlan(
        track_id="trk_test",
        source_audio=str(source),
        relative_source="source.bin",
        audio_format="flac",
        tags={},
        resolved={},
        lyrics={"status": "ignored"},
        assets=[asset],
    )
    plan = MigrationPlan(config={}, tracks=[track], status="ready")
    plan_path = tmp_path / "plan.json"
    data_root = tmp_path / "state"
    save_plan(plan, plan_path)

    applied = apply_plan(plan_path, data_root)
    verification = verify_plan(plan_path)

    assert applied.status == "applied"
    assert verification["ok"]
    assert load_plan(plan_path).status == "verified"
    assert destination.exists() and not source.exists()

    result = rollback_plan(plan_path, data_root)
    reloaded = load_plan(plan_path)
    assert result["status"] == "rolled_back"
    assert reloaded.status == "rolled_back"
    assert source.exists() and not destination.exists()


def test_cleanup_requires_verified_plan_and_removes_empty_tree(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    nested = source_root / "album" / "disc"
    nested.mkdir(parents=True)
    plan = MigrationPlan(config={"source": str(source_root)}, tracks=[], status="applied")
    plan_path = tmp_path / "plan.json"
    save_plan(plan, plan_path)

    try:
        cleanup_plan(plan_path, apply=True, include_root=True)
        raise AssertionError("cleanup should have been rejected")
    except CleanupError:
        pass

    plan.status = "verified"
    save_plan(plan, plan_path)
    result = cleanup_plan(plan_path, apply=True, include_root=True)
    assert result["count"] == 3
    assert not source_root.exists()
    assert load_plan(plan_path).status == "cleaned"


def test_apply_failure_automatically_rolls_back_committed_operations(tmp_path: Path) -> None:
    first_source = tmp_path / "first.bin"
    second_source = tmp_path / "second.bin"
    first_destination = tmp_path / "library" / "first.bin"
    occupied_destination = tmp_path / "library" / "second.bin"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    occupied_destination.parent.mkdir()
    occupied_destination.write_bytes(b"occupied")
    assets = [
        AssetPlan("audio", str(first_source), str(first_destination), fast_fingerprint(first_source), "move"),
        AssetPlan("audio", str(second_source), str(occupied_destination), fast_fingerprint(second_source), "move"),
    ]
    track = TrackPlan("trk_failure", str(first_source), "first.bin", "flac", {}, {}, {"status": "ignored"}, assets)
    plan = MigrationPlan(config={}, tracks=[track], status="ready")
    plan_path = tmp_path / "failure-plan.json"
    save_plan(plan, plan_path)

    try:
        apply_plan(plan_path, tmp_path / "state")
        raise AssertionError("apply should have failed")
    except PlanExecutionError as error:
        assert "自动回滚" in str(error)

    assert first_source.exists()
    assert not first_destination.exists()
    assert second_source.exists()
    assert occupied_destination.read_bytes() == b"occupied"
    assert load_plan(plan_path).status == "rolled_back"
