# Agent Room

A local, multi-project console for running coding agents against real tasks.

One `aroom` binary, a registry of repos anywhere on disk, and a per-repo
`.agent/config.json` that says how that project builds, tests, and stores tasks.
The dashboard shows every project and every run in one place.

No server, no database, no agent framework. State is git branches plus JSON/JSONL
files under each repo's `.agent/`.

**v1.0.2** · Python stdlib · Claude Code, OpenCode, or a deterministic mock runner.

## Requirements

- Linux or macOS with `git` and Python 3.10+
- One agent CLI on `PATH`: `claude` (Claude Code) or `opencode` (OpenCode)
- Optional: `gh` for GitHub task adapter and releases
- Each managed project must be a git repo with a clean base branch

On macOS the system `python3` is still 3.9 on many machines. Install a newer one
with `brew install python@3.12` (or from python.org); `install.sh` finds it even
when `python3` itself is too old.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/configuration.md](docs/configuration.md) | Every `.agent/config.json` key, adapters, roles, limits, push, preview |
| [docs/architecture.md](docs/architecture.md) | Modules, run state machine, async lanes, locks, merge and push flow |
| [docs/remote.md](docs/remote.md) | VPS install, phone access (Tailscale / Caddy), access token |
| [docs/operations.md](docs/operations.md) | systemd/launchd services, logs, reboot recovery, backups, upgrades |
| [docs/troubleshooting.md](docs/troubleshooting.md) | UI/loop failures, stuck tasks, conflicts, push and quota errors |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Install

One command, on Linux or macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.sh | bash
```

Then:

```bash
exec $SHELL -l
aroom --version
aroom doctor
```

The installer:

- clones the repo into `~/.local/share/aroom` (`AROOM_HOME` changes this), or
  updates it if it is already there
- picks a Python 3.10+ interpreter (including Homebrew `python3.12` when the
  macOS system `python3` is 3.9) and writes `~/.local/bin/aroom`
- adds `~/.local/bin` to `PATH` and `alias ar="aroom"` to your shell rc, once
  (`/usr/bin/ar` is the GNU archiver, so it is never shadowed)

Options go after `bash -s --`:

| Option | Effect |
| --- | --- |
| `--service` | Linux: run the dashboard and supervisor as systemd user services that survive logout and reboot (use this on a VPS) |
| `--listen ADDR` | Address the dashboard service binds. The default is `127.0.0.1` |
| `--ref REF` | Install a branch or tag, e.g. `--ref v1.1.0` |

**Upgrade:** run the same command again, or
`git -C ~/.local/share/aroom pull --ff-only`.

**From a clone:** `./install.sh` works the same way and links the launcher to
that checkout.

### On a VPS, used from your phone

```bash
curl -fsSL https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.sh | bash -s -- --service
sudo tailscale serve --bg 4400          # HTTPS on your tailnet, no open ports
aroom token --link --url https://<vps>.<tailnet>.ts.net
```

Open the link on the phone and add it to the home screen.
[docs/remote.md](docs/remote.md) covers Tailscale, Caddy with a domain, preview
links, and running the service.

## Quick start

```bash
cd /path/to/your-project
aroom init .                 # detect tasks, commands, base branch; register
aroom next                   # show the next open task
aroom run --mock             # end-to-end dry run with a fake model (free)
aroom run                    # real run: builder → checks → verifier → fix loop
aroom ui                     # http://127.0.0.1:4400
```

`aroom init` writes `.agent/config.json`, `.agent/env.sh` and a `.gitignore`
entry. Commit those before the first run (merges need a clean base):

```bash
git add .agent .gitignore && git commit -m "chore: add agent room config"
```

## Dashboard
`aroom ui` serves one page for **every registered project**, wherever it lives.
It polls each repo's `.agent/runs/*/run.json` and shows:

- a **needs you** inbox: every stuck task across projects, with the reason in
  plain words, the full evidence, and buttons that fix it (including a merge
  conflict resolver that runs in the task's worktree)
- project cards with the current task, state, step, elapsed time, cost and checks
- the event stream (tool calls from Claude Code / OpenCode)
- passed / needs-human / failed runs that need a merge or a look
- a task queue with **run** buttons, and **loop** for continuous work
- a git section per card: branch, origin link, upstream sync, HEAD, push state
- a details modal with every worktree, local branch, tracking state and remote
- a detail drawer with brief, events, verify.md, diff and check logs
- add-project from the UI (path to any git repo)

Deep links work: `http://127.0.0.1:4400/?project=aworin&task=M1.9`.

The UI can start, stop and merge runs. It binds `127.0.0.1` by default. Once
an access token exists (`aroom token --new`, or automatically with
`--host 0.0.0.0` or `--service`), every request must sign in. To use it from
another device, see [docs/remote.md](docs/remote.md).

## Switching runners and models

Each role has its own CLI and model: `builder`, `verifier`, `researcher`.
Runners are `claude`, `opencode`, or `mock`.

```bash
aroom models                          # what is available
aroom config aworin agents.verifier.runner claude
aroom config aworin agents.verifier.model  sonnet
aroom config aworin agents.builder.model   opus
```

Or use the **⚙** button on a project card: pick a runner and type/select a model
for each role, then save. It applies to the next run; a session already running
keeps the model it started with. To apply new models to a loop, stop it and start
it again.

Per-run overrides without changing the project:

```bash
aroom run aworin M1.9 --builder-model sonnet --verifier-model sonnet
aroom run aworin --loop --builder-runner opencode --builder-model google/gemini-3.5-flash
aroom verify aworin M1.9 --runner claude --model sonnet
```

The model string is passed straight to the CLI (`claude --model …` or
`opencode run --model …`), so aliases like `sonnet` and full IDs like
`google/gemini-3.5-flash` both work.

## Tracking a session Agent Room didn't start

```bash
aroom track /path/to/repo
```

This registers the repo **read-only** — no `.agent` files, no config, no commits.
The dashboard then shows any live Claude Code session in that repo:

- PID, session name and status (`busy` / `waiting`)
- model, branch, elapsed time, tokens processed
- the last assistant message or tool call
- an **open session** transcript of user/assistant/tool events

Sessions outside every registered repo appear in a “live sessions outside your
projects” strip with a **track** button. Data comes from `claude agents --json`
plus the session JSONL under `~/.claude/projects/`.

It is **read-only**: Agent Room cannot attach to, steer, or stop a session it did
not start. To hand the work over, stop that session, make sure the tree is
committed or stashed, then `aroom init` the repo and run tasks normally.


## Recovering a stopped or failed run

Never delete work by hand. The branch and worktree survive a timeout, a crash,
or a needed fix:

```bash
aroom verify aworin M1.9     # re-run checks + verifier on the existing branch
aroom clean aworin M1.9      # discard that worktree/branch
aroom run aworin M1.9 --fresh  # start over from the current base
```

In the dashboard, a failed/needs-human card with a preserved worktree shows
**re-verify** and **clean**. Once verification passes it becomes **merge**.
`aroom merge <project> <task> --force` exists for the case where the run record
is stale but the branch is known-good; use it deliberately.


The dashboard can add projects, start single runs, start a loop, stop runs, and
merge passed runs. It polls the same run files the CLI writes.

## Commands

| Command | What it does |
| --- | --- |
| `aroom init [path] [--name]` | Detect stack/tasks/commands, write `.agent/config.json`, `.agent/env.sh`, register |
| `aroom add <path>` | Register an existing repo |
| `aroom track <path>` | Register a repo read-only: no `.agent` writes; shows live Claude sessions and git state |
| `aroom remove <name>` | Unregister |
| `aroom projects` | List registered projects and task counts |
| `aroom status [--json]` | Table of every project: task, state, step, cost |
| `aroom next [project]` | Next open task with acceptance criteria |
| `aroom run [project] [task]` | One task: worktree → brief → build → checks → verify → fix ≤ N |
| `aroom run --loop` | Keep taking tasks; stops on failure or when a pass needs merging |
| `aroom run --loop --auto-merge` | Keep taking tasks and merge each PASS |
| `aroom run --loop --auto-merge --forever --detach` | Continuous daemon: keeps polling for new tasks, merges each PASS, survives the terminal |
| `aroom async <project> [--builders N] [--verifiers N]` | Async pipeline: builder pool, verifier pool, serialized merge queue |
| `aroom supervise [projects...]` | Keep loops/async pipelines alive, recover stalls, rotate models |
| `aroom preview <project> [--open/--stop/--restart/--logs]` | Start/stop the project's preview app and inspect its console |
| `aroom run --detach` | Run in the background (survives the terminal) |
| `aroom run --mock` | Deterministic fake runner for testing the pipeline |
| `aroom run --builder-model M` | Override the builder model for this run (same for `--verifier-model`, `--researcher-model`, and the matching `--*-runner` flags) |
| `aroom resume [project] [task]` | Continue a stopped, failed or conflicting run in its worktree |
| `aroom verify [project] [task]` | Re-run checks + verifier on an existing branch (after a timeout/failure) |
| `aroom clean [project] [task]` | Remove one worktree/branch, or all finished ones |
| `aroom models` | List models available to Claude Code and OpenCode |
| `aroom merge [project] [task] [--force]` | Squash-merge a passed run and tick the task |
| `aroom adopt [project] [task]` | Reconcile a hand-resolved squash merge as merged |
| `aroom blocked / unblock` | List tasks the supervisor skipped, or allow one to run again |
| `aroom requeue <project> [task...]` | Return needs-human/failed runs with worktrees to the builder queue |
| `aroom config <project> <key> [value]` | Read or write any config key, e.g. `agents.verifier.model` |
| `aroom research <project> <question>` | Research note into `docs/research/` |
| `aroom ui [--port N] [--host H]` | Start the dashboard |
| `aroom doctor` | Check git, runners, registry, configs |

If `project` is omitted, the current directory is used when it is registered.

## How a run works

```
next task from docs/PLAN.md or docs/TASKS.md
        │
        ├─ git worktree  ../_wt/<project>/<task>   branch agent/<task>
        ├─ brief.md       task + acceptance + commands + rules
        ├─ research       when the task names research, a vendor, or an LLM
        ├─ builder        reads AGENTS.md + skills + research, implements, commits
        ├─ checks         lint / typecheck / test / e2e (env.sh sourced)
        ├─ verifier       fresh session, runs checks itself, writes verify.md
        ├─ fix loop       max 2 rounds, only the findings go back
        └─ passed         merge on request, or automatically in a loop
```

If a task mentions research, a vendor, or an LLM, the researcher runs **before**
the builder inside the same worktree, writes
`docs/research/<task>-<slug>.md` with sources and a recommendation, commits it,
and the builder is told to read it. The verifier checks the code against the note.
Skill tags such as `(ai)` or `(job, ai)` do not trigger research.
Set `research.auto` to `false` to disable, or `research.required` to `true` to make
a missing note fail the run.

### Pushing

Set `push.enabled` to `true` (with `push.remote`, default `origin`). After every
successful squash merge and task tick, Agent Room pushes the base branch. It uses
`--no-verify` by default because the verifier already ran the project checks; set
`push.no_verify` to `false` to let pre-push hooks run. Pushes are never forced: if the
remote has commits that are not local, the push is recorded as failed in
`.agent/push.json` and the dashboard, and the merge queue keeps going. The scheduler
also retries the push every couple of minutes, so a temporary network/auth failure
catches up on the next successful push.

Terminal states: `passed`, `merged`, `needs-human`, `failed`, `stopped`.
If a builder or verifier session dies, the run is marked `failed`; rerun the task.

### Async pipeline

Set `limits.async` to `true`, then size the pools with `limits.builders` and
`limits.verifiers`. As soon as a build commits and its checks pass, the task is
marked `built` and handed to a verifier worker. Builders immediately start the next
task, so verification overlaps building instead of blocking it.

```
builders:  T1 build ─▶ T3 build ─────────▶ T5 build
           T2 build ─▶ T4 build
verifiers:            T1 verify ─▶ pass
                      T2 verify ─▶ fail ─▶ fix
merge queue:                       T1 merge ─▶ T2 merge ─▶ …
```

A verifier FAIL puts the task back in the builder queue as `fixing`, with the findings
in `issues`; the builder fixes it in the same worktree, then it is verified again.
Merges are serialized and tick the task file. Merge conflicts are marked
`needs-human` and blocked, like a normal run. `aroom async` runs the same scheduler
in the foreground; `aroom supervise` starts it automatically when `limits.async` is on.

Verifier workers are read-mostly. They run only the tests they touch, while builders
own the full lint/typecheck/test/e2e suite. Keep `limits.builders` at 1 for projects
whose checks use fixed ports or one shared database; raise it when tasks are
independent and checks are safe to overlap.

The scheduler skips any task already locked by a manual `aroom run`, so manual runs
and the pools do not fight over the same run record. After a reboot, runs left in an
active state are recovered: builds go back to `fixing`, verifications back to
`built`, and merges back to `passed`.

Before a PASS is accepted, the verifier merges the current base branch into the
worktree, runs `commands.pre_merge` (default: the project's typecheck command) on the
merged tree, then aborts the merge. A conflict or failed check sends the task back to
the builder with the reason, so a stale branch cannot break the base when it merges.

On quota/rate-limit failures the scheduler rotates builder and verifier models through
`opencode-go/deepseek-v4.1-flash` → `claude/sonnet` → `google/gemini-3.5-flash`. When
all are exhausted it waits 15 minutes and retries the primary, without blocking the
rest of the queue.

## Per-project config

`aroom init` writes `.agent/config.json`. Edit it per project:

```json
{
  "project": "aworin",
  "base_branch": "master",
  "tasks": {
    "adapter": "markdown",
    "file": "docs/PLAN.md",
    "id_regex": "M\\d+\\.\\d+(?:\\.\\d+)?"
  },
  "commands": {
    "setup": ["pnpm install"],
    "checks": ["pnpm lint", "pnpm typecheck", "pnpm test"],
    "e2e": "pnpm e2e",
    "e2e_on": ["apps/web"],
    "pre_merge": ["pnpm typecheck"]
  },
  "isolation": {
    "env_script": ".agent/env.sh",
    "copy_env": ["apps/api/.env", "packages/db/.env"]
  },
  "agents": {
    "builder":  { "runner": "claude",   "model": "", "timeout_min": 60 },
    "verifier": { "runner": "opencode", "model": "", "timeout_min": 40 },
    "researcher": { "runner": "claude", "model": "", "timeout_min": 40 }
  },
  "research": {
    "auto": true,
    "required": false,
    "triggers": ["\\bresearch\\b", "\\bvendor\\b", "\\bllm\\b"],
    "dir": "docs/research"
  },
  "limits": {
    "fix_rounds": 2,
    "auto_merge": false,
    "max_tasks": 10,
    "async": true,
    "builders": 2,
    "verifiers": 2
  },
  "push": { "enabled": true, "remote": "origin", "no_verify": true }
}
```

Task adapters:

- `markdown` — any checklist file with `- [ ] ID ...` lines; `- Accept:` lines become the verifier's checklist.
- `files` — one task per Markdown file in a folder.
- `github` — open issues labelled `agent` or `agent-room` (via `gh`).

Using a different verifier model family is deliberate: the reviewer should not
share the builder's blind spots.

## Isolation

Every task gets its own git worktree and branch. `.agent/env.sh` is sourced
before setup, checks, and agent sessions, so a project can give each run its own
database, Redis index, and ports using `$AR_RUN_ID`:

```bash
export DATABASE_URL="postgres://postgres:postgres@localhost:5432/app_$AR_RUN_ID"
export REDIS_DB=3
export WEB_PORT=3100
```

Runs use per-task locks (`.agent/locks/<task>.lock`); the async scheduler adds a
builder pool, a verifier pool and one serialized merge queue. A loop or scheduler
holds `.agent/loop.json`, so `aroom stop` can stop every lane. Runs in different
projects always proceed in parallel. Tasks that touch the same schema, lockfile or
generated file should keep `limits.builders` at 1.

On first start after a reboot, stale active runs are requeued automatically; see
[docs/operations.md](docs/operations.md).

## Files

```
~/.config/agent-room/registry.json     global registry: project name → path
~/.config/agent-room/config.json       dashboard host/port + defaults
~/.local/share/agent-room/worktrees/   worktrees, outside every repo
<repo>/.agent/config.json              committed per-project config
<repo>/.agent/env.sh                   committed isolation hook
<repo>/.agent/runs/<task>/             gitignored: run.json, brief.md,
                                       events.ndjson, verify.md, diff.patch, logs
<repo>/.agent/locks/                   per-task run locks
<repo>/.agent/scheduler.json           async lanes and heartbeat
<repo>/.agent/blocked.json             blocked task reasons
<repo>/.agent/push.json                last push result
```

Full reference: [docs/configuration.md](docs/configuration.md).


## Security

- The builder runs with the agent's unattended permissions inside a disposable
  worktree. Treat the machine as trusted; do not run untrusted repos.
- The dashboard binds `127.0.0.1` by default. `--host 0.0.0.0` exposes the ability
  to start runs and merge code to your network. Use Tailscale, not a public port.
- `auto_merge` is off by default. Enable it per project, or use
  `aroom run --loop --auto-merge` deliberately.
- Pushing is opt-in per project (`push.enabled`). When enabled, the base branch is
  pushed after each merge and retried by the scheduler. Pushes are never forced; a
  diverged remote is reported, not overwritten.
- Agent sessions run with the CLI's unattended permissions inside a disposable
  worktree. Treat the machine and the managed repos as trusted.

## Run it as a service

**Linux** — ready-to-copy systemd user units live in
[examples/systemd](examples/systemd). They enable lingering, restart on failure,
and keep loops alive across logout/reboot:

```bash
mkdir -p ~/.config/systemd/user
cp examples/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-room-supervisor.service agent-room-ui.service
loginctl enable-linger "$USER"
```

**macOS** — there is no systemd. Use the launchd agents in
[examples/launchd](examples/launchd):

```bash
mkdir -p ~/Library/LaunchAgents ~/.local/state/agent-room
for f in examples/launchd/*.plist; do
    sed "s#__HOME__#$HOME#g" "$f" > "$HOME/Library/LaunchAgents/$(basename "$f")"
done
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agentroom.ui.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agentroom.supervisor.plist
```

Then open <http://127.0.0.1:4400>. See
[docs/operations.md](docs/operations.md) for logs and recovery.
