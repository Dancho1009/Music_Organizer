from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from .common import utc_now


@dataclass
class AssetPlan:
    kind: str
    source: str
    destination: str
    fingerprint: dict[str, Any]
    action: str = "move"
    status: str = "planned"
    note: str | None = None
    execution: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetPlan":
        return cls(**data)


@dataclass
class TrackPlan:
    track_id: str
    source_audio: str
    relative_source: str
    audio_format: str
    tags: dict[str, str | None]
    resolved: dict[str, str]
    lyrics: dict[str, Any]
    assets: list[AssetPlan] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ready"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackPlan":
        copied = dict(data)
        copied["assets"] = [AssetPlan.from_dict(item) for item in data.get("assets", [])]
        return cls(**copied)


@dataclass
class MigrationPlan:
    config: dict[str, Any]
    tracks: list[TrackPlan]
    plan_id: str = field(default_factory=lambda: f"plan_{uuid4().hex}")
    schema_version: int = 1
    plan_version: int = 1
    created_at: str = field(default_factory=utc_now)
    status: str = "draft"
    frozen_at: str | None = None
    parent_plan_id: str | None = None
    decisions: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MigrationPlan":
        copied = dict(data)
        copied["tracks"] = [TrackPlan.from_dict(item) for item in data.get("tracks", [])]
        return cls(**copied)
