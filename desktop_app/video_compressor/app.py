from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import __version__
from .config import APP_NAME, CompressionSettings, CpuMode, encoder_threads, logical_cpu_count
from .database import (
    BLOCKED_IN_USE,
    BROKEN_SOURCE,
    COMPLETED,
    COMPRESSING,
    COPYING_BACK,
    FAILED,
    PENDING,
    PROBING,
    REPLACING,
    SKIPPED_LOW_BITRATE,
    VERIFYING,
    WAITING_REPLACE,
    TaskDatabase,
)
from .engine import (
    CompressionEngine,
    EnginePaused,
    ReplacementBlocked,
    StagingRequired,
    StorageUnavailable,
)
from .media import MediaCancelled, MediaTools
from .platform_utils import format_bytes, same_filesystem
from .scanner import ScanSummary, scan_videos


STATUS_TEXT = {
    PENDING: "等待处理",
    PROBING: "检查源视频",
    COMPRESSING: "压缩中",
    VERIFYING: "校验中",
    REPLACING: "替换中",
    COPYING_BACK: "写回源位置",
    COMPLETED: "已完成",
    SKIPPED_LOW_BITRATE: "低码率跳过",
    BROKEN_SOURCE: "源视频异常",
    BLOCKED_IN_USE: "文件被占用",
    WAITING_REPLACE: "等待替换",
    FAILED: "失败",
}


class CompressorApp:
    POLL_INTERVAL_MS = 100

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {__version__}")
        self.root.geometry("980x720")
        self.root.minsize(820, 620)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.event_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.engine: Optional[CompressionEngine] = None
        self.database: Optional[TaskDatabase] = None
        self.scan_summary: Optional[ScanSummary] = None
        self.closing = False
        self.task_rows: dict[int, str] = {}
        self.current_batch_index = 0
        self.current_batch_total = 0
        self.run_total_bytes = 0
        self.run_finished_bytes = 0
        self.eta_model_bytes = 0
        self.eta_model_seconds = 0.0

        self.source_var = tk.StringVar()
        self.staging_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=CpuMode.BALANCED.display_name)
        self.summary_var = tk.StringVar(value="请选择包含 MP4 视频的目录。")
        self.space_var = tk.StringVar(value="尚未检查空间。")
        self.cpu_var = tk.StringVar()
        self.eta_var = tk.StringVar(value="预计耗时：完成首个视频后，根据当前电脑实测更新。")
        self.current_var = tk.StringVar(value="尚未开始")
        self.overall_var = tk.StringVar(value="0 / 0")

        self._configure_style()
        self._build_ui()
        self._update_cpu_description()
        self.root.after(self.POLL_INTERVAL_MS, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "aqua" in available:
            style.theme_use("aqua")
        elif "clam" in available:
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Hint.TLabel", foreground="#555555")
        style.configure("Warning.TLabel", foreground="#a33a00")
        style.configure("Status.TLabel", font=("TkDefaultFont", 11, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="航拍视频压缩工具", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="保持原分辨率与帧率，使用 libx264 / preset fast / CRF 18，仅保留第一路视频画面。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        source_box = ttk.LabelFrame(outer, text="1. 选择视频目录", padding=12)
        source_box.pack(fill="x")
        source_row = ttk.Frame(source_box)
        source_row.pack(fill="x")
        ttk.Entry(source_row, textvariable=self.source_var).pack(side="left", fill="x", expand=True)
        ttk.Button(source_row, text="浏览…", command=self._choose_source).pack(side="left", padx=(8, 0))
        self.scan_button = ttk.Button(source_row, text="扫描", command=self._scan)
        self.scan_button.pack(side="left", padx=(8, 0))
        self.clean_button = ttk.Button(source_row, text="清理记录", command=self._clean_state)
        self.clean_button.pack(side="left", padx=(8, 0))
        ttk.Label(source_box, textvariable=self.summary_var, style="Hint.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        self.space_label = ttk.Label(source_box, textvariable=self.space_var)
        self.space_label.pack(anchor="w", pady=(3, 0))
        ttk.Label(source_box, textvariable=self.eta_var, style="Hint.TLabel").pack(anchor="w", pady=(3, 0))

        settings_box = ttk.LabelFrame(outer, text="2. 运行设置", padding=12)
        settings_box.pack(fill="x", pady=(12, 0))
        mode_row = ttk.Frame(settings_box)
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="CPU 档位：").pack(side="left")
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.mode_var,
            values=[mode.display_name for mode in CpuMode],
            state="readonly",
            width=10,
        )
        mode_combo.pack(side="left")
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_cpu_description())
        ttk.Label(mode_row, textvariable=self.cpu_var, style="Hint.TLabel").pack(side="left", padx=(10, 0))

        staging_row = ttk.Frame(settings_box)
        staging_row.pack(fill="x", pady=(10, 0))
        ttk.Label(staging_row, text="备用临时目录：").pack(side="left")
        ttk.Entry(staging_row, textvariable=self.staging_var).pack(side="left", fill="x", expand=True)
        ttk.Button(staging_row, text="浏览…", command=self._choose_staging).pack(side="left", padx=(8, 0))
        ttk.Label(
            settings_box,
            text="仅在源位置空间不足时使用；应选择另一个存储卷上空间充足的目录。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        progress_box = ttk.LabelFrame(outer, text="3. 压缩进度", padding=12)
        progress_box.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(progress_box, textvariable=self.current_var, style="Status.TLabel").pack(anchor="w")
        self.current_progress = ttk.Progressbar(progress_box, maximum=100, mode="determinate")
        self.current_progress.pack(fill="x", pady=(6, 3))
        overall_row = ttk.Frame(progress_box)
        overall_row.pack(fill="x")
        ttk.Label(overall_row, text="总体进度", style="Hint.TLabel").pack(side="left")
        ttk.Label(overall_row, textvariable=self.overall_var, style="Hint.TLabel").pack(side="right")
        self.overall_progress = ttk.Progressbar(progress_box, maximum=100, mode="determinate")
        self.overall_progress.pack(fill="x", pady=(3, 10))

        columns = ("status", "file", "size")
        self.task_tree = ttk.Treeview(progress_box, columns=columns, show="headings", height=9)
        self.task_tree.heading("status", text="状态")
        self.task_tree.heading("file", text="视频")
        self.task_tree.heading("size", text="原始大小")
        self.task_tree.column("status", width=120, stretch=False)
        self.task_tree.column("file", width=570)
        self.task_tree.column("size", width=110, anchor="e", stretch=False)
        tree_scroll = ttk.Scrollbar(progress_box, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=tree_scroll.set)
        self.task_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(14, 0))
        self.start_button = ttk.Button(actions, text="开始压缩", command=self._start)
        self.start_button.pack(side="right")
        self.stop_button = ttk.Button(actions, text="停止", command=self._stop, state="disabled")
        self.stop_button.pack(side="right", padx=(0, 8))
        ttk.Label(
            actions,
            text="处理期间请勿移动、重命名或打开正在处理的视频，也不要断开文件所在的存储设备。",
            style="Warning.TLabel",
            wraplength=650,
        ).pack(side="left", anchor="w")

    def _mode(self) -> CpuMode:
        for mode in CpuMode:
            if mode.display_name == self.mode_var.get():
                return mode
        return CpuMode.BALANCED

    def _update_cpu_description(self) -> None:
        cpus = logical_cpu_count()
        threads = encoder_threads(self._mode(), cpus)
        self.cpu_var.set(f"检测到 {cpus} 个逻辑处理器；单视频使用 {threads} 个编码线程，并发固定为 1。")

    def _choose_source(self) -> None:
        selected = filedialog.askdirectory(title="选择包含 DJI MP4 视频的目录", mustexist=True)
        if selected:
            self.source_var.set(selected)
            self._scan()

    def _choose_staging(self) -> None:
        selected = filedialog.askdirectory(title="选择备用临时目录", mustexist=True)
        if selected:
            self.staging_var.set(selected)

    def _source_path(self) -> Optional[Path]:
        raw = self.source_var.get().strip()
        return Path(raw).expanduser() if raw else None

    def _scan(self) -> bool:
        if self.worker and self.worker.is_alive():
            return False
        source = self._source_path()
        if source is None or not source.is_dir():
            messagebox.showerror("目录无效", "请选择一个存在的视频目录。")
            return False
        try:
            summary = scan_videos(source)
            database = TaskDatabase(source)
            database.register_files(summary.paths)
        except OSError as exc:
            messagebox.showerror("扫描失败", f"无法扫描所选目录：\n{exc}")
            return False

        self.scan_summary = summary
        self.database = database
        self.summary_var.set(
            f"发现 {len(summary.paths)} 个 MP4；输入 {format_bytes(summary.total_bytes)}；"
            f"预计输出约 {format_bytes(summary.estimated_output_bytes)}。"
        )
        if summary.needs_external_staging:
            self.space_var.set(
                f"空间不足：当前可用 {format_bytes(summary.available_bytes)}，"
                f"建议至少 {format_bytes(summary.required_free_bytes)}；开始前请选择备用临时目录。"
            )
            self.space_label.configure(style="Warning.TLabel")
        else:
            self.space_var.set(
                f"空间检查通过：当前可用 {format_bytes(summary.available_bytes)}，"
                f"最低建议 {format_bytes(summary.required_free_bytes)}。"
            )
            self.space_label.configure(style="Hint.TLabel")
        self._refresh_task_tree()
        return True

    def _refresh_task_tree(self) -> None:
        if self.database is None:
            return
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        self.task_rows.clear()
        for task in self.database.list_tasks():
            item = self.task_tree.insert(
                "",
                "end",
                values=(STATUS_TEXT.get(task.status, task.status), task.relative_path, format_bytes(task.source_size)),
            )
            self.task_rows[task.id] = item

    def _clean_state(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("任务运行中", "请先停止当前任务，再清理任务记录。")
            return
        source = self._source_path()
        if source is None:
            return
        database = self.database
        if database is None:
            state_dir = source / ".video-compressor"
            if not state_dir.is_dir():
                messagebox.showinfo("没有记录", "当前目录没有任务记录。")
                return
        else:
            state_dir = database.state_dir
            unsafe = {
                "compressing",
                "verifying",
                "ready_to_replace",
                "staged_ready",
                "copying_back",
                "replacing",
                "waiting_replace",
            }
            if database.list_tasks(unsafe):
                messagebox.showerror(
                    "不能清理",
                    "仍有等待恢复或替换的文件。请先恢复任务，避免丢失已完成的临时压缩结果。",
                )
                return
        if not messagebox.askyesno(
            "清理任务记录",
            "这会删除 SQLite 状态、日志和报告。清理后，软件将不再知道哪些视频已经处理；"
            "如果重新扫描同一目录，可能再次压缩视频。\n\n确认删除？",
        ):
            return
        try:
            shutil.rmtree(state_dir)
        except OSError as exc:
            messagebox.showerror("清理失败", str(exc))
            return
        self.database = None
        self.scan_summary = None
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        self.task_rows.clear()
        self.summary_var.set("任务记录已清理。重新扫描前请确认不会重复压缩已处理视频。")
        self.space_var.set("尚未重新检查空间。")

    def _ensure_staging_if_needed(self, source: Path) -> Optional[Path]:
        assert self.scan_summary is not None
        raw = self.staging_var.get().strip()
        staging = Path(raw).expanduser() if raw else None
        if not self.scan_summary.needs_external_staging:
            return staging
        if staging is None:
            selected = filedialog.askdirectory(
                title="源位置空间不足，请选择另一个存储卷上的临时目录", mustexist=True
            )
            if not selected:
                messagebox.showwarning(
                    "需要临时目录",
                    "源位置空间不足。为了保留原视频，必须选择一个空间充足的备用临时目录。",
                )
                return None
            staging = Path(selected)
            self.staging_var.set(str(staging))
        try:
            if same_filesystem(source, staging):
                messagebox.showerror(
                    "临时目录无效",
                    "备用临时目录与源视频位于同一存储卷，无法解决空间不足。请改选其他磁盘。",
                )
                return None
        except OSError as exc:
            messagebox.showerror("临时目录无效", str(exc))
            return None
        return staging

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self._scan():
            return
        assert self.scan_summary is not None
        assert self.database is not None
        if not self.scan_summary.paths and not self.database.list_tasks():
            messagebox.showinfo("没有视频", "所选目录中没有找到 MP4 视频。")
            return
        source = self._source_path()
        assert source is not None
        staging = self._ensure_staging_if_needed(source)
        if self.scan_summary.needs_external_staging and staging is None:
            return
        if not messagebox.askokcancel(
            "开始压缩",
            "软件将逐个压缩并替换原视频。\n\n"
            "请关闭播放器、剪辑软件和文件预览窗口；处理期间不要移动文件或断开其所在存储设备。\n\n"
            "是否开始？",
        ):
            return

        try:
            media = MediaTools()
        except FileNotFoundError as exc:
            messagebox.showerror("缺少组件", str(exc))
            return
        self.stop_event = threading.Event()
        self.engine = CompressionEngine(
            source_root=source,
            database=self.database,
            media=media,
            settings=CompressionSettings(mode=self._mode()),
            staging_dir=staging,
            stop_event=self.stop_event,
            on_event=lambda name, data: self.event_queue.put((name, data)),
        )
        self.current_progress["value"] = 0
        self.overall_progress["value"] = 0
        self.run_total_bytes = 0
        self.run_finished_bytes = 0
        self.eta_model_bytes = 0
        self.eta_model_seconds = 0.0
        self.eta_var.set("预计耗时：完成首个视频后，根据当前电脑实测更新。")
        self.start_button.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self.clean_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.current_var.set("正在准备任务…")
        self.worker = threading.Thread(target=self._run_engine, name="compression-worker", daemon=True)
        self.worker.start()

    def _run_engine(self) -> None:
        assert self.engine is not None
        try:
            result = self.engine.run()
            self.event_queue.put(("complete", {"result": result}))
        except MediaCancelled:
            self.event_queue.put(("stopped", {}))
        except ReplacementBlocked as exc:
            self.event_queue.put(("paused", {"message": str(exc), "kind": "occupied"}))
        except StagingRequired as exc:
            self.event_queue.put(("paused", {"message": str(exc), "kind": "staging"}))
        except StorageUnavailable as exc:
            self.event_queue.put(("paused", {"message": str(exc), "kind": "storage"}))
        except EnginePaused as exc:
            self.event_queue.put(("paused", {"message": str(exc), "kind": "general"}))
        except Exception as exc:
            self.event_queue.put(("fatal", {"message": f"未预期错误：{exc}"}))

    def _stop(self) -> None:
        if self.engine is None:
            return
        if messagebox.askyesno("停止任务", "停止后，当前视频下次需要从头压缩。是否停止？"):
            self.current_var.set("正在安全停止…")
            self.stop_button.configure(state="disabled")
            self.engine.request_stop()

    def _set_task_status(self, task_id: int, status: str) -> None:
        item = self.task_rows.get(task_id)
        if item is None or not self.task_tree.exists(item):
            return
        values = list(self.task_tree.item(item, "values"))
        values[0] = STATUS_TEXT.get(status, status)
        self.task_tree.item(item, values=values)
        self.task_tree.see(item)

    def _format_duration(self, seconds: float) -> str:
        total_minutes = max(0, int(round(seconds / 60)))
        days, remaining_minutes = divmod(total_minutes, 24 * 60)
        hours, minutes = divmod(remaining_minutes, 60)
        if days:
            return f"约 {days} 天 {hours} 小时"
        if hours:
            return f"约 {hours} 小时 {minutes} 分钟"
        return f"约 {max(1, minutes)} 分钟"

    def _handle_event(self, name: str, data: dict[str, object]) -> None:
        if name == "status":
            task_id = int(data.get("task_id", 0))
            status = str(data.get("status", ""))
            relative = str(data.get("relative_path", ""))
            self._set_task_status(task_id, status)
            self.current_var.set(f"{STATUS_TEXT.get(status, status)}：{relative}")
        elif name == "blocked":
            self._set_task_status(int(data.get("task_id", 0)), BLOCKED_IN_USE)
        elif name == "progress":
            fraction = float(data.get("fraction", 0.0))
            self.current_progress["value"] = fraction * 100
            if self.current_batch_total:
                overall = ((self.current_batch_index - 1) + fraction) / self.current_batch_total
                self.overall_progress["value"] = max(0, min(100, overall * 100))
        elif name == "batch_progress":
            self.current_batch_index = int(data.get("current", 0))
            self.current_batch_total = int(data.get("total", 0))
            self.overall_var.set(f"{self.current_batch_index} / {self.current_batch_total}")
            self.current_progress["value"] = 0
        elif name == "batch_started":
            self.run_total_bytes = int(data.get("total_bytes", 0))
        elif name == "task_finished":
            source_bytes = int(data.get("source_bytes", 0))
            elapsed = float(data.get("elapsed_seconds", 0.0))
            status = str(data.get("status", ""))
            self.run_finished_bytes += source_bytes
            if status == COMPLETED and source_bytes > 0 and elapsed > 0:
                self.eta_model_bytes += source_bytes
                self.eta_model_seconds += elapsed
            remaining = max(0, self.run_total_bytes - self.run_finished_bytes)
            if self.eta_model_bytes > 0 and remaining > 0:
                eta = remaining * self.eta_model_seconds / self.eta_model_bytes
                self.eta_var.set(f"预计剩余耗时：{self._format_duration(eta)}（按本机已完成视频估算）")
            elif remaining == 0:
                self.eta_var.set("预计剩余耗时：即将完成")
        elif name == "log":
            self.current_var.set(str(data.get("message", "")))
        elif name == "complete":
            result = data["result"]
            self._finish_running_state()
            self._refresh_task_tree()
            self.current_progress["value"] = 100
            self.overall_progress["value"] = 100
            self.current_var.set("任务完成")
            messagebox.showinfo(
                "压缩完成",
                f"已完成：{result.completed}\n"
                f"低码率跳过：{result.skipped}\n"
                f"失败：{result.failed}\n"
                f"文件占用：{result.blocked}\n\n"
                f"报告：{result.report_path}",
            )
        elif name == "stopped":
            self._finish_running_state()
            self._refresh_task_tree()
            self.current_var.set("任务已停止；下次将从未完成的视频继续。")
        elif name == "paused":
            self._finish_running_state()
            self._refresh_task_tree()
            self.current_var.set("任务已安全暂停")
            messagebox.showwarning(
                "任务已暂停",
                f"{data.get('message', '')}\n\n恢复文件或存储路径后，再次点击“开始压缩”即可继续。",
            )
        elif name == "fatal":
            self._finish_running_state()
            self._refresh_task_tree()
            self.current_var.set("任务异常停止")
            messagebox.showerror("程序错误", str(data.get("message", "")))

    def _finish_running_state(self) -> None:
        self.start_button.configure(state="normal")
        self.scan_button.configure(state="normal")
        self.clean_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.engine = None

    def _poll_events(self) -> None:
        try:
            while True:
                name, data = self.event_queue.get_nowait()
                self._handle_event(name, data)
        except queue.Empty:
            pass
        if self.closing:
            if self.worker is None or not self.worker.is_alive():
                self.root.destroy()
                return
        self.root.after(self.POLL_INTERVAL_MS, self._poll_events)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "退出软件", "当前任务仍在运行。退出后当前视频下次需要从头压缩，是否继续？"
            ):
                return
            self.closing = True
            if self.engine is not None:
                self.engine.request_stop()
            self.current_var.set("正在安全停止并退出…")
            return
        self.root.destroy()


def run_gui() -> None:
    root = tk.Tk()
    CompressorApp(root)
    root.mainloop()
