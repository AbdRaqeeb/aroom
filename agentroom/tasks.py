"""Task adapters: markdown checklists, a folder of files, or GitHub issues."""

from __future__ import annotations

import os
import re
from typing import Any

from . import util

TASK_LINE = re.compile(r"^\s*[-*]\s*\[(?P<state>[ xX])\]\s+(?P<rest>.+?)\s*$")
HEADING = re.compile(r"^#{1,6}\s")


def _clean_title(value: str, limit: int = 140) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t-—:.")
    value = value.replace("**", "")
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def parse_markdown(path: str, id_regex: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    header_re = re.compile(rf"^\s*[-*]\s*\[(?P<state>[ xX])\]\s+(?P<rest>.+?)\s*$")
    bold_re = re.compile(rf"^\*\*(?P<id>{id_regex})\b\s*(?P<title>.*?)\*\*(?P<desc>.*)$")
    plain_re = re.compile(rf"^(?P<id>{id_regex})\b\s*(?P<desc>.*)$")

    tasks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = header_re.match(line)
        if not match:
            i += 1
            continue
        rest = match.group("rest").strip()
        state = "x" if match.group("state").lower() == "x" else " "
        task_id = None
        title = ""
        desc = ""
        bold = bold_re.match(rest)
        if bold:
            task_id = bold.group("id")
            title = bold.group("title")
            desc = bold.group("desc")
        else:
            plain = plain_re.match(rest)
            if plain:
                task_id = plain.group("id")
                desc = plain.group("desc")
                title = desc.split(" — ")[0]
        if not task_id:
            i += 1
            continue

        body: list[str] = [desc.strip()] if desc.strip() else []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if header_re.match(nxt) or HEADING.match(nxt):
                break
            body.append(nxt.rstrip("\n"))
            j += 1

        acceptance: list[str] = []
        for raw in body:
            stripped = raw.strip()
            cleaned = re.sub(r"^[-*]\s+", "", stripped)
            if re.match(r"(?i)^accept(ance)?\b", cleaned):
                value = re.sub(r"(?i)^accept(ance)?\s*[:\-–]?\s*", "", cleaned).strip()
                if value:
                    acceptance.append(value)

        raw_text = "\n".join([line.rstrip("\n")] + body)
        status = state
        if "🔒" in raw_text or "[blocked]" in raw_text.lower():
            status = "blocked"
        if "~~" in rest:
            status = "dropped"

        tasks.append(
            {
                "id": task_id,
                "title": _clean_title(title) or task_id,
                "description": "\n".join(body).strip(),
                "acceptance": acceptance,
                "state": status,
                "line": i,
                "raw": raw_text,
                "source": path,
            }
        )
        i = j if j > i else i + 1
    return tasks


def parse_files(directory: str, id_regex: str) -> list[dict]:
    if not os.path.isdir(directory):
        return []
    tasks: list[dict] = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md") or name.lower() in {"readme.md", "index.md"}:
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        text = open(path, "r", encoding="utf-8", errors="replace").read()
        task_id = os.path.splitext(name)[0]
        title = task_id
        for line in text.splitlines():
            if line.startswith("#"):
                title = _clean_title(line.lstrip("#").strip()) or task_id
                break
        status = "x" if ".done" in name else " "
        if re.search(r"(?im)^status:\s*done", text):
            status = "x"
        acceptance = [
            re.sub(r"(?i)^accept(ance)?\s*[:\-–]?\s*", "", line.strip(" -*")).strip()
            for line in text.splitlines()
            if re.match(r"(?i)^\s*[-*]?\s*accept(ance)?\b", line)
        ]
        tasks.append(
            {
                "id": task_id,
                "title": title,
                "description": text.strip(),
                "acceptance": [a for a in acceptance if a],
                "state": status,
                "line": 0,
                "raw": text,
                "source": path,
            }
        )
    return tasks


def parse_github(repo: str, id_regex: str) -> list[dict]:
    proc = util.run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,body,labels",
        ],
        cwd=repo,
    )
    if proc.returncode != 0:
        return []
    import json

    try:
        issues = json.loads(proc.stdout or "[]")
    except ValueError:
        return []
    tasks: list[dict] = []
    for issue in issues:
        labels = {label.get("name", "") for label in issue.get("labels", [])}
        if labels and not ({"agent", "agent-room"} & labels):
            continue
        body = issue.get("body") or ""
        acceptance = [
            re.sub(r"(?i)^\s*[-*]?\s*accept(ance)?\s*[:\-–]?\s*", "", line).strip()
            for line in body.splitlines()
            if re.match(r"(?i)^\s*[-*]?\s*accept(ance)?\b", line)
        ]
        tasks.append(
            {
                "id": f"#{issue['number']}",
                "title": _clean_title(issue.get("title", "")),
                "description": body.strip(),
                "acceptance": [a for a in acceptance if a],
                "state": " ",
                "line": 0,
                "raw": f"#{issue['number']} {issue.get('title','')}\n\n{body}",
                "source": "github",
            }
        )
    return tasks


def load_tasks(cfg: dict) -> list[dict]:
    adapter = cfg["tasks"].get("adapter", "markdown")
    repo = cfg["repo"]
    id_regex = cfg["tasks"].get("id_regex") or r"[A-Z]+-?\d+(?:\.\d+)*"
    if adapter == "files":
        return parse_files(os.path.join(repo, cfg["tasks"].get("file", ".agent/tasks")), id_regex)
    if adapter == "github":
        return parse_github(repo, id_regex)
    return parse_markdown(os.path.join(repo, cfg["tasks"].get("file", "docs/PLAN.md")), id_regex)


def counts(tasks: list[dict]) -> dict:
    todo = sum(1 for t in tasks if t["state"] == " ")
    done = sum(1 for t in tasks if t["state"] == "x")
    return {"todo": todo, "done": done, "total": len(tasks)}


def next_task(tasks: list[dict], blocked: set[str] | None = None) -> dict | None:
    blocked = blocked or set()
    for task in tasks:
        if task["state"] == " " and task["id"] not in blocked:
            return task
    return None


def find_task(tasks: list[dict], task_id: str) -> dict | None:
    for task in tasks:
        if task["id"].lower() == task_id.lower():
            return task
    return None


def blocked_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "blocked.json")


def load_blocked(repo: str) -> dict:
    data = util.read_json(blocked_path(repo), {})
    return data if isinstance(data, dict) else {}


def blocked_ids(repo: str) -> set[str]:
    return set(load_blocked(repo))


def mark_blocked(repo: str, task_id: str, reason: str) -> None:
    data = load_blocked(repo)
    data[task_id] = {"reason": reason[:500], "at": util.now_iso()}
    util.write_json(blocked_path(repo), data)


def unmark_blocked(repo: str, task_id: str) -> bool:
    data = load_blocked(repo)
    if task_id not in data:
        return False
    del data[task_id]
    util.write_json(blocked_path(repo), data)
    return True


def tick(cfg: dict, task: dict, suffix: str = "") -> bool:
    """Mark a task done in place. Returns True when a line changed."""
    path = task.get("source")
    if not path or path == "github" or not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    # Match only the task header (optionally bold), never a "split into T-XXX" reference.
    header_re = re.compile(
        rf"^\s*[-*]\s*\[ \]\s+(?:\*\*)?{re.escape(task['id'])}(?![\w.])"
    )
    for index, line in enumerate(lines):
        if header_re.match(line):
            newline = line.replace("[ ]", "[x]", 1)
            if suffix:
                newline = newline.rstrip("\n") + suffix + "\n"
            if newline != line:
                lines[index] = newline
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines)
                return True
    return False


def acceptance_text(task: dict) -> str:
    if task["acceptance"]:
        return "\n".join(f"- [ ] {item}" for item in task["acceptance"])
    return (
        "- [ ] The task description above is implemented end to end.\n"
        "- [ ] Behaviour is covered by tests, including failure paths.\n"
        "- [ ] The project's checks pass, and no unrelated files changed.\n"
        "- [ ] Repo conventions in AGENTS.md (or README) are followed."
    )
