#!/usr/bin/env bash

set -euo pipefail

if (( $# < 4 )); then
    echo "用法: $0 <指标输出目录> <运行标签> -- <命令> [参数...]" >&2
    exit 2
fi

OUTPUT_DIR="$1"
RUN_LABEL="$2"
shift 2
if [[ "$1" != "--" ]]; then
    echo "缺少 -- 分隔符" >&2
    exit 2
fi
shift
if (( $# == 0 )); then
    echo "缺少要运行的命令" >&2
    exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/runtime_metrics.sh"

mkdir -p "$OUTPUT_DIR"
RUN_ID="$(date '+%Y%m%d_%H%M%S')_$$"
SAMPLES_FILE="$OUTPUT_DIR/resource_samples_$RUN_ID.tsv"
PHASES_FILE="$OUTPUT_DIR/phase_events_$RUN_ID.tsv"
STAGES_FILE="$OUTPUT_DIR/stage_summary_$RUN_ID.tsv"
SUMMARY_FILE="$OUTPUT_DIR/run_summary_$RUN_ID.txt"
COMMAND_LOG="$OUTPUT_DIR/command_$RUN_ID.log"
TIME_FILE="$OUTPUT_DIR/time_verbose_$RUN_ID.txt"
INTERVAL="${VIDEO_COMPRESSION_METRICS_INTERVAL:-5}"

export VIDEO_COMPRESSION_METRICS_FILE="$PHASES_FILE"
metrics_initialize
printf 'timestamp_ns\telapsed_ms\tprocesses\ttree_cpu_percent\ttree_rss_mib\tsystem_load1\tsystem_mem_available_mib\tsystem_gpu_avg_util_percent\tsystem_gpu_max_util_percent\tsystem_gpu_memory_used_mib\tprocess_tree_gpu_memory_mib\n' \
    > "$SAMPLES_FILE"

printf -v COMMAND_TEXT '%q ' "$@"
RUN_START_NS=$(metrics_phase_begin)

set +e
/usr/bin/time -v -o "$TIME_FILE" -- "$@" > >($SCRIPT_DIR/metrics_tee.sh "$COMMAND_LOG") 2>&1 &
RUN_PID=$!
set -e

runtime_sampler_loop "$RUN_PID" "$RUN_START_NS" "$SAMPLES_FILE" "$INTERVAL" &
SAMPLER_PID=$!

set +e
wait "$RUN_PID"
RUN_STATUS=$?
RUN_END_NS=$(metrics_now_ns)
metrics_phase_end "run" "total" "$RUN_LABEL" "$RUN_START_NS" "$RUN_STATUS"
wait "$SAMPLER_PID"
set -e

runtime_build_summaries "$SAMPLES_FILE" "$PHASES_FILE" \
    "$SUMMARY_FILE" "$STAGES_FILE" "$RUN_LABEL" "$COMMAND_TEXT" \
    "$RUN_START_NS" "$RUN_END_NS" "$RUN_STATUS"

rm -f "${VIDEO_COMPRESSION_METRICS_FILE}.lock"

echo
echo "运行指标:"
echo "  总结: $SUMMARY_FILE"
echo "  阶段: $STAGES_FILE"
echo "  资源采样: $SAMPLES_FILE"
echo "  命令日志: $COMMAND_LOG"
echo "  time -v: $TIME_FILE"

exit "$RUN_STATUS"
