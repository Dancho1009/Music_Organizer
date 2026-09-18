from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

SCORE_VERSION = "lyrics-score-v2"
TIME_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
TIME_RE = re.compile(r"^\s*((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]\s*)+)(.*)$")
HEADER_RE = re.compile(r"^\s*\[(?P<key>by|ti|ar|al|au|length|offset|re|ve|id|tool|kana|total|language):(?P<value>.*?)\]\s*$", re.IGNORECASE)
CREDIT_RE = re.compile(r"(?:作词|作詞|作曲|編曲|编曲|制作人|製作人|演唱|歌唱|混音|母带|母帶|录音|錄音|监制|監製|吉他|贝斯|貝斯|鼓手|和声|和聲|钢琴|鋼琴|弦乐|弦樂)", re.IGNORECASE)
NON_LYRICS_RE = re.compile(r"(?:纯音乐|純音樂|伴奏|instrumental|inst\.?|暂无歌词|暫無歌詞|无歌词|無歌詞|纯音乐请欣赏|純音樂請欣賞)", re.IGNORECASE)


def _decode(path: str | Path) -> tuple[str, bool]:
    raw = Path(path).read_bytes()
    for index, encoding in enumerate(("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "gb18030")):
        try:
            return raw.decode(encoding), index > 0
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), True


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\ufeff", "")).strip()


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", _clean(value)).casefold()
    text = re.sub(r"\b(?:feat\.?|ft\.?|featuring|with)\b.*$", "", text)
    text = re.sub(r"[\[\(（【].*?[\]\)）】]", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)


def _reason(code: str, severity: str, message: str, score_impact: float = 0.0, **evidence: object) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "score_impact": score_impact, "evidence": evidence}


def _json_texts(value: object) -> list[str]:
    if not isinstance(value, dict) or not isinstance(value.get("c"), list):
        return []
    return [_clean(item.get("tx")) for item in value["c"] if isinstance(item, dict) and item.get("tx") is not None]


def _is_actual_text(text: str) -> bool:
    compact = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return len(compact) >= 2 and not NON_LYRICS_RE.search(text) and not CREDIT_RE.search(text)


def _classify_text(text: str) -> str:
    if not text:
        return "empty"
    if NON_LYRICS_RE.search(text) or CREDIT_RE.search(text):
        return "metadata"
    return "actual" if _is_actual_text(text) else "other"


def _score_match(headers: dict[str, str], audio_tags: dict[str, str | None] | None, audio_path: str | Path | None, lrc_path: str | Path) -> tuple[float, list[dict[str, Any]]]:
    if not audio_tags and not audio_path:
        return 0.75, []
    reasons: list[dict[str, Any]] = []
    score = 0.5
    title = _normalize(audio_tags.get("title")) if audio_tags else ""
    artist = _normalize(audio_tags.get("artist")) if audio_tags else ""
    lyric_title = _normalize(headers.get("ti", ""))
    lyric_artist = _normalize(headers.get("ar", ""))
    if lyric_title and title:
        if lyric_title == title:
            score += 0.25
        else:
            score -= 0.25
            reasons.append(_reason("title_mismatch", "manual_review", f"歌词标题“{headers.get('ti')}”与音频标题不匹配。", -0.25, lyrics_title=headers.get("ti"), audio_title=audio_tags.get("title") if audio_tags else None))
    elif title and not lyric_title:
        reasons.append(_reason("title_metadata_missing", "warning", "歌词文件没有歌曲标题元数据。", -0.05))
    if lyric_artist and artist:
        if lyric_artist == artist:
            score += 0.2
        else:
            score -= 0.2
            reasons.append(_reason("artist_mismatch", "manual_review", f"歌词艺人“{headers.get('ar')}”与音频艺人不匹配。", -0.2, lyrics_artist=headers.get("ar"), audio_artist=audio_tags.get("artist") if audio_tags else None))
    elif artist and not lyric_artist:
        reasons.append(_reason("artist_metadata_missing", "warning", "歌词文件没有艺人元数据。", -0.04))
    if audio_path and Path(audio_path).stem.casefold() == Path(lrc_path).stem.casefold():
        score += 0.15
    elif audio_path:
        score -= 0.1
        reasons.append(_reason("filename_mismatch", "warning", "歌词文件名与音频文件名不一致。", -0.1, audio=Path(audio_path).name, lyrics=Path(lrc_path).name))
    return max(0.0, min(1.0, score)), reasons


def classify_lrc(path: str | Path, *, audio_tags: dict[str, str | None] | None = None, audio_path: str | Path | None = None) -> dict[str, object]:
    text, decode_fallback = _decode(path)
    actual: list[str] = []
    metadata: list[str] = []
    other: list[str] = []
    malformed: list[str] = []
    timestamps: list[float] = []
    headers: dict[str, str] = {}
    untimed_content = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        timed = TIME_RE.match(line)
        if timed:
            tags = TIME_TAG_RE.findall(timed.group(1))
            for minutes, seconds, fraction in tags:
                timestamps.append(int(minutes) * 60 + int(seconds) + (int(fraction or 0) / (1000 if len(fraction or "") > 2 else 100)))
            value = _clean(timed.group(2))
            if value:
                bucket = _classify_text(value)
                (metadata if bucket == "metadata" else actual if bucket == "actual" else other).append(value)
            continue
        header = HEADER_RE.match(line)
        if header:
            headers[header.group("key").casefold()] = _clean(header.group("value").rstrip("]"))
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                values = _json_texts(data)
                if isinstance(data.get("t"), (int, float)) and data["t"] >= 0:
                    for value in values:
                        bucket = _classify_text(value)
                        (metadata if bucket == "metadata" else actual if bucket == "actual" else other).append(value)
                else:
                    metadata.extend(value for value in values if value)
                continue
        if stripped.startswith("["):
            malformed.append(stripped)
            continue
        untimed_content += 1
        value = _clean(stripped)
        bucket = _classify_text(value)
        (metadata if bucket == "metadata" else other).append(value)

    reasons: list[dict[str, Any]] = []
    if decode_fallback:
        reasons.append(_reason("decode_fallback", "warning", "文件使用了非首选编码或降级解码。", -0.05))
    if malformed:
        reasons.append(_reason("malformed_time_tag", "manual_review", f"有 {len(malformed)} 行时间或格式无法解析。", -0.35, count=len(malformed)))
    duplicate_timestamps = len(timestamps) - len(set(timestamps))
    non_monotonic = sum(1 for previous, current in zip(timestamps, timestamps[1:]) if current < previous)
    if duplicate_timestamps:
        reasons.append(_reason("duplicate_timestamps", "warning", f"有 {duplicate_timestamps} 个重复时间标签。", -0.05, count=duplicate_timestamps))
    if non_monotonic:
        reasons.append(_reason("non_monotonic_timestamps", "manual_review", "歌词时间标签不是递增顺序。", -0.2, count=non_monotonic))
    if untimed_content:
        reasons.append(_reason("untimed_content", "manual_review", f"有 {untimed_content} 行未带时间标签的正文。", -0.2, count=untimed_content))
    lyric_duration = max(timestamps) if timestamps else 0.0
    audio_duration = audio_tags.get("duration_seconds") if audio_tags else None
    if isinstance(audio_duration, (int, float)) and audio_duration > 0 and lyric_duration > 0:
        ratio = lyric_duration / float(audio_duration)
        if ratio < 0.35:
            reasons.append(_reason("lyrics_duration_too_short", "warning", "歌词时间跨度明显短于音频时长。", -0.12, lyrics_seconds=round(lyric_duration, 2), audio_seconds=round(float(audio_duration), 2)))
        elif ratio > 1.2:
            reasons.append(_reason("lyrics_duration_too_long", "warning", "歌词时间跨度明显超过音频时长。", -0.12, lyrics_seconds=round(lyric_duration, 2), audio_seconds=round(float(audio_duration), 2)))
    if len(actual) < 2 and actual:
        reasons.append(_reason("too_few_lyric_lines", "manual_review", "有效歌词少于两行，无法自动确认。", -0.3, count=len(actual)))
    if not actual and metadata:
        code = "instrumental_marker" if any(NON_LYRICS_RE.search(value) for value in metadata) else "metadata_only"
        reasons.append(_reason(code, "manual_review", "文件只有元数据或无歌词说明，没有实际歌词。", -0.7))
    if not actual and not metadata and not other and not malformed:
        reasons.append(_reason("empty_file", "manual_review", "文件没有可用歌词内容。", -0.8))
    if actual:
        duplicate_ratio = 1 - (len(set(_normalize(value) for value in actual)) / len(actual))
        if duplicate_ratio > 0.3:
            reasons.append(_reason("high_duplicate_ratio", "warning", "歌词正文重复比例过高。", -0.2, ratio=round(duplicate_ratio, 3)))
    match_score, match_reasons = _score_match(headers, audio_tags, audio_path, path)
    reasons.extend(match_reasons)

    severe_match = any(reason.get("severity") == "manual_review" and reason.get("code") in {"title_mismatch", "artist_mismatch"} for reason in reasons)
    if not actual and metadata:
        status = "metadata_only"
    elif actual and len(actual) >= 2 and not malformed and not untimed_content and not any(item["severity"] == "manual_review" for item in match_reasons):
        status = "actual"
    elif actual or other:
        status = "suspect"
    elif malformed:
        status = "malformed"
    else:
        status = "empty"
    format_score = max(0.0, 1.0 - min(0.8, len(malformed) * 0.2) - (0.05 if decode_fallback else 0.0))
    duration_penalty = 0.12 if any(reason["code"] in {"lyrics_duration_too_short", "lyrics_duration_too_long"} for reason in reasons) else 0.0
    timing_score = max(0.0, 1.0 - min(0.82, duplicate_timestamps * 0.05 + non_monotonic * 0.2 + untimed_content * 0.2 + duration_penalty))
    content_score = 0.1 if not actual and metadata else 0.05 if not actual else max(0.0, min(1.0, 0.55 + min(len(actual), 20) * 0.02 - (0.2 if len(actual) < 2 else 0.0)))
    source_score = 1.0 if audio_path and Path(audio_path).stem.casefold() == Path(path).stem.casefold() else 0.8 if audio_path else 0.75
    confidence = format_score * 0.2 + timing_score * 0.2 + content_score * 0.25 + match_score * 0.25 + source_score * 0.1
    if status == "metadata_only":
        confidence = min(confidence, 0.2)
    elif status == "empty":
        confidence = min(confidence, 0.1)
    elif status == "malformed":
        confidence = min(confidence, 0.3)
    elif status == "suspect":
        confidence = min(confidence, 0.74)
    if severe_match:
        status = "manual_review"
    return {
        "status": status,
        "confidence": round(max(0.0, min(0.99, confidence)), 3),
        "confidence_version": SCORE_VERSION,
        "scores": {"format": round(format_score, 3), "timing": round(timing_score, 3), "content": round(content_score, 3), "match": round(match_score, 3), "source": round(source_score, 3)},
        "metrics": {"timed_line_count": len(timestamps), "content_line_count": len(actual), "metadata_line_count": len(metadata), "malformed_line_count": len(malformed), "untimed_content_line_count": untimed_content, "duplicate_timestamp_count": duplicate_timestamps, "non_monotonic_timestamp_count": non_monotonic, "duration_seconds": lyric_duration, "audio_duration_seconds": audio_duration if isinstance(audio_duration, (int, float)) else 0.0},
        "timed_lines": len(timestamps),
        "content_line_count": len(actual),
        "metadata_line_count": len(metadata),
        "malformed_line_count": len(malformed),
        "actual_samples": actual[:3],
        "metadata_samples": metadata[:5],
        "reasons": reasons,
        "source": str(path),
    }
