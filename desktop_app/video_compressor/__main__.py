from __future__ import annotations

import argparse
import sys

from . import __version__
from .app import run_gui
from .config import APP_NAME, CpuMode, encoder_threads, logical_cpu_count
from .media import discover_binary


def diagnostics() -> int:
    print(f"{APP_NAME} {__version__}")
    cpus = logical_cpu_count()
    print(f"logical_cpus={cpus}")
    for mode in CpuMode:
        print(f"threads_{mode.value}={encoder_threads(mode, cpus)}")
    try:
        print(f"ffmpeg={discover_binary('ffmpeg')}")
        print(f"ffprobe={discover_binary('ffprobe')}")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="aerial-video-compressor")
    parser.add_argument("--diagnose", action="store_true", help="检查 CPU 和 FFmpeg 组件")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if args.diagnose:
        return diagnostics()
    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
