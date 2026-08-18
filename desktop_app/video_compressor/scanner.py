from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import (
    ENCODE_TEMP_SUFFIX,
    EXPECTED_OUTPUT_RATIO,
    RESTORE_TEMP_SUFFIX,
    STATE_DIR_NAME,
    VIDEO_EXTENSIONS,
    required_free_bytes,
)
from .platform_utils import available_bytes


@dataclass(frozen=True)
class ScanSummary:
    paths: list[Path]
    total_bytes: int
    largest_bytes: int
    estimated_output_bytes: int
    available_bytes: int
    required_free_bytes: int

    @property
    def needs_external_staging(self) -> bool:
        return self.available_bytes < self.required_free_bytes


def _is_video(path: Path) -> bool:
    if path.suffix.casefold() not in VIDEO_EXTENSIONS:
        return False
    lowered = path.name.casefold()
    return not (
        lowered.endswith(ENCODE_TEMP_SUFFIX.casefold())
        or lowered.endswith(RESTORE_TEMP_SUFFIX.casefold())
        or lowered.endswith(".broken_compress")
    )


def scan_videos(source_root: Path) -> ScanSummary:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(str(source_root))
    paths: list[Path] = []
    total = 0
    largest = 0
    for path in source_root.rglob("*"):
        if STATE_DIR_NAME in path.parts:
            continue
        if not path.is_file() or not _is_video(path):
            continue
        size = path.stat().st_size
        paths.append(path)
        total += size
        largest = max(largest, size)
    paths.sort(key=lambda item: item.relative_to(source_root).as_posix().casefold())
    free = available_bytes(source_root)
    return ScanSummary(
        paths=paths,
        total_bytes=total,
        largest_bytes=largest,
        estimated_output_bytes=int(total * EXPECTED_OUTPUT_RATIO),
        available_bytes=free,
        required_free_bytes=required_free_bytes(largest),
    )


def relative_paths(source_root: Path, paths: Iterable[Path]) -> list[str]:
    return [path.relative_to(source_root).as_posix() for path in paths]
