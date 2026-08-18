#!/usr/bin/env bash
# 原位压缩：直接把每个 DJI 视频替换为 H.264/CRF18 压缩版。
# 输出参数：
#     libx264 / preset=fast / CRF=18 / yuv420p / +faststart / 无音轨
# 仅保留视频流（丢弃 DJI djmd/dbgi 私有元数据）。
#
# 流程：每个文件 -> ffprobe 前置检查 -> ffmpeg 压到同目录
#       *.compress_tmp.MP4 -> 校验包数 -> mv 覆盖原文件 -> 记入 DONE 列表
#
# 安全保护：
#   1. 源损坏时写入 BROKEN_LIST，跳过且不替换。
#   2. bitrate < 70 Mbps 时视为已经压缩，避免重复压缩。
#   3. 压缩后包数与源文件相差不得超过 50。
#   4. 先写完整临时文件，再用 mv 替换原文件。
#   5. DONE_LIST 记录已处理路径，支持断点续传。
#
# 用法：
#     bash batch_compress_in_place.sh <视频根目录> [并发数=8]

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/reporting.sh"
source "$SCRIPT_DIR/../tools/runtime_metrics.sh"
metrics_initialize
SCRIPT_METRICS_START=$(metrics_phase_begin)
INITIALIZE_METRICS_START=$(metrics_phase_begin)

SRC_ROOT="${1:?用法: $0 <视频根目录> [并发=8]}"
JOBS="${2:-8}"
SRC_ROOT="${SRC_ROOT%/}"

# 日志和状态写入用户自己的临时目录，不污染视频源目录。
TAG=$(echo "$SRC_ROOT" | tr '/' '_' | sed 's/^_//')
STATE_ROOT="${VIDEO_COMPRESSION_STATE_DIR:-$HOME/tmp/video_compression}"
META_BASE="$STATE_ROOT/inplace_meta/$TAG"
LOG_DIR="$META_BASE/logs"
BROKEN_LIST="$META_BASE/broken_sources.txt"
DONE_LIST="$META_BASE/done.txt"
LOW_BITRATE_THRESHOLD=70000000

mkdir -p "$LOG_DIR"
touch "$BROKEN_LIST" "$DONE_LIST"
report_init "$META_BASE/reports" "in_place"
metrics_phase_end "script" "initialization" "$SRC_ROOT" \
    "$INITIALIZE_METRICS_START" "ok"

compress_in_place() {
    local src="$1"
    local rel="${src#$SRC_ROOT/}"
    local log="$LOG_DIR/$(echo "$rel" | tr '/' '_').log"
    local file_metrics_start
    file_metrics_start=$(metrics_phase_begin)
    local src_size
    src_size=$(report_file_size "$src")

    if grep -qxF "$src" "$DONE_LIST" 2>/dev/null; then
        local current_bitrate resume_metrics_start
        resume_metrics_start=$(metrics_phase_begin)
        current_bitrate=$(report_probe_bitrate "$src")
        report_append "SKIPPED_DONE" "$src" "$src" \
            "" "$current_bitrate" "" "$src_size" "no" \
            "此前运行已完成，原始指标不属于本次运行"
        metrics_phase_end "file" "resume_check" "$src" \
            "$resume_metrics_start" "skipped"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
            "skipped_done"
        echo "[SKIP-DONE] $rel"
        return 0
    fi

    local src_n probe_metrics_start
    probe_metrics_start=$(metrics_phase_begin)
    src_n=$(ffprobe -v error -select_streams v:0 -count_packets \
            -show_entries stream=nb_read_packets -of csv=p=0 "$src" 2>/dev/null || echo "")
    if [[ -z "$src_n" || "$src_n" == "0" || "$src_n" == "N/A" ]]; then
        metrics_phase_end "file" "source_probe" "$src" \
            "$probe_metrics_start" "failed"
        echo "[BROKEN-SRC] $rel (源损坏或无视频流, 跳过, 不替换)"
        echo "$src" >> "$BROKEN_LIST"
        report_append "BROKEN_SOURCE" "$src" "" \
            "" "" "$src_size" "" "no" "源损坏或无视频流"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
            "broken_source"
        return 0
    fi

    local bitrate
    bitrate=$(report_probe_bitrate "$src")
    [[ -n "$bitrate" ]] || bitrate=0
    metrics_phase_end "file" "source_probe" "$src" \
        "$probe_metrics_start" "ok"
    if [[ -n "$bitrate" && "$bitrate" != "N/A" ]] \
        && (( bitrate > 0 )) && (( bitrate < LOW_BITRATE_THRESHOLD )); then
        echo "[SKIP-LOWBITRATE] $rel (bitrate=$((bitrate/1000000))Mbps, 疑似已压缩)"
        echo "$src" >> "$DONE_LIST"
        report_append "SKIPPED_LOW_BITRATE" "$src" "$src" \
            "$bitrate" "$bitrate" "$src_size" "$src_size" "yes" \
            "低于 70 Mbps，未执行重编码"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
            "skipped_low_bitrate"
        return 0
    fi

    local tmp="${src}.compress_tmp.MP4"
    local bitrate_mbps=$((bitrate/1000000))
    echo "[START] $rel ($src_n 帧, ${bitrate_mbps}Mbps)"

    rm -f "$tmp"
    local encode_metrics_start
    encode_metrics_start=$(metrics_phase_begin)
    if ! ffmpeg -hide_banner -loglevel error -y \
        -i "$src" \
        -map 0:v:0 \
        -c:v libx264 -preset fast -crf 18 \
        -pix_fmt yuv420p \
        -an \
        -map_metadata 0 \
        -movflags +faststart \
        "$tmp" 2> "$log"
    then
        metrics_phase_end "file" "encoding" "$src" \
            "$encode_metrics_start" "failed"
        echo "[FAIL-FFMPEG] $rel (见 $log, 保留原文件)"
        rm -f "$tmp"
        report_append "FAILED_FFMPEG" "$src" "" \
            "$bitrate" "" "$src_size" "" "no" "FFmpeg 编码失败"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
            "failed_ffmpeg"
        return 1
    fi
    metrics_phase_end "file" "encoding" "$src" "$encode_metrics_start" "ok"

    local tmp_n verify_metrics_start
    verify_metrics_start=$(metrics_phase_begin)
    tmp_n=$(ffprobe -v error -select_streams v:0 -count_packets \
            -show_entries stream=nb_read_packets -of csv=p=0 "$tmp" 2>/dev/null || echo "")
    local tmp_size tmp_bitrate
    tmp_size=$(report_file_size "$tmp")
    tmp_bitrate=$(report_probe_bitrate "$tmp")
    local frame_diff=999999
    if [[ -n "$tmp_n" && "$tmp_n" != "N/A" ]]; then
        frame_diff=$(( tmp_n > src_n ? tmp_n - src_n : src_n - tmp_n ))
    fi
    if (( frame_diff > 50 )); then
        metrics_phase_end "file" "output_validation" "$src" \
            "$verify_metrics_start" "failed"
        echo "[FAIL-VERIFY] $rel (src=$src_n vs tmp=$tmp_n, 差 $frame_diff > 50, 保留原文件)"
        mv "$tmp" "${src}.broken_compress"
        report_append "FAILED_VERIFY" "$src" "${src}.broken_compress" \
            "$bitrate" "$tmp_bitrate" "$src_size" "$tmp_size" "no" \
            "包数差 $frame_diff，大于允许值 50"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
            "failed_verify"
        return 1
    fi
    metrics_phase_end "file" "output_validation" "$src" \
        "$verify_metrics_start" "ok"

    local src_mb tmp_mb ratio finalize_metrics_start
    finalize_metrics_start=$(metrics_phase_begin)
    src_mb=$(du -m "$src" | cut -f1)
    tmp_mb=$(du -m "$tmp" | cut -f1)
    if (( tmp_mb > 0 )); then
        ratio=$(awk -v a=$src_mb -v b=$tmp_mb 'BEGIN{printf "%.2f", a/b}')
    else
        ratio="inf"
    fi

    if mv -f "$tmp" "$src"; then
        echo "$src" >> "$DONE_LIST"
        report_append "COMPRESSED" "$src" "$src" \
            "$bitrate" "$tmp_bitrate" "$src_size" "$tmp_size" "yes" \
            "原位替换成功"
        echo "[DONE] $rel  ${src_mb}MB -> ${tmp_mb}MB  (x${ratio})"
    else
        echo "[FAIL-MV] $rel (临时文件保留为 $tmp)"
        report_append "FAILED_MOVE" "$src" "$tmp" \
            "$bitrate" "$tmp_bitrate" "$src_size" "$tmp_size" "no" \
            "临时文件替换原文件失败"
        metrics_phase_end "file" "finalization" "$src" \
            "$finalize_metrics_start" "failed"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
            "failed_move"
        return 1
    fi
    metrics_phase_end "file" "finalization" "$src" \
        "$finalize_metrics_start" "ok"
    metrics_phase_end "file" "total" "$src" "$file_metrics_start" "ok"
}
export -f compress_in_place
export SRC_ROOT LOG_DIR BROKEN_LIST DONE_LIST LOW_BITRATE_THRESHOLD

echo "扫描源文件..."
SCAN_METRICS_START=$(metrics_phase_begin)
TOTAL=$(find "$SRC_ROOT" -type f \( -iname "*.mp4" -o -iname "*.mov" \) | wc -l)
metrics_phase_end "script" "source_scan" "$SRC_ROOT" \
    "$SCAN_METRICS_START" "ok"
echo "源文件总数: $TOTAL"
echo "已完成（DONE 列表）: $(wc -l < "$DONE_LIST")"
echo "broken 已记录: $(wc -l < "$BROKEN_LIST")"
echo "并发: $JOBS"
echo "日志: $LOG_DIR"
echo "DONE 列表: $DONE_LIST"
echo "BROKEN 列表: $BROKEN_LIST"
echo

PROCESS_METRICS_START=$(metrics_phase_begin)
set +e
find "$SRC_ROOT" -type f \( -iname "*.mp4" -o -iname "*.mov" \) \
    ! -iname "*.compress_tmp.MP4" ! -iname "*.broken_compress" -print0 \
    | xargs -0 -P "$JOBS" -I {} bash -c 'compress_in_place "$@"' _ {}
RUN_STATUS=$?
set -e
metrics_phase_end "script" "batch_processing" "$SRC_ROOT" \
    "$PROCESS_METRICS_START" "$RUN_STATUS"

echo
echo "全部完成。"
echo "DONE: $(wc -l < "$DONE_LIST") 段"
echo "BROKEN: $(wc -l < "$BROKEN_LIST") 段"
REPORT_METRICS_START=$(metrics_phase_begin)
report_finalize "$RUN_STATUS"
metrics_phase_end "script" "report_finalization" "$REPORT_FILE" \
    "$REPORT_METRICS_START" "ok"
metrics_phase_end "script" "total" "$SRC_ROOT" "$SCRIPT_METRICS_START" \
    "$RUN_STATUS"
exit "$RUN_STATUS"
