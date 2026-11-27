"""Platform differences in one place: Linux, macOS and native Windows.

On Windows, Agent Room runs project commands and agent CLIs through Git Bash
(Git for Windows is already required for git itself), detaches background
processes into their own process group without a console window, and stops
process trees with ``taskkill /T``.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys

IS_WINDOWS = os.name == "nt"

SIGTERM = signal.SIGTERM
# Windows has no SIGKILL; kill_tree treats anything but SIGTERM as "force".
SIGKILL = getattr(signal, "SIGKILL", 9)

if IS_WINDOWS:
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    # Background children: own process group (so stopping them never hits the
    # dashboard) and no console window popping up.
    DETACH: dict = {"creationflags": _NEW_GROUP | _NO_WINDOW}
else:
    DETACH = {"start_new_session": True}


def setup() -> None:
    """Process-wide defaults; call before anything prints or spawns."""
    if not IS_WINDOWS:
        return
    # UTF-8 everywhere: child Python processes inherit it, and our own output
    # (arrows, middots) never crashes on a cp1252 console.
    os.environ.setdefault("PYTHONUTF8", "1")
    # Git Bash login shells cd to $HOME unless this is set.
    os.environ.setdefault("CHERE_INVOKING", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    if _no_console():
        _hide_child_consoles()


def _no_console() -> bool:
    """True under pythonw.exe (the background service), where every console
    child would otherwise flash a window."""
    return sys.executable.lower().endswith("pythonw.exe") or sys.stdout is None


def _hide_child_consoles() -> None:
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | _NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]


_BASH: str | None = None


def bash() -> str:
    """The bash that runs project commands and agent CLIs."""
    global _BASH
    if _BASH:
        return _BASH
    if not IS_WINDOWS:
        _BASH = "bash"
        return _BASH
    override = os.environ.get("AROOM_BASH")
    candidates: list[str] = [override] if override else []
    git = shutil.which("git")
    if git:
        # ...\Git\cmd\git.exe or ...\Git\mingw64\bin\git.exe -> ...\Git
        root = os.path.dirname(os.path.dirname(git))
        if os.path.basename(root).lower() == "mingw64":
            root = os.path.dirname(root)
        candidates += [os.path.join(root, "bin", "bash.exe"), os.path.join(root, "usr", "bin", "bash.exe")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Git", "bin", "bash.exe"))
            candidates.append(os.path.join(base, "Programs", "Git", "bin", "bash.exe"))
    found = shutil.which("bash")
    # C:\Windows\System32\bash.exe starts WSL, which cannot see Windows paths
    # the same way; never use it.
    if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
        candidates.append(found)
    for path in candidates:
        if path and os.path.isfile(path):
            _BASH = path
            return _BASH
    raise SystemExit(
        "Agent Room needs Git Bash on Windows (it runs project commands and agent CLIs through it).\n"
        "Install Git for Windows from https://git-scm.com/download/win, or set AROOM_BASH to bash.exe."
    )


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if IS_WINDOWS:
        return _win_pid_alive(int(pid))
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    # A zombie still accepts signal 0 but will never do work.
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as fh:
            if fh.read().split()[2] == "Z":
                return False
    except (OSError, IndexError):
        pass
    return True


def _win_pid_alive(pid: int) -> bool:
    # Never os.kill(pid, 0) on Windows: signal 0 is CTRL_C_EVENT there.
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def kill_tree(pid: int, sig: int = SIGTERM) -> None:
    if not pid:
        return
    if IS_WINDOWS:
        cmd = ["taskkill", "/PID", str(pid), "/T"]
        if sig != SIGTERM:
            cmd.append("/F")
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        pgid = os.getpgid(pid)
        if pgid == os.getpgrp():
            # Never take out the caller's own process group (e.g. a foreground loop).
            os.kill(pid, sig)
        else:
            os.killpg(pgid, sig)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def resolve(cmd: list[str]) -> list[str]:
    """On Windows a bare 'claude' or 'gh' may be a .cmd shim that
    CreateProcess cannot find; resolve it through PATHEXT."""
    if not IS_WINDOWS or not cmd:
        return cmd
    head = cmd[0]
    if os.path.dirname(head) or os.path.splitext(head)[1]:
        return cmd
    found = shutil.which(head)
    return [found, *cmd[1:]] if found else cmd
