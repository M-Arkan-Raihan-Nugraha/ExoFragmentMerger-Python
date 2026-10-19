"""Detect and parse ExoPlayer cache formats (legacy and Media3 v3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CacheFormat(Enum):
    """Supported ExoPlayer cache naming conventions."""

    LEGACY = "legacy"
    MEDIA3_V3 = "media3_v3"


LEGACY_PATTERN = re.compile(r"^(\d+)\.")
MEDIA3_V3_PATTERN = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)\.v3\.exo$"
)


@dataclass
class ContentGroup:
    """A set of cache spans belonging to the same content stream."""

    content_id: int
    segments: list[Path] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.segments)


def parse_media3_filename(name: str) -> tuple[int, int, int] | None:
    """Parse a Media3 v3 filename into (content_id, position, timestamp).

    Returns None if the filename does not match the v3 pattern.
    """
    match = MEDIA3_V3_PATTERN.match(name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def detect_cache_format(root: Path) -> CacheFormat:
    """Auto-detect whether a folder uses legacy or Media3 v3 naming.

    If any ``.v3.exo`` file is found, the folder is treated as Media3.
    Falls back to LEGACY when no v3 files are present.
    """
    for path in root.rglob("*.exo"):
        if path.is_file() and MEDIA3_V3_PATTERN.match(path.name):
            return CacheFormat.MEDIA3_V3
    return CacheFormat.LEGACY


def group_media3_segments(root: Path) -> list[ContentGroup]:
    """Group Media3 v3 .exo files by content_id, sorted by byte offset.

    Empty files are silently excluded.  Groups are returned in content_id
    order so that callers can treat group 0 as the primary (usually video)
    stream and subsequent groups as secondary (audio, etc.) streams.
    """
    if not root.is_dir():
        raise ValueError(f"Input folder not found: {root}")

    buckets: dict[int, list[tuple[int, Path]]] = {}
    for path in root.rglob("*.exo"):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        parsed = parse_media3_filename(path.name)
        if parsed is None:
            continue
        content_id, position, _timestamp = parsed
        buckets.setdefault(content_id, []).append((position, path))

    groups: list[ContentGroup] = []
    for content_id in sorted(buckets):
        entries = sorted(buckets[content_id], key=lambda item: item[0])
        group = ContentGroup(
            content_id=content_id,
            segments=[path for _, path in entries],
        )
        groups.append(group)
    return groups
