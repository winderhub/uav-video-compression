#!/usr/bin/env bash

set -euo pipefail

ARCH="${1:-$(uname -m)}"
case "$ARCH" in
    x86_64|arm64) ;;
    *) echo "不支持的 macOS 架构: $ARCH" >&2; exit 2 ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
VENDOR_DIR="$PROJECT_ROOT/packaging/vendor/macos-$ARCH"
VENV_DIR="$PROJECT_ROOT/build/venv-macos-$ARCH"

for name in ffmpeg ffprobe; do
    if [[ ! -x "$VENDOR_DIR/$name" ]]; then
        echo "缺少可执行文件: $VENDOR_DIR/$name" >&2
        exit 2
    fi
done

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/packaging/requirements-build.txt"

export VIDEO_COMPRESSOR_PLATFORM_BIN_DIR="$VENDOR_DIR"
cd "$PROJECT_ROOT"
"$VENV_DIR/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$PROJECT_ROOT/dist/macos-$ARCH" \
    --workpath "$PROJECT_ROOT/build/pyinstaller-macos-$ARCH" \
    "$PROJECT_ROOT/packaging/aerial_video_compressor.spec"

echo "构建完成: dist/macos-$ARCH/Aerial Video Compressor.app"
