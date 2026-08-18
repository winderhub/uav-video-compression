from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import CompressionSettings


class MediaError(RuntimeError):
    pass


class MediaCancelled(MediaError):
    pass


@dataclass(frozen=True)
class ProbeResult:
    packets: int
    bitrate: int
    duration: float
    width: int
    height: int


def _bundled_binary(name: str) -> Optional[Path]:
    suffix = ".exe" if sys.platform == "win32" else ""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    candidates = [
        base / "resources" / f"{name}{suffix}",
        base / f"{name}{suffix}",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def discover_binary(name: str) -> Path:
    env_name = f"VIDEO_COMPRESSOR_{name.upper()}"
    configured = os.environ.get(env_name)
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    bundled = _bundled_binary(name)
    if bundled is not None:
        return bundled
    system_path = shutil.which(name)
    if system_path:
        return Path(system_path)
    raise FileNotFoundError(f"找不到 {name}，请重新安装软件或检查打包资源。")


class MediaTools:
    def __init__(self, ffmpeg: Optional[Path] = None, ffprobe: Optional[Path] = None):
        self.ffmpeg = ffmpeg or discover_binary("ffmpeg")
        self.ffprobe = ffprobe or discover_binary("ffprobe")
        self._active_lock = threading.Lock()
        self._active_process: Optional[subprocess.Popen[str]] = None

    def _popen_options(self) -> dict[str, object]:
        if sys.platform == "win32":
            return {"creationflags": subprocess.CREATE_NO_WINDOW}
        return {}

    def cancel_active(self) -> None:
        with self._active_lock:
            process = self._active_process
        if process is not None and process.poll() is None:
            process.terminate()

    def probe(self, path: Path, stop_event: Optional[threading.Event] = None) -> ProbeResult:
        command = [
            str(self.ffprobe),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_packets",
            "-show_entries",
            "stream=nb_read_packets,bit_rate,width,height,duration:format=bit_rate,duration",
            "-of",
            "json",
            str(path),
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **self._popen_options(),
        )
        with self._active_lock:
            self._active_process = process
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if stop_event is not None and stop_event.is_set():
                        process.terminate()
                        process.communicate()
                        raise MediaCancelled("操作已停止")
            if process.returncode != 0:
                raise MediaError(stderr.strip() or f"ffprobe 退出码 {process.returncode}")
        finally:
            with self._active_lock:
                self._active_process = None

        def integer_value(*values: object) -> int:
            for value in values:
                try:
                    return int(str(value))
                except (TypeError, ValueError):
                    continue
            return 0

        def float_value(*values: object) -> float:
            for value in values:
                try:
                    return float(str(value))
                except (TypeError, ValueError):
                    continue
            return 0.0

        try:
            data = json.loads(stdout)
            stream = data.get("streams", [])[0]
            container = data.get("format", {})
            packets = integer_value(stream.get("nb_read_packets"))
            bitrate = integer_value(stream.get("bit_rate"), container.get("bit_rate"))
            duration = float_value(stream.get("duration"), container.get("duration"))
            width = integer_value(stream.get("width"))
            height = integer_value(stream.get("height"))
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaError(f"无法解析视频信息：{exc}") from exc
        if packets <= 0:
            raise MediaError("没有可用的视频包")
        return ProbeResult(packets, bitrate, duration, width, height)

    def encode(
        self,
        source: Path,
        output: Path,
        settings: CompressionSettings,
        log_path: Path,
        stop_event: threading.Event,
        progress: Callable[[float], None],
        duration: float,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-preset",
            settings.preset,
            "-crf",
            str(settings.crf),
            "-threads:v",
            str(settings.threads),
            "-pix_fmt",
            settings.pixel_format,
            "-an",
            "-map_metadata",
            "0",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output),
        ]
        with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=log_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **self._popen_options(),
            )
            with self._active_lock:
                self._active_process = process
            try:
                assert process.stdout is not None
                try:
                    for raw_line in process.stdout:
                        if stop_event.is_set():
                            process.terminate()
                            process.wait()
                            raise MediaCancelled("操作已停止")
                        key, _, value = raw_line.strip().partition("=")
                        if key == "out_time_ms" and duration > 0:
                            try:
                                fraction = int(value) / (duration * 1_000_000)
                                progress(max(0.0, min(1.0, fraction)))
                            except ValueError:
                                pass
                finally:
                    process.stdout.close()
                return_code = process.wait()
                if stop_event.is_set():
                    raise MediaCancelled("操作已停止")
                if return_code != 0:
                    raise MediaError(f"FFmpeg 编码失败，退出码 {return_code}")
                progress(1.0)
            finally:
                with self._active_lock:
                    self._active_process = None
