#!/usr/bin/env bash
# 夜间启动：由 cron 在设定时间触发。
# 目标目录通过 VIDEO_COMPRESSION_SOURCE_DIR 指定，避免把部署路径写进仓库。

set -euo pipefail

SESSION="${VIDEO_COMPRESSION_SESSION:-video_compression_nightly}"
TARGET_DIR="${VIDEO_COMPRESSION_SOURCE_DIR:-}"
JOBS="${VIDEO_COMPRESSION_JOBS:-1}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COMPRESS_SCRIPT="$SCRIPT_DIR/../compression/batch_compress_in_place.sh"
STATE_ROOT="${VIDEO_COMPRESSION_STATE_DIR:-$HOME/tmp/video_compression}"
LOG_DIR="$STATE_ROOT/nightly_logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/start.log"
ERR_LOG="$LOG_DIR/start.err.log"

trap 'rc=$?; echo "$(date "+%F %T") nightly_start.sh 异常退出 rc=$rc at line $LINENO" >> "$ERR_LOG"' ERR

echo "----- $(date '+%F %T') nightly_start.sh 触发 -----" >> "$LOG"

if [[ -z "$TARGET_DIR" || ! -d "$TARGET_DIR" ]]; then
    echo "$(date '+%F %T') VIDEO_COMPRESSION_SOURCE_DIR 未设置或目录不存在" >> "$ERR_LOG"
    exit 2
fi

if [[ ! "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "$(date '+%F %T') VIDEO_COMPRESSION_JOBS 必须是正整数" >> "$ERR_LOG"
    exit 2
fi

SKIP_ONCE_FLAG="$LOG_DIR/skip_once"
if [[ -f "$SKIP_ONCE_FLAG" ]]; then
    echo "$(date '+%F %T') 检测到 skip_once 标记 -> 跳过本次启动 (一次性, 已删除标记)" >> "$LOG"
    rm -f "$SKIP_ONCE_FLAG"
    exit 0
fi

export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "$(date '+%F %T') 已有 session: $SESSION - 跳过本次启动" >> "$LOG"
    exit 0
fi

tmux new-session -d -s "$SESSION" \
    bash "$COMPRESS_SCRIPT" "$TARGET_DIR" "$JOBS"

echo "$(date '+%F %T') 启动 $SESSION 成功，目标=$TARGET_DIR，并发=$JOBS" >> "$LOG"
