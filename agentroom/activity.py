"""Cross-project activity feed: the notable events of recent runs, newest first."""

from __future__ import annotations

import json
import os
import time

from . import config as project_config
from . import util

# Pipeline milestones worth a line in the feed (tool calls and heartbeats are not).
NOTABLE = {
    "start", "brief", "research", "built", "verify", "verdict", "pass", "merge", "merged",
    "conflict", "error", "requeue", "warn", "fail",
}
# Only pipeline-level actors; builder/verifier tool chatter stays in the run view.
ACTORS = {"agent-room", "dashboard", "checks", "integration", "push", "supervisor"}
_NEEDLES = tuple(f'"actor": "{a}"' for a in ACTORS) + tuple(f'"actor":"{a}"' for a in ACTORS)
_CACHE: dict[str, tuple[float, list[dict]]] = {}
TAIL_BYTES = 96_000
MAX_AGE_DAYS = 14


def _tail_events(path: str) -> list[dict]:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    cached = _CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    events = _read_tail(path)
    _CACHE[path] = (mtime, events)
    return events


def _read_tail(path: str) -> list[dict]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()  # drop the partial first line
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        if not any(needle in line for needle in _NEEDLES):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("kind") in NOTABLE:
            out.append(event)
    return out


def tone(event: dict) -> str:
    kind = event.get("kind")
    text = str(event.get("text") or "").lower()
    if kind in {"merged", "pass"} or (kind == "verdict" and "pass" in text):
        return "good"
    if kind in {"error", "fail"} or (kind == "verdict" and "fail" in text):
        return "bad"
    if kind in {"conflict", "warn", "requeue"}:
        return "warn"
    return "info"


def feed(limit: int = 300, project: str = "") -> list[dict]:
    reg = project_config.load_registry()
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    items: list[dict] = []
    for name, path in sorted(reg["projects"].items()):
        if project and name != project:
            continue
        root = os.path.join(util.expand(path), ".agent", "runs")
        if not os.path.isdir(root):
            continue
        for folder in os.listdir(root):
            events_path = os.path.join(root, folder, "events.ndjson")
            try:
                if os.path.getmtime(events_path) < cutoff:
                    continue
            except OSError:
                continue
            run = util.read_json(os.path.join(root, folder, "run.json"), None) or {}
            task = run.get("task") or folder
            for event in _tail_events(events_path):
                items.append(
                    {
                        "ts": event.get("ts"),
                        "project": name,
                        "task": task,
                        "title": run.get("title") or "",
                        "actor": event.get("actor"),
                        "kind": event.get("kind"),
                        "text": event.get("text"),
                        "tone": tone(event),
                        "run_kind": run.get("kind") or "task",
                    }
                )
    items.sort(key=lambda e: e.get("ts") or "", reverse=True)
    return items[:limit]
