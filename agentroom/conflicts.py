"""Resolve a task branch's conflicts with the base from the dashboard.

Everything happens in the task's own worktree, never in the main checkout:

1. ``start``    ``git merge --no-commit <base>`` inside the worktree
2. ``file``     ours (the task), theirs (the base), and the working copy with markers
3. ``resolve``  keep ours / keep theirs / save edited content / delete, then ``git add``
4. ``finish``   refuse while unmerged paths or conflict markers remain, then commit
5. ``abort``    ``git merge --abort``

After ``finish`` the branch already contains the base, so the squash merge into
the base is clean; the caller can merge right away or re-verify first.
"""

from __future__ import annotations

import os
import re

from . import config as project_config
from . import gitops, pipeline, runners, util
from . import tasks as tasklib

MARKER = re.compile(r"^(<{7}|={7}|>{7})( |$)", re.M)
MAX_FILE = 400_000


class ConflictError(SystemExit):
    pass


def _git(worktree: str, *args: str, check: bool = False):
    proc = util.run(["git", "-C", worktree, *args])
    if check and proc.returncode != 0:
        raise ConflictError(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}".strip())
    return proc


def _context(project: str, task: str) -> tuple[str, str, dict, dict, str]:
    name, repo, cfg = project_config.find_project(project)
    if not task:
        raise ConflictError("task is required")
    run = util.read_json(os.path.join(pipeline.run_dir(repo, task), "run.json"), None)
    if not run:
        raise ConflictError(f"no run record for {name} {task}")
    worktree = run.get("worktree") or ""
    if not worktree or not gitops.worktree_exists(repo, worktree):
        raise ConflictError(
            f"{task} has no worktree, so there is nothing to resolve. Start it over instead."
        )
    if run.get("state") in util.ACTIVE_STATES and util.pid_alive(run.get("pid")):
        raise ConflictError(f"{task} is running ({run.get('state')}); stop it first")
    return name, repo, cfg, run, worktree


def _merging(worktree: str) -> bool:
    return _git(worktree, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0


def _unmerged(worktree: str) -> list[str]:
    out = _git(worktree, "diff", "--name-only", "--diff-filter=U").stdout
    return [line for line in out.splitlines() if line.strip()]


def _stage(worktree: str, stage: int, path: str) -> str | None:
    proc = _git(worktree, "show", f":{stage}:{path}")
    if proc.returncode != 0:
        return None
    return proc.stdout


def _safe_path(worktree: str, path: str, allowed: list[str]) -> str:
    if path not in allowed:
        raise ConflictError(f"{path} is not a conflicted file")
    full = os.path.realpath(os.path.join(worktree, path))
    if not full.startswith(os.path.realpath(worktree) + os.sep):
        raise ConflictError("path escapes the worktree")
    return full


def _record_path(run: dict, repo: str, task: str) -> str:
    return os.path.join(run.get("run_dir") or pipeline.run_dir(repo, task), "conflicts.json")


def _resolved_files(run: dict, repo: str, task: str, unmerged: list[str]) -> list[str]:
    started = (util.read_json(_record_path(run, repo, task), None) or {}).get("files") or []
    return [path for path in started if path not in unmerged]


def status(project: str, task: str) -> dict:
    name, repo, cfg, run, worktree = _context(project, task)
    base = run.get("base_branch") or cfg["base_branch"]
    merging = _merging(worktree)
    unmerged = _unmerged(worktree) if merging else []
    files = []
    for path in unmerged:
        full = os.path.join(worktree, path)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(MAX_FILE)
            markers = len(re.findall(r"^<{7}( |$)", text, re.M))
        except OSError:
            markers = 0
        files.append({"path": path, "markers": markers, "resolved": False})
    dirty = _git(worktree, "status", "--porcelain").stdout.strip() if not merging else ""
    predicted = []
    if not merging:
        from .diagnose import conflict_files

        predicted = conflict_files(repo, base, run.get("branch", ""))
    return {
        "project": name,
        "task": task,
        "base": base,
        "branch": run.get("branch"),
        "worktree": worktree,
        "merging": merging,
        "files": files,
        "resolved": _resolved_files(run, repo, task, unmerged) if merging else [],
        "predicted": predicted,
        "dirty": dirty,
        "base_dirty": not gitops.is_clean(repo)[0],
    }


def start(project: str, task: str) -> dict:
    name, repo, cfg, run, worktree = _context(project, task)
    base = run.get("base_branch") or cfg["base_branch"]
    if _merging(worktree):
        return status(project, task)
    dirty = _git(worktree, "status", "--porcelain").stdout.strip()
    if dirty:
        # Leftover uncommitted agent work: keep it on the branch, then merge.
        _git(worktree, "add", "-A", check=True)
        _git(worktree, "commit", "-m", f"wip({task}): uncommitted work before resolving conflicts", check=True)
    proc = _git(worktree, "merge", "--no-ff", "--no-commit", base)
    directory = run.get("run_dir") or pipeline.run_dir(repo, task)
    if proc.returncode != 0 and not _merging(worktree):
        raise ConflictError(f"git merge {base} failed:\n{proc.stdout}\n{proc.stderr}".strip())
    unmerged = _unmerged(worktree)
    util.write_json(_record_path(run, repo, task), {"files": unmerged, "started": util.now_iso()})
    runners.emit(
        directory, run, "dashboard", "conflict",
        f"merging {base} into the branch: {len(unmerged)} conflicted file(s)",
    )
    if not unmerged:
        result = finish(project, task, message=f"merge {base} into {run.get('branch')}")
        result["clean"] = True
        return result
    return status(project, task)


def file(project: str, task: str, path: str) -> dict:
    _, _, _, run, worktree = _context(project, task)
    full = _safe_path(worktree, path, _unmerged(worktree))
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            working = fh.read(MAX_FILE + 1)
    except OSError:
        working = None
    binary = working is not None and "\x00" in working
    return {
        "path": path,
        "ours": _stage(worktree, 2, path),      # the task branch
        "theirs": _stage(worktree, 3, path),    # the base
        "ancestor": _stage(worktree, 1, path),
        "working": None if binary else working,
        "binary": binary,
        "too_big": bool(working and len(working) > MAX_FILE),
    }


def resolve(project: str, task: str, path: str, mode: str, content: str | None = None) -> dict:
    _, repo, _, run, worktree = _context(project, task)
    full = _safe_path(worktree, path, _unmerged(worktree))
    if mode in {"ours", "theirs"}:
        stage = 2 if mode == "ours" else 3
        if _stage(worktree, stage, path) is None:
            # That side deleted the file.
            _git(worktree, "rm", "-q", "--", path, check=True)
        else:
            _git(worktree, "checkout", f"--{mode}", "--", path, check=True)
            _git(worktree, "add", "--", path, check=True)
    elif mode == "content":
        if content is None:
            raise ConflictError("content is required")
        if MARKER.search(content):
            raise ConflictError("the file still has conflict markers (<<<<<<<, =======, >>>>>>>); remove them first")
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        _git(worktree, "add", "--", path, check=True)
    elif mode == "delete":
        _git(worktree, "rm", "-q", "--", path, check=True)
    else:
        raise ConflictError(f"unknown mode {mode}")
    return status(project, task)


def abort(project: str, task: str) -> dict:
    _, repo, _, run, worktree = _context(project, task)
    if _merging(worktree):
        _git(worktree, "merge", "--abort", check=True)
        runners.emit(run.get("run_dir") or pipeline.run_dir(repo, task), run, "dashboard", "conflict", "conflict resolution aborted")
    return status(project, task)


def finish(project: str, task: str, message: str = "") -> dict:
    name, repo, cfg, run, worktree = _context(project, task)
    base = run.get("base_branch") or cfg["base_branch"]
    if _merging(worktree):
        left = _unmerged(worktree)
        if left:
            raise ConflictError("still unresolved:\n" + "\n".join(left))
        staged = _git(worktree, "diff", "--cached", "--name-only").stdout.split()
        for path in staged:
            full = os.path.join(worktree, path)
            if not os.path.isfile(full):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    if MARKER.search(fh.read(MAX_FILE)):
                        raise ConflictError(f"{path} still contains conflict markers")
            except OSError:
                continue
        _git(
            worktree, "commit", "--no-verify", "-m",
            message or f"merge {base} into {run.get('branch')} (resolved in dashboard)",
            check=True,
        )
    directory = run.get("run_dir") or pipeline.run_dir(repo, task)
    run.update(
        {
            "state": "needs-human",
            "step": "merge conflict resolved",
            "error": None,
            "issues": None,
            "merge_failures": 0,
            "updated": util.now_iso(),
        }
    )
    util.write_json(os.path.join(directory, "run.json"), run)
    tasklib.unmark_blocked(repo, task)
    runners.emit(directory, run, "dashboard", "conflict", f"conflicts resolved; branch now contains {base}")
    out = status(project, task)
    out["finished"] = True
    return out
