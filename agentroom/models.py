"""Discover models available to each runner."""

from __future__ import annotations

import time

from . import util

_CACHE: dict = {"at": 0.0, "data": None}


def claude_models() -> list[dict]:
    # `claude models` is a prompt, not a listing command. Keep aliases plus the
    # current IDs; the UI also accepts a free-text model.
    return [
        {"id": "", "label": "default (CLI)"},
        {"id": "opus", "label": "opus (alias)"},
        {"id": "sonnet", "label": "sonnet (alias)"},
        {"id": "haiku", "label": "haiku (alias)"},
        {"id": "fable", "label": "fable (alias)"},
        {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
        {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
        {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},
        {"id": "claude-fable-5-2", "label": "Claude Fable 5.2"},
    ]


def opencode_models() -> list[dict]:
    proc = util.run(["opencode", "models"], timeout=30)
    if proc.returncode != 0:
        return [{"id": "", "label": "default (CLI)"}]
    seen: set[str] = set()
    items = [{"id": "", "label": "default (CLI)"}]
    for line in proc.stdout.splitlines():
        value = line.strip()
        if not value or "/" not in value or " " in value or value in seen:
            continue
        seen.add(value)
        items.append({"id": value, "label": value})
    return items


def list_models() -> dict:
    if _CACHE["data"] and time.time() - _CACHE["at"] < 300:
        return _CACHE["data"]
    data = {
        "claude": claude_models(),
        "opencode": opencode_models(),
        "mock": [{"id": "", "label": "mock"}],
    }
    _CACHE.update({"at": time.time(), "data": data})
    return data
