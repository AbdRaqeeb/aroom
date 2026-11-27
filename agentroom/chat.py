"""A per-project chat agent, separate from task runs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid

from . import config as project_config
from . import osutil
from . import util

AR_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ar")


def state_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "chat.json")


def log_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "chat.log")


def load(repo: str) -> dict:
    data = util.read_json(state_path(repo), None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("session_id", "")
    data.setdefault("messages", [])
    data.setdefault("status", "idle")
    data.setdefault("pid", None)
    data.setdefault("runner", "")
    data.setdefault("model", "")
    data.setdefault("error", None)
    data.setdefault("updated", None)
    return data


def save(repo: str, state: dict) -> None:
    state["updated"] = util.now_iso()
    if len(state["messages"]) > 200:
        state["messages"] = state["messages"][-200:]
    util.write_json(state_path(repo), state)


def session_id(runner: str) -> str:
    if runner == "opencode":
        return "ses_" + uuid.uuid4().hex
    return str(uuid.uuid4())


def send(project: str, message: str) -> dict:
    _, repo, cfg = project_config.find_project(project)
    message = message.strip()
    if not message:
        raise SystemExit("message is empty")
    state = load(repo)
    if state["status"] == "running":
        if util.pid_alive(state.get("pid")):
            raise SystemExit("the chat agent is still thinking; wait for it to finish")
        state["status"] = "idle"
        state["pid"] = None
    spec = cfg.get("chat") or cfg["agents"].get("builder") or {}
    runner = spec.get("runner") or "opencode"
    model = spec.get("model") or ""
    state["runner"] = runner
    state["model"] = model
    if not state["session_id"]:
        state["session_id"] = session_id(runner)
    state["messages"].append({"role": "user", "text": message, "at": util.now_iso()})
    state["status"] = "running"
    state["error"] = None
    util.ensure_dir(os.path.join(repo, ".agent"))
    with open(log_path(repo), "w", encoding="utf-8") as log:
        log.write(f"\n=== {util.now_iso()} {runner}/{model or 'default'} ===\n")
        log.flush()
        proc = subprocess.Popen(
            [sys.executable, AR_MAIN, "_chat", project],
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            **osutil.DETACH,
        )
    state["pid"] = proc.pid
    save(repo, state)
    return state


def _prompt(project: str, repo: str, message: str, first: bool) -> str:
    if not first:
        return message
    return (
        f"You are the Agent Room project assistant for {project}, working in {repo}.\n"
        "You may read files, search, and run read-only commands. Do not edit files, commit, "
        "merge, push, or change configuration unless the user explicitly asks.\n"
        "Be concise and concrete. Use Markdown where useful.\n\n"
        f"User: {message}"
    )


def _run(cmd: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess:
    shell_command = shlex.join(cmd)
    return subprocess.run(
        [osutil.bash(), "-lc", shell_command],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _extract(runner: str, stdout: str) -> str:
    stdout = stdout.strip()
    if not stdout:
        return ""
    if runner == "claude":
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                return str(data.get("result") or "")
        except ValueError:
            pass
        return stdout
    texts = []
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        part = obj.get("part") if isinstance(obj.get("part"), dict) else {}
        if (obj.get("type") == "text" or part.get("type") == "text") and part.get("text"):
            texts.append(str(part["text"]))
    return "\n".join(texts).strip() or stdout


def run_turn(project: str) -> None:
    _, repo, cfg = project_config.find_project(project)
    state = load(repo)
    spec = cfg.get("chat") or cfg["agents"].get("builder") or {}
    runner = state.get("runner") or spec.get("runner") or "opencode"
    model = state.get("model") or spec.get("model") or ""
    user_messages = [m for m in state["messages"] if m.get("role") == "user"]
    if not user_messages:
        state["status"] = "idle"
        state["pid"] = None
        save(repo, state)
        return
    message = user_messages[-1]["text"]
    first = len(user_messages) == 1
    sid = state.get("session_id") or session_id(runner)
    state["session_id"] = sid
    prompt = _prompt(project, repo, message, first)
    timeout = int((cfg.get("chat") or {}).get("timeout_min", 10)) * 60

    try:
        if runner == "claude":
            cmd = ["claude", "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(["--session-id" if first else "--resume", sid])
        else:
            cmd = ["opencode", "run", prompt, "--format", "json", "--auto", "--session", sid]
            if model:
                cmd.extend(["--model", model])
        result = _run(cmd, repo, timeout)
        answer = _extract(runner, result.stdout)
        if result.returncode != 0 and not answer:
            answer = (result.stderr or result.stdout or "chat failed").strip()[-2500:]
        state["messages"].append({"role": "assistant", "text": answer, "at": util.now_iso()})
        state["status"] = "idle" if result.returncode == 0 else "failed"
        state["error"] = None if result.returncode == 0 else answer[-1000:]
    except subprocess.TimeoutExpired:
        state["messages"].append(
            {"role": "assistant", "text": f"Chat timed out after {timeout // 60} minutes.", "at": util.now_iso()}
        )
        state["status"] = "failed"
        state["error"] = "timeout"
    except Exception as exc:  # noqa: BLE001
        state["messages"].append(
            {"role": "assistant", "text": f"Chat failed: {exc}", "at": util.now_iso()}
        )
        state["status"] = "failed"
        state["error"] = str(exc)
    finally:
        state["pid"] = None
        save(repo, state)
