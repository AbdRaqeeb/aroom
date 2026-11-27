"""Explain why work is stuck, in plain words, with the evidence and the fixes.

Every task that needs a person (needs-human, failed, blocked, stalled) and every
project-level blocker (dirty main checkout, failed push) becomes a *problem*:

    {
      "id": "aworin:M1.9", "project": "aworin", "task": "M1.9", "kind": "merge-conflict",
      "headline": "...", "summary": "...", "next": "...",
      "actions": ["resolve", "agent-fix", ...], "primary": "resolve",
      "excerpt": "first lines of the most useful evidence",
    }

``full(...)`` adds ``sections``: every piece of evidence (error, verifier
findings, failing check logs, the agent's notes, conflicted files, events).
"""

from __future__ import annotations

import os
import re
import time

from . import gitops, runners, util
from .supervisor import TRANSIENT as _SUPERVISOR_TRANSIENT
from . import tasks as tasklib

TRANSIENT = _SUPERVISOR_TRANSIENT
ACCOUNT = re.compile(r"subscription|payment|past due|billing|credit balance|insufficient (funds|credit)", re.I)
CONFLICT = re.compile(r"conflict|squash merge failed|CONFLICT \(", re.I)


def _read(path: str, limit: int = 40000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    return text[-limit:]


def _first_lines(text: str, lines: int = 6, chars: int = 600) -> str:
    out = "\n".join([line for line in (text or "").strip().splitlines() if line.strip()][:lines])
    return out[:chars]


def _failed_checks(run: dict) -> list[tuple[str, dict]]:
    return [(cmd, info) for cmd, info in (run.get("checks") or {}).items() if info.get("state") == "fail"]


def conflict_files(repo: str, base: str, branch: str) -> list[str]:
    """Files that would conflict merging ``branch`` into ``base`` (no checkout touched)."""
    if not (base and branch and gitops.branch_exists(repo, branch)):
        return []
    proc = util.run(
        ["git", "-C", repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", base, branch]
    )
    if proc.returncode == 0:
        return []
    lines = proc.stdout.strip().splitlines()
    return [line for line in lines[1:] if line.strip()]  # first line is the tree id


ACTION_LABELS = {
    "resolve": "Resolve conflicts here",
    "agent-fix": "Let the agent fix it",
    "answer": "Answer and send back",
    "retry-merge": "Retry merge",
    "mark-merged": "Mark merged",
    "merge": "Merge",
    "resume": "Resume",
    "reverify": "Re-verify",
    "unblock": "Unblock (retry later)",
    "run-fresh": "Start over",
    "clean": "Discard work",
    "stash": "Stash changes",
    "commit-base": "Commit changes",
    "push": "Retry push",
    "stop": "Stop",
    "open": "Open run",
}


def _classify_run(run: dict, base_dirty: bool) -> dict:
    state = run.get("state") or ""
    step = str(run.get("step") or "")
    error = str(run.get("error") or "")
    issues = str(run.get("issues") or "")
    kept = bool(run.get("worktree_exists") and run.get("branch_exists"))
    failed_checks = _failed_checks(run)
    base = run.get("base_branch") or "main"
    p: dict = {}

    if step.startswith("merge") or "squash merge" in error:
        if "not clean" in error:
            p = {
                "kind": "dirty-base",
                "headline": f"Merge waiting: the main checkout has uncommitted changes",
                "summary": (
                    f"The task passed and is ready to merge into `{base}`, but the main checkout "
                    "has uncommitted changes, so Agent Room will not touch it."
                ),
                "next": "Commit or stash the changes in the main checkout, then retry the merge.",
                "actions": ["stash", "commit-base", "retry-merge"],
            }
        elif "commit failed" in error:
            p = {
                "kind": "merge-hook",
                "headline": "Merge rejected by a commit hook",
                "summary": f"Squashing into `{base}` worked, but a git hook rejected the commit. The base was reset; the branch still has the work.",
                "next": "Read the hook output below, fix the cause (often a commit-message rule or a lint hook), then retry the merge.",
                "actions": ["agent-fix", "retry-merge", "resolve"],
            }
        else:
            p = {
                "kind": "merge-conflict",
                "headline": f"Merge conflict with `{base}`",
                "summary": (
                    f"The task passed review, but `{base}` changed the same lines since the branch was "
                    "created, so the squash merge stopped. Nothing was merged; the branch keeps its work."
                ),
                "next": "Resolve the conflicting files here (pick a side or edit), or send it back to the agent to merge the base and fix.",
                "actions": ["resolve", "agent-fix", "retry-merge", "mark-merged"],
            }
    elif ACCOUNT.search(error + " " + str(run.get("error_detail") or "")):
        p = {
            "kind": "quota",
            "headline": "The agent's account can't be used (billing or subscription)",
            "summary": f"The {run.get('builder_runner') or 'agent'} CLI refused to start, so every task on this runner fails the same way until the account is fixed or the project switches models.",
            "next": "Fix the billing/subscription for that account, or switch the project's builder and verifier to another runner/model (⚙ models), then resume.",
            "actions": ["resume", "unblock"],
        }
    elif state in {"failed", "needs-human"} and TRANSIENT.search(error + " " + str(run.get("error_detail") or "")):
        p = {
            "kind": "quota",
            "headline": "Model quota or rate limit hit",
            "summary": "The agent CLI stopped because the model refused more requests (quota, rate limit or the model is unavailable). This is not a problem with the task.",
            "next": "Switch the builder/verifier model (⚙ models), or wait for the quota to reset; the supervisor retries automatically.",
            "actions": ["resume", "reverify", "unblock"],
        }
    elif "budget exceeded" in error:
        p = {
            "kind": "budget",
            "headline": "Run stopped at its cost budget",
            "summary": f"The run used more than the configured budget ({error}).",
            "next": "Raise `limits.budget_usd` for the project, or resume with a cheaper model.",
            "actions": ["resume", "clean"],
        }
    elif step == "verification failed" or (state == "needs-human" and run.get("verdict") == "FAIL" and issues):
        p = {
            "kind": "verification-failed",
            "headline": "Verifier rejected the work",
            "summary": f"The verifier read the diff against the acceptance criteria and failed it after {run.get('round') or 0} fix round(s). Its findings are below.",
            "next": "Send it back to the builder with the findings (add your own guidance if the verifier is wrong), or re-verify after fixing by hand.",
            "actions": ["agent-fix", "reverify", "run-fresh", "clean"],
        }
    elif step in {"final checks failed", "checks failed"} or failed_checks:
        names = ", ".join(cmd for cmd, _ in failed_checks) or "a check"
        p = {
            "kind": "checks-failed",
            "headline": f"Checks failing: {names}",
            "summary": "The project's own checks failed on the branch. The failing output is below.",
            "next": "Send it back to the builder with the failure, or fix it in the worktree and re-verify.",
            "actions": ["agent-fix", "reverify", "run-fresh", "clean"],
        }
    elif step == "integration check failed":
        p = {
            "kind": "integration-failed",
            "headline": f"Branch breaks when combined with current `{base}`",
            "summary": f"The branch passes alone, but merging the latest `{base}` into it fails (conflicts or checks).",
            "next": "Let the agent merge the base and fix, or resolve the conflicts here.",
            "actions": ["agent-fix", "resolve", "reverify"],
        }
    elif state == "failed":
        detail = str(run.get("error_detail") or "")
        p = {
            "kind": "build-failed",
            "headline": "The agent run crashed",
            "summary": f"The {('verifier' if 'verif' in (step + error).lower() else 'builder')} stopped with an error before finishing: {(_first_lines(detail or error, 2, 240) or 'no message')}",
            "next": "Read the error below. If it is environmental (missing tool, auth), fix that and resume; otherwise resume with guidance or start over.",
            "actions": ["resume", "agent-fix", "reverify", "run-fresh", "clean"],
        }
    elif "produced no commits" in error or step == "builder failed":
        p = {
            "kind": "build-failed",
            "headline": "Builder finished without committing anything",
            "summary": f"The builder ran {run.get('round') or 1} round(s) but left no commits on the branch, so there is nothing to check or verify. Usually the task was unclear, already done, or the agent got stuck; its notes and the last events are below.",
            "next": "Read the agent's notes. If the work is already in the base, mark the task done; otherwise send it back with clearer guidance or start over.",
            "actions": ["agent-fix", "run-fresh", "clean"],
        }
    elif state == "needs-human":
        p = {
            "kind": "needs-human",
            "headline": f"Stopped at: {step or 'needs a decision'}",
            "summary": "The pipeline stopped and asked for a decision. Everything it recorded is below.",
            "next": "Read the evidence, then send it back to the agent with guidance or re-verify.",
            "actions": ["agent-fix", "reverify", "run-fresh", "clean"],
        }
    elif state == "stopped":
        p = {
            "kind": "stopped",
            "headline": "Run was stopped",
            "summary": f"The run was stopped ({step or 'interrupted'}).",
            "next": "Resume to continue from the existing worktree, or start over.",
            "actions": ["resume", "run-fresh", "clean"],
        }

    if not kept:
        p["actions"] = [a for a in p.get("actions", []) if a not in {"resume", "reverify", "agent-fix", "resolve", "clean"}]
        if p.get("kind") != "dirty-base":
            p["actions"] = [a for a in p["actions"] if a not in {"retry-merge"}] + ["run-fresh"]
            p["summary"] = p.get("summary", "") + " The worktree/branch no longer exists, so it can only start over."
    if base_dirty and p.get("kind") not in {"dirty-base"} and any(
        a in p.get("actions", []) for a in ("retry-merge", "mark-merged")
    ):
        p["warning"] = "The main checkout has uncommitted changes; merging will refuse until they are committed or stashed."
    return p


def _dedupe(seq: list[str]) -> list[str]:
    out: list[str] = []
    for item in seq:
        if item not in out:
            out.append(item)
    return out


def for_project(
    name: str, repo: str, cfg: dict, runs: list[dict], git: dict | None = None, loop_alive: bool = False
) -> list[dict]:
    problems: list[dict] = []
    blocked = tasklib.load_blocked(repo)
    git = git or {}
    base_dirty = git.get("clean") is False
    by_task = {r.get("task"): r for r in runs if r.get("kind", "task") == "task" and r.get("task")}
    seen: set[str] = set()

    for task, run in by_task.items():
        state = run.get("state")
        stalled = run.get("stalled")
        if stalled and state in {"queued", "fixing"}:
            # Requeued work waits for a free builder. That is only a problem
            # when no loop is running to pick it up, and then only after a while.
            updated = util.parse_iso(run.get("updated")) or 0
            stalled = (not loop_alive) and bool(updated and time.time() - updated > 1800)
        if state not in {"needs-human", "failed"} and not stalled and task not in blocked:
            continue
        if state in {"merged", "passed"} and task not in blocked:
            continue
        if stalled:
            waiting = state in {"queued", "fixing"}
            p = {
                "kind": "stalled",
                "headline": "Queued, but no loop is running to pick it up" if waiting else f"Run looks stuck ({state})",
                "summary": (
                    "It is waiting for a builder, but the project's loop is not running."
                    if waiting
                    else f"The run has been `{state}` with no progress for over 10 minutes, or its process died."
                ),
                "next": "Start the loop (or the supervisor), or resume this task directly." if waiting else "Stop it and resume, or wait if a long check is running.",
                "actions": ["resume"] if waiting else ["stop", "resume"],
            }
        else:
            p = _classify_run(run, base_dirty)
        if not p:
            if task in blocked:
                p = {}
            else:
                continue
        if task in blocked:
            reason = str(blocked[task].get("reason") or "")
            p.setdefault("kind", "blocked")
            p.setdefault("headline", "Skipped by the supervisor")
            p.setdefault("summary", "")
            p["blocked"] = {"reason": reason, "at": blocked[task].get("at")}
            p["summary"] = (p["summary"] + f" The supervisor stopped retrying it: {_first_lines(reason, 1, 200)}").strip()
            p.setdefault("next", "Fix the cause, then unblock so the loop picks it up again.")
            p["actions"] = list(p.get("actions") or []) + ["unblock"]
        notes = _read(os.path.join(run.get("run_dir", ""), "notes.md"), 4000).strip()
        if notes and state in {"needs-human", "failed"}:
            p["question"] = _first_lines(notes, 8, 800)
            if run.get("worktree_exists") and run.get("branch_exists"):
                p["actions"] = ["answer"] + list(p.get("actions") or [])
        p["actions"] = _dedupe(list(p.get("actions") or []) + ["open"])
        p.update(
            {
                "id": f"{name}:{task}",
                "project": name,
                "task": task,
                "title": run.get("title") or "",
                "state": "stalled" if stalled else state,
                "step": run.get("step"),
                "since": run.get("finished") or run.get("updated"),
                "has_run": True,
                "worktree_exists": run.get("worktree_exists"),
                "excerpt": _excerpt(run, p),
            }
        )
        p["primary"] = p["actions"][0]
        problems.append(p)
        seen.add(task)

    for task, info in blocked.items():
        if task in seen:
            continue
        reason = str(info.get("reason") or "")
        kind = "merge-conflict" if CONFLICT.search(reason) else "blocked"
        problems.append(
            {
                "id": f"{name}:{task}",
                "project": name,
                "task": task,
                "title": "",
                "kind": kind,
                "state": "blocked",
                "headline": "Skipped by the supervisor",
                "summary": f"The supervisor will not pick this task up: {_first_lines(reason, 2, 300) or 'no reason recorded'}",
                "next": "Unblock it to let the loop retry, or start it over from scratch.",
                "actions": ["unblock", "run-fresh"],
                "primary": "unblock",
                "blocked": {"reason": reason, "at": info.get("at")},
                "since": info.get("at"),
                "has_run": False,
                "excerpt": _first_lines(reason),
            }
        )

    if base_dirty:
        problems.append(
            {
                "id": f"{name}:__base__",
                "project": name,
                "task": "",
                "kind": "dirty-base",
                "state": "blocked",
                "headline": "Main checkout has uncommitted changes",
                "summary": (
                    f"{git.get('changes', 'Some')} file(s) changed in the main checkout on `{git.get('branch', '')}`. "
                    "New runs and merges refuse to start until the checkout is clean."
                ),
                "next": "Commit the changes if they are yours to keep, or stash them (recoverable with `git stash pop`).",
                "actions": ["stash", "commit-base"],
                "primary": "commit-base",
                "since": None,
                "has_run": False,
                "excerpt": "",
            }
        )

    push = util.read_json(os.path.join(repo, ".agent", "push.json"), None) or {}
    if push.get("enabled") and push.get("ok") is False:
        problems.append(
            {
                "id": f"{name}:__push__",
                "project": name,
                "task": "",
                "kind": "push-failed",
                "state": "blocked",
                "headline": f"Push to {push.get('remote') or 'origin'} failed",
                "summary": "Merges are committed locally but not on GitHub.",
                "next": "Read the error (often auth or a diverged remote branch), fix it, then retry the push.",
                "actions": ["push"],
                "primary": "push",
                "since": push.get("checked"),
                "has_run": False,
                "excerpt": _first_lines(str(push.get("error") or "")),
            }
        )
    order = {"merge-conflict": 0, "dirty-base": 1, "verification-failed": 2, "checks-failed": 3}
    problems.sort(key=lambda p: (order.get(p["kind"], 5), p.get("since") or ""))
    return problems


def _excerpt(run: dict, p: dict) -> str:
    if p.get("question"):
        return p["question"]
    if p.get("kind") in {"verification-failed", "integration-failed"}:
        return _first_lines(str(run.get("issues") or ""))
    if p.get("kind") == "checks-failed":
        for cmd, info in _failed_checks(run):
            tail = _read(info.get("log", ""), 3000)
            return f"$ {cmd}\n" + "\n".join(tail.strip().splitlines()[-5:])
    return _first_lines(str(run.get("error_detail") or run.get("error") or run.get("issues") or ""))


def full(name: str, repo: str, cfg: dict, problem: dict, run: dict | None) -> dict:
    """Attach every piece of evidence for one problem."""
    sections: list[dict] = []

    def add(label: str, text: str, kind: str = "text") -> None:
        text = (text or "").strip()
        if text:
            sections.append({"label": label, "text": text, "kind": kind})

    if problem.get("kind") == "dirty-base" and not problem.get("task"):
        status = util.run(["git", "-C", repo, "status", "--short"]).stdout
        add("Changed files in the main checkout", status, "code")
        diff = util.run(["git", "-C", repo, "diff", "--stat"]).stdout
        add("Diff summary", diff, "code")
    if problem.get("kind") == "push-failed":
        push = util.read_json(os.path.join(repo, ".agent", "push.json"), None) or {}
        add("Push error", str(push.get("error") or ""), "code")
    if problem.get("blocked"):
        add("Why the supervisor blocked it", problem["blocked"].get("reason", ""), "code")

    if run:
        directory = run.get("run_dir", "")
        base = run.get("base_branch") or cfg.get("base_branch") or "main"
        notes = _read(os.path.join(directory, "notes.md"), 20000)
        add("The agent's notes / question", notes)
        if problem.get("kind") in {"merge-conflict", "integration-failed", "merge-hook"} or CONFLICT.search(
            str(run.get("error") or "")
        ):
            files = conflict_files(repo, base, run.get("branch", ""))
            problem["conflicts"] = files
            add(
                f"Files that conflict with {base}",
                "\n".join(files) if files else f"No conflicts now: `{base}` and the branch merge cleanly. Retry the merge.",
                "code",
            )
        if str(run.get("issues") or "").strip() not in str(run.get("error") or ""):
            add("Verifier findings", str(run.get("issues") or ""))
        verify = _read(os.path.join(directory, "verify.md"), 30000)
        if verify and verify.strip() != str(run.get("issues") or "").strip():
            add("verify.md (full)", verify)
        for cmd, info in _failed_checks(run):
            add(f"Failing check: {cmd}", _read(info.get("log", ""), 12000), "code")
        add("Error", str(run.get("error") or ""), "code")
        for role in ("builder", "verifier"):
            detail = runners.summarize_error(os.path.join(directory, f"{role}.log"))
            if detail and detail not in str(run.get("error") or ""):
                add(f"{role.title()} log: last error", detail, "code")
        events = util.read_jsonl(os.path.join(directory, "events.ndjson"), limit=25)
        add(
            "Recent events",
            "\n".join(f"{(e.get('ts') or '')[11:19]}  {e.get('actor', ''):<12} {e.get('text', '')}" for e in events),
            "code",
        )
        facts = [
            f"state: {run.get('state')} · step: {run.get('step')}",
            f"branch: {run.get('branch')} → {base}",
            f"worktree: {run.get('worktree')} ({'exists' if run.get('worktree_exists') else 'missing'})",
            f"builder: {run.get('builder_runner')}/{run.get('builder_model') or 'default'} · verifier: {run.get('verifier_runner')}/{run.get('verifier_model') or 'default'}",
            f"rounds: {run.get('round') or 0} · requeues: {run.get('requeue_count') or 0} · cost: ${float(run.get('cost_usd') or 0):.2f}",
        ]
        add("Run facts", "\n".join(facts), "code")
    out = dict(problem)
    out["sections"] = sections
    out["labels"] = {a: ACTION_LABELS.get(a, a) for a in problem.get("actions", [])}
    return out


def agent_fix_note(problem: dict, run: dict, cfg: dict) -> str:
    base = run.get("base_branch") or cfg.get("base_branch") or "main"
    kind = problem.get("kind")
    if kind in {"merge-conflict", "integration-failed"}:
        return (
            f"The branch conflicts with `{base}`. In the worktree run `git merge {base}`, resolve every "
            "conflict keeping both the task's behaviour and the base's changes, keep the acceptance "
            "criteria and tests green, and commit the merge."
        )
    if kind == "merge-hook":
        return "A commit hook rejected the merge commit. Read the hook output in the issues below, fix the cause on the branch, and commit."
    if kind == "checks-failed":
        logs = []
        for cmd, info in _failed_checks(run):
            logs.append(f"$ {cmd}\n" + "\n".join(_read(info.get("log", ""), 6000).strip().splitlines()[-60:]))
        return "These checks fail on the branch. Fix the cause (not the test) and commit:\n\n" + "\n\n".join(logs)
    return ""
