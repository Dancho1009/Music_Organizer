from __future__ import annotations

import json
import re
from pathlib import Path

TIME_RE = re.compile(r"^\s*\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)$")
HEADER_RE = re.compile(r"^\s*\[(?:by|ti|ar|al|au|length|offset|re|ve):", re.IGNORECASE)
CREDIT_RE = re.compile(
    r"(?:作词|作曲|編曲|编曲|制作人|製作人|演唱|歌唱|混音|母带|母帶|录音|錄音|监制|監製|吉他|贝斯|貝斯|鼓手|和声|和聲|钢琴|鋼琴|弦乐|弦樂)",
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


def classify_lrc(path: str | Path) -> dict[str, object]:
    lines = _decode(path).splitlines()
    actual: list[str] = []
    metadata: list[str] = []
    timed_lines = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        timed = TIME_RE.match(line)
        if timed:
            timed_lines += 1
            text = _clean(timed.group(4))
            if text:
                (metadata if CREDIT_RE.search(text) else actual).append(text)
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
                            (metadata if CREDIT_RE.search(text) else actual).append(text)
                else:
                    metadata.extend(text for text in texts if text)
                continue
        (metadata if CREDIT_RE.search(stripped) else actual).append(_clean(stripped))

    if actual:
        status = "actual"
    elif metadata:
        status = "metadata_only"
    else:
        status = "empty"
    return {
        "status": status,
        "timed_lines": timed_lines,
        "actual_samples": actual[:3],
        "metadata_samples": metadata[:5],
    }
