#!/usr/bin/env bash
# 早晨停止：由 cron 在设定时间触发。
# 停止指定 tmux session，并清理目标目录中未完成的临时压缩文件。

set -euo pipefail

STATE_ROOT="${VIDEO_COMPRESSION_STATE_DIR:-$HOME/tmp/video_compression}"
SESSION="${VIDEO_COMPRESSION_SESSION:-video_compression_nightly}"
TARGET_DIR="${VIDEO_COMPRESSION_SOURCE_DIR:-}"
LOG_DIR="$STATE_ROOT/nightly_logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/stop.log"

echo "----- $(date '+%F %T') nightly_stop.sh 触发 -----" >> "$LOG"

export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

killed=0
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "$(date '+%F %T') kill $SESSION" >> "$LOG"
    tmux kill-session -t "$SESSION" 2>>"$LOG" || true
    killed=1
fi

sleep 1

echo "$(date '+%F %T') 清理残留 .compress_tmp.MP4" >> "$LOG"
if [[ -n "$TARGET_DIR" && -d "$TARGET_DIR" ]]; then
    cnt=$(find "$TARGET_DIR" -name "*.compress_tmp.MP4" -delete -print 2>/dev/null | wc -l)
    echo "  $TARGET_DIR 清理 $cnt 个临时文件" >> "$LOG"
else
    echo "  VIDEO_COMPRESSION_SOURCE_DIR 未设置或目录不存在，跳过临时文件清理" >> "$LOG"
fi

echo "$(date '+%F %T') 完成 (killed $killed sessions)" >> "$LOG"
