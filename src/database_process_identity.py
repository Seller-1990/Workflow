"""Conservative local process identity: PID plus OS creation token, never PID alone."""
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import sys
import uuid


@dataclass(frozen=True)
class OwnerIdentity:
    owner_token: str
    host_id: str
    process_id: int
    process_started: str | None


def local_host_id() -> str:
    return f"{socket.gethostname()}:{uuid.getnode():012x}"


def _windows_process(pid: int) -> tuple[str, str | None]:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ("dead" if ctypes.get_last_error() == 87 else "unknown"), None
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        code = wintypes.DWORD()
        if not kernel.GetProcessTimes(handle, created, exited, system, user):
            return "unknown", None
        token = str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        if not kernel.GetExitCodeProcess(handle, code):
            return "unknown", None
        return ("alive" if code.value == 259 else "dead"), token
    finally:
        kernel.CloseHandle(handle)


def inspect_process(pid: int) -> tuple[str, str | None]:
    if pid <= 0:
        return "unknown", None
    if sys.platform == "win32":
        return _windows_process(pid)
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2:].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            return ("dead" if fields[0] == "Z" else "alive"), f"{boot}:{fields[19]}"
        except FileNotFoundError:
            return ("dead" if not Path(f"/proc/{pid}").exists() else "unknown"), None
        except (OSError, ValueError, IndexError):
            return "unknown", None
    return "unknown", None


def new_owner_identity() -> OwnerIdentity:
    _state, started = inspect_process(os.getpid())
    return OwnerIdentity(uuid.uuid4().hex, local_host_id(), os.getpid(), started)


def owner_liveness(owner) -> str:
    if owner.released_at is not None:
        return "released"
    if owner.host_id != local_host_id():
        return "unknown"
    state, started = inspect_process(owner.process_id)
    if state == "dead":
        return "dead"
    if state != "alive" or not started or not owner.process_started:
        return "unknown"
    return "alive" if started == owner.process_started else "dead"
