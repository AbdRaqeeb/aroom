"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import config as project_config
from . import __version__
from . import async_loop, chat, gitops, models, pipeline, preview, supervisor, ui, util

VERSION = __version__
AR_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ar")


def cmd_init(args) -> int:
    project, repo, cfg = project_config.init_project(args.path or ".", args.name)
    print(f"initialised {project} at {repo}")
    print(f"  base branch   {cfg['base_branch']}")
    print(f"  tasks         {cfg['tasks'].get('file')}  (adapter: {cfg['tasks'].get('adapter')})")
    print(f"  checks        {', '.join(cfg['commands'].get('checks') or []) or '(none detected)'}")
    print(f"  e2e           {cfg['commands'].get('e2e') or '(none)'}")
    print(f"  worktrees     {cfg['worktree_root']}")
    print(f"  config        {project_config.config_path(repo)}")
    print(f"  env hook      {os.path.join(repo, '.agent', 'env.sh')}")
    notes = cfg.get("hygiene_notes") or []
    for note in notes:
        print(f"  {note}")
    status = util.run(
        ["git", "-C", repo, "status", "--porcelain", "--", ".agent", ".gitignore", ".gitattributes", ".editorconfig"]
    )
    if status.stdout.strip():
        print()
        print("note: commit the agent-room files before the first run:")
        print(
            f"      git -C {repo} add .agent .gitignore .gitattributes .editorconfig && "
            f"git -C {repo} commit -m 'chore: add agent room config'"
        )
    return 0


def cmd_add(args) -> int:
    project, repo, cfg = project_config.init_project(args.path, args.name)
    print(f"added {project} → {repo}")
    return 0


def cmd_track(args) -> int:
    project, repo = project_config.register(args.path, args.name)
    print(f"tracking {project} → {repo}")
    print("read-only: no .agent files written. Run `aroom init` there to manage tasks.")
    return 0


def cmd_remove(args) -> int:
    if project_config.unregister(args.project):
        print(f"removed {args.project}")
        return 0
    print(f"not registered: {args.project}")
    return 1


def cmd_projects(_args) -> int:
    paths = project_config.project_paths()
    if not paths:
        print("no projects registered. Try: aroom init /path/to/repo")
        return 0
    width = max(len(name) for name in paths)
    for name, repo in sorted(paths.items()):
        if not os.path.isfile(project_config.config_path(repo)):
            print(f"{name:<{width}}  {'tracked (no config)':<22}  {repo}")
            continue
        cfg = project_config.load_project(repo)
        try:
            counts = pipeline.tasklib.counts(pipeline.tasklib.load_tasks(cfg))
            stat = f"{counts['todo']} open / {counts['done']} done"
        except Exception:  # noqa: BLE001
            stat = "unreadable tasks"
        print(f"{name:<{width}}  {stat:<22}  {repo}")
    return 0


def cmd_status(args) -> int:
    state = ui.build_state()
    if args.json:
        print(json.dumps(state, indent=2))
        return 0
    totals = state["totals"]
    print(
        f"agent room · {totals['projects']} projects · {totals['running']} running · "
        f"{totals['todo']} todo · ${totals['cost_today']:.2f} today"
    )
    print()
    header = f"{'PROJECT':<14} {'TASK':<14} {'STATE':<12} {'STEP':<24} {'ELAPSED':>8} {'COST':>7}"
    print(header)
    print("-" * len(header))
    for project in state["projects"]:
        if not project.get("configured"):
            print(f"{project['name']:<14} {'-':<14} {'unconfigured':<12} {'-':<24} {'-':>8} {'-':>7}")
            continue
        run = project.get("current") or project.get("attention")
        if not run and (project.get("loop") or {}).get("alive"):
            nxt = (project.get("next") or [{}])[0]
            print(
                f"{project['name']:<14} {nxt.get('id', '-'):<14} {'looping':<12} "
                f"{'between tasks':<24} {'-':>8} {'-':>7}"
            )
            continue
        if not run:
            next_task = (project.get("next") or [{}])[0]
            print(
                f"{project['name']:<14} {next_task.get('id', '-'):<14} {'idle':<12} "
                f"{'next: ' + (next_task.get('title') or '-')[:22]:<24} {'-':>8} {'-':>7}"
            )
            continue
        print(
            f"{project['name']:<14} {run.get('task', '-'):<14} {run.get('state', '-'):<12} "
            f"{(run.get('step') or '')[:23]:<24} "
            f"{util.human_duration(run.get('elapsed_s')):>8} "
            f"${float(run.get('cost_usd') or 0):>6.2f}"
        )
        lanes = project.get("lanes") or {}
        for extra in lanes.get("builders") or []:
            if extra.get("task") == run.get("task"):
                continue
            print(
                f"{'':<14} ↳ build   {extra.get('task', '-'):<14} "
                f"{(extra.get('step') or '')[:23]:<24} "
                f"{util.human_duration(extra.get('elapsed_s')):>8}"
            )
        for verifier in lanes.get("verifiers") or []:
            if verifier.get("task") == run.get("task") and run.get("state") == "verifying":
                continue
            print(
                f"{'':<14} ↳ verify  {verifier.get('task', '-'):<14} "
                f"{(verifier.get('step') or '')[:23]:<24} "
                f"{util.human_duration(verifier.get('elapsed_s')):>8}"
            )
        waiting = lanes.get("waiting") or []
        if waiting:
            print(
                f"{'':<14} ↳ waiting {', '.join(str(w.get('task')) for w in waiting):<14} "
                f"{'built, awaiting verifier':<24}"
            )
        queued = lanes.get("queued") or []
        if queued:
            print(
                f"{'':<14} ↳ queue   {str(len(queued)) + ' task(s)':<14} "
                f"{'waiting for a builder slot':<24}"
            )
    return 0


def cmd_next(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    blocked = pipeline.tasklib.blocked_ids(repo)
    runs_root = os.path.join(repo, ".agent", "runs")
    if os.path.isdir(runs_root):
        for folder in os.listdir(runs_root):
            run = util.read_json(os.path.join(runs_root, folder, "run.json"), None) or {}
            if run.get("task") and run.get("state") not in {"merged", "stopped"}:
                blocked.add(run["task"])
    task = pipeline.tasklib.next_task(pipeline.tasklib.load_tasks(cfg), blocked)
    if not task:
        print(f"{project}: no open tasks")
        return 0
    print(f"{task['id']} — {task['title']}")
    if task["acceptance"]:
        print()
        for item in task["acceptance"]:
            print(f"  - {item}")
    return 0


def overrides_from_args(args) -> dict:
    overrides: dict = {}
    for role in ("builder", "verifier", "researcher"):
        runner = getattr(args, f"{role}_runner", None)
        model = getattr(args, f"{role}_model", None)
        if runner is not None or model is not None:
            overrides[role] = {"runner": runner, "model": model}
    return overrides


def cmd_run(args) -> int:
    if args.mock:
        os.environ["AR_MOCK"] = "1"
    if args.forever:
        args.loop = True
    overrides = overrides_from_args(args)

    project, repo, cfg = project_config.find_project(args.project)
    if args.detach:
        command = [sys.executable, AR_MAIN, "run"]
        command.append(project)
        if args.task and not args.loop:
            command.append(args.task)
        if args.loop:
            command.append("--loop")
        if args.forever:
            command.append("--forever")
        if args.auto_merge:
            command.append("--auto-merge")
        if args.max_tasks:
            command.extend(["--max-tasks", str(args.max_tasks)])
        if args.interval:
            command.extend(["--interval", str(args.interval)])
        if args.fresh:
            command.append("--fresh")
        if args.mock:
            command.append("--mock")
        for role in ("builder", "verifier", "researcher"):
            if getattr(args, f"{role}_runner", None):
                command.extend([f"--{role}-runner", getattr(args, f"{role}_runner")])
            if getattr(args, f"{role}_model", None):
                command.extend([f"--{role}-model", getattr(args, f"{role}_model")])
        log_path = os.path.join(repo, ".agent", "daemon.log")
        util.ensure_dir(os.path.dirname(log_path))
        env = dict(os.environ)
        if args.mock:
            env["AR_MOCK"] = "1"
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n=== {util.now_iso()} {' '.join(command)} ===\n")
            log.flush()
            proc = subprocess.Popen(
                command,
                cwd=repo,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        print(f"started {project} in the background (pid {proc.pid})")
        print(f"log: {log_path}")
        print(f"dashboard: aroom ui")
        return 0

    if args.loop:
        results = pipeline.run_loop(
            project,
            max_tasks=args.max_tasks,
            auto_merge=args.auto_merge,
            interval=args.interval,
            forever=args.forever,
            overrides=overrides,
            fresh=args.fresh,
        )
        if not results:
            return 0
        last = results[-1]
        return 0 if last.get("state") in {"merged", "passed"} else 2

    tasks = pipeline.tasklib.load_tasks(cfg)
    if args.task:
        task = pipeline.tasklib.find_task(tasks, args.task)
        if not task:
            print(f"task {args.task} not found in {cfg['tasks'].get('file')}")
            return 1
    else:
        task = pipeline.tasklib.next_task(tasks)
        if not task:
            print(f"{project}: no open tasks")
            return 0
    run = pipeline.run_task(
        project,
        task,
        auto_merge=args.auto_merge,
        overrides=overrides,
        fresh=args.fresh,
    )
    print()
    print(f"{project} {task['id']} → {run['state']}")
    print(f"branch   {run.get('branch')}")
    print(f"run dir  {run.get('run_dir')}")
    if run.get("verdict"):
        print(f"verdict  {run['verdict']}")
    if run.get("error"):
        print(f"error    {str(run['error']).splitlines()[-1]}")
    if run["state"] == "passed":
        print(f"merge    aroom merge {project} {task['id']}")
    return 0 if run["state"] in {"passed", "merged"} else 2


def cmd_resume(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    task_id = args.task
    if not task_id:
        latest = pipeline.find_run(project)
        task_id = latest["task"]
    overrides = overrides_from_args(args)
    if args.detach:
        command = [sys.executable, AR_MAIN, "resume", project, task_id]
        if args.note:
            command.extend(["--note", args.note])
        if args.allow_lockfile:
            command.append("--allow-lockfile")
        for role in ("builder", "verifier", "researcher"):
            if getattr(args, f"{role}_runner", None):
                command.extend([f"--{role}-runner", getattr(args, f"{role}_runner")])
            if getattr(args, f"{role}_model", None):
                command.extend([f"--{role}-model", getattr(args, f"{role}_model")])
        log_path = os.path.join(repo, ".agent", "daemon.log")
        util.ensure_dir(os.path.dirname(log_path))
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
        print(f"resuming {project} {task_id} in the background (pid {proc.pid})")
        print(f"log: {log_path}")
        return 0
    task = pipeline.tasklib.find_task(pipeline.tasklib.load_tasks(cfg), task_id)
    if not task:
        print(f"task {task_id} not found")
        return 1
    run = pipeline.run_task(
        project,
        task,
        overrides=overrides,
        resume=True,
        note=args.note or "",
        allow_lockfile=args.allow_lockfile,
    )
    print()
    print(f"{project} {task_id} → {run['state']}")
    print(f"verdict  {run.get('verdict')}")
    if run.get("error"):
        print(f"error    {str(run['error']).splitlines()[-1]}")
    if run["state"] == "passed":
        print(f"merge    aroom merge {project} {task_id}")
    return 0 if run["state"] in {"passed", "merged"} else 2


def cmd_stop(args) -> int:
    project, _, _ = project_config.find_project(args.project)
    return 0 if pipeline.stop(project) else 1


def cmd_clean(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    if args.task:
        existed = pipeline.clean_task(project, args.task)
        print(f"{project} {args.task}: {'removed' if existed else 'nothing to remove'}")
        return 0
    root = util.expand(cfg["worktree_root"])
    if not os.path.isdir(root):
        print(f"{project}: no worktrees")
        return 0
    removed = 0
    for name in sorted(os.listdir(root)):
        worktree = os.path.join(root, name)
        if not os.path.isdir(worktree):
            continue
        run = util.read_json(os.path.join(pipeline.run_dir(repo, name), "run.json"), {}) or {}
        state = run.get("state")
        if not args.all and state not in {"merged", "failed", "stopped"}:
            print(f"keep   {name} ({state or 'unknown'})")
            continue
        branch = run.get("branch") or f"agent/{name}"
        gitops.remove_worktree(repo, worktree, branch)
        print(f"remove {name}")
        removed += 1
    print(f"{removed} worktree(s) removed")
    return 0


def cmd_merge(args) -> int:
    project, _, _ = project_config.find_project(args.project)
    run = pipeline.merge_run(project, args.task, force=args.force)
    print(f"{project} {run['task']} → {run['state']}")
    if run.get("merge"):
        print(f"merged {run['merge'].get('sha', '')[:10]}")
    if run["state"] != "merged" and run.get("error"):
        print(str(run["error"])[:1000])
    return 0 if run["state"] == "merged" else 1


def cmd_adopt(args) -> int:
    project, _, _ = project_config.find_project(args.project)
    run = pipeline.mark_merged(project, args.task)
    print(f"{project} {run['task']} → merged (manual)")
    if run.get("merge"):
        print(f"merged {str(run['merge'].get('sha', ''))[:10]}")
    return 0


def cmd_watch(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    task = args.task
    if not task:
        latest = pipeline.find_run(project)
        task = latest["task"]
    interactive = sys.stdout.isatty()
    try:
        while True:
            try:
                detail = ui.run_detail(project, task)
            except Exception as exc:  # noqa: BLE001
                print(f"waiting for {project} {task}: {exc}")
                time.sleep(1)
                continue
            if interactive:
                sys.stdout.write("\033[2J\033[H")
            print(
                f"{project} · {detail.get('task')} {detail.get('title', '')}\n"
                f"state {detail.get('state')} · {detail.get('step')} · "
                f"{util.human_duration(detail.get('elapsed_s'))} · ${float(detail.get('cost_usd') or 0):.2f}"
            )
            for command, info in (detail.get("checks") or {}).items():
                print(f"  check {info.get('state', '?'):<5} {command}")
            print()
            for event in (detail.get("events") or [])[-14:]:
                print(f"{event.get('ts', '')[11:19]}  {event.get('actor', ''):<10} {event.get('text', '')[:150]}")
            if not interactive:
                print("-" * 60)
            if detail.get("state") in util.TERMINAL_STATES:
                break
            time.sleep(2)
    except KeyboardInterrupt:
        return 0
    return 0


def cmd_chat(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    if args.message:
        state = chat.send(project, " ".join(args.message))
        print(f"{project}: thinking… open the dashboard chat panel or run `aroom chat {project}`")
        return 0
    state = chat.load(repo)
    if not state["messages"]:
        print(f"{project}: no chat yet")
        return 0
    for message in state["messages"]:
        print(f"{message.get('role', '?')}: {message.get('text', '')}\n")
    return 0


def cmd_chat_turn(args) -> int:
    chat.run_turn(args.project)
    return 0


def cmd_preview(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    if args.logs:
        data = preview.tail(project, args.lines)
        if args.grep:
            rows = [line for line in data["log"].splitlines() if args.grep.lower() in line.lower()]
            print("\n".join(rows[-args.lines:]))
        else:
            if data["highlights"]:
                print("--- OTP / verification links ---")
                print("\n".join(data["highlights"]))
                print("--- end ---\n")
            print(data["log"])
        return 0
    if args.stop:
        state = preview.stop(project)
        print(f"{project}: app stopped")
        return 0
    if args.restart:
        state = preview.restart(project)
        print(f"{project}: {state['url']} ({'running' if state['running'] else 'stopped'})")
        print(f"log: {state['log']}")
        return 0 if state.get("running") else 2
    if args.status:
        state = preview.status(cfg)
    else:
        state = preview.start(project)
        if args.open and state.get("url"):
            try:
                import webbrowser

                webbrowser.open(state["url"])
            except Exception:  # noqa: BLE001
                pass
    if not state.get("configured"):
        print(f"{project}: no preview configured")
        return 1
    print(f"{project}: {state['url']} ({'running' if state['running'] else 'stopped'})")
    if state.get("external"):
        print("note: the port was already in use; linking to the existing server")
    print(f"log: {state['log']}")
    return 0 if state.get("running") else 2


def cmd_supervise(args) -> int:
    if args.stop:
        data = util.read_json(supervisor.PID_PATH, None)
        if not data or not util.pid_alive(data.get("pid")):
            print("supervisor is not running")
            return 1
        util.kill_tree(data["pid"])
        print(f"supervisor stopped (pid {data['pid']})")
        try:
            os.unlink(supervisor.PID_PATH)
        except OSError:
            pass
        return 0
    if args.once:
        supervisor.supervise(args.projects or None, args.interval, once=True)
        return 0
    if args.detach:
        command = [sys.executable, AR_MAIN, "supervise", *args.projects, "--interval", str(args.interval)]
        util.ensure_dir(os.path.dirname(supervisor.LOG_PATH))
        with open(supervisor.LOG_PATH, "a", encoding="utf-8") as log:
            log.write(f"\n=== {util.now_iso()} {' '.join(command)} ===\n")
            log.flush()
            proc = subprocess.Popen(
                command,
                cwd=os.path.expanduser("~"),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        util.write_json(supervisor.PID_PATH, {"pid": proc.pid, "started": util.now_iso()})
        print(f"supervisor started (pid {proc.pid})")
        print(f"log: {supervisor.LOG_PATH}")
        return 0
    supervisor.supervise(args.projects or None, args.interval)
    return 0


def cmd_blocked(args) -> int:
    project, repo, _ = project_config.find_project(args.project)
    data = pipeline.tasklib.load_blocked(repo)
    if not data:
        print(f"{project}: no blocked tasks")
        return 0
    for task_id, info in sorted(data.items()):
        print(f"{task_id:<10} {info.get('at', '')}  {info.get('reason', '')}")
    return 0


def cmd_unblock(args) -> int:
    project, repo, _ = project_config.find_project(args.project)
    if pipeline.tasklib.unmark_blocked(repo, args.task):
        print(f"{project} {args.task}: unblocked")
        return 0
    print(f"{project} {args.task}: not blocked")
    return 1


def cmd_research(args) -> int:
    project, _, _ = project_config.find_project(args.project)
    question = " ".join(args.question)
    run = pipeline.research(project, question)
    print(f"{project} research → {run['state']}")
    print(f"output: {run.get('output')}")
    return 0 if run["state"] == "passed" else 1


def cmd_build_phase(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    task = pipeline.tasklib.find_task(pipeline.tasklib.load_tasks(cfg), args.task)
    if not task:
        raise SystemExit(f"task {args.task} not found")
    previous = util.read_json(os.path.join(pipeline.run_dir(repo, args.task), "run.json"), None)
    worktree = os.path.join(util.expand(cfg["worktree_root"]), util.slug(args.task))
    resume = bool(previous) and gitops.worktree_exists(repo, worktree) and bool(previous.get("base_sha"))
    if previous and previous.get("state") in {"passed", "built", "merged"}:
        print(f"{project} {args.task} is {previous.get('state')}; not building")
        return 0
    run = pipeline.run_task(
        project,
        task,
        resume=resume,
        continue_round=resume,
        stop_after_checks=True,
    )
    print(f"{project} {args.task} -> {run['state']} ({run.get('step')})")
    return 0


def cmd_verify_phase(args) -> int:
    run = pipeline.verify_task_phase(args.project, args.task)
    print(f"{args.project} {args.task} -> {run['state']} ({run.get('verdict')})")
    return 0


def cmd_async(args) -> int:
    async_loop.run_async(
        args.project,
        verifiers=args.verifiers,
        builders=args.builders,
        interval=args.interval,
        once=args.once,
    )
    return 0


def cmd_requeue(args) -> int:
    project, repo, _ = project_config.find_project(args.project)
    task_ids = list(args.tasks)
    if not task_ids:
        root = os.path.join(repo, ".agent", "runs")
        if os.path.isdir(root):
            for folder in os.listdir(root):
                run = util.read_json(os.path.join(root, folder, "run.json"), None) or {}
                if run.get("state") in {"needs-human", "failed", "stopped"}:
                    task_ids.append(run.get("task") or folder)
    if not task_ids:
        print(f"{project}: nothing to requeue")
        return 0
    for task_id in sorted(set(task_ids)):
        try:
            run = pipeline.requeue_task(project, task_id, note=args.note or "")
            print(f"{project} {task_id} → {run['state']} ({run.get('step')})")
        except SystemExit as exc:
            print(f"{project} {task_id}: {exc}")
    return 0


def cmd_verify(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    task_id = args.task
    if not task_id:
        latest = pipeline.find_run(project)
        task_id = latest["task"]
    overrides = {}
    if args.runner or args.model:
        overrides["verifier"] = {"runner": args.runner, "model": args.model}
    run = pipeline.verify_run(project, task_id, overrides=overrides)
    print(f"{project} {task_id} → {run['state']}")
    print(f"verdict  {run.get('verdict')}")
    print(f"run dir  {run.get('run_dir')}")
    if run.get("error"):
        print(f"error    {str(run['error']).splitlines()[-1]}")
    if run["state"] == "passed":
        print(f"merge    aroom merge {project} {task_id}")
    return 0 if run["state"] in {"passed", "merged"} else 2


def cmd_models(args) -> int:
    data = models.list_models()
    if args.runner:
        data = {args.runner: data.get(args.runner, [])}
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    for runner, items in data.items():
        print(f"{runner}:")
        for item in items:
            label = item.get("label") or item.get("id")
            marker = f"  {item['id']}" if item.get("label") and item.get("id") else ""
            print(f"  {label}{marker}")
    return 0


def cmd_config(args) -> int:
    project, repo, cfg = project_config.find_project(args.project)
    if args.value is None:
        node = cfg
        for key in args.key.split("."):
            node = node.get(key, {}) if isinstance(node, dict) else None
        print(json.dumps(node, indent=2) if isinstance(node, (dict, list)) else node)
        return 0
    raw = args.value
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    project_config.set_raw(repo, args.key, value)
    committed = project_config.commit_config(repo)
    print(f"{project} {args.key} = {json.dumps(value)}")
    if not committed:
        print(f"note: commit .agent/config.json before the next run/merge")
    return 0


def cmd_ui(args) -> int:
    ui.serve(host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def cmd_doctor(_args) -> int:
    checks = [
        ("python", sys.executable),
        ("git", util.which("git")),
        ("gh", util.which("gh")),
        ("claude", util.which("claude")),
        ("opencode", util.which("opencode")),
    ]
    ok = True
    for name, path in checks:
        print(f"{name:<10} {path or 'MISSING'}")
        if name in {"python", "git"} and not path:
            ok = False
    reg = project_config.load_registry()
    print(f"registry   {util.REGISTRY} ({len(reg['projects'])} projects)")
    print(f"dashboard  http://{reg['ui'].get('host')}:{reg['ui'].get('port')}")
    for name, path in sorted(reg["projects"].items()):
        repo = util.expand(path)
        if not os.path.isdir(repo):
            print(f"  {name}: MISSING {repo}")
            continue
        configured = os.path.isfile(project_config.config_path(repo))
        print(f"  {name}: {'ok' if configured else 'no .agent/config.json'}  {repo}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aroom", description="Agent Room — multi-project build console")
    parser.add_argument("--version", action="version", version=f"agent-room {VERSION}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="initialise a project and register it")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--name")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add", help="register an existing project")
    p.add_argument("path")
    p.add_argument("--name")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("track", help="register a project read-only (no .agent writes)")
    p.add_argument("path")
    p.add_argument("--name")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("remove", help="unregister a project")
    p.add_argument("project")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("projects", help="list registered projects")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("status", help="status across all projects")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("next", help="show the next task")
    p.add_argument("project", nargs="?")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("run", help="run one task or a loop")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.add_argument("--loop", action="store_true", help="keep taking tasks")
    p.add_argument("--forever", action="store_true", help="keep polling for new tasks (implies --loop)")
    p.add_argument("--max-tasks", type=int)
    p.add_argument("--auto-merge", action="store_true", default=None)
    p.add_argument("--detach", action="store_true", help="run in the background")
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--mock", action="store_true", help="use the deterministic mock runner")
    p.add_argument("--fresh", action="store_true", help="discard an existing worktree/branch first")
    for role in ("builder", "verifier", "researcher"):
        p.add_argument(f"--{role}-runner", choices=["claude", "opencode", "mock"], help=f"{role} runner")
        p.add_argument(f"--{role}-model", help=f"{role} model")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("stop", help="stop the current run")
    p.add_argument("project", nargs="?")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("resume", help="continue a failed run in its existing worktree")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.add_argument("--note", help="instruction for the resumed builder")
    p.add_argument("--allow-lockfile", action="store_true", help="allow pnpm-lock.yaml changes")
    p.add_argument("--detach", action="store_true")
    for role in ("builder", "verifier", "researcher"):
        p.add_argument(f"--{role}-runner", choices=["claude", "opencode", "mock"])
        p.add_argument(f"--{role}-model")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("clean", help="remove finished worktrees")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.add_argument("--all", action="store_true", help="also remove passed-but-unmerged worktrees")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("async", help="builder lane + verifier pool, asynchronously")
    p.add_argument("project")
    p.add_argument("--verifiers", type=int, default=2)
    p.add_argument("--builders", type=int, default=None)
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--once", action="store_true", help="exit when no runnable work remains")
    p.set_defaults(func=cmd_async)

    p = sub.add_parser("_build", help=argparse.SUPPRESS)
    p.add_argument("project")
    p.add_argument("task")
    p.set_defaults(func=cmd_build_phase)

    p = sub.add_parser("_verify", help=argparse.SUPPRESS)
    p.add_argument("project")
    p.add_argument("task")
    p.set_defaults(func=cmd_verify_phase)

    p = sub.add_parser("requeue", help="return needs-human/failed runs to the builder queue")
    p.add_argument("project", nargs="?")
    p.add_argument("tasks", nargs="*")
    p.add_argument("--note", help="instruction prepended to the builder's fix prompt")
    p.set_defaults(func=cmd_requeue)

    p = sub.add_parser("verify", help="re-run checks + verifier on an existing branch")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.add_argument("--runner", choices=["claude", "opencode", "mock"])
    p.add_argument("--model")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("models", help="list models available to each runner")
    p.add_argument("--runner", choices=["claude", "opencode", "mock"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("config", help="get or set a project config value")
    p.add_argument("project", nargs="?")
    p.add_argument("key", help="dotted key, e.g. agents.verifier.model")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("merge", help="squash-merge a passed run")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.add_argument("--force", action="store_true", help="merge the branch even if the run record is not passed")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("adopt", help="mark a hand-resolved squash merge as merged")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.set_defaults(func=cmd_adopt)

    p = sub.add_parser("watch", help="follow a run in the terminal")
    p.add_argument("project", nargs="?")
    p.add_argument("task", nargs="?")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("research", help="run a research note")
    p.add_argument("project")
    p.add_argument("question", nargs="+")
    p.set_defaults(func=cmd_research)

    p = sub.add_parser("ui", help="start the dashboard")
    p.add_argument("--port", type=int)
    p.add_argument("--host")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("chat", help="talk to a project agent")
    p.add_argument("project", nargs="?")
    p.add_argument("message", nargs="*")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("_chat", help=argparse.SUPPRESS)
    p.add_argument("project")
    p.set_defaults(func=cmd_chat_turn)

    p = sub.add_parser("preview", help="start/stop the project's web app")
    p.add_argument("project", nargs="?")
    p.add_argument("--stop", action="store_true")
    p.add_argument("--restart", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--open", action="store_true")
    p.add_argument("--logs", action="store_true", help="show the preview server log (OTP, links)")
    p.add_argument("--grep", help="filter --logs by text")
    p.add_argument("--lines", type=int, default=300)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("supervise", help="keep project loops running unattended")
    p.add_argument("projects", nargs="*")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--detach", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--stop", action="store_true")
    p.set_defaults(func=cmd_supervise)

    p = sub.add_parser("blocked", help="list tasks the supervisor skipped")
    p.add_argument("project", nargs="?")
    p.set_defaults(func=cmd_blocked)

    p = sub.add_parser("unblock", help="allow a blocked task to run again")
    p.add_argument("project", nargs="?")
    p.add_argument("task")
    p.set_defaults(func=cmd_unblock)

    p = sub.add_parser("doctor", help="check the environment")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
