from __future__ import annotations

import json
import re
from pathlib import Path

TIME_TAG_RE = re.compile(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")
TIME_RE = re.compile(r"^\s*((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]\s*)+)(.*)$")
HEADER_RE = re.compile(r"^\s*\[(?:by|ti|ar|al|au|length|offset|re|ve|id|tool|kana|total|language):", re.IGNORECASE)
CREDIT_RE = re.compile(
    r"(?:作词|作詞|作曲|編曲|编曲|制作人|製作人|演唱|歌唱|混音|母带|母帶|录音|錄音|监制|監製|吉他|贝斯|貝斯|鼓手|和声|和聲|钢琴|鋼琴|弦乐|弦樂)",
    re.IGNORECASE,
)
NON_LYRICS_RE = re.compile(
    r"(?:纯音乐|純音樂|伴奏|instrumental|inst\.?|暂无歌词|暫無歌詞|无歌词|無歌詞|纯音乐请欣赏|純音樂請欣賞)",
    re.IGNORECASE,
)


def _decode(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\ufeff", "")).strip()


def _json_texts(value: object) -> list[str]:
    if not isinstance(value, dict) or not isinstance(value.get("c"), list):
        return []
    return [
        _clean(item.get("tx"))
        for item in value["c"]
        if isinstance(item, dict) and item.get("tx") is not None
    ]


def _is_actual_text(text: str) -> bool:
    compact = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return len(compact) >= 2 and not NON_LYRICS_RE.search(text) and not CREDIT_RE.search(text)


def _classify_text(text: str) -> str:
    if not text:
        return "empty"
    if NON_LYRICS_RE.search(text) or CREDIT_RE.search(text):
        return "metadata"
    return "actual" if _is_actual_text(text) else "other"


def classify_lrc(path: str | Path) -> dict[str, object]:
    lines = _decode(path).splitlines()
    actual: list[str] = []
    metadata: list[str] = []
    other: list[str] = []
    malformed: list[str] = []
    timed_lines = 0
    untimed_content = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        timed = TIME_RE.match(line)
        if timed:
            timed_lines += len(TIME_TAG_RE.findall(timed.group(1)))
            text = _clean(timed.group(2))
            if text:
                bucket = _classify_text(text)
                if bucket == "metadata":
                    metadata.append(text)
                elif bucket == "actual":
                    actual.append(text)
                else:
                    other.append(text)
            continue
        if HEADER_RE.match(line):
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                data = None
            if data is not None:
                texts = _json_texts(data)
                if isinstance(data.get("t"), (int, float)) and data["t"] >= 0:
                    for text in texts:
                        if text:
                            bucket = _classify_text(text)
                            if bucket == "metadata":
                                metadata.append(text)
                            elif bucket == "actual":
                                actual.append(text)
                            else:
                                other.append(text)
                else:
                    metadata.extend(text for text in texts if text)
                continue
        if stripped.startswith("["):
            malformed.append(stripped)
            continue
        text = _clean(stripped)
        if not text:
            continue
        untimed_content += 1
        bucket = _classify_text(text)
        if bucket == "metadata":
            metadata.append(text)
        else:
            other.append(text)

    reasons: list[str] = []
    if actual and len(actual) < 2:
        reasons.append("只有一行有效歌词，无法自动确认")
    if malformed:
        reasons.append(f"有 {len(malformed)} 行时间或格式无法解析")
    if untimed_content:
        reasons.append(f"有 {untimed_content} 行未带时间标签的正文")
    if len(actual) >= 2 and not malformed and not untimed_content:
        status = "actual"
    elif metadata and not actual:
        status = "metadata_only"
    elif actual or other:
        status = "suspect"
    elif malformed:
        status = "malformed"
    else:
        status = "empty"
    if status == "actual":
        confidence = min(0.99, 0.82 + min(len(actual), 17) * 0.01)
    elif status in {"metadata_only", "empty", "malformed"}:
        confidence = 0.95
    else:
        confidence = 0.45
    return {
        "status": status,
        "confidence": confidence,
        "timed_lines": timed_lines,
        "content_line_count": len(actual),
        "metadata_line_count": len(metadata),
        "malformed_line_count": len(malformed),
        "actual_samples": actual[:3],
        "metadata_samples": metadata[:5],
        "reasons": reasons,
    }
