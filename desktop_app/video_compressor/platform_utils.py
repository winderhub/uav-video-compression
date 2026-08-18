from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def format_bytes(value: int) -> str:
    amount = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024.0
    return f"{amount:.1f} TiB"


def available_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def same_filesystem(first: Path, second: Path) -> bool:
    first = first.resolve()
    second = second.resolve()
    if sys.platform == "win32":
        return first.drive.casefold() == second.drive.casefold()
    return os.stat(first).st_dev == os.stat(second).st_dev


def make_hidden(path: Path) -> None:
    if sys.platform != "win32":
        return
    FILE_ATTRIBUTE_HIDDEN = 0x2
    get_attrs = ctypes.windll.kernel32.GetFileAttributesW
    set_attrs = ctypes.windll.kernel32.SetFileAttributesW
    attrs = get_attrs(str(path))
    if attrs != -1:
        set_attrs(str(path), attrs | FILE_ATTRIBUTE_HIDDEN)


def sync_file(path: Path) -> None:
    """Ask the OS to commit an app-created file before it replaces source data."""
    # Windows requires a writable file handle for FlushFileBuffers, which is
    # what os.fsync() uses there. A read-only handle fails with EBADF.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _restore_windows_creation_time(path: Path, birthtime_ns: int) -> None:
    FILE_WRITE_ATTRIBUTES = 0x0100
    FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path),
        FILE_WRITE_ATTRIBUTES,
        FILE_SHARE_ALL,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        raise OSError("无法打开文件以恢复创建时间")
    try:
        windows_ticks = birthtime_ns // 100 + 116_444_736_000_000_000
        creation = FileTime(windows_ticks & 0xFFFFFFFF, windows_ticks >> 32)
        if not ctypes.windll.kernel32.SetFileTime(
            ctypes.c_void_p(handle), ctypes.byref(creation), None, None
        ):
            raise OSError("无法恢复文件创建时间")
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def restore_file_times(
    path: Path, atime_ns: int, mtime_ns: int, birthtime_ns: Optional[int] = None
) -> None:
    os.utime(path, ns=(atime_ns, mtime_ns))
    if sys.platform == "win32" and birthtime_ns is not None:
        _restore_windows_creation_time(path, birthtime_ns)


def source_birthtime_ns(path: Path) -> Optional[int]:
    stat = path.stat()
    if sys.platform == "win32":
        return int(stat.st_ctime_ns)
    birthtime = getattr(stat, "st_birthtime", None)
    return int(birthtime * 1_000_000_000) if birthtime is not None else None


def is_file_in_use(path: Path) -> bool:
    """Best-effort preflight check; Windows is the only platform that blocks replacement."""
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError:
        return True

    if sys.platform != "win32":
        return False

    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        return True
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    return False


def can_write_directory(path: Path) -> bool:
    return path.is_dir() and os.access(str(path), os.W_OK)


def safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
