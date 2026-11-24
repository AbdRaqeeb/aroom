"""Global registry and per-project configuration."""

from __future__ import annotations

import copy
import os
import re
from typing import Any

from . import util

DEFAULT_AGENT = {
    "runner": "claude",
    "model": "",
    "timeout_min": 45,
}

DEFAULT_PROJECT: dict[str, Any] = {
    "project": "",
    "base_branch": "main",
    "worktree_root": "",
    "tasks": {
        "adapter": "markdown",
        "file": "docs/PLAN.md",
        "id_regex": r"[A-Z]+-?\d+(?:\.\d+)*",
        "done_marker": "[x]",
    },
    "commands": {
        "setup": [],
        "checks": [],
        "e2e": "",
        "e2e_on": [],
        "setup_timeout_min": 25,
        "check_timeout_min": 25,
    },
    "isolation": {
        "env_script": ".agent/env.sh",
        "copy_env": [],
        "parallel_safe": True,
    },
    "agents": {
        "builder": dict(DEFAULT_AGENT, timeout_min=60),
        "verifier": dict(DEFAULT_AGENT, runner="opencode", timeout_min=40),
        "researcher": dict(DEFAULT_AGENT, timeout_min=40),
    },
    "limits": {
        "fix_rounds": 2,
        "run_budget_usd": 20,
        "auto_merge": False,
        "max_tasks": 10,
        "async": False,
        "builders": 1,
        "verifiers": 2,
    },
    "research": {
        "auto": True,
        "required": False,
        "triggers": [r"\bai\b", r"\bresearch\b", r"\bvendor\b"],
        "dir": "docs/research",
        "timeout_min": 30,
    },
    "paths": {"allow": [], "deny": []},
    "tick": {"suffix": ""},
    "push": {"enabled": False, "remote": "origin", "branch": "", "no_verify": True},
    "preview": {"command": "", "url": "", "port": 0, "cwd": ".", "env_script": True},
}

DEFAULT_REGISTRY: dict[str, Any] = {
    "version": 1,
    "ui": {"host": "127.0.0.1", "port": 4400},
    "defaults": {
        "worktree_root": "~/.local/share/agent-room/worktrees",
        "fix_rounds": 2,
        "auto_merge": False,
    },
    "projects": {},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_registry() -> dict:
    data = util.read_json(util.REGISTRY, {}) or {}
    reg = deep_merge(DEFAULT_REGISTRY, data)
    reg["projects"] = dict(reg.get("projects") or {})
    return reg


def save_registry(reg: dict) -> None:
    util.write_json(util.REGISTRY, reg)


def register(path: str, name: str | None = None) -> tuple[str, str]:
    repo = util.expand(path)
    if not os.path.isdir(repo):
        raise SystemExit(f"not a directory: {repo}")
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SystemExit(
            f"{repo} is not a git repository. Agent Room needs git worktrees.\n"
            f"Run `git init` there first (or point at the repo root)."
        )
    cfg = load_project(repo, register_missing=False)
    project = name or cfg.get("project") or os.path.basename(repo)
    reg = load_registry()
    # remove any older entry pointing at the same path
    for existing, value in list(reg["projects"].items()):
        if util.expand(value) == repo and existing != project:
            del reg["projects"][existing]
    reg["projects"][project] = repo
    save_registry(reg)
    return project, repo


def unregister(name: str) -> bool:
    reg = load_registry()
    if name not in reg["projects"]:
        return False
    del reg["projects"][name]
    save_registry(reg)
    return True


def project_paths() -> dict[str, str]:
    reg = load_registry()
    return {k: util.expand(v) for k, v in reg["projects"].items()}


def config_path(repo: str) -> str:
    return os.path.join(repo, ".agent", "config.json")


def load_project(repo: str, register_missing: bool = False) -> dict:
    repo = util.expand(repo)
    raw = util.read_json(config_path(repo), {}) or {}
    cfg = deep_merge(DEFAULT_PROJECT, raw)
    cfg["repo"] = repo
    cfg["project"] = cfg.get("project") or os.path.basename(repo)
    branch = current_branch(repo)
    if not raw.get("base_branch") and branch:
        cfg["base_branch"] = branch
    if not cfg.get("worktree_root"):
        default = load_registry()["defaults"]["worktree_root"]
        cfg["worktree_root"] = os.path.join(util.expand(default), cfg["project"])
    raw_limits = raw.get("limits") or {}
    if "auto_merge" not in raw_limits:
        cfg["limits"]["auto_merge"] = bool(load_registry()["defaults"].get("auto_merge"))
    if "fix_rounds" not in raw_limits:
        cfg["limits"]["fix_rounds"] = load_registry()["defaults"].get("fix_rounds", 2)
    if os.environ.get("AR_MOCK"):
        for agent in cfg.get("agents", {}).values():
            agent["runner"] = "mock"
    return cfg


def save_project(repo: str, cfg: dict) -> None:
    clean = {k: v for k, v in cfg.items() if k != "repo"}
    util.write_json(config_path(repo), clean)


def current_branch(repo: str) -> str:
    proc = util.run(["git", "-C", repo, "branch", "--show-current"])
    return proc.stdout.strip()


def detect_tasks(repo: str) -> dict:
    candidates = [
        "docs/PLAN.md",
        "docs/TASKS.md",
        "docs/BACKLOG.md",
        "TASKS.md",
        "PLAN.md",
        "TODO.md",
        "docs/TODO.md",
    ]
    for rel in candidates:
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            continue
        regex = detect_id_regex(path)
        if regex:
            return {"adapter": "markdown", "file": rel, "id_regex": regex}
    return {"adapter": "files", "file": ".agent/tasks", "id_regex": r"[A-Za-z0-9._-]+"}


def detect_id_regex(path: str) -> str | None:
    patterns = [
        r"M\d+\.\d+",
        r"T-\d{3,}",
        r"[A-Z]{1,4}-\d{2,}",
        r"\d+\.\d+",
    ]
    try:
        text = open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    for pattern in patterns:
        matches = re.findall(rf"^\s*[-*]\s*\[[ xX]\]\s+(?:\*\*)?({pattern})", text, re.MULTILINE)
        if matches:
            # T-NNN would also match the generic pattern; prefer the specific one.
            return pattern
    return None


def detect_preview(repo: str) -> dict:
    """Guess how to run the web app for a clickable preview."""
    root_pkg = util.read_json(os.path.join(repo, "package.json"), {}) or {}
    scripts = root_pkg.get("scripts") if isinstance(root_pkg.get("scripts"), dict) else {}
    if os.path.exists(os.path.join(repo, "pnpm-lock.yaml")) or os.path.exists(os.path.join(repo, "pnpm-workspace.yaml")):
        pm = "pnpm"
    elif os.path.exists(os.path.join(repo, "yarn.lock")):
        pm = "yarn"
    else:
        pm = "npm"

    port = 0
    for rel in ("apps/web/.env", "apps/web/.env.local", ".env", ".env.local"):
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        match = re.search(r"^(?:WEB_PORT|PORT|VITE_PORT)\s*=\s*(\d+)", text, re.MULTILINE)
        if match:
            port = int(match.group(1))
            break

    vite = os.path.join(repo, "apps/web/vite.config.ts")
    if not os.path.exists(vite):
        vite = os.path.join(repo, "vite.config.ts")
    if os.path.exists(vite):
        try:
            text = open(vite, "r", encoding="utf-8", errors="replace").read()
            match = re.search(r"port:\s*(\d+)", text)
            if match and not port:
                port = int(match.group(1))
        except OSError:
            pass

    has_web = os.path.isdir(os.path.join(repo, "apps/web"))
    has_next = any(os.path.exists(os.path.join(repo, name)) for name in ("next.config.ts", "next.config.js", "next.config.mjs"))
    has_vite = os.path.exists(vite)
    command = ""
    if scripts.get("dev"):
        command = f"{pm} dev"
    elif has_web:
        web_pkg = util.read_json(os.path.join(repo, "apps/web/package.json"), {}) or {}
        name = web_pkg.get("name")
        if name:
            command = f"{pm} --filter {name} dev"

    if not command:
        return {"command": "", "url": "", "port": 0, "cwd": ".", "env_script": True}
    if not port:
        port = 3000 if has_next else 5173
    return {
        "command": command,
        "url": f"http://localhost:{port}",
        "port": port,
        "cwd": ".",
        "env_script": True,
    }


def detect_commands(repo: str) -> dict:
    scripts: dict[str, str] = {}
    pkg = util.read_json(os.path.join(repo, "package.json"), {}) or {}
    if isinstance(pkg.get("scripts"), dict):
        scripts = pkg["scripts"]
    if os.path.exists(os.path.join(repo, "pnpm-lock.yaml")) or os.path.exists(os.path.join(repo, "pnpm-workspace.yaml")):
        pm = "pnpm"
        setup = ["pnpm install"]
    elif os.path.exists(os.path.join(repo, "package-lock.json")):
        pm = "npm"
        setup = ["npm install"]
    elif os.path.exists(os.path.join(repo, "yarn.lock")):
        pm = "yarn"
        setup = ["yarn install"]
    elif os.path.exists(os.path.join(repo, "bun.lockb")) or os.path.exists(os.path.join(repo, "bun.lock")):
        pm = "bun"
        setup = ["bun install"]
    elif os.path.exists(os.path.join(repo, "composer.json")):
        return {
            "setup": ["composer install"],
            "checks": ["composer test"] if os.path.exists(os.path.join(repo, "vendor")) else [],
            "e2e": "",
            "e2e_on": [],
        }
    elif os.path.exists(os.path.join(repo, "pyproject.toml")):
        return {"setup": ["uv sync"], "checks": ["uv run pytest -q"], "e2e": "", "e2e_on": []}
    elif os.path.exists(os.path.join(repo, "go.mod")):
        return {"setup": ["go mod download"], "checks": ["go test ./..."], "e2e": "", "e2e_on": []}
    else:
        return {"setup": [], "checks": [], "e2e": "", "e2e_on": []}

    checks = [f"{pm} {name}" for name in ("lint", "typecheck", "test") if name in scripts]
    if not checks and "check" in scripts:
        checks = [f"{pm} check"]
    e2e = f"{pm} e2e" if "e2e" in scripts else ""
    e2e_on: list[str] = []
    if e2e:
        for candidate in ("apps/web", "src", "web"):
            if os.path.isdir(os.path.join(repo, candidate)):
                e2e_on = [candidate]
                break
    return {"setup": setup, "checks": checks, "e2e": e2e, "e2e_on": e2e_on}


ENV_TEMPLATE = """#!/usr/bin/env bash
# Sourced before setup, checks and every agent session for this project.
# Agent Room provides: AR_PROJECT, AR_TASK, AR_RUN_ID, AR_WORKTREE, AR_RUN_DIR.
# Use it to give each run its own database, Redis index and ports.
#
# example:
# export DATABASE_URL="postgres://postgres:postgres@localhost:5432/{name}_${{AR_RUN_ID}}"
# export REDIS_DB=3
# export WEB_PORT=3100
# export API_PORT=6100
"""

GITATTRIBUTES = """# Keep text files LF in the repository and in the working tree.
# This is the single source of truth, regardless of core.autocrlf.

* text=auto eol=lf

*.sh text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf

# Binary assets
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.webp binary
*.ico binary
*.woff binary
*.woff2 binary
*.ttf binary
*.otf binary
*.mp4 binary
*.mov binary
*.webm binary
*.mp3 binary
*.wav binary
*.pdf binary
*.zip binary
"""

EDITORCONFIG = """root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{md,mdx}]
trim_trailing_whitespace = false
"""


def ensure_repo_hygiene(repo: str) -> list[str]:
    """Make LF the repo rule so agents and humans cannot fight over endings."""
    notes: list[str] = []
    attributes = os.path.join(repo, ".gitattributes")
    if not os.path.exists(attributes):
        with open(attributes, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(GITATTRIBUTES)
        notes.append(".gitattributes created (text=auto eol=lf)")
    else:
        try:
            text = open(attributes, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        if "eol=lf" not in text:
            notes.append("warning: .gitattributes has no `eol=lf` rule; add `* text=auto eol=lf`")

    editor = os.path.join(repo, ".editorconfig")
    if not os.path.exists(editor):
        with open(editor, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(EDITORCONFIG)
        notes.append(".editorconfig created (end_of_line = lf)")
    else:
        try:
            text = open(editor, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        if "end_of_line" not in text:
            notes.append("warning: .editorconfig has no `end_of_line = lf`")

    util.run(["git", "-C", repo, "config", "core.autocrlf", "false"], check=False)
    return notes


def init_project(path: str = ".", name: str | None = None) -> tuple[str, str, dict]:
    repo = util.expand(path)
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SystemExit(
            f"{repo} is not a git repository.\n"
            f"Agent Room isolates every task in a git worktree, so the project must be a repo.\n"
            f"Run: git -C {repo} init"
        )
    existing = util.read_json(config_path(repo), None)
    cfg = load_project(repo)
    if existing is None:
        cfg["project"] = name or os.path.basename(repo)
        cfg["base_branch"] = current_branch(repo) or "main"
        cfg["tasks"] = detect_tasks(repo)
        cfg["commands"].update(detect_commands(repo))
        cfg["preview"] = detect_preview(repo)
        env_files: list[str] = []
        for root, dirs, files in os.walk(repo):
            depth = root[len(repo) :].count(os.sep)
            if depth > 2:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".next", "dist", "build", "vendor"}]
            for filename in files:
                if filename == ".env" or (filename.startswith(".env.") and filename != ".env.example"):
                    env_files.append(os.path.relpath(os.path.join(root, filename), repo))
        cfg["isolation"]["copy_env"] = sorted(env_files)[:8]
        save_project(repo, cfg)
    if name:
        cfg["project"] = name
        save_project(repo, cfg)

    env_path = os.path.join(repo, ".agent", "env.sh")
    if not os.path.exists(env_path):
        util.ensure_dir(os.path.dirname(env_path))
        with open(env_path, "w", encoding="utf-8") as fh:
            fh.write(ENV_TEMPLATE.format(name=cfg["project"]))
        os.chmod(env_path, 0o755)

    gitignore = os.path.join(repo, ".gitignore")
    try:
        ignore_text = open(gitignore, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        ignore_text = ""
    if ".agent/runs/" not in ignore_text:
        util.append_once(
            gitignore,
            "# agent-room run artifacts\n.agent/runs/\n.agent/lock\n.agent/loop.json\n.agent/daemon.log\n.agent/preview.json\n.agent/preview.log\n.agent/chat.json\n.agent/chat.log\n",
        )
    elif ".agent/loop.json" not in ignore_text:
        util.append_once(
            gitignore,
            ".agent/loop.json\n.agent/preview.json\n.agent/preview.log\n.agent/chat.json\n.agent/chat.log\n",
        )

    hygiene_notes = ensure_repo_hygiene(repo)
    project, repo = register(repo, cfg["project"])
    final_cfg = load_project(repo)
    final_cfg["hygiene_notes"] = hygiene_notes
    return project, repo, final_cfg


def find_project(name: str | None = None) -> tuple[str, str, dict]:
    """Resolve a project by registry name, or by cwd."""
    if name:
        paths = project_paths()
        if name in paths:
            repo = paths[name]
            return name, repo, load_project(repo)
        candidate = util.expand(name)
        if os.path.isdir(candidate):
            project, repo = register(candidate)
            return project, repo, load_project(repo)
        raise SystemExit(f"unknown project: {name}. Try `aroom projects` or `aroom add <path>`.")

    cwd = os.getcwd()
    paths = project_paths()
    for project, repo in paths.items():
        if cwd == repo or cwd.startswith(repo + os.sep):
            return project, repo, load_project(repo)
    if os.path.isfile(config_path(cwd)):
        project, repo = register(cwd)
        return project, repo, load_project(repo)
    raise SystemExit("No project given and the current directory is not registered. Try `aroom run <project>`.")


def patch_project(repo: str, dotted: str, value: Any) -> dict:
    cfg = load_project(repo)
    node = cfg
    keys = dotted.split(".")
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    save_project(repo, cfg)
    return cfg


def set_raw(repo: str, dotted: str, value: Any) -> dict:
    """Write one dotted key into the config file, preserving everything else."""
    raw = util.read_json(config_path(repo), {}) or {}
    node = raw
    keys = dotted.split(".")
    for key in keys[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value
    util.write_json(config_path(repo), raw)
    return load_project(repo)


def update_agents(repo: str, updates: dict) -> dict:
    """Update agents.<role>.runner/model and validate the values."""
    raw = util.read_json(config_path(repo), {}) or {}
    agents = raw.setdefault("agents", {})
    for role in ("builder", "verifier", "researcher"):
        values = updates.get(role) or {}
        runner = values.get("runner")
        model = values.get("model")
        if runner is not None and runner not in {"claude", "opencode", "mock"}:
            raise ValueError(f"unknown runner: {runner}")
        if model is not None and not re.fullmatch(r"[A-Za-z0-9._:/#@+\-]*", str(model)):
            raise ValueError(f"invalid model id: {model}")
        entry = agents.setdefault(role, {})
        if runner is not None:
            entry["runner"] = runner
        if model is not None:
            entry["model"] = str(model)
    util.write_json(config_path(repo), raw)
    commit_config(repo)
    return load_project(repo)


def commit_config(repo: str) -> bool:
    """Commit .agent/config.json when it is the only tracked change.

    Model switches must not leave the base dirty, or the next merge will be
    refused. If the user has other work in progress, leave it alone.
    """
    status = util.run(
        ["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"]
    ).stdout.strip()
    if status != "M .agent/config.json":
        return False
    util.run(["git", "-C", repo, "add", "--", ".agent/config.json"], check=False)
    proc = util.run(
        ["git", "-C", repo, "commit", "-m", "chore: update agent config"], check=False
    )
    return proc.returncode == 0
