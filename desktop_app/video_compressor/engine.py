from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import (
    ENCODE_TEMP_SUFFIX,
    LOW_BITRATE_THRESHOLD,
    MAX_PACKET_DIFFERENCE,
    RESTORE_TEMP_SUFFIX,
    CompressionSettings,
    required_free_bytes,
)
from .database import (
    BLOCKED_IN_USE,
    BROKEN_SOURCE,
    COMPLETED,
    COMPRESSING,
    COPYING_BACK,
    FAILED,
    PENDING,
    PROBING,
    READY_TO_REPLACE,
    RECOVERABLE_STATUSES,
    REPLACING,
    SKIPPED_LOW_BITRATE,
    STAGED_READY,
    VERIFYING,
    WAITING_REPLACE,
    TaskDatabase,
    TaskRecord,
)
from .media import MediaCancelled, MediaError, MediaTools, ProbeResult
from .platform_utils import (
    available_bytes,
    can_write_directory,
    is_file_in_use,
    restore_file_times,
    safe_unlink,
    same_filesystem,
    sync_file,
)
from .reporting import write_report


class EnginePaused(RuntimeError):
    pass


class StorageUnavailable(EnginePaused):
    pass


class ReplacementBlocked(EnginePaused):
    pass


class StagingRequired(EnginePaused):
    pass


@dataclass(frozen=True)
class BatchResult:
    completed: int
    skipped: int
    failed: int
    blocked: int
    stopped: bool
    report_path: Path


class CompressionEngine:
    def __init__(
        self,
        source_root: Path,
        database: TaskDatabase,
        media: MediaTools,
        settings: CompressionSettings,
        staging_dir: Optional[Path] = None,
        stop_event: Optional[threading.Event] = None,
        on_event: Optional[Callable[[str, dict[str, object]], None]] = None,
    ):
        self.source_root = source_root.resolve()
        self.database = database
        self.media = media
        self.settings = settings
        self.staging_dir = staging_dir.resolve() if staging_dir else None
        self.stop_event = stop_event or threading.Event()
        self.on_event = on_event or (lambda _name, _data: None)

    def emit(self, name: str, **data: object) -> None:
        self.on_event(name, data)

    def request_stop(self) -> None:
        self.stop_event.set()
        self.media.cancel_active()

    def _source_path(self, task: TaskRecord) -> Path:
        return self.source_root / Path(task.relative_path)

    def _task_log(self, task: TaskRecord) -> Path:
        digest = hashlib.sha256(task.relative_path.encode("utf-8")).hexdigest()[:12]
        return self.database.logs_dir / f"{task.id}_{digest}.log"

    def _external_temp(self, task: TaskRecord) -> Path:
        if self.staging_dir is None:
            raise StagingRequired("源位置空间不足，请选择空间充足的本地临时目录。")
        work_dir = self.staging_dir / ".video-compressor-staging"
        work_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(task.relative_path.encode("utf-8")).hexdigest()[:16]
        return work_dir / f"{task.id}_{digest}{ENCODE_TEMP_SUFFIX}"

    def _same_volume_temp(self, task: TaskRecord, source: Path) -> Path:
        digest = hashlib.sha256(task.relative_path.encode("utf-8")).hexdigest()[:12]
        return source.parent / f".vc_{task.id}_{digest}{ENCODE_TEMP_SUFFIX}"

    def _restore_partial(self, task: TaskRecord, source: Path) -> Path:
        digest = hashlib.sha256(task.relative_path.encode("utf-8")).hexdigest()[:12]
        return source.parent / f".vc_restore_{task.id}_{digest}{RESTORE_TEMP_SUFFIX}"

    def _cleanup_external_parent(self, temp: Path) -> None:
        if temp.parent.name != ".video-compressor-staging":
            return
        try:
            temp.parent.rmdir()
        except OSError:
            pass

    def _select_temp(self, task: TaskRecord, source: Path) -> tuple[Path, bool]:
        required = required_free_bytes(task.source_size)
        if available_bytes(source.parent) >= required:
            return self._same_volume_temp(task, source), False
        if self.staging_dir is None:
            raise StagingRequired("源位置空间不足，请选择空间充足的本地临时目录。")
        if not can_write_directory(self.staging_dir):
            raise StagingRequired("选择的临时目录不存在或不可写。")
        if same_filesystem(source.parent, self.staging_dir):
            raise StagingRequired("临时目录与源文件位于同一存储卷，无法解决空间不足。")
        if available_bytes(self.staging_dir) < required:
            raise StagingRequired("选择的临时目录剩余空间仍然不足。")
        return self._external_temp(task), True

    def _validate_output(self, source_probe: ProbeResult, output_path: Path) -> ProbeResult:
        output_probe = self.media.probe(output_path, self.stop_event)
        packet_difference = abs(source_probe.packets - output_probe.packets)
        if packet_difference > MAX_PACKET_DIFFERENCE:
            raise MediaError(
                f"视频包数差异过大：{source_probe.packets} -> {output_probe.packets}，"
                f"允许值为 {MAX_PACKET_DIFFERENCE}"
            )
        return output_probe

    def _restore_times(self, task: TaskRecord, path: Path) -> None:
        try:
            restore_file_times(
                path,
                task.source_atime_ns,
                task.source_mtime_ns,
                task.source_birthtime_ns,
            )
        except OSError as exc:
            self.emit("log", message=f"无法恢复文件时间：{path.name}：{exc}")

    def _lightweight_open_check(self, path: Path) -> None:
        with path.open("rb") as handle:
            if not handle.read(16):
                raise MediaError("替换后的文件为空")

    def _source_is_original(self, task: TaskRecord, source: Path) -> bool:
        if not source.is_file():
            return False
        stat = source.stat()
        return stat.st_size == task.source_size and stat.st_mtime_ns == task.source_mtime_ns

    def _finalize_same_volume(self, task: TaskRecord, source: Path, temp: Path) -> None:
        if not self._source_is_original(task, source):
            self.database.update(task.id, WAITING_REPLACE, error="压缩期间原文件发生变化或不可访问")
            raise StorageUnavailable("压缩期间原文件发生变化或不可访问，已保留验证通过的临时文件。")
        self.database.update(task.id, READY_TO_REPLACE, temp_path=str(temp), temp_external=False)
        self.database.update(task.id, REPLACING)
        try:
            os.replace(str(temp), str(source))
        except PermissionError as exc:
            self.database.update(task.id, WAITING_REPLACE, error=str(exc))
            raise ReplacementBlocked(
                f"{task.relative_path} 正被其他程序占用。已保留校验通过的临时文件，任务已暂停。"
            ) from exc
        except OSError as exc:
            self.database.update(task.id, WAITING_REPLACE, error=str(exc))
            raise StorageUnavailable(f"替换原文件失败：{exc}") from exc
        try:
            self._restore_times(task, source)
            self._lightweight_open_check(source)
        except (OSError, MediaError) as exc:
            self.database.update(task.id, REPLACING, error=str(exc))
            raise StorageUnavailable(
                "文件替换已执行，但替换后确认失败。任务已暂停，重启后会优先恢复检查。"
            ) from exc
        self.database.update(task.id, COMPLETED, temp_path=None, error=None)

    def _copy_with_progress(self, source: Path, destination: Path, task: TaskRecord) -> None:
        total = max(1, source.stat().st_size)
        copied = 0
        with source.open("rb") as input_handle, destination.open("wb") as output_handle:
            while True:
                if self.stop_event.is_set():
                    raise MediaCancelled("操作已停止")
                chunk = input_handle.read(8 * 1024 * 1024)
                if not chunk:
                    break
                output_handle.write(chunk)
                copied += len(chunk)
                self.emit(
                    "progress",
                    task_id=task.id,
                    relative_path=task.relative_path,
                    phase="copying_back",
                    fraction=min(1.0, copied / total),
                )
            output_handle.flush()
            os.fsync(output_handle.fileno())

    def _finalize_external(
        self,
        task: TaskRecord,
        source: Path,
        temp: Path,
        source_probe: ProbeResult,
        output_probe: ProbeResult,
    ) -> None:
        self.database.update(task.id, STAGED_READY, temp_path=str(temp), temp_external=True)
        source_may_already_be_removed = task.status in {
            STAGED_READY,
            COPYING_BACK,
            REPLACING,
            WAITING_REPLACE,
        }
        if not source.exists() and not source_may_already_be_removed:
            raise StorageUnavailable("原文件在压缩期间消失，本地压缩副本已保留，任务已暂停。")
        if source.exists():
            if not self._source_is_original(task, source):
                raise StorageUnavailable("压缩期间原文件发生变化，已停止替换。")
            capacity_after_delete = available_bytes(source.parent) + task.source_size
            if temp.stat().st_size > capacity_after_delete:
                raise StorageUnavailable("即使释放原文件空间，源位置仍放不下压缩结果。")
            try:
                source.unlink()
            except PermissionError as exc:
                self.database.update(task.id, WAITING_REPLACE, error=str(exc))
                raise ReplacementBlocked(
                    f"{task.relative_path} 正被其他程序占用。本地压缩副本已保留，任务已暂停。"
                ) from exc
        partial = self._restore_partial(task, source)
        self.database.update(task.id, COPYING_BACK, error=None)
        safe_unlink(partial)
        try:
            self._copy_with_progress(temp, partial, task)
            copied_probe = self._validate_output(source_probe, partial)
            if copied_probe.packets != output_probe.packets:
                raise MediaError("复制回源位置后的包数与已验证压缩文件不一致")
            self.database.update(task.id, REPLACING)
            os.replace(str(partial), str(source))
            self._restore_times(task, source)
            self._lightweight_open_check(source)
            self.database.update(task.id, COMPLETED, temp_path=None, error=None)
            safe_unlink(temp)
            self._cleanup_external_parent(temp)
        except MediaCancelled:
            safe_unlink(partial)
            raise
        except PermissionError as exc:
            self.database.update(task.id, WAITING_REPLACE, error=str(exc))
            raise ReplacementBlocked(
                f"无法写回 {task.relative_path}。本地压缩副本已保留，任务已暂停。"
            ) from exc
        except (OSError, MediaError) as exc:
            safe_unlink(partial)
            self.database.update(task.id, STAGED_READY, error=str(exc))
            raise StorageUnavailable(
                f"写回源位置失败，本地压缩副本已保留：{exc}"
            ) from exc

    def _recover_task(self, task: TaskRecord) -> None:
        source = self._source_path(task)
        temp = Path(task.temp_path) if task.temp_path else None

        if task.status in {PROBING, COMPRESSING, VERIFYING}:
            if temp is not None:
                safe_unlink(temp)
            self.database.update(task.id, PENDING, temp_path=None, error="上次运行中断，重新处理")
            return

        if task.status in {READY_TO_REPLACE, REPLACING, WAITING_REPLACE} and not task.temp_external:
            if temp is not None and temp.exists() and source.exists():
                if not self._source_is_original(task, source):
                    if task.output_size is not None and source.stat().st_size == task.output_size:
                        recovered_probe = self.media.probe(source, self.stop_event)
                        if recovered_probe.packets == task.output_packets:
                            self._restore_times(task, source)
                            self.database.update(task.id, COMPLETED, temp_path=None, error=None)
                            safe_unlink(temp)
                            return
                    raise StorageUnavailable(
                        f"原文件在中断后发生变化，拒绝自动替换：{task.relative_path}"
                    )
                self._finalize_same_volume(task, source, temp)
                return
            if source.exists() and task.output_size is not None and source.stat().st_size == task.output_size:
                self._restore_times(task, source)
                self.database.update(task.id, COMPLETED, temp_path=None, error=None)
                return
            self.database.update(task.id, PENDING, temp_path=None, error="替换恢复信息不完整，重新处理")
            return

        if task.status in {STAGED_READY, COPYING_BACK, REPLACING, WAITING_REPLACE} and task.temp_external:
            if temp is None or not temp.exists():
                if source.exists() and task.output_size is not None and source.stat().st_size == task.output_size:
                    self.database.update(task.id, COMPLETED, temp_path=None, error=None)
                    return
                raise StorageUnavailable(f"找不到用于恢复的本地压缩文件：{task.relative_path}")
            if source.exists() and task.output_size is not None and source.stat().st_size == task.output_size:
                try:
                    recovered_probe = self.media.probe(source, self.stop_event)
                except MediaError:
                    recovered_probe = None
                if recovered_probe is not None and recovered_probe.packets == task.output_packets:
                    self._restore_times(task, source)
                    self.database.update(task.id, COMPLETED, temp_path=None, error=None)
                    safe_unlink(temp)
                    self._cleanup_external_parent(temp)
                    return
            if task.source_packets is None or task.output_packets is None:
                raise StorageUnavailable(f"恢复记录缺少视频校验信息：{task.relative_path}")
            source_probe = ProbeResult(
                task.source_packets,
                task.source_bitrate or 0,
                task.source_duration or 0,
                0,
                0,
            )
            output_probe = ProbeResult(
                task.output_packets,
                task.output_bitrate or 0,
                task.source_duration or 0,
                0,
                0,
            )
            self._finalize_external(task, source, temp, source_probe, output_probe)

    def recover(self) -> None:
        for task in self.database.list_tasks(RECOVERABLE_STATUSES):
            if self.stop_event.is_set():
                return
            self.emit("status", task_id=task.id, relative_path=task.relative_path, status="recovering")
            self._recover_task(task)

    def _process_task(self, task: TaskRecord) -> None:
        source = self._source_path(task)
        if not source.is_file():
            self.database.update(task.id, FAILED, error="源文件不存在")
            return
        if is_file_in_use(source):
            self.database.update(task.id, BLOCKED_IN_USE, error="文件正被其他程序占用")
            self.emit("blocked", task_id=task.id, relative_path=task.relative_path)
            return
        current_stat = source.stat()
        if current_stat.st_size != task.source_size or current_stat.st_mtime_ns != task.source_mtime_ns:
            self.database.update(task.id, BLOCKED_IN_USE, error="文件在扫描后发生变化")
            self.emit("blocked", task_id=task.id, relative_path=task.relative_path)
            return

        temp, external = self._select_temp(task, source)
        safe_unlink(temp)
        self.database.increment_attempts(task.id)
        self.database.update(
            task.id,
            PROBING,
            temp_path=str(temp),
            temp_external=external,
            error=None,
        )
        self.emit("status", task_id=task.id, relative_path=task.relative_path, status=PROBING)
        try:
            source_probe = self.media.probe(source, self.stop_event)
        except MediaCancelled:
            self.database.update(task.id, PENDING, temp_path=None, error="用户停止")
            raise
        except MediaError as exc:
            self.database.update(task.id, BROKEN_SOURCE, temp_path=None, error=str(exc))
            self.emit("log", message=f"损坏或无法读取：{task.relative_path}：{exc}")
            return

        self.database.update(
            task.id,
            source_packets=source_probe.packets,
            source_bitrate=source_probe.bitrate,
            source_duration=source_probe.duration,
        )
        if 0 < source_probe.bitrate < LOW_BITRATE_THRESHOLD:
            self.database.update(
                task.id,
                SKIPPED_LOW_BITRATE,
                temp_path=None,
                output_size=task.source_size,
                output_packets=source_probe.packets,
                output_bitrate=source_probe.bitrate,
                error=None,
            )
            self.emit("log", message=f"低于 70 Mbps，跳过：{task.relative_path}")
            return

        self.database.update(task.id, COMPRESSING)
        self.emit("status", task_id=task.id, relative_path=task.relative_path, status=COMPRESSING)
        try:
            self.media.encode(
                source,
                temp,
                self.settings,
                self._task_log(task),
                self.stop_event,
                lambda fraction: self.emit(
                    "progress",
                    task_id=task.id,
                    relative_path=task.relative_path,
                    phase=COMPRESSING,
                    fraction=fraction,
                ),
                source_probe.duration,
            )
            sync_file(temp)
            self.database.update(task.id, VERIFYING)
            self.emit("status", task_id=task.id, relative_path=task.relative_path, status=VERIFYING)
            output_probe = self._validate_output(source_probe, temp)
            output_size = temp.stat().st_size
            self.database.update(
                task.id,
                output_size=output_size,
                output_packets=output_probe.packets,
                output_bitrate=output_probe.bitrate,
            )
            if self.stop_event.is_set():
                raise MediaCancelled("操作已停止")
            refreshed = self.database.get(task.id)
            if external:
                self._finalize_external(refreshed, source, temp, source_probe, output_probe)
            else:
                self._finalize_same_volume(refreshed, source, temp)
            self.emit("status", task_id=task.id, relative_path=task.relative_path, status=COMPLETED)
        except MediaCancelled:
            if self.database.get(task.id).status not in {STAGED_READY, COPYING_BACK, REPLACING}:
                safe_unlink(temp)
                self.database.update(task.id, PENDING, temp_path=None, error="用户停止")
            raise
        except ReplacementBlocked:
            raise
        except StorageUnavailable:
            raise
        except (MediaError, OSError) as exc:
            safe_unlink(temp)
            if external:
                self._cleanup_external_parent(temp)
            self.database.update(task.id, FAILED, temp_path=None, error=str(exc))
            self.emit("log", message=f"处理失败：{task.relative_path}：{exc}")

    def run(self) -> BatchResult:
        self.recover()
        work_statuses = {PENDING, FAILED, BLOCKED_IN_USE, BROKEN_SOURCE}
        tasks = self.database.list_tasks(work_statuses)
        total = len(tasks)
        self.emit("batch_started", total=total, total_bytes=sum(task.source_size for task in tasks))
        for index, task in enumerate(tasks, start=1):
            if self.stop_event.is_set():
                break
            self.emit(
                "batch_progress",
                current=index,
                total=total,
                relative_path=task.relative_path,
            )
            started = time.monotonic()
            self._process_task(task)
            refreshed = self.database.get(task.id)
            self.emit(
                "task_finished",
                task_id=task.id,
                status=refreshed.status,
                source_bytes=task.source_size,
                elapsed_seconds=time.monotonic() - started,
            )

        report = write_report(self.database)
        counts = self.database.counts()
        return BatchResult(
            completed=counts.get(COMPLETED, 0),
            skipped=counts.get(SKIPPED_LOW_BITRATE, 0),
            failed=counts.get(FAILED, 0) + counts.get(BROKEN_SOURCE, 0),
            blocked=counts.get(BLOCKED_IN_USE, 0) + counts.get(WAITING_REPLACE, 0),
            stopped=self.stop_event.is_set(),
            report_path=report,
        )
