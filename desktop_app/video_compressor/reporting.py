from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .database import TaskDatabase


def write_report(database: TaskDatabase) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = database.reports_dir / f"compression_report_{timestamp}.tsv"
    fields = [
        "status",
        "relative_path",
        "original_bitrate_bps",
        "compressed_bitrate_bps",
        "original_size_bytes",
        "compressed_size_bytes",
        "saved_bytes",
        "saved_percent",
        "error",
    ]
    with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for task in database.list_tasks():
            saved = None
            percent = None
            if task.output_size is not None and task.source_size > 0:
                saved = task.source_size - task.output_size
                percent = round(saved * 100 / task.source_size, 3)
            writer.writerow(
                {
                    "status": task.status,
                    "relative_path": task.relative_path,
                    "original_bitrate_bps": task.source_bitrate or "",
                    "compressed_bitrate_bps": task.output_bitrate or "",
                    "original_size_bytes": task.source_size,
                    "compressed_size_bytes": task.output_size or "",
                    "saved_bytes": saved if saved is not None else "",
                    "saved_percent": percent if percent is not None else "",
                    "error": task.error or "",
                }
            )
    return report_path
