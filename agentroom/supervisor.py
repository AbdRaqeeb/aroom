"""Unattended supervisor: keep loops running, merge passes, retry, block, move on."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from . import config as project_config
from . import pipeline, runners, tasks as tasklib, util

AR_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ar")
LOG_PATH = os.path.join(util.STATE_DIR, "supervisor.log")
PID_PATH = os.path.join(util.STATE_DIR, "supervisor.pid")
STATE_PATH = os.path.join(util.STATE_DIR, "supervisor.json")

FALLBACKS = [
    {"runner": "opencode", "model": "opencode-go/deepseek-v4.1-flash"},
    {"runner": "claude", "model": "sonnet"},
]

TRANSIENT = re.compile(
    r"limit|quota|rate.?limit|429|timeout|timed out|unavailable|no-route|exceeded|connection",
    re.IGNORECASE,
)


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    util.ensure_dir(os.path.dirname(LOG_PATH))
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_state() -> dict:
    data = util.read_json(STATE_PATH, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("projects", {})
    return data


def save_state(state: dict) -> None:
    util.write_json(STATE_PATH, state)


def project_state(state: dict, project: str) -> dict:
    return state["projects"].setdefault(project, {"attempts": {}, "rotations": {}})


def latest_run(repo: str) -> dict | None:
    root = os.path.join(repo, ".agent", "runs")
    if not os.path.isdir(root):
        return None
    runs = []
    for folder in os.listdir(root):
        run = util.read_json(os.path.join(root, folder, "run.json"), None)
        if run and run.get("kind") == "task":
            runs.append(run)
    if not runs:
        return None
    return max(runs, key=lambda r: r.get("updated") or "")


def active(repo: str) -> bool:
    loop = util.read_json(os.path.join(repo, ".agent", "loop.json"), None)
    if loop and util.pid_alive(loop.get("pid")):
        return True
    for _, data in pipeline.active_locks(repo):
        if util.pid_alive(data.get("pid")):
            return True
    return False


def mark_stalled(latest: dict | None) -> dict | None:
    """A run whose process died, or wrote nothing at all for 20m, is marked failed."""
    if not latest or latest.get("state") not in util.ACTIVE_STATES:
        return latest
    pid = latest.get("pid")
    updated = max(util.parse_iso(latest.get("updated")) or 0, util.last_activity(latest))
    silent = updated and (time.time() - updated) > 1200
    if util.pid_alive(pid) and not silent:
        return latest
    if util.pid_alive(pid):
        util.kill_tree(pid)
        time.sleep(1)
        if util.pid_alive(pid):
            util.kill_tree(pid, 9)
    latest["state"] = "failed"
    latest["step"] = "stalled"
    latest["error"] = "run process died or produced no events for 20m; recovered by the supervisor"
    latest["finished"] = util.now_iso()
    if latest.get("run_dir"):
        util.write_json(os.path.join(latest["run_dir"], "run.json"), latest)
    log(f"{latest.get('project')}: {latest.get('task')} was stalled; marked failed")
    return latest


def failure_text(run: dict) -> str:
    text = " ".join(
        str(part or "")
        for part in (
            run.get("error"),
            run.get("issues"),
            runners.summarize_error(os.path.join(run.get("run_dir", ""), "builder.log")),
            runners.summarize_error(os.path.join(run.get("run_dir", ""), "verifier.log")),
        )
    )
    return text.strip()


def spawn(cmd: list[str], repo: str) -> int:
    util.ensure_dir(os.path.dirname(LOG_PATH))
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"\n=== {util.now_iso()} {' '.join(cmd)} ===\n")
        fh.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=repo,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def spawn_loop(project: str, repo: str) -> int:
    return spawn(
        [
            sys.executable,
            AR_MAIN,
            "run",
            project,
            "--loop",
            "--forever",
            "--auto-merge",
            "--interval",
            "10",
        ],
        repo,
    )


def spawn_async(project: str, repo: str, verifiers: int = 2) -> int:
    return spawn(
        [
            sys.executable,
            AR_MAIN,
            "async",
            project,
            "--verifiers",
            str(max(1, verifiers)),
            "--interval",
            "10",
        ],
        repo,
    )


def spawn_resume(project: str, repo: str, task_id: str, note: str = "") -> int:
    cmd = [sys.executable, AR_MAIN, "resume", project, task_id]
    if note:
        cmd.extend(["--note", note])
    return spawn(cmd, repo)


def rotate_model(cfg: dict, project: str, state: dict, task_id: str) -> dict | None:
    repo = cfg["repo"]
    builder = cfg.get("agents", {}).get("builder") or {}
    current = (builder.get("runner"), builder.get("model") or "")
    index = next(
        (i for i, item in enumerate(FALLBACKS) if (item["runner"], item["model"]) == current),
        -1,
    )
    for candidate in FALLBACKS[index + 1 :]:
        if (candidate["runner"], candidate["model"]) == current:
            continue
        log(f"{project}: switching models to {candidate['runner']}/{candidate['model']}")
        try:
            project_config.update_agents(
                repo, {role: dict(candidate) for role in ("builder", "verifier", "researcher")}
            )
        except Exception as exc:  # noqa: BLE001
            log(f"{project}: model switch failed: {exc}")
            return None
        project_state(state, project)["rotations"][task_id] = index + 1
        save_state(state)
        return candidate
    return None


def run_once(projects: list[str] | None = None) -> None:
    registered = project_config.project_paths()
    names = projects or [
        name for name, repo in registered.items() if os.path.isfile(project_config.config_path(repo))
    ]
    state = load_state()
    for project in names:
        repo = util.expand(registered.get(project, ""))
        if not repo or not os.path.isdir(repo):
            log(f"{project}: missing repo")
            continue
        try:
            cfg = project_config.load_project(repo)
        except Exception as exc:  # noqa: BLE001
            log(f"{project}: config error: {exc}")
            continue
        if cfg["limits"].get("async"):
            loop = util.read_json(os.path.join(repo, ".agent", "loop.json"), None) or {}
            lanes = util.read_json(os.path.join(repo, ".agent", "scheduler.json"), None) or {}
            if util.pid_alive(loop.get("pid")):
                if loop.get("mode") == "async":
                    beat = util.parse_iso(lanes.get("updated")) or util.parse_iso(loop.get("started")) or 0
                    if beat and time.time() - beat > 600:
                        log(f"{project}: async scheduler went silent; restarting")
                        util.kill_tree(loop.get("pid"))
                        try:
                            os.unlink(os.path.join(repo, ".agent", "loop.json"))
                        except OSError:
                            pass
                continue
            verifiers = int(cfg["limits"].get("verifiers", 2))
            log(f"{project}: starting async pipeline (builder + {verifiers} verifiers)")
            pid = spawn_async(project, repo, verifiers)
            log(f"{project}: async pid {pid}")
            continue
        latest = latest_run(repo)
        latest = mark_stalled(latest)
        if active(repo):
            continue

        auto = bool(cfg["limits"].get("auto_merge"))
        pstate = project_state(state, project)
        if latest and latest.get("task") in tasklib.blocked_ids(repo):
            latest = None

        if latest:
            run_state = latest.get("state")
            task_id = latest.get("task", "")
            if run_state == "passed" and auto:
                log(f"{project}: merging passed {task_id}")
                try:
                    result = pipeline.merge_run(project, task_id)
                    log(f"{project}: {task_id} → {result.get('state')}")
                    if result.get("state") != "merged":
                        tasklib.mark_blocked(repo, task_id, "merge failed; needs a human")
                except Exception as exc:  # noqa: BLE001
                    log(f"{project}: merge error: {exc}")
                    tasklib.mark_blocked(repo, task_id, f"merge error: {exc}")
                continue

            retry_merge = (
                run_state == "needs-human"
                and latest.get("verdict") == "PASS"
                and str(latest.get("step", "")).startswith("merge")
            )
            if retry_merge and auto:
                log(f"{project}: retrying merge for {task_id}")
                try:
                    result = pipeline.merge_run(project, task_id)
                    if result.get("state") != "merged":
                        tasklib.mark_blocked(repo, task_id, "merge failed; needs a human")
                except Exception as exc:  # noqa: BLE001
                    log(f"{project}: merge error: {exc}")
                    tasklib.mark_blocked(repo, task_id, f"merge error: {exc}")
                continue

            if run_state in {"failed", "needs-human"}:
                text = failure_text(latest)
                transient = bool(TRANSIENT.search(text))
                attempts = int(pstate["attempts"].get(task_id) or 0)
                rotations = int(pstate["rotations"].get(task_id) or 0)
                if transient:
                    if rotations < len(FALLBACKS) - 1:
                        rotated = rotate_model(cfg, project, state, task_id)
                        if rotated:
                            pstate["rotations"][task_id] = rotations + 1
                            pstate["attempts"][task_id] = attempts + 1
                            save_state(state)
                            log(f"{project}: resuming {task_id} on {rotated['model']}")
                            spawn_resume(project, repo, task_id)
                            continue
                    waits = pstate.setdefault("wait", {})
                    wait_until = float(waits.get(task_id) or 0)
                    now = time.time()
                    if wait_until and now < wait_until:
                        continue
                    if wait_until and now >= wait_until:
                        log(f"{project}: retrying {task_id} on the primary model")
                        project_config.update_agents(
                            repo,
                            {role: dict(FALLBACKS[0]) for role in ("builder", "verifier", "researcher")},
                        )
                        waits.pop(task_id, None)
                        pstate["rotations"].pop(task_id, None)
                        pstate["attempts"].pop(task_id, None)
                        save_state(state)
                        spawn_resume(project, repo, task_id)
                        continue
                    waits[task_id] = now + 900
                    pstate["rotations"].pop(task_id, None)
                    pstate["attempts"].pop(task_id, None)
                    save_state(state)
                    log(f"{project}: all models limited; retrying {task_id} in 15m")
                    continue
                if attempts < 1:
                    pstate["attempts"][task_id] = attempts + 1
                    save_state(state)
                    note = "The previous attempt failed. Read the brief, notes.md and verify.md, fix the cause, and finish."
                    log(f"{project}: retrying {task_id} once")
                    spawn_resume(project, repo, task_id, note)
                    continue
                log(f"{project}: blocking {task_id} — {text[:180] or 'needs a human'}")
                tasklib.mark_blocked(repo, task_id, text or "needs a human")
                pstate["attempts"].pop(task_id, None)
                pstate["rotations"].pop(task_id, None)
                pstate.setdefault("wait", {}).pop(task_id, None)
                save_state(state)
                continue

            if run_state == "passed" and not auto:
                log(f"{project}: {task_id} passed; auto_merge is off (human gate)")
                continue

        open_task = tasklib.next_task(tasklib.load_tasks(cfg), tasklib.blocked_ids(repo))
        if not open_task:
            continue
        log(f"{project}: starting forever loop at {open_task['id']}")
        pid = spawn_loop(project, repo)
        log(f"{project}: loop pid {pid}")


def supervise(projects: list[str] | None = None, interval: int = 60, once: bool = False) -> None:
    if not once:
        util.write_json(
            PID_PATH,
            {"pid": os.getpid(), "started": util.now_iso(), "interval": interval},
        )
    log(f"supervisor starting (interval {interval}s, once={once})")
    try:
        while True:
            try:
                run_once(projects)
            except Exception as exc:  # noqa: BLE001
                log(f"supervisor error: {exc}")
            if once:
                return
            time.sleep(max(15, interval))
    finally:
        data = util.read_json(PID_PATH, None) or {}
        if data.get("pid") == os.getpid():
            try:
                os.unlink(PID_PATH)
            except OSError:
                pass
