from pathlib import Path

from music_organizer.lyrics import classify_lrc


def test_classifies_empty_metadata_only_and_actual_lyrics(tmp_path: Path) -> None:
    empty = tmp_path / "empty.lrc"
    credits = tmp_path / "credits.lrc"
    actual = tmp_path / "actual.lrc"
    netease_credits = tmp_path / "netease.lrc"
    empty.write_text("[ti:Song]\n[ar:Artist]\n", encoding="utf-8")
    credits.write_text("[00:01.00]作词：甲\n[00:03.00]作曲：乙\n", encoding="utf-8")
    actual.write_text("[00:01.00]第一句歌词\n[00:03.00]第二句歌词\n", encoding="utf-8")
    netease_credits.write_text('{"t":1000,"c":[{"tx":"作词：甲"}]}\n', encoding="utf-8")

    assert classify_lrc(empty)["status"] == "empty"
    assert classify_lrc(credits)["status"] == "metadata_only"
    assert classify_lrc(actual)["status"] == "actual"
    assert classify_lrc(netease_credits)["status"] == "metadata_only"


def test_classifies_non_lyric_markers_and_uncertain_content(tmp_path: Path) -> None:
    instrumental = tmp_path / "instrumental.lrc"
    one_line = tmp_path / "one-line.lrc"
    malformed = tmp_path / "malformed.lrc"
    untimed = tmp_path / "untimed.lrc"

    instrumental.write_text("[00:00.00]纯音乐，请欣赏\n", encoding="utf-8")
    one_line.write_text("[00:01.00]只有一句歌词\n", encoding="utf-8")
    malformed.write_text("[00:xx.00]损坏时间\n", encoding="utf-8")
    untimed.write_text("这是一行没有时间标签的内容\n", encoding="utf-8")

    assert classify_lrc(instrumental)["status"] == "metadata_only"
    assert classify_lrc(one_line)["status"] == "suspect"
    assert classify_lrc(malformed)["status"] == "malformed"
    assert classify_lrc(untimed)["status"] == "suspect"


def test_classifies_actual_lyrics_with_counts_and_confidence(tmp_path: Path) -> None:
    path = tmp_path / "actual.lrc"
    path.write_text("[00:01.00]第一句歌词\n[00:03.00]第二句歌词\n", encoding="utf-8")

    result = classify_lrc(path)

    assert result["status"] == "actual"
    assert result["content_line_count"] == 2
    assert result["malformed_line_count"] == 0
    assert result["confidence"] >= 0.8


def test_accepts_multiple_time_tags_on_one_lyric_line(tmp_path: Path) -> None:
    path = tmp_path / "multi-tag.lrc"
    path.write_text(
        "[00:01.00][00:03.00]重复显示的歌词\n[00:05.00]下一句歌词\n",
        encoding="utf-8",
    )

    result = classify_lrc(path)

    assert result["status"] == "actual"
    assert result["timed_lines"] == 3
