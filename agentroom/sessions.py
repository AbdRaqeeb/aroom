"""Discover Claude Code sessions running outside Agent Room.

Read-only: we never attach to or control another process. Claude writes a
JSONL transcript per session; `claude agents --json` tells us which are live.
"""

from __future__ import annotations

import glob
import json
import os
import threading
import time
from datetime import datetime

from . import util

_AGENTS_CACHE: dict = {"at": 0.0, "data": []}
_PARSE_CACHE: dict[str, dict] = {}
_LOCK = threading.Lock()
_MAX_EVENTS = 120


def claude_agents() -> list[dict]:
    now = time.time()
    if _AGENTS_CACHE["data"] and now - _AGENTS_CACHE["at"] < 3:
        return _AGENTS_CACHE["data"]
    proc = util.run(["claude", "agents", "--json"], timeout=15)
    data: list[dict] = []
    if proc.returncode == 0:
        try:
            parsed = json.loads(proc.stdout or "[]")
            if isinstance(parsed, list):
                data = parsed
        except ValueError:
            data = []
    _AGENTS_CACHE.update({"at": now, "data": data})
    return data


def _session_file(session_id: str) -> str | None:
    matches = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def _iso(value) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value / 1000).isoformat(timespec="seconds") + "Z"
    if isinstance(value, str):
        return value
    return None


def _parse(path: str) -> dict:
    """Incrementally parse a session JSONL and keep the last few events."""
    with _LOCK:
        stat = os.stat(path)
        state = _PARSE_CACHE.get(path)
        if state and state.get("size") == stat.st_size and state.get("mtime") == stat.st_mtime:
            return state
        if not state or stat.st_size < state.get("offset", 0):
            state = {
                "offset": 0,
                "size": 0,
                "mtime": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cache_read": 0,
                "model": "",
                "cwd": "",
                "branch": "",
                "last_text": "",
                "last_tool": "",
                "started": None,
                "updated": None,
                "events": [],
                "file": path,
            }
        try:
            with open(path, "rb") as fh:
                fh.seek(state["offset"])
                chunk = fh.read()
        except OSError:
            return state
        end = chunk.rfind(b"\n")
        if end == -1:
            return state
        offset = state["offset"]
        for raw in chunk[: end + 1].split(b"\n"):
            if not raw:
                offset += 1
                continue
            offset += len(raw) + 1
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            ts = obj.get("timestamp")
            if ts:
                if not state["started"] or ts < state["started"]:
                    state["started"] = ts
                state["updated"] = ts
            if obj.get("cwd"):
                state["cwd"] = obj["cwd"]
            if obj.get("gitBranch"):
                state["branch"] = obj["gitBranch"]
            kind = obj.get("type")
            message = obj.get("message") or {}
            if kind == "assistant":
                if message.get("model"):
                    state["model"] = message["model"]
                usage = message.get("usage") or {}
                state["tokens_in"] += int(usage.get("input_tokens") or 0)
                state["tokens_in"] += int(usage.get("cache_creation_input_tokens") or 0)
                state["tokens_in"] += int(usage.get("cache_read_input_tokens") or 0)
                state["tokens_out"] += int(usage.get("output_tokens") or 0)
                state["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                for block in message.get("content") or []:
                    btype = block.get("type")
                    if btype == "text" and block.get("text", "").strip():
                        text = " ".join(block["text"].split())
                        state["last_text"] = text[:400]
                        _push(state, ts, "assistant", text)
                    elif btype == "tool_use":
                        tool = block.get("name") or "tool"
                        data = block.get("input") or {}
                        summary = _tool_summary(tool, data)
                        state["last_tool"] = summary
                        _push(state, ts, "tool", summary)
            elif kind == "user":
                content = message.get("content")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text += block.get("text", "")
                if text.strip():
                    _push(state, ts, "user", " ".join(text.split())[:400])
        state["offset"] = offset
        state["size"] = stat.st_size
        state["mtime"] = stat.st_mtime
        _PARSE_CACHE[path] = state
        return state


def _push(state: dict, ts, role: str, text: str) -> None:
    state["events"].append({"ts": ts or "", "role": role, "text": text[:400]})
    if len(state["events"]) > _MAX_EVENTS:
        del state["events"][: len(state["events"]) - _MAX_EVENTS]


def _tool_summary(name: str, data: dict) -> str:
    lower = (name or "").lower()
    if lower in {"bash", "shell"}:
        return f"Bash {str(data.get('command') or data.get('cmd') or '')}"[:300]
    if lower in {"edit", "write", "read", "multiedit"}:
        path = data.get("file_path") or data.get("path") or ""
        return f"{name} {path}"[:300]
    if lower in {"grep", "glob"}:
        return f"{name} {data.get('pattern', '')}"[:300]
    return name or "tool"


def summarize(agent: dict) -> dict:
    session_id = agent.get("sessionId", "")
    path = _session_file(session_id)
    state = _parse(path) if path else {}
    started = _iso(agent.get("startedAt")) or state.get("started")
    updated = state.get("updated")
    if path:
        try:
            mtime = os.path.getmtime(path)
            if not updated or datetime.utcfromtimestamp(mtime).isoformat(timespec="seconds") > updated.replace("Z", ""):
                updated = datetime.utcfromtimestamp(mtime).isoformat(timespec="seconds")
        except OSError:
            pass
    status = agent.get("status") or "idle"
    return {
        "id": session_id,
        "name": agent.get("name") or session_id[:8],
        "pid": agent.get("pid"),
        "kind": agent.get("kind", "interactive"),
        "status": status,
        "busy": status == "busy",
        "live": status in {"busy", "idle"},
        "cwd": agent.get("cwd") or state.get("cwd", ""),
        "branch": state.get("branch", ""),
        "model": state.get("model", ""),
        "started": started,
        "updated": updated,
        "tokens_in": state.get("tokens_in", 0),
        "tokens_out": state.get("tokens_out", 0),
        "cache_read": state.get("cache_read", 0),
        "last_text": state.get("last_text", ""),
        "last_tool": state.get("last_tool", ""),
        "file": path or "",
    }


def all_sessions() -> list[dict]:
    out: list[dict] = []
    for agent in claude_agents():
        cwd = agent.get("cwd") or ""
        if _is_managed(cwd):
            continue
        out.append(summarize(agent))
    out.sort(key=lambda item: (not item["live"], item.get("updated") or ""), reverse=False)
    return out


def _is_managed(cwd: str) -> bool:
    worktrees = util.expand("~/.local/share/agent-room/worktrees")
    return cwd.startswith(worktrees + os.sep) or "/agent-room/worktrees/" in cwd


def for_project(sessions: list[dict], repo: str) -> list[dict]:
    repo = util.expand(repo)
    return [
        session
        for session in sessions
        if session.get("cwd") == repo or str(session.get("cwd", "")).startswith(repo + os.sep)
    ]


def unregistered(sessions: list[dict], repos: dict[str, str]) -> list[dict]:
    paths = [util.expand(path) for path in repos.values()]
    out = []
    for session in sessions:
        cwd = session.get("cwd") or ""
        if not cwd or any(cwd == path or cwd.startswith(path + os.sep) for path in paths):
            continue
        if not os.path.isdir(os.path.join(cwd, ".git")):
            continue
        out.append(session)
    return out


def detail(session_id: str) -> dict:
    agent = next((a for a in claude_agents() if a.get("sessionId") == session_id), None)
    if not agent:
        path = _session_file(session_id)
        if not path:
            raise KeyError(session_id)
        state = _parse(path)
        agent = {
            "sessionId": session_id,
            "cwd": state.get("cwd"),
            "status": "ended",
            "name": session_id[:8],
            "startedAt": state.get("started"),
        }
    summary = summarize(agent)
    path = summary.get("file")
    state = _parse(path) if path else {"events": []}
    summary["events"] = state.get("events", [])[-_MAX_EVENTS:]
    return summary
