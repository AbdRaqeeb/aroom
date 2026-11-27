"""Small shared helpers. Standard library only."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

from . import osutil

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "agent-room")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.join(HOME, ".local", "state")), "agent-room")
GLOBAL_CONFIG = os.path.join(CONFIG_DIR, "config.json")
REGISTRY = os.path.join(CONFIG_DIR, "registry.json")

ACTIVE_STATES = {"queued", "briefing", "researching", "building", "checking", "verifying", "fixing", "merging"}
WAITING_STATES = {"built"}
TERMINAL_STATES = {"merged", "passed", "needs-human", "failed", "stopped"}


def now_iso_after(seconds: float) -> str:
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _replace(tmp: str, path: str) -> None:
    """os.replace, retried briefly: on Windows it fails with access denied while
    another process (the dashboard, a loop) has the target open."""
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not osutil.IS_WINDOWS or attempt == 19:
                raise
            time.sleep(0.05)


def write_json(path: str, data: Any) -> None:
    ensure_dir(os.path.dirname(path))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
        _replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append_jsonl(path: str, obj: Any) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")


def read_jsonl(path: str, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    rows.append({"kind": "raw", "text": line, "ts": ""})
    except OSError:
        return []
    if limit:
        rows = rows[-limit:]
    return rows


def last_activity(run: dict) -> float:
    """Newest write in the run directory; agents log continuously while they work."""
    directory = run.get("run_dir") or ""
    if not directory:
        return 0.0
    paths = [
        os.path.join(directory, name)
        for name in ("run.json", "builder.log", "verifier.log", "researcher.log", "events.ndjson")
    ]
    checks = os.path.join(directory, "checks")
    if os.path.isdir(checks):
        paths.extend(os.path.join(checks, name) for name in os.listdir(checks))
    newest = 0.0
    for path in paths:
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            pass
    return newest


def slug(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return out or "x"


def tail(path: str, lines: int = 80) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return ""


def pid_alive(pid: int | None) -> bool:
    return osutil.pid_alive(pid)


def kill_tree(pid: int, sig: int = signal.SIGTERM) -> None:
    osutil.kill_tree(pid, sig)


def _cwd_pids_lsof(prefix: str) -> list[int]:
    """Processes whose cwd is under `prefix`, using lsof (macOS, no /proc)."""
    try:
        proc = subprocess.run(
            ["lsof", "-a", "-d", "cwd", "-Fpn", "-w"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[int] = []
    pid: int | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = None
        elif line.startswith("n") and pid:
            path = line[1:]
            if path == prefix or path.startswith(prefix + os.sep):
                found.append(pid)
    return found


def kill_cwd_processes(prefix: str, sig: int = signal.SIGTERM) -> int:
    """Kill processes whose cwd is inside a worktree (leaked dev servers)."""
    if osutil.IS_WINDOWS:
        return 0  # no cheap per-process cwd query; worktree removal still works
    prefix = os.path.abspath(prefix)
    killed = 0
    me = os.getpid()
    if os.path.isdir("/proc"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == me:
                continue
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                continue
            if cwd == prefix or cwd.startswith(prefix + os.sep):
                kill_tree(pid, sig)
                killed += 1
        return killed

    # macOS: no /proc, ask lsof instead.
    for pid in _cwd_pids_lsof(prefix):
        if pid == me:
            continue
        kill_tree(pid, sig)
        killed += 1
    return killed


def run(
    cmd: str | list[str],
    cwd: str | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    shell: bool | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    if shell is None:
        shell = isinstance(cmd, str)
    merged = dict(os.environ)
    if env:
        merged.update(env)
    if not shell and isinstance(cmd, list):
        cmd = osutil.resolve(cmd)
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=merged,
            shell=shell,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        # A tool that is not installed (claude, gh, lsof...) is a failed
        # command, not a crash: report it like a shell would.
        proc = subprocess.CompletedProcess(cmd, 127, "", f"{exc}")
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {cmd}\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
        )
    return proc


def which(name: str) -> str | None:
    from shutil import which as _which

    return _which(name)


def human_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def file_has(path: str, needle: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return needle in fh.read()
    except OSError:
        return False


def append_once(path: str, block: str) -> bool:
    """Append block unless its marker line already exists."""
    marker = block.strip().splitlines()[0]
    if file_has(path, marker):
        return False
    ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as fh:
        if os.path.getsize(path) if os.path.exists(path) else 0:
            fh.write("\n")
        fh.write(block.rstrip() + "\n")
    return True


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def primary_ip() -> str:
    """Best guess at this machine's outward-facing address (no packets sent)."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return ""
