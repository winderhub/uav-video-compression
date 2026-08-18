from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


APP_NAME = "Aerial Video Compressor"
APP_ID = "aerial-video-compressor"
STATE_DIR_NAME = ".video-compressor"
DATABASE_NAME = "state.sqlite3"
VIDEO_EXTENSIONS = {".mp4"}
LOW_BITRATE_THRESHOLD = 70_000_000
MAX_PACKET_DIFFERENCE = 50
EXPECTED_OUTPUT_RATIO = 0.72
SPACE_MULTIPLIER = 1.25
SPACE_RESERVE_BYTES = 1 * 1024**3
ENCODE_TEMP_SUFFIX = ".compress_tmp.MP4"
RESTORE_TEMP_SUFFIX = ".restore_partial.MP4"


class CpuMode(str, Enum):
    QUIET = "quiet"
    BALANCED = "balanced"
    FAST = "fast"

    @property
    def display_name(self) -> str:
        return {
            CpuMode.QUIET: "安静",
            CpuMode.BALANCED: "均衡",
            CpuMode.FAST: "全速",
        }[self]


def logical_cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def encoder_threads(mode: CpuMode, logical_cpus: Optional[int] = None) -> int:
    """Return a conservative x264 thread count without changing output quality settings."""
    cpus = max(1, logical_cpus or logical_cpu_count())
    ratios = {
        CpuMode.QUIET: 0.25,
        CpuMode.BALANCED: 0.50,
        CpuMode.FAST: 0.75,
    }
    return max(1, min(cpus, round(cpus * ratios[mode])))


def required_free_bytes(largest_source_bytes: int) -> int:
    if largest_source_bytes <= 0:
        return SPACE_RESERVE_BYTES
    return int(largest_source_bytes * SPACE_MULTIPLIER) + SPACE_RESERVE_BYTES


@dataclass(frozen=True)
class CompressionSettings:
    mode: CpuMode = CpuMode.BALANCED
    crf: int = 18
    preset: str = "fast"
    pixel_format: str = "yuv420p"

    @property
    def threads(self) -> int:
        return encoder_threads(self.mode)
