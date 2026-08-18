#!/usr/bin/env bash

metrics_enabled() {
    [[ -n "${VIDEO_COMPRESSION_METRICS_FILE:-}" ]]
}

metrics_now_ns() {
    date '+%s%N'
}

metrics_sanitize_field() {
    printf '%s' "${1:-}" | tr '\t\r\n' '   '
}

metrics_initialize() {
    metrics_enabled || return 0

    VIDEO_COMPRESSION_METRICS_LOCK="${VIDEO_COMPRESSION_METRICS_FILE}.lock"
    mkdir -p "$(dirname -- "$VIDEO_COMPRESSION_METRICS_FILE")"
    {
        flock -x 9
        if [[ ! -s "$VIDEO_COMPRESSION_METRICS_FILE" ]]; then
            printf 'scope\tphase\titem\tstart_ns\tend_ns\tduration_ms\tstatus\tpid\n' \
                > "$VIDEO_COMPRESSION_METRICS_FILE"
        fi
    } 9>>"$VIDEO_COMPRESSION_METRICS_LOCK"
    export VIDEO_COMPRESSION_METRICS_LOCK
}

metrics_phase_begin() {
    metrics_enabled || return 0
    metrics_now_ns
}

metrics_phase_end() {
    local scope="${1:-}"
    local phase="${2:-}"
    local item="${3:-}"
    local start_ns="${4:-}"
    local status="${5:-ok}"
    local end_ns duration_ms

    metrics_enabled || return 0
    [[ "$start_ns" =~ ^[0-9]+$ ]] || return 0

    end_ns=$(metrics_now_ns)
    duration_ms=$(( (end_ns - start_ns) / 1000000 ))
    scope=$(metrics_sanitize_field "$scope")
    phase=$(metrics_sanitize_field "$phase")
    item=$(metrics_sanitize_field "$item")
    status=$(metrics_sanitize_field "$status")

    {
        flock -x 9
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$scope" "$phase" "$item" "$start_ns" "$end_ns" \
            "$duration_ms" "$status" "${BASHPID:-$$}" \
            >> "$VIDEO_COMPRESSION_METRICS_FILE"
    } 9>>"$VIDEO_COMPRESSION_METRICS_LOCK"
}

runtime_collect_tree_pids() {
    local root_pid="$1"
    local parent child
    local -a queue next all children

    queue=("$root_pid")
    all=("$root_pid")
    while (( ${#queue[@]} > 0 )); do
        next=()
        for parent in "${queue[@]}"; do
            children=()
            mapfile -t children < <(pgrep -P "$parent" 2>/dev/null || true)
            for child in "${children[@]}"; do
                [[ "$child" =~ ^[0-9]+$ ]] || continue
                all+=("$child")
                next+=("$child")
            done
        done
        queue=("${next[@]}")
    done

    printf '%s\n' "${all[@]}" | awk '!seen[$0]++'
}

runtime_sample_resources() {
    local root_pid="$1"
    local start_ns="$2"
    local samples_file="$3"
    local now_ns elapsed_ms pids pid_csv process_count
    local process_metrics tree_cpu tree_rss_kib tree_rss_mib
    local load1 mem_available_kib mem_available_mib
    local gpu_values gpu_metrics gpu_avg gpu_max gpu_mem_used
    local gpu_apps tree_gpu_mem

    now_ns=$(metrics_now_ns)
    elapsed_ms=$(( (now_ns - start_ns) / 1000000 ))
    pids=$(runtime_collect_tree_pids "$root_pid")
    pid_csv=$(printf '%s\n' "$pids" | paste -sd, -)
    process_count=$(printf '%s\n' "$pids" | awk 'NF { count++ } END { print count + 0 }')

    if [[ -n "$pid_csv" ]]; then
        process_metrics=$(ps -o pcpu=,rss= -p "$pid_csv" 2>/dev/null \
            | awk '{ cpu += $1; rss += $2 } END { printf "%.3f %d", cpu + 0, rss + 0 }')
    else
        process_metrics="0 0"
    fi
    read -r tree_cpu tree_rss_kib <<< "$process_metrics"
    tree_rss_mib=$(awk -v value="${tree_rss_kib:-0}" 'BEGIN { printf "%.3f", value / 1024 }')

    read -r load1 _ < /proc/loadavg
    mem_available_kib=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
    mem_available_mib=$(awk -v value="${mem_available_kib:-0}" \
        'BEGIN { printf "%.3f", value / 1024 }')

    gpu_avg=0
    gpu_max=0
    gpu_mem_used=0
    tree_gpu_mem=0
    if command -v nvidia-smi >/dev/null 2>&1; then
        gpu_values=$(nvidia-smi \
            --query-gpu=utilization.gpu,memory.used \
            --format=csv,noheader,nounits 2>/dev/null || true)
        gpu_metrics=$(printf '%s\n' "$gpu_values" \
            | awk -F',' '
                {
                    gsub(/ /, "", $1)
                    gsub(/ /, "", $2)
                    if ($1 ~ /^[0-9.]+$/) {
                        count++
                        sum += $1
                        if ($1 > max) max = $1
                    }
                    if ($2 ~ /^[0-9.]+$/) memory += $2
                }
                END { printf "%.3f %.3f %.3f", count ? sum / count : 0, max + 0, memory + 0 }
            ')
        read -r gpu_avg gpu_max gpu_mem_used <<< "$gpu_metrics"

        gpu_apps=$(nvidia-smi \
            --query-compute-apps=pid,used_memory \
            --format=csv,noheader,nounits 2>/dev/null || true)
        tree_gpu_mem=$(printf '%s\n' "$gpu_apps" \
            | awk -F',' -v ids=",$pid_csv," '
                {
                    gsub(/ /, "", $1)
                    gsub(/ /, "", $2)
                    if (index(ids, "," $1 ",") && $2 ~ /^[0-9.]+$/) sum += $2
                }
                END { printf "%.3f", sum + 0 }
            ')
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$now_ns" "$elapsed_ms" "$process_count" "$tree_cpu" \
        "$tree_rss_mib" "$load1" "$mem_available_mib" \
        "$gpu_avg" "$gpu_max" "$gpu_mem_used" "$tree_gpu_mem" \
        >> "$samples_file"
}

runtime_sampler_loop() {
    local root_pid="$1"
    local start_ns="$2"
    local samples_file="$3"
    local interval="$4"

    while kill -0 "$root_pid" 2>/dev/null; do
        runtime_sample_resources "$root_pid" "$start_ns" "$samples_file"
        sleep "$interval"
    done
}

runtime_build_summaries() {
    local samples_file="$1"
    local phases_file="$2"
    local summary_file="$3"
    local stages_file="$4"
    local label="$5"
    local command_text="$6"
    local start_ns="$7"
    local end_ns="$8"
    local exit_code="$9"
    local elapsed_ms

    elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    {
        printf 'label=%s\n' "$label"
        printf 'command=%s\n' "$command_text"
        printf 'start_ns=%s\n' "$start_ns"
        printf 'end_ns=%s\n' "$end_ns"
        printf 'elapsed_seconds=%.3f\n' "$(awk -v value="$elapsed_ms" \
            'BEGIN { print value / 1000 }')"
        printf 'exit_code=%s\n' "$exit_code"
        awk -F '\t' '
            NR == 1 { next }
            {
                samples++
                cpu_sum += $4
                if ($4 > cpu_max) cpu_max = $4
                if ($5 > rss_max) rss_max = $5
                gpu_sum += $8
                if ($9 > gpu_max) gpu_max = $9
                if ($10 > gpu_memory_max) gpu_memory_max = $10
                if ($11 > tree_gpu_memory_max) tree_gpu_memory_max = $11
                if ($6 > load1_max) load1_max = $6
                if (samples == 1 || $7 < memory_available_min) memory_available_min = $7
            }
            END {
                printf "resource_samples=%d\n", samples
                printf "tree_cpu_average_percent=%.3f\n", samples ? cpu_sum / samples : 0
                printf "tree_cpu_peak_percent=%.3f\n", cpu_max + 0
                printf "tree_rss_peak_mib=%.3f\n", rss_max + 0
                printf "system_load1_peak=%.3f\n", load1_max + 0
                printf "system_memory_available_min_mib=%.3f\n", memory_available_min + 0
                printf "system_gpu_average_util_percent=%.3f\n", samples ? gpu_sum / samples : 0
                printf "system_gpu_peak_util_percent=%.3f\n", gpu_max + 0
                printf "system_gpu_memory_used_peak_mib=%.3f\n", gpu_memory_max + 0
                printf "process_tree_gpu_memory_peak_mib=%.3f\n", tree_gpu_memory_max + 0
            }
        ' "$samples_file"
    } > "$summary_file"

    {
        printf 'scope\tphase\tcalls\tsummed_duration_seconds\tmax_single_duration_seconds\n'
        awk -F '\t' '
            NR == 1 { next }
            {
                key = $1 SUBSEP $2
                count[key]++
                sum[key] += $6
                if ($6 > max[key]) max[key] = $6
            }
            END {
                for (key in count) {
                    split(key, parts, SUBSEP)
                    printf "%s\t%s\t%d\t%.3f\t%.3f\n",
                        parts[1], parts[2], count[key], sum[key] / 1000, max[key] / 1000
                }
            }
        ' "$phases_file" | sort
    } > "$stages_file"
}

export -f metrics_enabled metrics_now_ns metrics_sanitize_field
export -f metrics_initialize metrics_phase_begin metrics_phase_end
