#!/usr/bin/env bash
# 批量压缩原始视频到独立输出目录，不修改源文件。
# 输出参数：
#     libx264 / preset=fast / CRF=18 / yuv420p / +faststart / 无音轨
# 仅保留视频流，不保留 DJI djmd/dbgi 私有元数据流。
#
# 用法：
#     bash batch_compress_raw_videos.sh <源根目录> <输出根目录> [并发数=3]

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/reporting.sh"
source "$SCRIPT_DIR/../tools/runtime_metrics.sh"
metrics_initialize
SCRIPT_METRICS_START=$(metrics_phase_begin)
INITIALIZE_METRICS_START=$(metrics_phase_begin)

SRC_ROOT="${1:?用法: $0 <源目录> <输出目录> [并发=3]}"
DST_ROOT="${2:?用法: $0 <源目录> <输出目录> [并发=3]}"
JOBS="${3:-3}"

SRC_ROOT="${SRC_ROOT%/}"
DST_ROOT="${DST_ROOT%/}"
LOG_DIR="${DST_ROOT}/_logs"
BROKEN_LIST="${DST_ROOT}/broken_sources.txt"
mkdir -p "$LOG_DIR"
touch "$BROKEN_LIST"
report_init "$DST_ROOT/_reports" "to_directory"
metrics_phase_end "script" "initialization" "$SRC_ROOT" \
    "$INITIALIZE_METRICS_START" "ok"

compress_one() {
    local src="$1"
    local rel="${src#$SRC_ROOT/}"
    local dst="$DST_ROOT/$rel"
    local log="$LOG_DIR/$(echo "$rel" | tr '/' '_').log"
    local file_metrics_start probe_metrics_start
    file_metrics_start=$(metrics_phase_begin)
    probe_metrics_start=$(metrics_phase_begin)
    local src_size src_bitrate
    src_size=$(report_file_size "$src")
    src_bitrate=$(report_probe_bitrate "$src")

    local src_n
    src_n=$(ffprobe -v error -select_streams v:0 -count_packets \
            -show_entries stream=nb_read_packets -of csv=p=0 "$src" 2>/dev/null || echo "")
    if [[ -z "$src_n" || "$src_n" == "0" || "$src_n" == "N/A" ]]; then
        metrics_phase_end "file" "source_probe" "$src" "$probe_metrics_start" "failed"
        echo "[BROKEN-SRC] $rel (源损坏或无视频流, 跳过)"
        echo "$src" >> "$BROKEN_LIST"
        report_append "BROKEN_SOURCE" "$src" "" \
            "$src_bitrate" "" "$src_size" "" "no" "源损坏或无视频流"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" "broken_source"
        return 0
    fi
    metrics_phase_end "file" "source_probe" "$src" "$probe_metrics_start" "ok"

    if [[ -f "$dst" ]]; then
        local existing_metrics_start
        existing_metrics_start=$(metrics_phase_begin)
        local dst_n dst_size dst_bitrate
        dst_n=$(ffprobe -v error -select_streams v:0 -count_packets \
                -show_entries stream=nb_read_packets -of csv=p=0 "$dst" 2>/dev/null || echo "")
        if [[ -n "$dst_n" && "$src_n" == "$dst_n" ]]; then
            dst_size=$(report_file_size "$dst")
            dst_bitrate=$(report_probe_bitrate "$dst")
            report_append "SKIPPED_EXISTING" "$src" "$dst" \
                "$src_bitrate" "$dst_bitrate" "$src_size" "$dst_size" "yes" \
                "目标已存在且包数一致"
            metrics_phase_end "file" "existing_output_check" "$src" \
                "$existing_metrics_start" "skipped"
            metrics_phase_end "file" "total" "$src" "$file_metrics_start" \
                "skipped_existing"
            echo "[SKIP] $rel (已存在, $src_n 帧)"
            return 0
        fi
        metrics_phase_end "file" "existing_output_check" "$src" \
            "$existing_metrics_start" "redo"
        echo "[REDO] $rel (帧数 $src_n vs $dst_n 不一致, 重新压缩)"
    fi

    mkdir -p "$(dirname "$dst")"
    local tmp="${dst}.partial.mp4"

    echo "[START] $rel"
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
        metrics_phase_end "file" "encoding" "$src" "$encode_metrics_start" "failed"
        local failed_size failed_bitrate failed_path
        failed_size=$(report_file_size "$tmp")
        failed_bitrate=$(report_probe_bitrate "$tmp")
        failed_path=""
        if [[ -f "$tmp" ]]; then
            failed_path="${dst}.broken"
            mv -f "$tmp" "$failed_path"
        fi
        report_append "FAILED_FFMPEG" "$src" "$failed_path" \
            "$src_bitrate" "$failed_bitrate" "$src_size" "$failed_size" "no" \
            "FFmpeg 编码失败"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" "failed_ffmpeg"
        echo "[FAIL-FFMPEG] $rel (见日志 $log)"
        return 1
    fi
    metrics_phase_end "file" "encoding" "$src" "$encode_metrics_start" "ok"

    local verify_metrics_start
    verify_metrics_start=$(metrics_phase_begin)
    local dst_n tmp_size tmp_bitrate
    dst_n=$(ffprobe -v error -select_streams v:0 -count_packets \
            -show_entries stream=nb_read_packets -of csv=p=0 "$tmp" 2>/dev/null || echo "")
    tmp_size=$(report_file_size "$tmp")
    tmp_bitrate=$(report_probe_bitrate "$tmp")
    if [[ "$src_n" != "$dst_n" ]]; then
        metrics_phase_end "file" "output_validation" "$src" \
            "$verify_metrics_start" "failed"
        echo "[FAIL] $rel 帧数不匹配 $src_n -> $dst_n, 见日志 $log"
        mv "$tmp" "${dst}.broken"
        report_append "FAILED_VERIFY" "$src" "${dst}.broken" \
            "$src_bitrate" "$tmp_bitrate" "$src_size" "$tmp_size" "no" \
            "源和输出包数不一致"
        metrics_phase_end "file" "total" "$src" "$file_metrics_start" "failed_verify"
        return 1
    fi
    metrics_phase_end "file" "output_validation" "$src" \
        "$verify_metrics_start" "ok"

    local finalize_metrics_start
    finalize_metrics_start=$(metrics_phase_begin)
    mv "$tmp" "$dst"
    touch -r "$src" "$dst"
    report_append "COMPRESSED" "$src" "$dst" \
        "$src_bitrate" "$tmp_bitrate" "$src_size" "$tmp_size" "yes" \
        "压缩成功"

    local src_mb dst_mb ratio
    src_mb=$(du -m "$src" | cut -f1)
    dst_mb=$(du -m "$dst" | cut -f1)
    if (( dst_mb > 0 )); then
        ratio=$(awk -v s="$src_mb" -v d="$dst_mb" 'BEGIN{printf "%.2f", s/d}')
    else
        ratio="inf"
    fi
    echo "[DONE] $rel  ${src_mb}MB -> ${dst_mb}MB  (x${ratio})"
    metrics_phase_end "file" "finalization" "$src" "$finalize_metrics_start" "ok"
    metrics_phase_end "file" "total" "$src" "$file_metrics_start" "ok"
}
export -f compress_one
export SRC_ROOT DST_ROOT LOG_DIR BROKEN_LIST

PROCESS_METRICS_START=$(metrics_phase_begin)
set +e
find "$SRC_ROOT" -type f \( -iname "*.mp4" -o -iname "*.mov" \) -print0 \
    | xargs -0 -P "$JOBS" -I {} bash -c 'compress_one "$@"' _ {}
RUN_STATUS=$?
set -e
metrics_phase_end "script" "batch_processing" "$SRC_ROOT" \
    "$PROCESS_METRICS_START" "$RUN_STATUS"

echo "全部完成。"
echo "日志目录: $LOG_DIR"
echo "损坏源列表: $BROKEN_LIST ($(wc -l < "$BROKEN_LIST") 条)"
REPORT_METRICS_START=$(metrics_phase_begin)
report_finalize "$RUN_STATUS"
metrics_phase_end "script" "report_finalization" "$REPORT_FILE" \
    "$REPORT_METRICS_START" "ok"
metrics_phase_end "script" "total" "$SRC_ROOT" "$SCRIPT_METRICS_START" \
    "$RUN_STATUS"
exit "$RUN_STATUS"
