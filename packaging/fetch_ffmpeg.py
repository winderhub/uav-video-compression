#!/usr/bin/env python3
"""Download pinned FFmpeg/FFprobe binaries used by desktop packages."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Tuple


RELEASE_BASE = (
    "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1"
)

# target: (vendor directory, upstream platform name, executable suffix)
TARGETS: Dict[str, Tuple[str, str, str]] = {
    "windows-modern": ("windows-x64-modern", "win32-x64", ".exe"),
    "windows-win7": ("windows-x64-win7", "win32-x64", ".exe"),
    "macos-x86_64": ("macos-x86_64", "darwin-x64", ""),
    "macos-arm64": ("macos-arm64", "darwin-arm64", ""),
}

SHA256 = {
    "darwin-arm64": {
        "ffmpeg": "a90e3db6a3fd35f6074b013f948b1aa45b31c6375489d39e572bea3f18336584",
        "ffprobe": "bb2db6f5d8cef919da12fbf592119a987202a8c060a886f3cab091f9cab90b64",
        "license": "cb48bf09a11f5fb576cddb0431c8f5ed0a60157a9ec942adffc13907cbe083f2",
        "readme": "05ba4b92c96605434b1aaae3eedf5a2c280c9607bf78ffca9a5b536d9af2dc6a",
    },
    "darwin-x64": {
        "ffmpeg": "ebdddc936f61e14049a2d4b549a412b8a40deeff6540e58a9f2a2da9e6b18894",
        "ffprobe": "fa3add0ce901f7241abe0dfc0155d958fc834aca3f8ce61f87cc712ae669c1e0",
        "license": "2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af",
        "readme": "e88a0325f8e5b75210355e37341824f074d3cd82def2125be54c914b62848a36",
    },
    "win32-x64": {
        "ffmpeg": "04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00",
        "ffprobe": "3a7e2dc003dc2cd1472827e4c7c4f056ae1ae0ae7c5bbc580c99b49827351ba4",
        "license": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
        "readme": "a636a7183c58006351acbaf35303c0ed85c6e1320fd4e80de453ba6157de6311",
    },
}


def configure_utf8_stdio() -> None:
    """Keep status messages printable on Windows CI runners using cp1252."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, destination: Path, expected_sha256: str) -> None:
    if destination.is_file() and file_sha256(destination) == expected_sha256:
        print(f"已校验：{destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".download")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "uav-video-compression-builder/1.0"}
        )
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, partial.open(
            "wb"
        ) as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise RuntimeError(
                f"SHA-256 不匹配：{destination.name}，期望 {expected_sha256}，实际 {actual}"
            )
        os.replace(partial, destination)
    finally:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass

    print(f"已下载并校验：{destination}")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="下载桌面安装包所需的固定 FFmpeg 组件")
    parser.add_argument("target", choices=sorted(TARGETS))
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    vendor_name, platform_name, suffix = TARGETS[args.target]
    vendor_dir = project_root / "packaging" / "vendor" / vendor_name
    hashes = SHA256[platform_name]

    assets = (
        (f"ffmpeg-{platform_name}", f"ffmpeg{suffix}", hashes["ffmpeg"]),
        (f"ffprobe-{platform_name}", f"ffprobe{suffix}", hashes["ffprobe"]),
        (
            f"{platform_name}.LICENSE",
            "FFmpeg-GPLv3-LICENSE.txt",
            hashes["license"],
        ),
        (
            f"{platform_name}.README",
            "FFmpeg-BUILD-README.txt",
            hashes["readme"],
        ),
    )
    for remote_name, local_name, expected_hash in assets:
        destination = vendor_dir / local_name
        fetch(f"{RELEASE_BASE}/{remote_name}", destination, expected_hash)
        if local_name.startswith(("ffmpeg", "ffprobe")) and not suffix:
            destination.chmod(destination.stat().st_mode | 0o111)

    print(f"FFmpeg 组件准备完成：{vendor_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"下载失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
