"""Local dashboard: reads every registered project's run files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config as project_config
from . import chat, gitops, models, pipeline, preview, runners, sessions, tasks as tasklib, util

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
AR_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ar")


def _elapsed(run: dict) -> int:
    start = util.parse_iso(run.get("started"))
    if not start:
        return 0
    end = util.parse_iso(run.get("finished")) or time.time()
    return max(0, int(end - start))


def _stalled(run: dict) -> bool:
    if run.get("state") not in util.ACTIVE_STATES:
        return False
    if not util.pid_alive(run.get("pid")):
        return True
    updated = util.parse_iso(run.get("updated"))
    return bool(updated and time.time() - updated > 600)


def _events(directory: str, limit: int = 6) -> list[dict]:
    return util.read_jsonl(os.path.join(directory, "events.ndjson"), limit=limit)


def _summary(run: dict, events: int = 6, probe: bool = False) -> dict:
    out = {
        key: run.get(key)
        for key in (
            "run_id",
            "kind",
            "project",
            "task",
            "title",
            "state",
            "step",
            "round",
            "started",
            "updated",
            "finished",
            "branch",
            "base_branch",
            "base_sha",
            "pid",
            "cost_usd",
            "checks",
            "verdict",
            "error",
            "merge",
            "files_changed",
            "insertions",
            "deletions",
            "commits",
            "last_event",
            "run_dir",
            "worktree",
            "output",
            "research",
            "research_output",
            "builder_runner",
            "builder_model",
            "verifier_runner",
            "verifier_model",
            "researcher_runner",
            "researcher_model",
            "issues",
        )
    }
    out["elapsed_s"] = _elapsed(run)
    out["pid_alive"] = util.pid_alive(run.get("pid"))
    out["stalled"] = _stalled(run)
    out["events"] = _events(run.get("run_dir", ""), events) if events else []
    if run.get("state") == "failed":
        detail = runners.summarize_error(os.path.join(run.get("run_dir", ""), "builder.log"))
        if not detail:
            detail = runners.summarize_error(os.path.join(run.get("run_dir", ""), "verifier.log"))
        if detail:
            out["error_detail"] = detail
    if probe:
        repo = run.get("repo", "")
        worktree = run.get("worktree", "")
        branch = run.get("branch", "")
        out["worktree_exists"] = bool(repo and worktree and gitops.worktree_exists(repo, worktree))
        out["branch_exists"] = bool(repo and branch and gitops.branch_exists(repo, branch))
    return out


def _read(path: str, limit: int = 60000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()[-limit:]
    except OSError:
        return ""


def project_state(name: str, repo: str, external: list[dict] | None = None) -> dict:
    entry: dict = {"name": name, "path": repo, "configured": False}
    entry["git"] = gitops_state(repo)
    ext = external if external is not None else sessions.all_sessions()
    entry["sessions"] = sessions.for_project(ext, repo)
    if not os.path.isfile(project_config.config_path(repo)):
        return entry
    try:
        cfg = project_config.load_project(repo)
    except Exception as exc:  # noqa: BLE001
        entry["error"] = str(exc)
        return entry
    entry["configured"] = True
    entry["base_branch"] = cfg["base_branch"]
    entry["tasks_file"] = cfg["tasks"].get("file")
    entry["worktree_root"] = cfg["worktree_root"]
    entry["agents"] = {
        role: {
            "runner": (cfg.get("agents", {}).get(role) or {}).get("runner", ""),
            "model": (cfg.get("agents", {}).get(role) or {}).get("model", ""),
        }
        for role in ("builder", "verifier", "researcher")
    }
    entry["preview"] = preview.status(cfg)
    chat_state = chat.load(repo)
    entry["chat"] = {
        "status": chat_state.get("status", "idle"),
        "messages": len(chat_state.get("messages") or []),
    }
    try:
        task_list = tasklib.load_tasks(cfg)
    except Exception as exc:  # noqa: BLE001
        task_list = []
        entry["tasks_error"] = str(exc)
    entry["counts"] = tasklib.counts(task_list)
    blocked = tasklib.blocked_ids(repo)
    entry["blocked"] = tasklib.load_blocked(repo)
    entry["tasks"] = [
        {"id": t["id"], "title": t["title"], "state": t["state"], "acceptance": len(t["acceptance"])}
        for t in task_list
    ]
    entry["next"] = [
        {"id": t["id"], "title": t["title"], "acceptance": len(t["acceptance"])}
        for t in task_list
        if t["state"] == " " and t["id"] not in blocked
    ][:6]
    loop = util.read_json(os.path.join(repo, ".agent", "loop.json"), None)
    entry["loop"] = (
        {
            "pid": loop.get("pid"),
            "started": loop.get("started"),
            "mode": loop.get("mode") or "sync",
            "alive": util.pid_alive(loop.get("pid")),
        }
        if loop
        else None
    )

    runs_root = os.path.join(repo, ".agent", "runs")
    runs: list[dict] = []
    if os.path.isdir(runs_root):
        for folder in os.listdir(runs_root):
            run = util.read_json(os.path.join(runs_root, folder, "run.json"), None)
            if run:
                runs.append(run)
    runs.sort(key=lambda r: r.get("updated") or "", reverse=True)
    entry["runs"] = [_summary(r, events=0) for r in runs[:8]]
    entry["push"] = util.read_json(os.path.join(repo, ".agent", "push.json"), None)
    entry["cost_today"] = round(
        sum(float(r.get("cost_usd") or 0) for r in runs if (r.get("started") or "").startswith(util.today())),
        2,
    )

    active = [r for r in runs if r.get("state") in util.ACTIVE_STATES | util.WAITING_STATES]
    builders = [
        r
        for r in active
        if r.get("state") in {"queued", "briefing", "researching", "building", "checking", "fixing"}
    ]
    builders.sort(key=lambda r: r.get("started") or "")
    builder = builders[0] if builders else None
    verifying = [r for r in active if r.get("state") == "verifying"]
    waiting = [r for r in active if r.get("state") == "built"]
    entry["mode"] = "async" if cfg["limits"].get("async") else "sync"
    entry["lanes"] = {
        "builders": [_summary(r, events=0, probe=True) for r in builders],
        "builder": _summary(builder, events=0, probe=True) if builder else None,
        "verifiers": [_summary(r, events=0, probe=True) for r in verifying],
        "waiting": [_summary(r, events=0, probe=True) for r in waiting],
        "capacity": int(cfg["limits"].get("verifiers", 1)),
        "build_capacity": int(cfg["limits"].get("builders", 1)),
    }
    entry["active_ids"] = [r.get("task") for r in active if r.get("task")]
    active_ids = set(entry["active_ids"])
    used_ids = {
        r.get("task") for r in runs if r.get("task") and r.get("state") not in {"merged", "stopped"}
    }
    entry["next"] = [
        task for task in entry["next"] if task["id"] not in active_ids | used_ids
    ]
    current = builder or next((r for r in runs if r.get("state") in util.ACTIVE_STATES), None)
    attention = next(
        (
            r
            for r in runs
            if r.get("state") in {"passed", "needs-human", "failed"}
            and r.get("kind") == "task"
        ),
        None,
    )
    entry["current"] = _summary(current, events=8, probe=True) if current else None
    entry["attention"] = _summary(attention, events=4, probe=True) if attention else None
    return entry


def gitops_state(repo: str) -> dict:
    try:
        return gitops.detail(repo)
    except Exception:  # noqa: BLE001
        return {"branch": "", "clean": True, "head": "", "short": "", "subject": ""}


def build_state() -> dict:
    reg = project_config.load_registry()
    external = sessions.all_sessions()
    projects = []
    running = todo = done = 0
    cost_today = 0.0
    for name, path in sorted(reg["projects"].items()):
        entry = project_state(name, util.expand(path), external)
        projects.append(entry)
        if not entry.get("configured"):
            continue
        if entry.get("current") or (entry.get("loop") or {}).get("alive"):
            running += 1
        todo += int(entry.get("counts", {}).get("todo", 0))
        done += int(entry.get("counts", {}).get("done", 0))
        cost_today += float(entry.get("cost_today") or 0)
    return {
        "generated": util.now_iso(),
        "totals": {
            "projects": len(projects),
            "running": running,
            "todo": todo,
            "done": done,
            "cost_today": round(cost_today, 2),
        },
        "supervisor": supervisor_status(),
        "projects": projects,
        "external": sessions.unregistered(external, reg["projects"]),
    }


def supervisor_status() -> dict:
    data = util.read_json(os.path.join(util.STATE_DIR, "supervisor.pid"), None) or {}
    return {"pid": data.get("pid"), "alive": util.pid_alive(data.get("pid"))}


def run_detail(project: str, task: str) -> dict:
    _, repo, cfg = project_config.find_project(project)
    directory = pipeline.run_dir(repo, task)
    run = util.read_json(os.path.join(directory, "run.json"), None)
    if not run:
        raise KeyError(task)
    detail = _summary(run, events=0, probe=True)
    detail["events"] = util.read_jsonl(os.path.join(directory, "events.ndjson"), limit=400)
    detail["brief"] = _read(os.path.join(directory, "brief.md"), 60000)
    detail["verify"] = _read(os.path.join(directory, "verify.md"), 60000)
    detail["diff"] = _read(os.path.join(directory, "diff.patch"), 240000)
    detail["notes"] = _read(os.path.join(directory, "notes.md"), 20000)
    checks = {}
    for command, info in (run.get("checks") or {}).items():
        checks[command] = dict(info, tail=_read(info.get("log", ""), 20000))
    detail["checks"] = checks
    return detail


def start_run(payload: dict) -> dict:
    project = payload.get("project")
    name, repo, cfg = project_config.find_project(project)
    clean, status = gitops.is_clean(repo)
    if not clean:
        raise SystemExit(
            f"{name} has uncommitted changes:\n{status}\n"
            "Commit or stash them before starting a run."
        )
    directory = util.ensure_dir(os.path.join(repo, ".agent"))
    command = [sys.executable, AR_MAIN, "run", name]
    task = (payload.get("task") or "").strip()
    if task and not payload.get("loop"):
        command.append(task)
    if payload.get("loop"):
        command.append("--loop")
    if payload.get("forever"):
        command.append("--forever")
    if payload.get("auto_merge"):
        command.append("--auto-merge")
    if payload.get("max_tasks"):
        command.extend(["--max-tasks", str(int(payload["max_tasks"]))])
    if payload.get("mock"):
        command.append("--mock")
    log_path = os.path.join(directory, "daemon.log")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n=== {util.now_iso()} {' '.join(command)} ===\n")
        log.flush()
        proc = subprocess.Popen(
            command,
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"pid": proc.pid, "log": log_path, "command": command}


def start_resume(payload: dict) -> dict:
    project = payload.get("project")
    task = (payload.get("task") or "").strip()
    name, repo, cfg = project_config.find_project(project)
    if not task:
        raise SystemExit("task is required for resume")
    directory = pipeline.run_dir(repo, task)
    run = util.read_json(os.path.join(directory, "run.json"), None)
    if not run:
        raise SystemExit(f"no run record for {project} {task}")
    if run.get("state") == "merged":
        raise SystemExit(f"{task} is already merged")
    if run.get("state") == "passed":
        raise SystemExit(f"{task} already passed; use merge, not resume")
    if str(run.get("step", "")).startswith("merge"):
        raise SystemExit(
            f"{task} is a merge conflict. Commit the resolved squash merge, then use "
            f"`mark merged` (aroom adopt {project} {task})."
        )
    worktree = run.get("worktree") or os.path.join(util.expand(cfg["worktree_root"]), util.slug(task))
    if not gitops.worktree_exists(repo, worktree):
        raise SystemExit(f"{task} has no worktree to resume; use merge or clean")
    project_config.commit_config(repo)
    clean, status = gitops.is_clean(repo)
    if not clean:
        raise SystemExit(
            f"{repo} is not clean; commit or stash the conflict resolution first:\n{status}"
        )
    tasklib.unmark_blocked(repo, task)
    directory = util.ensure_dir(os.path.join(repo, ".agent"))
    command = [sys.executable, AR_MAIN, "resume", name, task]
    if payload.get("note"):
        command.extend(["--note", str(payload["note"])])
    if payload.get("allow_lockfile"):
        command.append("--allow-lockfile")
    for role in ("builder", "verifier", "researcher"):
        values = payload.get(role) or {}
        if values.get("runner"):
            command.extend([f"--{role}-runner", str(values["runner"])])
        if values.get("model"):
            command.extend([f"--{role}-model", str(values["model"])])
    log_path = os.path.join(directory, "daemon.log")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n=== {util.now_iso()} {' '.join(command)} ===\n")
        log.flush()
        proc = subprocess.Popen(
            command,
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"pid": proc.pid, "log": log_path, "command": command}


def start_verify(payload: dict) -> dict:
    project = payload.get("project")
    task = (payload.get("task") or "").strip()
    name, repo, cfg = project_config.find_project(project)
    if not task:
        raise SystemExit("task is required for verify")
    directory = util.ensure_dir(os.path.join(repo, ".agent"))
    command = [sys.executable, AR_MAIN, "verify", name, task]
    if payload.get("runner"):
        command.extend(["--runner", str(payload["runner"])])
    if payload.get("model"):
        command.extend(["--model", str(payload["model"])])
    log_path = os.path.join(directory, "daemon.log")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n=== {util.now_iso()} {' '.join(command)} ===\n")
        log.flush()
        proc = subprocess.Popen(
            command,
            cwd=repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"pid": proc.pid, "log": log_path, "command": command}


def update_project_config(payload: dict) -> dict:
    name, repo, cfg = project_config.find_project(payload.get("project"))
    agents = payload.get("agents") or {}
    if not isinstance(agents, dict):
        raise ValueError("agents must be an object")
    project_config.update_agents(repo, agents)
    return {"project": name, "agents": project_config.load_project(repo).get("agents")}


def add_project(path: str) -> dict:
    project, repo, cfg = project_config.init_project(path)
    return {"project": project, "path": repo}


def track_project(path: str) -> dict:
    project, repo = project_config.register(path)
    return {"project": project, "path": repo}


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-room/1"

    def log_message(self, *args):  # noqa: D401
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in {"/", "/index.html"}:
            path = os.path.join(ASSETS, "index.html")
            try:
                with open(path, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            except OSError:
                self._error("dashboard asset missing", 500)
            return
        if parsed.path == "/api/health":
            self._json({"ok": True})
            return
        if parsed.path == "/api/state":
            self._json(build_state())
            return
        if parsed.path == "/api/git":
            project = (query.get("project") or [""])[0]
            name, repo, _ = project_config.find_project(project)
            payload = {"project": name, "git": gitops.detail(repo)}
            payload.update(gitops.inventory(repo))
            self._json(payload)
            return
        if parsed.path == "/api/models":
            self._json(models.list_models())
            return
        if parsed.path == "/api/session":
            sid = (query.get("id") or [""])[0]
            try:
                self._json(sessions.detail(sid))
            except KeyError:
                self._error("session not found", 404)
            return
        if parsed.path == "/api/preview/log":
            project = (query.get("project") or [""])[0]
            lines = int((query.get("lines") or ["300"])[0])
            try:
                self._json(preview.tail(project, lines))
            except SystemExit as exc:
                self._error(str(exc), 404)
            return
        if parsed.path == "/api/chat":
            project = (query.get("project") or [""])[0]
            name, repo, _ = project_config.find_project(project)
            data = chat.load(repo)
            data["pid_alive"] = util.pid_alive(data.get("pid"))
            if data.get("status") == "running" and not data["pid_alive"]:
                data["status"] = "stalled"
            self._json(data)
            return
        if parsed.path == "/api/run":
            project = (query.get("project") or [""])[0]
            task = (query.get("task") or [""])[0]
            try:
                self._json(run_detail(project, task))
            except SystemExit as exc:
                self._error(str(exc), 404)
            except KeyError:
                self._error("run not found", 404)
            return
        self._error("not found", 404)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        payload = self._body()
        try:
            if parsed.path == "/api/run":
                self._json(start_run(payload))
                return
            if parsed.path == "/api/stop":
                ok = pipeline.stop(payload.get("project", ""))
                self._json({"stopped": ok})
                return
            if parsed.path == "/api/verify":
                self._json(start_verify(payload))
                return
            if parsed.path == "/api/resume":
                self._json(start_resume(payload))
                return
            if parsed.path == "/api/clean":
                task = (payload.get("task") or "").strip()
                if not task:
                    self._error("task is required", 400)
                    return
                ok = pipeline.clean_task(payload.get("project", ""), task)
                self._json({"removed": ok})
                return
            if parsed.path == "/api/unblock":
                task = (payload.get("task") or "").strip()
                name, repo, _ = project_config.find_project(payload.get("project"))
                if not task:
                    self._error("task is required", 400)
                    return
                ok = tasklib.unmark_blocked(repo, task)
                self._json({"unblocked": ok})
                return
            if parsed.path == "/api/preview":
                project = payload.get("project", "")
                action = payload.get("action", "start")
                if action == "stop":
                    self._json(preview.stop(project))
                elif action == "restart":
                    self._json(preview.restart(project))
                else:
                    self._json(preview.start(project))
                return
            if parsed.path == "/api/chat":
                self._json(chat.send(payload.get("project", ""), str(payload.get("message") or "")))
                return
            if parsed.path == "/api/project/config":
                self._json(update_project_config(payload))
                return
            if parsed.path == "/api/adopt":
                run = pipeline.mark_merged(
                    payload.get("project", ""), payload.get("task")
                )
                self._json({"state": run["state"], "merge": run.get("merge")})
                return
            if parsed.path == "/api/merge":
                run = pipeline.merge_run(
                    payload.get("project", ""),
                    payload.get("task"),
                    force=bool(payload.get("force")),
                )
                self._json({"state": run["state"], "merge": run.get("merge")})
                return
            if parsed.path == "/api/projects":
                self._json(add_project(payload.get("path", "")))
                return
            if parsed.path == "/api/track":
                self._json(track_project(payload.get("path", "")))
                return
        except SystemExit as exc:
            self._error(str(exc), 400)
            return
        except Exception as exc:  # noqa: BLE001
            self._error(f"{type(exc).__name__}: {exc}", 500)
            return
        self._error("not found", 404)


def serve(host: str | None = None, port: int | None = None, open_browser: bool = True) -> None:
    reg = project_config.load_registry()
    host = host or reg["ui"].get("host", "127.0.0.1")
    port = int(port or reg["ui"].get("port", 4400))
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
    print(f"agent room → {url}")
    print(f"watching {len(reg['projects'])} project(s); Ctrl+C to stop")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
