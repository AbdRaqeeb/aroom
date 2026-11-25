"""Asynchronous pipeline: one builder lane, a verifier pool, and a serialized merge queue."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from . import config as project_config
from . import gitops, pipeline, tasks as tasklib, util
from . import supervisor as supervisor_mod

AR_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ar")

BUILDING = {"queued", "briefing", "researching", "building", "checking"}
VERIFYING = {"verifying", "merging"}
BUSY = BUILDING | VERIFYING | {"fixing", "built", "passed"}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] async: {message}", flush=True)


def lanes_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "scheduler.json")


def loop_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "loop.json")


def acquire_loop(repo: str, project: str) -> None:
    path = loop_path(repo)
    payload = {
        "project": project,
        "pid": os.getpid(),
        "started": util.now_iso(),
        "forever": True,
        "mode": "async",
    }
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            util.write_json(path, payload)
            return
        except FileExistsError:
            existing = util.read_json(path, None)
            if existing and util.pid_alive(existing.get("pid")):
                raise SystemExit(f"a loop is already running for {project} (pid {existing.get('pid')})")
            try:
                os.unlink(path)
            except OSError:
                pass
    raise SystemExit(f"could not acquire the loop lock at {path}")


def release_loop(repo: str) -> None:
    data = util.read_json(loop_path(repo), None) or {}
    if data.get("pid") == os.getpid():
        try:
            os.unlink(loop_path(repo))
        except OSError:
            pass


def load_runs(repo: str) -> dict[str, dict]:
    root = os.path.join(repo, ".agent", "runs")
    runs: dict[str, dict] = {}
    if not os.path.isdir(root):
        return runs
    for folder in os.listdir(root):
        run = util.read_json(os.path.join(root, folder, "run.json"), None)
        if run and run.get("kind") == "task" and run.get("task"):
            runs[run["task"]] = run
    return runs


def save_lanes(repo: str, lanes: dict) -> None:
    lanes["updated"] = util.now_iso()
    util.write_json(lanes_path(repo), lanes)


def spawn_child(kind: str, project: str, repo: str, task: str) -> int:
    directory = pipeline.run_dir(repo, task)
    util.ensure_dir(directory)
    command = [sys.executable, AR_MAIN, "_build" if kind == "builder" else "_verify", project, task]
    with open(os.path.join(directory, "daemon.log"), "a", encoding="utf-8") as log_file:
        log_file.write(f"\n=== {util.now_iso()} {' '.join(command)} ===\n")
        log_file.flush()
        proc = subprocess.Popen(
            command,
            cwd=repo,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def stop_pid(pid: int | None) -> None:
    if not pid or not util.pid_alive(pid):
        return
    util.kill_tree(pid, signal.SIGTERM)
    time.sleep(1)
    if util.pid_alive(pid):
        util.kill_tree(pid, signal.SIGKILL)


def run_json(run: dict, repo: str) -> str:
    directory = run.get("run_dir") or pipeline.run_dir(repo, run.get("task", ""))
    util.ensure_dir(directory)
    return os.path.join(directory, "run.json")


def transient(reason: str) -> bool:
    return bool(supervisor_mod.TRANSIENT.search(reason or ""))


def rotate(repo: str, project: str, cfg: dict, task: str) -> dict | None:
    state = supervisor_mod.load_state()
    candidate = supervisor_mod.rotate_model(cfg, project, state, task)
    supervisor_mod.save_state(state)
    return candidate


def reset_primary(repo: str) -> None:
    project_config.update_agents(
        repo,
        {role: dict(supervisor_mod.FALLBACKS[0]) for role in ("builder", "verifier", "researcher")},
    )


def retry_ready(run: dict) -> bool:
    return (util.parse_iso(run.get("retry_after")) or 0) <= time.time()


def fail_build(repo: str, run: dict, reason: str) -> None:
    task = run.get("task", "")
    if transient(reason):
        cfg = project_config.load_project(repo)
        candidate = rotate(repo, run.get("project", ""), cfg, task)
        if candidate:
            run.update(
                {
                    "state": "fixing",
                    "step": f"retry on {candidate['model']}",
                    "issues": reason,
                    "error": reason,
                    "verdict": "FAIL",
                    "finished": None,
                    "updated": util.now_iso(),
                }
            )
            util.write_json(run_json(run, repo), run)
            log(f"{task}: transient failure; switching to {candidate['model']} and retrying")
        else:
            reset_primary(repo)
            retry_at = util.now_iso_after(900)
            run.update(
                {
                    "state": "fixing",
                    "step": "waiting for model quota",
                    "issues": reason,
                    "error": reason,
                    "verdict": "FAIL",
                    "finished": None,
                    "retry_after": retry_at,
                    "updated": util.now_iso(),
                }
            )
            util.write_json(run_json(run, repo), run)
            log(f"{task}: all models limited; retrying on the primary in 15m")
        return
    attempts = int(run.get("build_failures") or 0) + 1
    if attempts <= 1:
        run.update(
            {
                "state": "fixing",
                "step": "builder crashed",
                "issues": reason,
                "error": reason,
                "verdict": "FAIL",
                "finished": None,
                "build_failures": attempts,
                "updated": util.now_iso(),
            }
        )
        util.write_json(run_json(run, repo), run)
        log(f"{task}: build failed, retrying once — {reason[:120]}")
    else:
        run.update(
            {
                "state": "needs-human",
                "step": "builder failed",
                "error": reason,
                "finished": util.now_iso(),
                "build_failures": attempts,
                "updated": util.now_iso(),
            }
        )
        util.write_json(run_json(run, repo), run)
        tasklib.mark_blocked(repo, task, reason)
        log(f"{task}: blocked after repeated build failures — {reason[:120]}")


def fail_verify(repo: str, run: dict, reason: str) -> None:
    task = run.get("task", "")
    if transient(reason):
        cfg = project_config.load_project(repo)
        candidate = rotate(repo, run.get("project", ""), cfg, task)
        if candidate:
            run.update(
                {
                    "state": "built",
                    "step": f"awaiting verifier ({candidate['model']})",
                    "error": reason,
                    "finished": None,
                    "updated": util.now_iso(),
                }
            )
            util.write_json(run_json(run, repo), run)
            log(f"{task}: verifier hit a transient error; switching to {candidate['model']}")
        else:
            reset_primary(repo)
            retry_at = util.now_iso_after(900)
            run.update(
                {
                    "state": "built",
                    "step": "waiting for model quota",
                    "error": reason,
                    "finished": None,
                    "retry_after": retry_at,
                    "updated": util.now_iso(),
                }
            )
            util.write_json(run_json(run, repo), run)
            log(f"{task}: all models limited; verifying on the primary in 15m")
        return
    attempts = int(run.get("verify_failures") or 0) + 1
    if attempts <= 1:
        run.update(
            {
                "state": "built",
                "step": "awaiting verifier (retry)",
                "error": reason,
                "finished": None,
                "verify_failures": attempts,
                "updated": util.now_iso(),
            }
        )
        util.write_json(run_json(run, repo), run)
        log(f"{task}: verifier crashed, retrying once — {reason[:120]}")
    else:
        run.update(
            {
                "state": "needs-human",
                "step": "verifier failed",
                "error": reason,
                "finished": util.now_iso(),
                "verify_failures": attempts,
                "updated": util.now_iso(),
            }
        )
        util.write_json(run_json(run, repo), run)
        tasklib.mark_blocked(repo, task, reason)
        log(f"{task}: blocked after repeated verifier failures — {reason[:120]}")


def recover_orphans(repo: str, lanes: dict, runs: dict[str, dict]) -> None:
    """Runs left in an active state by a reboot/dead scheduler go back to their lane."""
    lane_tasks = set((lanes.get("builders") or {}).keys()) | set(
        (lanes.get("verifiers") or {}).keys()
    )
    for task, run in list(runs.items()):
        state = run.get("state")
        if state not in util.ACTIVE_STATES or task in lane_tasks:
            continue
        if util.pid_alive(run.get("pid")):
            continue
        worktree = run.get("worktree") or ""
        directory = run.get("run_dir") or ""
        if state == "merging":
            marker = os.path.join(repo, ".agent", "merge.json")
            if os.path.exists(marker):
                util.run(["git", "-C", repo, "reset", "--hard", "HEAD"], check=False)
                try:
                    os.unlink(marker)
                except OSError:
                    pass
            run.update(
                {
                    "state": "passed",
                    "step": "ready to merge (recovered after restart)",
                    "finished": None,
                    "updated": util.now_iso(),
                }
            )
        elif state == "verifying":
            run.update(
                {
                    "state": "built",
                    "step": "awaiting verifier (recovered after restart)",
                    "finished": None,
                    "updated": util.now_iso(),
                }
            )
        elif worktree and gitops.worktree_exists(repo, worktree):
            run.update(
                {
                    "state": "fixing",
                    "step": "recovered after restart",
                    "issues": (
                        "The agent process was interrupted by a restart. Inspect the worktree, "
                        "keep useful work, finish the task, run the checks and commit."
                    ),
                    "error": None,
                    "finished": None,
                    "updated": util.now_iso(),
                }
            )
        else:
            run.update(
                {
                    "state": "failed",
                    "step": "interrupted; no worktree",
                    "finished": util.now_iso(),
                    "updated": util.now_iso(),
                }
            )
            tasklib.mark_blocked(repo, task, "interrupted by a restart with no worktree")
        if directory:
            util.write_json(os.path.join(directory, "run.json"), run)
        log(f"{task}: recovered {state} run after restart → {run.get('state')}")


def reap(repo: str, lanes: dict, runs: dict[str, dict]) -> None:
    now = time.time()
    failures = lanes.setdefault("spawn_failures", {})
    builders = lanes.setdefault("builders", {})
    legacy = lanes.pop("builder", None)
    if legacy:
        builders.setdefault(legacy.get("task", ""), legacy)
    for task, entry in list(builders.items()):
        pid = entry.get("pid")
        run = runs.get(task)
        alive = util.pid_alive(pid)
        silent = run and (now - max(util.parse_iso(entry.get("started")) or 0, util.last_activity(run))) > 1200
        if alive and not silent:
            continue
        if silent and alive:
            stop_pid(pid)
        if run and run.get("state") in BUILDING | {"failed"}:
            fail_build(repo, run, run.get("error") or "builder exited without finishing")
        elif not run and task:
            attempts = int(failures.get(task) or 0) + 1
            failures[task] = attempts
            if attempts > 1:
                tasklib.mark_blocked(repo, task, "build failed before creating a run record")
                log(f"{task}: blocked — build failed before creating a run record")
            else:
                log(f"{task}: build failed before creating a run record; retrying once")
        builders.pop(task, None)
    verifiers = lanes.get("verifiers") or {}
    for task, entry in list(verifiers.items()):
        pid = entry.get("pid")
        run = runs.get(task)
        alive = util.pid_alive(pid)
        silent = run and (now - max(util.parse_iso(entry.get("started")) or 0, util.last_activity(run))) > 1200
        if alive and not silent:
            continue
        if silent and alive:
            stop_pid(pid)
        if run and run.get("state") in {"verifying", "failed"}:
            fail_verify(repo, run, run.get("error") or "verifier exited without finishing")
        verifiers.pop(task, None)


def locked_tasks(repo: str) -> set[str]:
    return {
        str(data.get("task"))
        for _, data in pipeline.active_locks(repo)
        if util.pid_alive(data.get("pid"))
    }


def auto_requeue(
    project: str,
    repo: str,
    runs: dict[str, dict],
    blocked: set[str],
    limit: int,
) -> int:
    """Requeue needs-human/failed runs up to a bounded number of times."""
    if limit <= 0:
        return 0
    touched = 0
    blocked_now = set(blocked)
    for task, run in sorted(runs.items(), key=lambda item: item[1].get("updated") or ""):
        state = run.get("state")
        if state not in {"needs-human", "failed"} or task in blocked_now:
            continue
        attempts = int(run.get("requeue_count") or 0)
        if attempts >= limit:
            if state == "needs-human":
                tasklib.mark_blocked(
                    repo, task, f"still needs a human after {attempts} automatic requeues"
                )
                log(f"{task}: blocked after {attempts} automatic requeues")
            blocked_now.add(task)
            continue
        worktree = run.get("worktree") or ""
        if not worktree or not gitops.worktree_exists(repo, worktree):
            tasklib.mark_blocked(repo, task, "needs a human: no worktree to resume")
            blocked_now.add(task)
            log(f"{task}: blocked — no worktree to requeue")
            continue
        try:
            pipeline.requeue_task(
                project,
                task,
                note=(
                    f"Automatic retry {attempts + 1}/{limit} after `{state}`. "
                    "Read the findings, keep useful work, finish the task and commit."
                ),
            )
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            tasklib.mark_blocked(repo, task, f"requeue failed: {exc}")
            blocked_now.add(task)
            log(f"{task}: requeue failed — {exc}")
            continue
        touched += 1
        log(f"{task}: requeued automatically ({attempts + 1}/{limit})")
    return touched


def merge_one(
    repo: str, project: str, lanes: dict, runs: dict[str, dict], blocked: set[str]
) -> bool:
    verifying = set((lanes.get("verifiers") or {}).keys())
    candidates = [
        run
        for run in runs.values()
        if run.get("state") == "passed"
        and run.get("task") not in blocked
        and run.get("task") not in verifying
    ]
    if not candidates:
        return False
    run = min(candidates, key=lambda r: r.get("updated") or "")
    task = run.get("task", "")
    try:
        result = pipeline.merge_run(project, task, auto_fix=True)
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        if "another merge is already running" in str(exc):
            log(f"{task}: another merge is running; will retry")
            return True
        tasklib.mark_blocked(repo, task, f"merge error: {exc}")
        log(f"{task}: merge error — {exc}")
        return True
    if result.get("state") == "merged":
        log(f"{task}: merged {str((result.get('merge') or {}).get('sha', ''))[:8]}")
    elif result.get("state") == "fixing":
        log(f"{task}: merge conflict; back to the builder")
    else:
        reason = (result.get("error") or result.get("step") or "merge failed")
        tasklib.mark_blocked(repo, task, f"merge failed: {reason}")
        log(f"{task}: merge needs a human — {str(reason)[:140]}")
    return True


def fill_verifiers(
    project: str,
    repo: str,
    lanes: dict,
    runs: dict[str, dict],
    blocked: set[str],
    capacity: int,
    locked: set[str] | None = None,
) -> int:
    locked = locked or set()
    verifiers = lanes.setdefault("verifiers", {})
    free = capacity - len(verifiers)
    if free <= 0:
        return 0
    candidates = [
        run
        for run in runs.values()
        if run.get("state") == "built"
        and retry_ready(run)
        and run.get("task") not in blocked
        and run.get("task") not in verifiers
        and run.get("task") not in locked
        and run.get("task") not in (lanes.get("builders") or {})
        and gitops.worktree_exists(run.get("repo", ""), run.get("worktree", ""))
    ]
    candidates.sort(key=lambda r: r.get("updated") or "")
    started = 0
    for run in candidates[:free]:
        task = run.get("task", "")
        pid = spawn_child("verifier", project, repo, task)
        verifiers[task] = {"pid": pid, "started": util.now_iso()}
        log(f"{task}: verifying (pid {pid})")
        started += 1
    return started


def next_builds(
    project: str,
    repo: str,
    lanes: dict,
    runs: dict[str, dict],
    cfg: dict,
    blocked: set[str],
    locked: set[str] | None = None,
    override: int | None = None,
) -> list[str]:
    locked = locked or set()
    builders = lanes.setdefault("builders", {})
    capacity = max(1, int(override or cfg["limits"].get("builders", 1)))
    free = capacity - len(builders)
    if free <= 0:
        return []
    picked: list[str] = []
    fixing = [
        run
        for run in runs.values()
        if run.get("state") == "fixing"
        and run.get("task") not in blocked
        and run.get("task") not in locked
        and run.get("task") not in builders
        and retry_ready(run)
    ]
    for run in sorted(fixing, key=lambda r: r.get("updated") or ""):
        if len(picked) >= free:
            break
        task = run.get("task")
        if task and task not in picked:
            picked.append(task)
    if len(picked) < free:
        task_list = tasklib.load_tasks(cfg)
        blocked_ids = tasklib.blocked_ids(repo)
        for candidate in task_list:
            if len(picked) >= free:
                break
            task_id = candidate["id"]
            if candidate["state"] != " " or task_id in blocked_ids:
                continue
            if task_id in locked or task_id in builders or task_id in picked:
                continue
            existing = runs.get(task_id)
            if existing and existing.get("state") not in {"merged", "stopped"}:
                continue
            worktree = os.path.join(util.expand(cfg["worktree_root"]), util.slug(task_id))
            branch = f"agent/{util.slug(task_id)}"
            if not existing and (
                gitops.worktree_exists(repo, worktree) or gitops.branch_exists(repo, branch)
            ):
                reason = "stale worktree/branch exists without a run record; clean or resume it"
                tasklib.mark_blocked(repo, task_id, reason)
                log(f"{task_id}: blocked — {reason}")
                continue
            picked.append(task_id)
    return picked


def run_async(
    project: str,
    *,
    verifiers: int = 2,
    builders: int | None = None,
    interval: int = 10,
    once: bool = False,
) -> None:
    _, repo, cfg = project_config.find_project(project)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    acquire_loop(repo, project)
    lanes = util.read_json(lanes_path(repo), None) or {}
    if lanes.get("pid") != os.getpid():
        legacy = lanes.get("builder") or {}
        existing_builders = lanes.get("builders") or {}
        if legacy.get("task"):
            existing_builders.setdefault(legacy["task"], legacy)
        existing_verifiers = lanes.get("verifiers") or {}
        lanes = {
            "pid": os.getpid(),
            "started": util.now_iso(),
            "builders": {
                task: entry for task, entry in existing_builders.items() if util.pid_alive(entry.get("pid"))
            },
            "verifiers": {
                task: entry
                for task, entry in existing_verifiers.items()
                if util.pid_alive(entry.get("pid"))
            },
        }
    lanes.pop("builder", None)
    lanes.setdefault("builders", {})
    lanes.setdefault("verifiers", {})
    save_lanes(repo, lanes)
    recover_orphans(repo, lanes, load_runs(repo))
    build_capacity = max(1, int(builders or cfg["limits"].get("builders", 1)))
    log(
        f"starting {project}: {build_capacity} builder(s) + {max(1, verifiers)} verifier(s), "
        f"auto_merge={bool(cfg['limits'].get('auto_merge'))}"
    )
    try:
        while True:
            cfg = project_config.load_project(repo)
            blocked = tasklib.blocked_ids(repo)
            runs = load_runs(repo)
            recover_orphans(repo, lanes, runs)
            runs = load_runs(repo)
            reap(repo, lanes, runs)
            runs = load_runs(repo)
            work = False
            requeue_limit = int(cfg["limits"].get("requeue_attempts", 2))
            if auto_requeue(project, repo, runs, blocked, requeue_limit):
                work = True
                runs = load_runs(repo)
            if cfg["limits"].get("auto_merge"):
                if any(run.get("state") == "passed" for run in runs.values()):
                    save_lanes(repo, lanes)
                work = merge_one(repo, project, lanes, runs, blocked) or work
            locked = locked_tasks(repo)
            capacity = max(1, int(cfg["limits"].get("verifiers", verifiers)))
            if fill_verifiers(project, repo, lanes, runs, blocked, capacity, locked):
                work = True
            for task_id in next_builds(
                project, repo, lanes, runs, cfg, blocked, locked, builders
            ):
                pid = spawn_child("builder", project, repo, task_id)
                lanes.setdefault("builders", {})[task_id] = {
                    "pid": pid,
                    "started": util.now_iso(),
                }
                log(f"{task_id}: building (pid {pid})")
                work = True
            save_lanes(repo, lanes)
            try:
                pipeline.push_if_needed(project)
            except Exception as exc:  # noqa: BLE001
                log(f"push check failed: {exc}")
            runs = load_runs(repo)
            idle = not lanes.get("builders") and not lanes.get("verifiers") and not any(
                run.get("state") in BUSY for run in runs.values()
            )
            if once and idle:
                log("no runnable work; exiting")
                return
            if not work:
                time.sleep(max(2, interval))
    finally:
        children = list((lanes.get("builders") or {}).values()) + list(
            (lanes.get("verifiers") or {}).values()
        )
        for entry in children:
            stop_pid(entry.get("pid"))
        try:
            os.unlink(lanes_path(repo))
        except OSError:
            pass
        release_loop(repo)
