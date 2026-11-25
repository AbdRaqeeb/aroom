"""The task pipeline: brief -> build -> check -> verify -> fix -> merge."""

from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
import traceback
from typing import Any

from . import config as project_config
from . import gitops, runners, tasks as tasklib, util

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def render(name: str, **values: Any) -> str:
    path = os.path.join(TEMPLATE_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def run_dir(repo: str, task_id: str) -> str:
    return os.path.join(repo, ".agent", "runs", util.slug(task_id))


def locks_dir(repo: str) -> str:
    return os.path.join(repo, ".agent", "locks")


def lock_path(repo: str, task_id: str | None = None) -> str:
    if not task_id:
        return os.path.join(repo, ".agent", "lock")
    return os.path.join(locks_dir(repo), f"{util.slug(task_id)}.lock")


def acquire_lock(repo: str, project: str, task_id: str, directory: str) -> None:
    path = lock_path(repo, task_id)
    util.ensure_dir(os.path.dirname(path))
    payload = {
        "project": project,
        "task": task_id,
        "pid": os.getpid(),
        "run_dir": directory,
        "started": util.now_iso(),
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
                raise SystemExit(
                    f"{project} is already running {existing.get('task')} (pid {existing.get('pid')}).\n"
                    f"Use `aroom stop {project}` first."
                )
            try:
                os.unlink(path)
            except OSError:
                pass
    raise SystemExit(f"could not acquire the run lock at {path}")


def release_lock(repo: str, task_id: str | None = None) -> None:
    try:
        os.unlink(lock_path(repo, task_id))
    except OSError:
        pass


def active_locks(repo: str) -> list[tuple[str, dict]]:
    directory = locks_dir(repo)
    if not os.path.isdir(directory):
        return []
    found: list[tuple[str, dict]] = []
    for name in os.listdir(directory):
        if not name.endswith(".lock"):
            continue
        path = os.path.join(directory, name)
        data = util.read_json(path, None)
        if data:
            found.append((path, data))
    return found


def _cfg_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def check_commands(cfg: dict, include_e2e: bool) -> list[str]:
    commands = _cfg_list(cfg["commands"].get("checks"))
    e2e = cfg["commands"].get("e2e")
    if include_e2e and e2e:
        commands.append(e2e)
    return commands


def write_brief(
    cfg: dict,
    task: dict,
    run: dict,
    worktree: str,
    branch: str,
    research_path: str | None = None,
    allow_lockfile: bool = False,
    resume_note: str = "",
) -> str:
    directory = run["run_dir"]
    path = os.path.join(directory, "brief.md")
    allow = _cfg_list(cfg["paths"].get("allow")) or ["the whole worktree, except the deny list"]
    deny_defaults = [
        ".git/",
        ".agent/runs/",
        "prototype/" if os.path.isdir(os.path.join(cfg["repo"], "prototype")) else "",
        "pnpm-lock.yaml" if (not allow_lockfile and os.path.exists(os.path.join(cfg["repo"], "pnpm-lock.yaml"))) else "",
    ]
    deny = _cfg_list(cfg["paths"].get("deny")) + [item for item in deny_defaults if item]
    checks = check_commands(cfg, include_e2e=True)
    skills = [s for s in ("api-endpoint", "db-schema", "background-job", "ai-provider", "web-screen", "design-system", "code-quality") if os.path.isdir(os.path.join(cfg["repo"], ".claude", "skills", s))]
    notes = os.path.join(directory, "notes.md")

    pieces = [
        f"# {task['id']} — {task['title']}",
        "",
        f"- Project: **{cfg['project']}**",
        f"- Repo: `{cfg['repo']}`",
        f"- Worktree: `{worktree}`",
        f"- Branch: `{branch}`",
        f"- Base: `{cfg['base_branch']}` at `{run.get('base_sha', '')}`",
        f"- Task source: `{task.get('source', '')}`",
        "",
        "## Task",
        "",
        task["description"].strip() or task["raw"].strip(),
        "",
        "## Acceptance criteria",
        "",
        tasklib.acceptance_text(task),
        "",
    ]
    if not task["acceptance"]:
        pieces += [
            "> The task file has no explicit `Accept:` lines. Treat the description plus the repo's",
            "> conventions as the contract; the verifier will derive concrete checks from them.",
            "",
        ]
    if research_path:
        pieces += [
            "## Research",
            "",
            f"Read `{research_path}` before choosing a vendor, API or approach. It contains the",
            "options, sources and the recommendation for this task. Do not guess vendor behaviour.",
            "",
        ]
    if allow_lockfile:
        pieces += [
            "## Lockfile exception",
            "",
            "`pnpm-lock.yaml` may be edited for this task (dependency changes were approved).",
            "",
        ]
    if resume_note or run.get("resumed_at"):
        pieces += [
            "## Resume",
            "",
            "This run is being resumed in an existing worktree. It may contain uncommitted work",
            "from a previous attempt. Inspect `git status` and `git diff` first, keep the useful",
            "parts, finish the task, run the checks, and commit.",
            "",
        ]
        if resume_note:
            pieces += [f"Instruction: {resume_note}", ""]
    pieces += [
        "## Commands",
        "",
        "- Setup: " + (", ".join(f"`{c}`" for c in _cfg_list(cfg["commands"].get("setup"))) or "(none)"),
        "- Checks: " + (", ".join(f"`{c}`" for c in checks) or "(none configured)"),
        "",
        "## Rules",
        "",
        "- You are in a disposable git worktree. Commit your work; do not push or merge.",
        "- Allowed paths: " + ", ".join(f"`{a}`" for a in allow),
        "- Never edit: " + ", ".join(f"`{d}`" for d in deny),
        f"- Task file (do not edit): `{cfg['tasks'].get('file')}`",
        f"- If blocked, write the question to `{notes}` and stop.",
        "- Follow `AGENTS.md` and the named skills.",
        "",
        "## Skills to read",
        "",
    ]
    if skills:
        pieces += [f"- `.claude/skills/{s}/SKILL.md`" for s in skills]
    else:
        pieces += ["- (none in this repo; follow `AGENTS.md` / `README.md`)"]
    pieces += ["", "## Definition of done", ""]
    pieces += ["- Checks pass, new behaviour has tests, no unrelated changes, one concern per commit."]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(pieces).rstrip() + "\n")
    return path


def copy_env_files(cfg: dict, worktree: str) -> None:
    for rel in _cfg_list(cfg.get("isolation", {}).get("copy_env")):
        source = os.path.join(cfg["repo"], rel)
        target = os.path.join(worktree, rel)
        if os.path.isfile(source) and not os.path.exists(target):
            util.ensure_dir(os.path.dirname(target))
            shutil.copy2(source, target)
            log(f"copied {rel}")
    env_script = cfg.get("isolation", {}).get("env_script")
    if env_script:
        source = os.path.join(cfg["repo"], env_script)
        target = os.path.join(worktree, env_script)
        if os.path.isfile(source) and not os.path.exists(target):
            util.ensure_dir(os.path.dirname(target))
            shutil.copy2(source, target)
            log(f"copied {env_script}")


def shell_command(cfg: dict, worktree: str, command: str) -> list[str]:
    env_script = cfg.get("isolation", {}).get("env_script")
    prefix = ""
    if env_script and os.path.isfile(os.path.join(worktree, env_script)):
        prefix = f"set -a; source {shlex.quote(env_script)}; set +a; "
    return ["bash", "-lc", prefix + command]


def execute(cfg: dict, worktree: str, command: str, log_path: str, timeout_min: float) -> tuple[int, float]:
    util.ensure_dir(os.path.dirname(log_path))
    started = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen(
            shell_command(cfg, worktree, command),
            cwd=worktree,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
            code = proc.wait(timeout=max(1, timeout_min * 60 - (time.time() - started)))
        except subprocess.TimeoutExpired:
            util.kill_tree(proc.pid, signal.SIGKILL)
            fh.write("\n[agent-room] timeout\n")
            code = -9
        except Exception:
            util.kill_tree(proc.pid, signal.SIGKILL)
            raise
    return code, round(time.time() - started, 1)


def run_checks(cfg: dict, worktree: str, run: dict, include_e2e: bool, actor: str = "checks") -> bool:
    commands = check_commands(cfg, include_e2e)
    if not commands:
        run["checks"] = {}
        util.write_json(os.path.join(run["run_dir"], "run.json"), run)
        return True
    directory = os.path.join(run["run_dir"], "checks")
    util.ensure_dir(directory)
    run["state"] = "checking"
    run["step"] = "checks"
    util.write_json(os.path.join(run["run_dir"], "run.json"), run)
    ok = True
    for index, command in enumerate(commands, start=1):
        name = f"{index}-{util.slug(command)}"
        log_path = os.path.join(directory, f"{name}.log")
        runners.emit(run["run_dir"], run, actor, "check", f"$ {command}")
        code, duration = execute(
            cfg,
            worktree,
            command,
            log_path,
            float(cfg["commands"].get("check_timeout_min", 25)),
        )
        state = "pass" if code == 0 else "fail"
        run.setdefault("checks", {})[command] = {
            "state": state,
            "exit": code,
            "duration_s": duration,
            "log": log_path,
        }
        util.write_json(os.path.join(run["run_dir"], "run.json"), run)
        runners.emit(run["run_dir"], run, actor, "check", f"{state} {command} ({duration}s)")
        if code != 0:
            ok = False
            break
    return ok


def failed_check_logs(run: dict, limit: int = 120) -> str:
    lines: list[str] = []
    for command, info in (run.get("checks") or {}).items():
        if info.get("state") == "fail":
            lines.append(f"### `{command}` (exit {info.get('exit')})")
            lines.append(util.tail(info.get("log", ""), limit))
    return "\n".join(lines) or "Checks failed but no log was captured."


def parse_verify(path: str) -> tuple[str, str]:
    try:
        text = open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return "FAIL", "The verifier did not write verify.md."
    match = re.search(r"(?im)^\s*verdict\s*:\s*(PASS|FAIL)\b", text)
    verdict = match.group(1).upper() if match else "FAIL"
    issues = [
        line.strip()
        for line in text.splitlines()
        if re.match(r"(?i)^\s*[-*]\s*\[(blocker|major|minor|critical)\]", line)
    ]
    blockers = [line for line in issues if re.search(r"(?i)\[(blocker|critical|major)\]", line)]
    if verdict == "FAIL" and not blockers:
        body = re.search(r"(?is)##\s*Issues\s*(.+)$", text)
        issues_text = body.group(1).strip() if body else text[-2500:]
    else:
        issues_text = "\n".join(blockers) if blockers else "See verify.md."
    return verdict, issues_text


def task_commit_type(cfg: dict) -> str:
    return str(cfg.get("commit_type") or "feat")


def build_prompt(
    cfg: dict,
    task: dict,
    run: dict,
    worktree: str,
    branch: str,
    round_no: int,
    issues: str = "",
    research_path: str | None = None,
    resume_note: str = "",
    allow_lockfile: bool = False,
) -> str:
    allow = _cfg_list(cfg["paths"].get("allow")) or ["the whole worktree"]
    deny = _cfg_list(cfg["paths"].get("deny")) or ["nothing beyond the rules above"]
    round_section = ""
    if round_no > 1 or issues:
        round_section = (
            f"## Fix round {round_no}\n\n"
            "The verifier reported the following. Fix these issues, keep the rest working, "
            "re-run the checks and commit.\n\n"
            f"{issues}\n"
        )
    research_section = ""
    if research_path:
        research_section = (
            "## Research\n\n"
            f"Read `{research_path}` before choosing a vendor, API or approach. "
            "It contains the options, sources and recommendation for this task.\n"
        )
    resume_section = ""
    if resume_note or run.get("resumed_at"):
        resume_section = (
            "## Resume\n\n"
            "This worktree already contains work from a previous attempt. Do **not** discard it. "
            "Run `git status` and `git diff`, keep the useful edits, finish the task, run the checks, "
            "and commit everything that belongs to this task.\n"
        )
        if resume_note:
            resume_section += f"\nInstruction: {resume_note}\n"
        if allow_lockfile:
            resume_section += (
                "\nYou may edit `pnpm-lock.yaml` for this task. Add the dependency with the package "
                "manager so the lockfile is generated, never by hand.\n"
            )
    return render(
        "builder.md",
        PROJECT=cfg["project"],
        TASK=task["id"],
        TITLE=task["title"],
        WORKTREE=worktree,
        BRANCH=branch,
        BASE=cfg["base_branch"],
        BASE_SHA=run.get("base_sha", ""),
        BRIEF=os.path.join(run["run_dir"], "brief.md"),
        NOTES=os.path.join(run["run_dir"], "notes.md"),
        TASK_FILE=cfg["tasks"].get("file"),
        ALLOW=", ".join(f"`{a}`" for a in allow),
        DENY=", ".join(f"`{d}`" for d in deny),
        CHECKS=", ".join(f"`{c}`" for c in check_commands(cfg, include_e2e=True)) or "(none)",
        ROUND_SECTION=round_section,
        RESEARCH_SECTION=research_section,
        RESUME_SECTION=resume_section,
    )


def verifier_prompt(
    cfg: dict,
    task: dict,
    run: dict,
    worktree: str,
    branch: str,
    round_no: int,
    research_path: str | None = None,
    include_e2e: bool = True,
) -> str:
    research_section = ""
    if research_path:
        research_section = (
            "## Research\n\n"
            f"The builder was given `{research_path}`. Check that the implementation matches "
            "the documented API/limits and does not rely on guessed behaviour.\n"
        )
    return render(
        "verifier.md",
        PROJECT=cfg["project"],
        TASK=task["id"],
        WORKTREE=worktree,
        BRANCH=branch,
        BASE=cfg["base_branch"],
        BASE_SHA=run.get("base_sha", ""),
        DIFF=os.path.join(run["run_dir"], "diff.patch"),
        BRIEF=os.path.join(run["run_dir"], "brief.md"),
        VERIFY=os.path.join(run["run_dir"], "verify.md"),
        CHECKS=", ".join(f"`{c}`" for c in check_commands(cfg, include_e2e)) or "(none)",
        ROUND=round_no,
        RESEARCH_SECTION=research_section,
    )


def commit_verifier_changes(worktree: str, task: dict) -> bool:
    proc = util.run(["git", "-C", worktree, "status", "--porcelain"], check=False)
    if not proc.stdout.strip():
        return False
    util.run(["git", "-C", worktree, "add", "-A"], check=False)
    util.run(
        ["git", "-C", worktree, "commit", "-m", f"test: verifier checks ({task['id']})"],
        check=False,
    )
    return True


def research_needed(cfg: dict, task: dict) -> bool:
    research = cfg.get("research", {})
    if not research.get("auto", True):
        return False
    text = f"{task['id']} {task['title']} {task.get('raw', '')}"
    # Skill tags such as "(ai)" or "(job, ai)" are not a request to research.
    text = re.sub(r"\([^()]*\)", " ", text)
    for trigger in research.get("triggers", []):
        try:
            if re.search(trigger, text, re.IGNORECASE):
                return True
        except re.error:
            if trigger.lower() in text.lower():
                return True
    return False


def ensure_research(cfg: dict, task: dict, run: dict, worktree: str) -> str | None:
    """Run the researcher inside the worktree when a task looks like it needs it."""
    if not research_needed(cfg, task):
        return None
    directory = os.path.join(worktree, cfg.get("research", {}).get("dir", "docs/research"))
    pattern = os.path.join(directory, f"{util.slug(task['id'])}*.md")
    existing = sorted(glob.glob(pattern))
    if existing:
        rel = os.path.relpath(existing[0], worktree)
        runners.emit(run["run_dir"], run, "researcher", "research", f"using existing {rel}")
        return rel
    util.ensure_dir(directory)
    output = os.path.join(directory, f"{util.slug(task['id'])}-{util.slug(task['title'])[:50]}.md")
    rel = os.path.relpath(output, worktree)
    run["state"] = "researching"
    run["step"] = "research"
    run["research"] = rel
    run["research_output"] = output
    util.write_json(os.path.join(run["run_dir"], "run.json"), run)
    runners.emit(run["run_dir"], run, "agent-room", "research", f"researching {task['id']} → {rel}")
    question = (
        f"What do we need to know to implement {task['id']} — {task['title']}?\n\n"
        f"Task context:\n{task.get('description', '')[:3000]}\n\n"
        "Focus on the vendor APIs, limits, costs and risks this task depends on. "
        "If the task does not need a vendor, research the library/API it uses and say so."
    )
    prompt = render(
        "researcher.md",
        PROJECT=cfg["project"],
        QUESTION=question,
        REPO=worktree,
        OUTPUT=output,
    )
    result = runners.run_agent("researcher", prompt, worktree, run["run_dir"], run, cfg)
    if result["returncode"] != 0 or not os.path.isfile(output):
        message = "the researcher did not produce a note"
        runners.emit(run["run_dir"], run, "researcher", "warn", message)
        if cfg.get("research", {}).get("required"):
            raise RuntimeError(message)
        return None
    util.run(["git", "-C", worktree, "add", "--", rel], check=False)
    util.run(
        ["git", "-C", worktree, "commit", "-m", f"docs: research for {task['id']}"],
        check=False,
    )
    runners.emit(run["run_dir"], run, "researcher", "research", f"wrote {rel}")
    return rel


def apply_agent_overrides(cfg: dict, overrides: dict | None) -> None:
    for role, values in (overrides or {}).items():
        if role not in cfg.get("agents", {}):
            continue
        for key in ("runner", "model"):
            value = values.get(key)
            if value not in (None, ""):
                cfg["agents"][role][key] = value


def run_task(
    project: str,
    task: dict,
    *,
    auto_merge: bool | None = None,
    max_fix_rounds: int | None = None,
    overrides: dict | None = None,
    fresh: bool = False,
    resume: bool = False,
    note: str = "",
    allow_lockfile: bool = False,
    stop_after_checks: bool = False,
    continue_round: bool = False,
) -> dict:
    cfg = project_config.load_project(project_config.find_project(project)[1])
    apply_agent_overrides(cfg, overrides)
    repo = cfg["repo"]
    project_config.commit_config(repo)
    clean, status = gitops.is_clean(repo)
    if not clean:
        raise SystemExit(
            f"{repo} has uncommitted changes:\n{status}\n"
            "Commit or stash them before running a task (merges need a clean base)."
        )
    branch = f"agent/{util.slug(task['id'])}"
    worktree = os.path.join(util.expand(cfg["worktree_root"]), util.slug(task["id"]))
    directory = run_dir(repo, task["id"])
    os.makedirs(util.ensure_dir(os.path.join(repo, ".agent", "runs")), exist_ok=True)

    previous = util.read_json(os.path.join(directory, "run.json"), None)
    if previous and previous.get("state") in util.ACTIVE_STATES and util.pid_alive(previous.get("pid")):
        raise SystemExit(f"{project} {task['id']} is already running (pid {previous.get('pid')}).")

    exists = gitops.worktree_exists(repo, worktree) or gitops.branch_exists(repo, branch)
    if resume:
        if not exists:
            raise SystemExit(
                f"{project} {task['id']} has no worktree/branch to resume. "
                f"Run it first: aroom run {project} {task['id']}"
            )
        if (previous or {}).get("state") == "passed":
            raise SystemExit(
                f"{project} {task['id']} passed already; merge it instead:\n"
                f"  aroom merge {project} {task['id']}"
            )
    if exists and not fresh and not resume:
        state = (previous or {}).get("state") or "unknown"
        if state == "passed":
            raise SystemExit(
                f"{project} {task['id']} already passed and is waiting for merge.\n"
                f"Merge it:  aroom merge {project} {task['id']}\n"
                f"Or discard: aroom clean {project} {task['id']}"
            )
        raise SystemExit(
            f"{project} {task['id']} already has a worktree/branch ({state}).\n"
            f"Resume it:    aroom resume {project} {task['id']}\n"
            f"Re-verify it: aroom verify {project} {task['id']}\n"
            f"Remove it:    aroom clean {project} {task['id']}\n"
            f"Start over:   aroom run {project} {task['id']} --fresh"
        )
    if exists and fresh:
        gitops.remove_worktree(repo, worktree, branch)
    if os.path.isdir(directory) and not resume:
        shutil.rmtree(directory)
    util.ensure_dir(directory)

    if resume and previous:
        run: dict[str, Any] = dict(previous)
        run.update(
            {
                "state": "queued",
                "step": "resume",
                "round": int(previous.get("round") or 0) if continue_round else 0,
                "issues": previous.get("issues") if continue_round else None,
                "started": util.now_iso(),
                "updated": util.now_iso(),
                "finished": None,
                "pid": os.getpid(),
                "verdict": None,
                "error": None,
                "merge": None,
                "checks": {},
                "resumed_at": util.now_iso(),
                "resume_count": int(previous.get("resume_count") or 0) + 1,
                "base_sha": gitops.merge_base(repo, cfg["base_branch"], branch)
                or previous.get("base_sha", ""),
            }
        )
    else:
        run = {
            "run_id": f"{cfg['project']}-{task['id']}",
            "kind": "task",
            "project": cfg["project"],
            "task": task["id"],
            "title": task["title"],
            "state": "queued",
            "step": "queued",
            "round": 0,
            "started": util.now_iso(),
            "updated": util.now_iso(),
            "finished": None,
            "repo": repo,
            "run_dir": directory,
            "worktree": worktree,
            "branch": branch,
            "base_branch": cfg["base_branch"],
            "base_sha": "",
            "pid": os.getpid(),
            "cost_usd": 0.0,
            "checks": {},
            "verdict": None,
            "error": None,
            "merge": None,
            "events_count": 0,
        }
    # Claim the task before touching its run record, so a manual run and the
    # scheduler cannot overwrite each other's state.
    acquire_lock(repo, cfg["project"], task["id"], directory)
    util.write_json(os.path.join(directory, "run.json"), run)
    runners.emit(directory, run, "agent-room", "start", f"{cfg['project']} · {task['id']}")

    try:
        run["state"] = "briefing"
        run["step"] = "worktree"
        util.write_json(os.path.join(directory, "run.json"), run)
        abort_pending_merge(worktree)
        if not resume:
            gitops.add_worktree(repo, worktree, branch, cfg["base_branch"])
            run["base_sha"] = gitops.rev(worktree, "HEAD")
        else:
            run["base_sha"] = run.get("base_sha") or gitops.merge_base(repo, cfg["base_branch"], branch)
            if not run["base_sha"]:
                raise RuntimeError("could not determine the branch point")
        copy_env_files(cfg, worktree)

        for command in _cfg_list(cfg["commands"].get("setup")):
            runners.emit(directory, run, "setup", "run", f"$ {command}")
            code, duration = execute(
                cfg,
                worktree,
                command,
                os.path.join(directory, "checks", f"setup-{util.slug(command)}.log"),
                float(cfg["commands"].get("setup_timeout_min", 25)),
            )
            runners.emit(directory, run, "setup", "run", f"exit {code} ({duration}s)")
            if code != 0:
                raise RuntimeError(f"setup failed: {command}")

        research_path = ensure_research(cfg, task, run, worktree)
        brief = write_brief(
            cfg,
            task,
            run,
            worktree,
            branch,
            research_path,
            allow_lockfile=allow_lockfile,
            resume_note=note if resume else "",
        )
        runners.emit(directory, run, "agent-room", "brief", os.path.basename(brief))
        util.write_json(os.path.join(directory, "run.json"), run)

        fix_rounds = int(max_fix_rounds if max_fix_rounds is not None else cfg["limits"].get("fix_rounds", 2))
        round_no = int(run.get("round") or 0) if continue_round else 0
        verdict = "FAIL"
        issues = (run.get("issues") or "") if continue_round else ""
        checked_sha = gitops.rev(worktree)
        verifier_committed = False
        while round_no <= fix_rounds:
            round_no += 1
            run["round"] = round_no
            run["state"] = "fixing" if issues else "building"
            run["step"] = f"builder round {round_no}"
            util.write_json(os.path.join(directory, "run.json"), run)
            prompt = build_prompt(
                cfg,
                task,
                run,
                worktree,
                branch,
                round_no,
                issues,
                research_path,
                resume_note=note if (resume and round_no == 1) else "",
                allow_lockfile=allow_lockfile,
            )
            result = runners.run_agent("builder", prompt, worktree, directory, run, cfg)
            if result["returncode"] != 0:
                detail = runners.summarize_error(os.path.join(directory, "builder.log"))
                raise RuntimeError(
                    f"builder exited {result['returncode']}" + (f": {detail}" if detail else "")
                )
            if budget_exceeded(cfg, run):
                raise RuntimeError(f"run budget exceeded (${run.get('cost_usd'):.2f})")

            commits = gitops.commit_count(worktree, run["base_sha"])
            if commits == 0:
                raise RuntimeError("builder produced no commits")
            stat = gitops.diff_stat(worktree, run["base_sha"])
            run.update(
                {
                    "files_changed": stat["files"],
                    "insertions": stat["insertions"],
                    "deletions": stat["deletions"],
                    "commits": commits,
                }
            )
            util.write_json(os.path.join(directory, "run.json"), run)

            include_e2e = needs_e2e(cfg, worktree, run["base_sha"])
            checks_ok = run_checks(cfg, worktree, run, include_e2e)
            checked_sha = gitops.rev(worktree)
            gitops.write_diff(worktree, run["base_sha"], os.path.join(directory, "diff.patch"))

            if not checks_ok:
                verdict = "FAIL"
                issues = "The project checks failed:\n\n" + failed_check_logs(run)
                runners.emit(directory, run, "checks", "fail", "checks failed; sending back to builder")
                if stop_after_checks:
                    finished = round_no > fix_rounds
                    run.update(
                        {
                            "state": "needs-human" if finished else "fixing",
                            "step": "checks failed" if finished else f"fix round {round_no}",
                            "verdict": "FAIL",
                            "issues": issues,
                            "finished": util.now_iso() if finished else None,
                        }
                    )
                    util.write_json(os.path.join(directory, "run.json"), run)
                    return run
            else:
                if stop_after_checks:
                    run.update(
                        {
                            "state": "built",
                            "step": "awaiting verifier",
                            "verdict": None,
                            "issues": None,
                            "finished": None,
                        }
                    )
                    util.write_json(os.path.join(directory, "run.json"), run)
                    runners.emit(directory, run, "agent-room", "built", "checks passed — awaiting verifier")
                    return run
                run["state"] = "verifying"
                run["step"] = f"verifier round {round_no}"
                util.write_json(os.path.join(directory, "run.json"), run)
                try:
                    os.unlink(os.path.join(directory, "verify.md"))
                except OSError:
                    pass
                result = runners.run_agent(
                    "verifier",
                    verifier_prompt(
                        cfg, task, run, worktree, branch, round_no, research_path, include_e2e
                    ),
                    worktree,
                    directory,
                    run,
                    cfg,
                )
                if result["returncode"] != 0:
                    detail = runners.summarize_error(os.path.join(directory, "verifier.log"))
                    runners.emit(
                        directory,
                        run,
                        "verifier",
                        "warn",
                        f"verifier exited {result['returncode']}"
                        + (f": {detail}" if detail else ""),
                    )
                if budget_exceeded(cfg, run):
                    raise RuntimeError(f"run budget exceeded (${run.get('cost_usd'):.2f})")
                verifier_committed = commit_verifier_changes(worktree, task)
                verdict, issues = parse_verify(os.path.join(directory, "verify.md"))
                run["verdict"] = verdict
                util.write_json(os.path.join(directory, "run.json"), run)
                runners.emit(directory, run, "agent-room", "verdict", verdict)
                if verdict == "PASS":
                    break
            if round_no > fix_rounds:
                break

        if verdict != "PASS":
            run["state"] = "needs-human"
            run["step"] = "verification failed"
            run["finished"] = util.now_iso()
            run["issues"] = issues
            util.write_json(os.path.join(directory, "run.json"), run)
            return run

        # final authoritative check — only when the verifier changed the tree
        if verifier_committed or gitops.rev(worktree) != checked_sha:
            if not run_checks(cfg, worktree, run, needs_e2e(cfg, worktree, run["base_sha"])):
                run["state"] = "needs-human"
                run["step"] = "final checks failed"
                run["finished"] = util.now_iso()
                util.write_json(os.path.join(directory, "run.json"), run)
                return run
        else:
            runners.emit(
                directory, run, "agent-room", "checks", "skipped re-run; tree unchanged since last pass"
            )

        integrated, integration_detail = integration_gate(cfg, run, worktree)
        if not integrated:
            run["state"] = "needs-human"
            run["step"] = "integration check failed"
            run["issues"] = integration_detail
            run["finished"] = util.now_iso()
            util.write_json(os.path.join(directory, "run.json"), run)
            return run

        run["state"] = "passed"
        run["step"] = "ready to merge"
        run["verdict"] = "PASS"
        run["finished"] = util.now_iso()
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "pass", "PASS — branch ready")

        should_merge = cfg["limits"].get("auto_merge", False) if auto_merge is None else auto_merge
        if should_merge:
            return merge_run(cfg["project"], task["id"])
        return run

    except KeyboardInterrupt:
        run["state"] = "stopped"
        run["step"] = "interrupted"
        run["finished"] = util.now_iso()
        util.write_json(os.path.join(directory, "run.json"), run)
        raise
    except Exception as exc:  # noqa: BLE001
        run["state"] = "failed"
        run["step"] = "error"
        run["error"] = f"{exc}"
        run["traceback"] = traceback.format_exc()[-4000:]
        run["finished"] = util.now_iso()
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "error", str(exc)[:280])
        return run
    finally:
        release_lock(repo, task["id"])


def budget_exceeded(cfg: dict, run: dict) -> bool:
    return float(run.get("cost_usd") or 0) > float(cfg["limits"].get("run_budget_usd", 20))


def abort_pending_merge(worktree: str) -> None:
    if not worktree or not os.path.isdir(worktree):
        return
    head = util.run(
        ["git", "-C", worktree, "rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False
    )
    if head.returncode == 0:
        util.run(["git", "-C", worktree, "merge", "--abort"], check=False)


def pre_merge_commands(cfg: dict) -> list[str]:
    configured = cfg["commands"].get("pre_merge")
    if configured is not None:
        return _cfg_list(configured)
    # Default: typecheck the tree produced by merging the current base, if available.
    return [c for c in _cfg_list(cfg["commands"].get("checks")) if "typecheck" in c.lower()][:1]


def integration_gate(cfg: dict, run: dict, worktree: str) -> tuple[bool, str]:
    """Merge the current base branch into the worktree, run a fast check, then abort."""
    commands = pre_merge_commands(cfg)
    if not commands:
        return True, ""
    base = cfg["base_branch"]
    merge = util.run(
        ["git", "-C", worktree, "merge", "--no-commit", "--no-ff", base], check=False
    )
    if merge.returncode != 0:
        util.run(["git", "-C", worktree, "merge", "--abort"], check=False)
        return False, (
            f"The branch conflicts with the current `{base}`. Merge `{base}` into the branch, "
            "resolve the conflicts and keep the checks green."
        )
    if "Already up to date" in (merge.stdout or ""):
        return True, ""
    failures: list[str] = []
    try:
        for index, command in enumerate(commands, start=1):
            log_path = os.path.join(
                run["run_dir"], "pre-merge", f"{index}-{util.slug(command)}.log"
            )
            code, duration = execute(
                cfg,
                worktree,
                command,
                log_path,
                float(cfg["commands"].get("check_timeout_min", 25)),
            )
            runners.emit(run["run_dir"], run, "integration", "check", f"{command}: exit {code} ({duration}s)")
            if code != 0:
                failures.append(f"`{command}` failed on the merged tree:\n\n{util.tail(log_path, 80)}")
        return (not failures), (
            "The branch merges cleanly but fails on the current base:\n\n" + "\n\n".join(failures)
            if failures
            else ""
        )
    finally:
        util.run(["git", "-C", worktree, "merge", "--abort"], check=False)


def needs_e2e(cfg: dict, worktree: str, base: str) -> bool:
    if not cfg["commands"].get("e2e"):
        return False
    prefixes = _cfg_list(cfg["commands"].get("e2e_on"))
    if not prefixes:
        return True
    for changed in gitops.changed_files(worktree, base):
        if any(changed.startswith(prefix) for prefix in prefixes):
            return True
    return False


def commit_message(cfg: dict, item: dict) -> str:
    kind = task_commit_type(cfg)
    area = str(cfg.get("commit_area") or "")
    scope = f"({area})" if area else ""
    task_id = item.get("id") or item.get("task") or ""
    title = (item.get("title") or "").strip().rstrip(".")
    if title:
        title = title[0].lower() + title[1:]
    if len(title) > 70:
        title = title[:69].rstrip() + "…"
    return f"{kind}{scope}: {title} ({task_id})"


def push_if_needed(project: str, force: bool = False) -> dict:
    """Push the base branch when the project has push enabled and is ahead."""
    _, repo, cfg = project_config.find_project(project)
    settings = cfg.get("push") or {}
    if not settings.get("enabled"):
        return {"enabled": False}
    remote = settings.get("remote") or "origin"
    branch = settings.get("branch") or cfg["base_branch"]
    state_path = os.path.join(repo, ".agent", "push.json")
    previous = util.read_json(state_path, None) or {}
    if not force:
        checked = util.parse_iso(previous.get("checked")) or 0
        if time.time() - checked < 120:
            return previous
    result = {
        "enabled": True,
        "remote": remote,
        "branch": branch,
        "checked": util.now_iso(),
        "ok": False,
        "pushed": False,
        "error": None,
    }
    if not gitops.remote_exists(repo, remote):
        result["error"] = f"remote {remote} is not configured"
        util.write_json(state_path, result)
        return result
    if gitops.current_branch(repo) != branch:
        result["error"] = f"base checkout is on {gitops.current_branch(repo)}, not {branch}"
        util.write_json(state_path, result)
        return result
    lock = os.path.join(repo, ".agent", "push.lock")
    util.ensure_dir(os.path.dirname(lock))
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
    except FileExistsError:
        other = util.read_json(lock, None) or {}
        if util.pid_alive(other.get("pid")):
            return previous or {"enabled": True, "ok": False, "error": "another push is running"}
        try:
            os.unlink(lock)
        except OSError:
            pass
    util.write_json(lock, {"pid": os.getpid(), "at": util.now_iso()})
    try:
        local = gitops.rev(repo)
        remote_sha = gitops.remote_branch_sha(repo, remote, branch)
        result.update({"local": local, "remote_sha": remote_sha})
        if remote_sha == local:
            result["ok"] = True
        elif remote_sha and not gitops.is_ancestor(repo, remote_sha, local):
            result["error"] = (
                f"{remote}/{branch} has commits that are not in the local branch; "
                "pull/rebase before pushing"
            )
        else:
            output = gitops.push_branch(
                repo,
                remote,
                branch,
                set_upstream=not remote_sha,
                no_verify=bool(settings.get("no_verify", True)),
            )
            result.update({"ok": True, "pushed": True, "output": output[-2000:]})
            log(f"{project}: pushed {branch} to {remote}")
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[-2000:]
        log(f"{project}: push failed — {str(exc).splitlines()[0][:200]}")
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass
        util.write_json(state_path, result)
    return result


def merge_lock_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "merge.lock")


def acquire_merge_lock(repo: str, task_id: str) -> None:
    path = merge_lock_path(repo)
    util.ensure_dir(os.path.dirname(path))
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            util.write_json(path, {"pid": os.getpid(), "task": task_id, "started": util.now_iso()})
            return
        except FileExistsError:
            existing = util.read_json(path, None) or {}
            if util.pid_alive(existing.get("pid")):
                raise SystemExit(
                    f"another merge is already running for {existing.get('task')} "
                    f"(pid {existing.get('pid')})"
                )
            try:
                os.unlink(path)
            except OSError:
                pass
    raise SystemExit("could not acquire the merge lock")


def release_merge_lock(repo: str) -> None:
    try:
        os.unlink(merge_lock_path(repo))
    except OSError:
        pass


def find_run(project: str, task_id: str | None = None) -> dict:
    _, repo, cfg = project_config.find_project(project)
    if task_id:
        directory = run_dir(repo, task_id)
        run = util.read_json(os.path.join(directory, "run.json"), None)
        if not run:
            raise SystemExit(f"no run found for {project} {task_id}")
        return run
    candidates = []
    runs_root = os.path.join(repo, ".agent", "runs")
    if os.path.isdir(runs_root):
        for name in os.listdir(runs_root):
            run = util.read_json(os.path.join(runs_root, name, "run.json"), None)
            if run and run.get("kind") == "task":
                candidates.append(run)
    if not candidates:
        raise SystemExit(f"no runs found for {project}")
    return max(candidates, key=lambda r: r.get("updated", ""))


def merge_run(
    project: str, task_id: str | None = None, force: bool = False, auto_fix: bool = False
) -> dict:
    _, repo, cfg = project_config.find_project(project)
    run = find_run(project, task_id)
    directory = run["run_dir"]
    project_config.commit_config(repo)
    if run["state"] == "merged":
        return run
    if force and not gitops.branch_exists(repo, run.get("branch", "")):
        raise SystemExit(f"branch {run.get('branch')} does not exist; nothing to merge")
    retry = (
        run["state"] == "needs-human"
        and run.get("verdict") == "PASS"
        and str(run.get("step", "")).startswith("merge")
    )
    if run["state"] != "passed" and not retry and not force:
        raise SystemExit(f"{project} {run['task']} is {run['state']}, not passed. Nothing to merge.")
    clean, status = gitops.is_clean(repo)
    if not clean:
        raise SystemExit(f"main checkout is not clean:\n{status}\nCommit or stash first.")
    acquire_merge_lock(repo, run["task"])
    run["state"] = "merging"
    run["step"] = "squash merge"
    util.write_json(os.path.join(directory, "run.json"), run)
    runners.emit(directory, run, "agent-room", "merge", f"merging {run['branch']}")
    marker = os.path.join(repo, ".agent", "merge.json")
    util.write_json(marker, {"pid": os.getpid(), "task": run["task"], "started": util.now_iso()})
    try:
        sha = gitops.merge_squash(repo, run["branch"], cfg["base_branch"], commit_message(cfg, run))
        task = tasklib.find_task(tasklib.load_tasks(cfg), run["task"])
        ticked = False
        if task:
            suffix = str(cfg.get("tick", {}).get("suffix") or "").replace("{date}", util.today())
            ticked = tasklib.tick(cfg, task, suffix)
        if ticked:
            util.run(["git", "-C", repo, "add", "--", cfg["tasks"]["file"]], check=False)
            util.run(
                ["git", "-C", repo, "commit", "-m", f"chore: mark {run['task']} done"],
                check=False,
            )
            check = tasklib.find_task(tasklib.load_tasks(cfg), run["task"])
            if not check or check["state"] != "x":
                run["tick_error"] = "tick did not persist; check the task file"
                runners.emit(directory, run, "agent-room", "warn", run["tick_error"])
        push_result = push_if_needed(project, force=True)
        if push_result.get("enabled") and not push_result.get("ok"):
            runners.emit(
                directory,
                run,
                "push",
                "warn",
                f"push failed: {str(push_result.get('error') or '')[:200]}",
            )
        run.update(
            {
                "state": "merged",
                "step": "merged",
                "finished": util.now_iso(),
                "error": None,
                "push": push_result,
                "merge": {
                    "sha": sha,
                    "ticked": ticked,
                    "at": util.now_iso(),
                    "pushed": bool(push_result.get("pushed")),
                },
            }
        )
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "merged", f"merged as {sha[:8]}")
        gitops.remove_worktree(repo, run["worktree"], run["branch"])
        return run
    except gitops.GitError as exc:
        conflict = "squash merge failed" in str(exc)
        failures = int(run.get("merge_failures") or 0) + 1
        if auto_fix and conflict and failures <= 1:
            run.update(
                {
                    "state": "fixing",
                    "step": "merge conflict",
                    "verdict": "FAIL",
                    "issues": (
                        f"The squash merge into `{cfg['base_branch']}` conflicts. In the worktree, run "
                        f"`git merge {cfg['base_branch']}`, resolve every conflict, keep the acceptance "
                        f"criteria and tests green, and commit.\n\n{str(exc)[-2000:]}"
                    ),
                    "error": str(exc)[-3000:],
                    "finished": None,
                    "merge_failures": failures,
                }
            )
            util.write_json(os.path.join(directory, "run.json"), run)
            runners.emit(directory, run, "agent-room", "conflict", "merge conflict — sending back to builder")
            return run
        run["state"] = "needs-human"
        run["step"] = "merge conflict" if conflict else "merge failed"
        run["error"] = str(exc)[-3000:]
        if auto_fix:
            tasklib.mark_blocked(repo, run["task"], run["error"] or run["step"])
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "error", "merge failed; needs a human")
        return run
    finally:
        try:
            os.unlink(marker)
        except OSError:
            pass
        release_merge_lock(repo)


def verify_run(project: str, task_id: str, *, overrides: dict | None = None) -> dict:
    """Re-run checks + verifier on an existing branch, without rebuilding."""
    _, repo, cfg = project_config.find_project(project)
    apply_agent_overrides(cfg, overrides)
    task = tasklib.find_task(tasklib.load_tasks(cfg), task_id)
    if not task:
        raise SystemExit(f"task {task_id} not found in {cfg['tasks'].get('file')}")
    branch = f"agent/{util.slug(task_id)}"
    worktree = os.path.join(util.expand(cfg["worktree_root"]), util.slug(task_id))
    if not gitops.worktree_exists(repo, worktree):
        raise SystemExit(f"no worktree for {project} {task_id}; run it first")
    if not gitops.branch_exists(repo, branch):
        raise SystemExit(f"branch {branch} is missing")
    abort_pending_merge(worktree)
    directory = run_dir(repo, task_id)
    util.ensure_dir(directory)
    previous = util.read_json(os.path.join(directory, "run.json"), None) or {}
    if previous.get("state") in util.ACTIVE_STATES and util.pid_alive(previous.get("pid")):
        raise SystemExit(f"{project} {task_id} is already running (pid {previous.get('pid')})")
    base_sha = gitops.merge_base(repo, cfg["base_branch"], branch) or previous.get("base_sha", "")
    if not base_sha:
        raise SystemExit("could not determine the branch point")
    if gitops.commit_count(worktree, base_sha) == 0:
        raise SystemExit(f"{branch} has no commits to verify")

    run: dict[str, Any] = dict(previous)
    run.update(
        {
            "run_id": f"{cfg['project']}-{task['id']}",
            "kind": "task",
            "project": cfg["project"],
            "task": task["id"],
            "title": task["title"],
            "state": "verifying",
            "step": "verifier (re-run)",
            "round": int(previous.get("round") or 1),
            "started": util.now_iso(),
            "updated": util.now_iso(),
            "finished": None,
            "repo": repo,
            "run_dir": directory,
            "worktree": worktree,
            "branch": branch,
            "base_branch": cfg["base_branch"],
            "base_sha": base_sha,
            "pid": os.getpid(),
            "cost_usd": float(previous.get("cost_usd") or 0),
            "checks": {},
            "verdict": None,
            "error": None,
            "merge": None,
            "recovered": True,
        }
    )
    stat = gitops.diff_stat(worktree, base_sha)
    run.update({"files_changed": stat["files"], "insertions": stat["insertions"], "deletions": stat["deletions"]})
    util.write_json(os.path.join(directory, "run.json"), run)
    acquire_lock(repo, cfg["project"], task["id"], directory)
    runners.emit(directory, run, "agent-room", "start", f"re-verify {task['id']}")
    try:
        copy_env_files(cfg, worktree)
        include_e2e = needs_e2e(cfg, worktree, base_sha)
        checks_ok = run_checks(cfg, worktree, run, include_e2e)
        gitops.write_diff(worktree, base_sha, os.path.join(directory, "diff.patch"))
        if not checks_ok:
            run["state"] = "needs-human"
            run["step"] = "checks failed"
            run["finished"] = util.now_iso()
            run["issues"] = failed_check_logs(run)
            util.write_json(os.path.join(directory, "run.json"), run)
            return run
        run["state"] = "verifying"
        run["step"] = "verifier (re-run)"
        util.write_json(os.path.join(directory, "run.json"), run)
        try:
            os.unlink(os.path.join(directory, "verify.md"))
        except OSError:
            pass
        result = runners.run_agent(
            "verifier",
            verifier_prompt(
                cfg, task, run, worktree, branch, run["round"], include_e2e=include_e2e
            ),
            worktree,
            directory,
            run,
            cfg,
        )
        if result["returncode"] != 0:
            runners.emit(directory, run, "verifier", "warn", f"verifier exited {result['returncode']}")
        verifier_committed = commit_verifier_changes(worktree, task)
        verdict, issues = parse_verify(os.path.join(directory, "verify.md"))
        if verdict == "PASS" and verifier_committed:
            if not run_checks(cfg, worktree, run, needs_e2e(cfg, worktree, base_sha)):
                verdict = "FAIL"
                issues = "The verifier's added tests failed:\n\n" + failed_check_logs(run)
        if verdict == "PASS":
            integrated, integration_detail = integration_gate(cfg, run, worktree)
            if not integrated:
                verdict = "FAIL"
                issues = integration_detail
        run["verdict"] = verdict
        run["state"] = "passed" if verdict == "PASS" else "needs-human"
        run["step"] = "ready to merge" if verdict == "PASS" else "verification failed"
        run["finished"] = util.now_iso()
        if verdict == "FAIL":
            run["issues"] = issues
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "verdict", verdict)
        return run
    except Exception as exc:  # noqa: BLE001
        run["state"] = "failed"
        run["step"] = "error"
        run["error"] = str(exc)
        run["traceback"] = traceback.format_exc()[-4000:]
        run["finished"] = util.now_iso()
        util.write_json(os.path.join(directory, "run.json"), run)
        return run
    finally:
        release_lock(repo, task["id"])


def requeue_task(project: str, task_id: str | None = None, note: str = "") -> dict:
    """Put a needs-human/failed/stopped run back in the builder queue, keeping its worktree."""
    _, repo, cfg = project_config.find_project(project)
    run = find_run(project, task_id)
    if run.get("state") not in {"needs-human", "failed", "stopped"}:
        raise SystemExit(f"{project} {run.get('task')} is {run.get('state')}, not needs-human/failed/stopped")
    worktree = run.get("worktree") or ""
    if not worktree or not gitops.worktree_exists(repo, worktree):
        raise SystemExit(
            f"{project} {run.get('task')} has no worktree; run it fresh instead: "
            f"aroom run {project} {run.get('task')} --fresh"
        )
    issues = (run.get("issues") or run.get("error") or "").strip()
    if note:
        issues = (note + "\n\n" + issues).strip()
    run.update(
        {
            "state": "fixing",
            "step": "requeued",
            "round": 0,
            "issues": issues or "Requeued for another attempt. Inspect the worktree, finish the task and commit.",
            "verdict": "FAIL",
            "error": None,
            "finished": None,
            "retry_after": None,
            "build_failures": 0,
            "verify_failures": 0,
            "merge_failures": 0,
            "integration_failures": 0,
            "started": util.now_iso(),
            "requeued_at": util.now_iso(),
            "requeue_count": int(run.get("requeue_count") or 0) + 1,
            "updated": util.now_iso(),
        }
    )
    directory = run.get("run_dir") or run_dir(repo, run["task"])
    util.ensure_dir(directory)
    util.write_json(os.path.join(directory, "run.json"), run)
    tasklib.unmark_blocked(repo, run["task"])
    release_lock(repo, run["task"])
    runners.emit(directory, run, "agent-room", "requeue", "returned to the builder queue")
    return run


def verify_task_phase(project: str, task_id: str, *, overrides: dict | None = None) -> dict:
    """Verify an already-built run, without rebuilding. Used by the async scheduler."""
    cfg = project_config.load_project(project_config.find_project(project)[1])
    apply_agent_overrides(cfg, overrides)
    repo = cfg["repo"]
    task = tasklib.find_task(tasklib.load_tasks(cfg), task_id)
    if not task:
        raise SystemExit(f"task {task_id} not found in {cfg['tasks'].get('file')}")
    directory = run_dir(repo, task_id)
    run = util.read_json(os.path.join(directory, "run.json"), None)
    if not run:
        raise SystemExit(f"no run record for {project} {task_id}")
    if run.get("state") == "passed":
        return run
    if run.get("state") != "built":
        raise SystemExit(f"{project} {task_id} is {run.get('state')}, not built")
    worktree = run.get("worktree") or os.path.join(util.expand(cfg["worktree_root"]), util.slug(task_id))
    branch = run.get("branch") or f"agent/{util.slug(task_id)}"
    if not gitops.worktree_exists(repo, worktree):
        raise SystemExit(f"{project} {task_id} has no worktree")
    if not gitops.branch_exists(repo, branch):
        raise SystemExit(f"{project} {task_id} has no branch")
    abort_pending_merge(worktree)

    fix_rounds = int(cfg["limits"].get("fix_rounds", 2))
    round_no = int(run.get("round") or 1)
    acquire_lock(repo, cfg["project"], task["id"], directory)
    try:
        run.update(
            {
                "state": "verifying",
                "step": f"verifier round {round_no}",
                "updated": util.now_iso(),
                "finished": None,
                "pid": os.getpid(),
            }
        )
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "verify", f"verifier round {round_no}")
        include_e2e = needs_e2e(cfg, worktree, run.get("base_sha", ""))
        gitops.write_diff(worktree, run.get("base_sha", ""), os.path.join(directory, "diff.patch"))
        try:
            os.unlink(os.path.join(directory, "verify.md"))
        except OSError:
            pass
        result = runners.run_agent(
            "verifier",
            verifier_prompt(
                cfg, task, run, worktree, branch, round_no, None, include_e2e
            ),
            worktree,
            directory,
            run,
            cfg,
        )
        if result["returncode"] != 0:
            detail = runners.summarize_error(os.path.join(directory, "verifier.log"))
            runners.emit(
                directory,
                run,
                "verifier",
                "warn",
                f"verifier exited {result['returncode']}" + (f": {detail}" if detail else ""),
            )
        if result["returncode"] != 0 and not os.path.exists(os.path.join(directory, "verify.md")):
            detail = runners.summarize_error(os.path.join(directory, "verifier.log"))
            raise RuntimeError(
                f"verifier exited {result['returncode']}: {detail or 'no verify.md written'}"
            )
        if budget_exceeded(cfg, run):
            raise RuntimeError(f"run budget exceeded (${run.get('cost_usd'):.2f})")
        verifier_committed = commit_verifier_changes(worktree, task)
        verdict, issues = parse_verify(os.path.join(directory, "verify.md"))
        if verdict == "PASS" and verifier_committed:
            if not run_checks(cfg, worktree, run, needs_e2e(cfg, worktree, run.get("base_sha", ""))):
                verdict = "FAIL"
                issues = "The verifier's added tests failed:\n\n" + failed_check_logs(run)
        if verdict == "PASS":
            integrated, integration_detail = integration_gate(cfg, run, worktree)
            if not integrated:
                verdict = "FAIL"
                issues = integration_detail
        run["verdict"] = verdict
        if verdict == "PASS":
            run.update(
                {
                    "state": "passed",
                    "step": "ready to merge",
                    "verdict": "PASS",
                    "issues": None,
                    "finished": util.now_iso(),
                }
            )
            runners.emit(directory, run, "agent-room", "pass", "PASS — branch ready")
        else:
            exhausted = round_no > fix_rounds
            integration_conflict = verdict == "FAIL" and "conflicts with the current" in (issues or "")
            integration_attempts = int(run.get("integration_failures") or 0)
            if exhausted and integration_conflict and integration_attempts < 1:
                exhausted = False
                run["integration_failures"] = integration_attempts + 1
            run.update(
                {
                    "state": "needs-human" if exhausted else "fixing",
                    "step": "verification failed" if exhausted else f"fix round {round_no}",
                    "verdict": "FAIL",
                    "issues": issues,
                    "finished": util.now_iso() if exhausted else None,
                }
            )
            runners.emit(
                directory,
                run,
                "agent-room",
                "verdict",
                "FAIL — sending back to builder" if not exhausted else "FAIL — needs a human",
            )
            if exhausted:
                tasklib.mark_blocked(repo, task_id, issues or "verification failed")
        util.write_json(os.path.join(directory, "run.json"), run)
        return run
    except Exception as exc:  # noqa: BLE001
        run["state"] = "failed"
        run["step"] = "verifier error"
        run["error"] = str(exc)
        run["traceback"] = traceback.format_exc()[-4000:]
        run["finished"] = util.now_iso()
        util.write_json(os.path.join(directory, "run.json"), run)
        runners.emit(directory, run, "agent-room", "error", str(exc)[:280])
        return run
    finally:
        release_lock(repo, task["id"])


def clean_task(project: str, task_id: str) -> bool:
    _, repo, cfg = project_config.find_project(project)
    directory = run_dir(repo, task_id)
    run = util.read_json(os.path.join(directory, "run.json"), None) or {}
    lock = util.read_json(lock_path(repo, task_id), None) or {}
    if util.pid_alive(lock.get("pid")):
        raise SystemExit(f"{project} {task_id} is running (pid {lock.get('pid')}); stop it first")
    if run.get("state") in util.ACTIVE_STATES and util.pid_alive(run.get("pid")):
        raise SystemExit(f"{project} {task_id} is running (pid {run.get('pid')}); stop it first")
    worktree = run.get("worktree") or os.path.join(util.expand(cfg["worktree_root"]), util.slug(task_id))
    branch = run.get("branch") or f"agent/{util.slug(task_id)}"
    existed = gitops.worktree_exists(repo, worktree) or gitops.branch_exists(repo, branch)
    gitops.remove_worktree(repo, worktree, branch)
    if run:
        run["state"] = "stopped"
        run["step"] = "worktree removed"
        run["finished"] = util.now_iso()
        util.write_json(os.path.join(directory, "run.json"), run)
    return existed


def mark_merged(project: str, task_id: str | None = None) -> dict:
    """Reconcile a run whose squash merge was resolved and committed by hand."""
    _, repo, cfg = project_config.find_project(project)
    run = find_run(project, task_id)
    directory = run["run_dir"]
    if run["state"] == "merged":
        return run
    if not str(run.get("step", "")).startswith("merge") and run["state"] != "passed":
        raise SystemExit(
            f"{project} {run['task']} is {run['state']}, not a merge. Use resume/verify instead."
        )
    unmerged = util.run(
        ["git", "-C", repo, "diff", "--name-only", "--diff-filter=U"], check=False
    ).stdout.strip()
    if unmerged:
        raise SystemExit(f"unresolved conflicts remain:\n{unmerged}")
    project_config.commit_config(repo)
    clean, status = gitops.is_clean(repo)
    if not clean:
        raise SystemExit(
            f"the resolved merge is not committed yet:\n{status}\n"
            "Commit it first, then mark merged."
        )
    task = tasklib.find_task(tasklib.load_tasks(cfg), run["task"])
    ticked = False
    if task:
        suffix = str(cfg.get("tick", {}).get("suffix") or "").replace("{date}", util.today())
        ticked = tasklib.tick(cfg, task, suffix)
    if ticked:
        util.run(["git", "-C", repo, "add", "--", cfg["tasks"]["file"]], check=False)
        util.run(
            ["git", "-C", repo, "commit", "-m", f"chore: mark {run['task']} done"],
            check=False,
        )
    sha = gitops.rev(repo)
    run.update(
        {
            "state": "merged",
            "step": "merged",
            "verdict": run.get("verdict") or "PASS",
            "error": None,
            "finished": util.now_iso(),
            "merge": {"sha": sha, "ticked": ticked, "at": util.now_iso(), "manual": True},
        }
    )
    util.write_json(os.path.join(directory, "run.json"), run)
    tasklib.unmark_blocked(repo, run["task"])
    gitops.remove_worktree(repo, run.get("worktree", ""), run.get("branch"))
    release_lock(repo, run["task"])
    runners.emit(directory, run, "agent-room", "merged", f"marked merged manually at {sha[:8]}")
    return run


def run_loop(
    project: str,
    *,
    max_tasks: int | None = None,
    auto_merge: bool | None = None,
    interval: int = 5,
    forever: bool = False,
    overrides: dict | None = None,
    fresh: bool = False,
) -> list[dict]:
    _, repo, cfg = project_config.find_project(project)
    effective_merge = cfg["limits"].get("auto_merge", False) if auto_merge is None else auto_merge
    loop_file = os.path.join(repo, ".agent", "loop.json")
    payload = {"project": project, "pid": os.getpid(), "started": util.now_iso(), "forever": forever}
    for _ in range(2):
        try:
            fd = os.open(loop_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            util.write_json(loop_file, payload)
            break
        except FileExistsError:
            existing = util.read_json(loop_file, None)
            if existing and util.pid_alive(existing.get("pid")):
                raise SystemExit(f"a loop is already running for {project} (pid {existing.get('pid')})")
            try:
                os.unlink(loop_file)
            except OSError:
                pass
    else:
        raise SystemExit(f"could not acquire the loop lock at {loop_file}")
    limit = int(max_tasks or cfg["limits"].get("max_tasks", 10))
    results: list[dict] = []
    completed = 0
    try:
        while forever or completed < limit:
            if os.path.exists(os.path.join(repo, ".agent", "drain")):
                log(f"{project}: drain requested; exiting loop")
                break
            # Reload config each cycle: plans, regexes and models may change while a loop runs.
            cfg = project_config.load_project(repo)
            if cfg["limits"].get("async"):
                log(f"{project}: async mode enabled; handing over to the async pipeline")
                break
            tasks = tasklib.load_tasks(cfg)
            task = tasklib.next_task(tasks, tasklib.blocked_ids(repo))
            if not task:
                if forever:
                    log(f"{project}: no open tasks — waiting {max(interval, 10)}s")
                    time.sleep(max(interval, 10))
                    continue
                log(f"{project}: no open tasks")
                break
            completed += 1
            position = f"#{completed}" if forever else f"{completed}/{limit}"
            existing = util.read_json(os.path.join(run_dir(repo, task["id"]), "run.json"), None)
            if existing and existing.get("state") == "passed":
                if effective_merge:
                    log(f"{project}: merging already-passed {task['id']}")
                    merged = merge_run(project, task["id"])
                    results.append(merged)
                    if merged["state"] == "merged":
                        continue
                log(f"{project}: {task['id']} already passed; merge it first")
                break
            remerge = (
                existing
                and existing.get("state") == "needs-human"
                and existing.get("verdict") == "PASS"
                and str(existing.get("step", "")).startswith("merge")
            )
            if remerge and effective_merge:
                log(f"{project}: retrying merge for {task['id']}")
                merged = merge_run(project, task["id"])
                results.append(merged)
                if merged["state"] == "merged":
                    continue
                break
            worktree = os.path.join(util.expand(cfg["worktree_root"]), util.slug(task["id"]))
            branch = f"agent/{util.slug(task['id'])}"
            if not fresh and (gitops.worktree_exists(repo, worktree) or gitops.branch_exists(repo, branch)):
                log(
                    f"{project}: {task['id']} has a leftover worktree/branch; "
                    f"run `aroom verify {project} {task['id']}` or `aroom clean {project} {task['id']}`"
                )
                break
            log(f"{project}: starting {task['id']} — {task['title']} ({position})")
            run = run_task(project, task, auto_merge=auto_merge, overrides=overrides, fresh=fresh)
            results.append(run)
            log(f"{project}: {task['id']} → {run['state']}")
            if run["state"] == "merged":
                try:
                    push_if_needed(project)
                except Exception:  # noqa: BLE001
                    pass
            if run["state"] != "merged":
                log(f"{project}: stopping the loop; {task['id']} is {run['state']}")
                break
            if float(run.get("cost_usd") or 0) > float(cfg["limits"].get("run_budget_usd", 20)):
                log(f"{project}: run budget reached (${run.get('cost_usd'):.2f}); stopping")
                break
            if interval:
                time.sleep(max(0, interval))
    finally:
        try:
            os.unlink(loop_file)
        except OSError:
            pass
    return results


def stop(project: str) -> bool:
    _, repo, cfg = project_config.find_project(project)
    stopped = False
    marker = os.path.join(repo, ".agent", "merge.json")
    in_flight = util.read_json(marker, None) or {}
    if in_flight and util.pid_alive(in_flight.get("pid")):
        print(f"{project}: waiting for {in_flight.get('task')} to finish its merge…")
        deadline = time.time() + 180
        while os.path.exists(marker) and time.time() < deadline:
            time.sleep(1)
        if os.path.exists(marker) and util.pid_alive(in_flight.get("pid")):
            print(f"{project}: merge still running after 3m; stopping it anyway")
    try:
        os.unlink(marker)
    except OSError:
        pass
    release_merge_lock(repo)
    loop_file = os.path.join(repo, ".agent", "loop.json")
    loop = util.read_json(loop_file, None)
    if loop and util.pid_alive(loop.get("pid")):
        util.kill_tree(loop["pid"], signal.SIGTERM)
        time.sleep(1)
        if util.pid_alive(loop["pid"]):
            util.kill_tree(loop["pid"], signal.SIGKILL)
        print(f"{project}: stopped loop pid {loop['pid']}")
        stopped = True
        try:
            os.unlink(loop_file)
        except OSError:
            pass

    lanes = util.read_json(os.path.join(repo, ".agent", "scheduler.json"), None) or {}
    children = []
    for entry in (lanes.get("builders") or {}).values():
        if entry.get("pid"):
            children.append(entry)
    builder = lanes.get("builder") or {}
    if builder.get("pid"):
        children.append(builder)
    for entry in (lanes.get("verifiers") or {}).values():
        if entry.get("pid"):
            children.append(entry)
    for entry in children:
        pid = entry.get("pid")
        if pid and util.pid_alive(pid):
            util.kill_tree(pid, signal.SIGTERM)
            time.sleep(1)
            if util.pid_alive(pid):
                util.kill_tree(pid, signal.SIGKILL)
            print(f"{project}: stopped pid {pid} ({entry.get('task')})")
            stopped = True
    try:
        os.unlink(os.path.join(repo, ".agent", "scheduler.json"))
    except OSError:
        pass

    locks = active_locks(repo)
    if not locks and not stopped:
        print(f"{project}: nothing is running")
        return stopped
    for path, data in locks:
        pid = data.get("pid")
        if pid and util.pid_alive(pid):
            util.kill_tree(pid, signal.SIGTERM)
            time.sleep(1)
            if util.pid_alive(pid):
                util.kill_tree(pid, signal.SIGKILL)
            print(f"{project}: stopped pid {pid} ({data.get('task')})")
            stopped = True
        directory = data.get("run_dir")
        if directory:
            run = util.read_json(os.path.join(directory, "run.json"), None)
            if run and run.get("state") in util.ACTIVE_STATES:
                run["state"] = "stopped"
                run["step"] = "stopped by user"
                run["finished"] = util.now_iso()
                util.write_json(os.path.join(directory, "run.json"), run)
        try:
            os.unlink(path)
        except OSError:
            pass
    return stopped


def research(project: str, question: str) -> dict:
    _, repo, cfg = project_config.find_project(project)
    slug = util.slug(question)[:50]
    task_id = f"research-{slug}"
    directory = run_dir(repo, task_id)
    if os.path.isdir(directory):
        shutil.rmtree(directory)
    util.ensure_dir(directory)
    output = os.path.join(repo, "docs", "research", f"{util.today()}-{slug}.md")
    run: dict[str, Any] = {
        "run_id": f"{cfg['project']}-{task_id}",
        "kind": "research",
        "project": cfg["project"],
        "task": task_id,
        "title": question[:120],
        "state": "queued",
        "step": "queued",
        "started": util.now_iso(),
        "updated": util.now_iso(),
        "finished": None,
        "repo": repo,
        "run_dir": directory,
        "worktree": repo,
        "branch": cfg["base_branch"],
        "base_branch": cfg["base_branch"],
        "base_sha": "",
        "pid": os.getpid(),
        "cost_usd": 0.0,
        "checks": {},
        "verdict": None,
        "output": output,
        "events_count": 0,
    }
    util.write_json(os.path.join(directory, "run.json"), run)
    runners.emit(directory, run, "agent-room", "start", f"research · {question[:80]}")
    run["state"] = "building"
    run["step"] = "researching"
    util.write_json(os.path.join(directory, "run.json"), run)
    prompt = render(
        "researcher.md",
        PROJECT=cfg["project"],
        QUESTION=question,
        REPO=repo,
        OUTPUT=output,
    )
    result = runners.run_agent("researcher", prompt, repo, directory, run, cfg)
    ok = result["returncode"] == 0 and os.path.isfile(output)
    run["state"] = "passed" if ok else "failed"
    run["step"] = "done" if ok else "research failed"
    run["finished"] = util.now_iso()
    if not ok:
        run["error"] = "researcher did not produce the output file"
    util.write_json(os.path.join(directory, "run.json"), run)
    return run
