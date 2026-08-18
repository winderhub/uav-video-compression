# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path


project_root = Path(SPECPATH).parent
binary_dir_raw = os.environ.get("VIDEO_COMPRESSOR_PLATFORM_BIN_DIR")
if not binary_dir_raw:
    raise SystemExit("请设置 VIDEO_COMPRESSOR_PLATFORM_BIN_DIR，指向包含 ffmpeg/ffprobe 的目录。")
binary_dir = Path(binary_dir_raw).resolve()
suffix = ".exe" if sys.platform == "win32" else ""
ffmpeg = binary_dir / f"ffmpeg{suffix}"
ffprobe = binary_dir / f"ffprobe{suffix}"
for required in (ffmpeg, ffprobe):
    if not required.is_file():
        raise SystemExit(f"缺少打包组件：{required}")


a = Analysis(
    [str(project_root / "desktop_app" / "main.py")],
    pathex=[str(project_root / "desktop_app")],
    binaries=[(str(ffmpeg), "resources"), (str(ffprobe), "resources")],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AerialVideoCompressor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AerialVideoCompressor",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Aerial Video Compressor.app",
        icon=None,
        bundle_identifier="org.aerial.video-compressor",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Internal research data tooling",
        },
    )
