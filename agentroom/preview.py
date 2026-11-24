"""Run a project's dev server so the dashboard can link to the live app."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
import time

from . import config as project_config
from . import util

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CODE_RE = re.compile(r"(?i)(verify-email|magic[- ]?link|one[- ]time|\botp\b|passcode|verification code|token=)")


def tail(project: str, lines: int = 300) -> dict:
    _, repo, cfg = project_config.find_project(project)
    path = log_path(repo)
    try:
        text = open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    text = ANSI_RE.sub("", text)
    rows = [line[:1000] for line in text.splitlines()][-lines:]
    highlights = [line for line in rows if CODE_RE.search(line)][-60:]
    return {
        "project": project,
        "path": path,
        "running": status(cfg)["running"],
        "log": "\n".join(rows),
        "highlights": highlights,
    }


def state_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "preview.json")


def log_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "preview.log")


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    if not port:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def status(cfg: dict) -> dict:
    repo = cfg["repo"]
    pv = cfg.get("preview") or {}
    command = pv.get("command") or ""
    url = pv.get("url") or ""
    port = int(pv.get("port") or 0)
    data = util.read_json(state_path(repo), None) or {}
    pid_alive = util.pid_alive(data.get("pid"))
    port_open = _port_open(port)
    configured_services = pv.get("services") or []
    services = []
    if configured_services:
        for service in configured_services:
            service_port = int(service.get("port") or 0)
            services.append({**service, "open": _port_open(service_port)})
    else:
        services = [{"name": "app", "url": url, "port": port, "open": port_open}]
    return {
        "configured": bool(command and url),
        "command": command,
        "url": url,
        "port": port,
        "pid": data.get("pid"),
        "pid_alive": pid_alive,
        "port_open": port_open,
        "running": pid_alive or port_open,
        "external": port_open and not pid_alive,
        "started": data.get("started"),
        "log": log_path(repo),
        "services": services,
    }


def start(project: str) -> dict:
    _, repo, cfg = project_config.find_project(project)
    pv = cfg.get("preview") or {}
    command = pv.get("command") or ""
    url = pv.get("url") or ""
    port = int(pv.get("port") or 0)
    if not command or not url:
        raise SystemExit(
            f"{project}: no preview command configured. Add `preview.command` and `preview.url` "
            f"to .agent/config.json."
        )
    current = status(cfg)
    if current["pid_alive"]:
        return current
    if current["port_open"]:
        current["note"] = f"port {port} is already in use; linking to the existing server"
        return current

    util.ensure_dir(os.path.join(repo, ".agent"))
    env_script = cfg.get("isolation", {}).get("env_script")
    prefix = ""
    if pv.get("env_script", True) and env_script and os.path.isfile(os.path.join(repo, env_script)):
        prefix = f"set -a; source {shlex.quote(env_script)}; set +a; "
    shell_command = f"{prefix}{command}"
    cwd = os.path.join(repo, pv.get("cwd") or ".")
    with open(log_path(repo), "w", encoding="utf-8") as log:
        log.write(f"\n=== {util.now_iso()} {command} ({cwd}) ===\n")
        log.flush()
        proc = subprocess.Popen(
            ["bash", "-lc", shell_command],
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    util.write_json(
        state_path(repo),
        {
            "pid": proc.pid,
            "command": command,
            "url": url,
            "port": port,
            "cwd": cwd,
            "started": util.now_iso(),
        },
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if _port_open(port):
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    return status(cfg)


def stop(project: str) -> dict:
    _, repo, cfg = project_config.find_project(project)
    data = util.read_json(state_path(repo), None) or {}
    pid = data.get("pid")
    if pid and util.pid_alive(pid):
        util.kill_tree(pid)
        time.sleep(1)
        if util.pid_alive(pid):
            util.kill_tree(pid, 9)
    try:
        os.unlink(state_path(repo))
    except OSError:
        pass
    port = int((cfg.get("preview") or {}).get("port") or 0)
    for _ in range(20):
        if not _port_open(port):
            break
        time.sleep(0.25)
    return status(cfg)


def restart(project: str) -> dict:
    stop(project)
    time.sleep(1)
    return start(project)
