from pathlib import Path

from music_organizer.lyrics import classify_lrc


def test_classifies_empty_metadata_only_and_actual_lyrics(tmp_path: Path) -> None:
    empty = tmp_path / "empty.lrc"
    credits = tmp_path / "credits.lrc"
    actual = tmp_path / "actual.lrc"
    netease_credits = tmp_path / "netease.lrc"
    empty.write_text("[ti:Song]\n[ar:Artist]\n", encoding="utf-8")
    credits.write_text("[00:01.00]作词：甲\n[00:03.00]作曲：乙\n", encoding="utf-8")
    actual.write_text("[00:01.00]第一句歌词\n", encoding="utf-8")
    netease_credits.write_text('{"t":1000,"c":[{"tx":"作词：甲"}]}\n', encoding="utf-8")

    assert classify_lrc(empty)["status"] == "empty"
    assert classify_lrc(credits)["status"] == "metadata_only"
    assert classify_lrc(actual)["status"] == "actual"
    assert classify_lrc(netease_credits)["status"] == "metadata_only"
