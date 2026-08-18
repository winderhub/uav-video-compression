#!/usr/bin/env bash

report_probe_bitrate() {
    local file="$1"
    local bitrate

    bitrate=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=bit_rate -of csv=p=0 "$file" 2>/dev/null || true)
    if [[ ! "$bitrate" =~ ^[0-9]+$ ]]; then
        bitrate=$(ffprobe -v error \
            -show_entries format=bit_rate -of csv=p=0 "$file" 2>/dev/null || true)
    fi

    if [[ "$bitrate" =~ ^[0-9]+$ ]]; then
        printf '%s' "$bitrate"
    fi
}

report_file_size() {
    local file="$1"
    stat -c '%s' -- "$file" 2>/dev/null || true
}

report_to_mbps() {
    local value="${1:-}"
    if [[ "$value" =~ ^[0-9]+$ ]]; then
        awk -v value="$value" 'BEGIN { printf "%.3f", value / 1000000 }'
    fi
}

report_to_mib() {
    local value="${1:-}"
    if [[ "$value" =~ ^-?[0-9]+$ ]]; then
        awk -v value="$value" 'BEGIN { printf "%.3f", value / 1048576 }'
    fi
}

report_sanitize_field() {
    printf '%s' "${1:-}" | tr '\t\r\n' '   '
}

report_init() {
    local report_dir="$1"
    local run_mode="$2"
    local timestamp

    mkdir -p "$report_dir"
    timestamp=$(date '+%Y%m%d_%H%M%S')
    REPORT_FILE="$report_dir/compression_report_${timestamp}_$$.tsv"
    REPORT_LOCK="$REPORT_FILE.lock"

    : > "$REPORT_FILE"
    : > "$REPORT_LOCK"
    {
        printf '# video_compression_report_version=1\n'
        printf '# run_mode=%s\n' "$run_mode"
        printf '# started_at=%s\n' "$(date '+%F %T %Z')"
        printf 'status\tsource_path\toutput_path\toriginal_bitrate_bps\toriginal_bitrate_mbps\tcompressed_bitrate_bps\tcompressed_bitrate_mbps\toriginal_size_bytes\toriginal_size_mib\tcompressed_size_bytes\tcompressed_size_mib\tsaved_bytes\tsaved_mib\tsaved_percent\tincluded_in_totals\tnote\n'
    } >> "$REPORT_FILE"

    export REPORT_FILE REPORT_LOCK
}

report_append() {
    local status="${1:-}"
    local source_path="${2:-}"
    local output_path="${3:-}"
    local source_bitrate="${4:-}"
    local output_bitrate="${5:-}"
    local source_size="${6:-}"
    local output_size="${7:-}"
    local included="${8:-no}"
    local note="${9:-}"
    local source_mbps output_mbps source_mib output_mib
    local saved_bytes saved_mib saved_percent

    source_mbps=$(report_to_mbps "$source_bitrate")
    output_mbps=$(report_to_mbps "$output_bitrate")
    source_mib=$(report_to_mib "$source_size")
    output_mib=$(report_to_mib "$output_size")

    saved_bytes=""
    saved_mib=""
    saved_percent=""
    if [[ "$included" == "yes" && "$source_size" =~ ^[0-9]+$ \
        && "$output_size" =~ ^[0-9]+$ ]]; then
        saved_bytes=$((source_size - output_size))
        saved_mib=$(report_to_mib "$saved_bytes")
        if (( source_size > 0 )); then
            saved_percent=$(awk -v source="$source_size" -v output="$output_size" \
                'BEGIN { printf "%.3f", (source - output) * 100 / source }')
        fi
    fi

    status=$(report_sanitize_field "$status")
    source_path=$(report_sanitize_field "$source_path")
    output_path=$(report_sanitize_field "$output_path")
    note=$(report_sanitize_field "$note")

    {
        flock -x 9
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$status" "$source_path" "$output_path" \
            "$source_bitrate" "$source_mbps" \
            "$output_bitrate" "$output_mbps" \
            "$source_size" "$source_mib" \
            "$output_size" "$output_mib" \
            "$saved_bytes" "$saved_mib" "$saved_percent" \
            "$included" "$note" >> "$REPORT_FILE"
    } 9>>"$REPORT_LOCK"
}

report_finalize() {
    local run_status="${1:-0}"

    awk -F '\t' -v run_status="$run_status" '
        /^#/ || $1 == "status" { next }
        {
            total_rows++
            status_count[$1]++
            if ($15 == "yes" && $8 ~ /^[0-9]+$/ && $10 ~ /^[0-9]+$/) {
                comparable++
                source_total += $8
                output_total += $10
            }
        }
        END {
            saved = source_total - output_total
            percent = source_total > 0 ? saved * 100 / source_total : 0
            print "# SUMMARY"
            printf "# finished_at=%s\n", strftime("%Y-%m-%d %H:%M:%S")
            printf "# run_exit_code=%s\n", run_status
            printf "# total_rows=%d\n", total_rows
            printf "# comparable_files=%d\n", comparable
            printf "# original_total_bytes=%.0f\n", source_total
            printf "# original_total_gib=%.6f\n", source_total / 1073741824
            printf "# compressed_total_bytes=%.0f\n", output_total
            printf "# compressed_total_gib=%.6f\n", output_total / 1073741824
            printf "# saved_total_bytes=%.0f\n", saved
            printf "# saved_total_gib=%.6f\n", saved / 1073741824
            printf "# saved_percent=%.3f\n", percent
            for (status in status_count) {
                printf "# status_%s=%d\n", status, status_count[status]
            }
        }
    ' "$REPORT_FILE" >> "$REPORT_FILE"

    rm -f "$REPORT_LOCK"
    printf '压缩报告: %s\n' "$REPORT_FILE"
}

export -f report_probe_bitrate report_file_size report_to_mbps report_to_mib
export -f report_sanitize_field report_append
