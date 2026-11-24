# Configuration

Agent Room has one global registry and one configuration file per project.

| File | Purpose |
| --- | --- |
| `~/.config/agent-room/registry.json` | Project name → repository path |
| `~/.config/agent-room/config.json` | Dashboard host/port and defaults |
| `<repo>/.agent/config.json` | Tasks, checks, agents, limits, push, preview |
| `<repo>/.agent/env.sh` | Optional per-run environment hook (sourced before setup/checks/agents) |

`aroom init` detects sensible defaults. Read or change any key without editing JSON:

```bash
aroom config aworin limits.builders
aroom config aworin limits.builders 2
aroom config aworin push.enabled true
```

Changing `agents.*` or `push.*` is committed automatically by the next run/merge; commit `.agent/config.json` yourself if you want it in history immediately.

## Full example

```json
{
  "project": "aworin",
  "base_branch": "master",
  "worktree_root": "~/.local/share/agent-room/worktrees/aworin",
  "commit_type": "feat",
  "commit_area": "web",

  "tasks": {
    "adapter": "markdown",
    "file": "docs/PLAN.md",
    "id_regex": "M\\d+\\.\\d+(?:\\.\\d+)?",
    "done_marker": "[x]"
  },

  "commands": {
    "setup": ["pnpm install"],
    "checks": ["pnpm lint", "pnpm typecheck", "pnpm test"],
    "e2e": "pnpm e2e",
    "e2e_on": ["apps/web"],
    "pre_merge": ["pnpm typecheck"],
    "setup_timeout_min": 25,
    "check_timeout_min": 25
  },

  "isolation": {
    "env_script": ".agent/env.sh",
    "copy_env": ["apps/api/.env", "packages/db/.env"],
    "parallel_safe": true
  },

  "agents": {
    "builder":    { "runner": "opencode", "model": "opencode-go/deepseek-v4.1-flash", "timeout_min": 60 },
    "verifier":   { "runner": "opencode", "model": "opencode-go/deepseek-v4.1-flash", "timeout_min": 40 },
    "researcher": { "runner": "opencode", "model": "opencode-go/deepseek-v4.1-flash", "timeout_min": 40 }
  },

  "limits": {
    "fix_rounds": 2,
    "run_budget_usd": 20,
    "auto_merge": true,
    "max_tasks": 10,
    "async": true,
    "builders": 2,
    "verifiers": 2
  },

  "research": {
    "auto": true,
    "required": false,
    "triggers": ["\\bresearch\\b", "\\bvendor\\b", "\\bllm\\b"],
    "dir": "docs/research",
    "timeout_min": 30
  },

  "paths": { "allow": [], "deny": [] },
  "tick": { "suffix": "" },

  "push": {
    "enabled": true,
    "remote": "origin",
    "branch": "",
    "no_verify": true
  },

  "preview": {
    "command": "pnpm dev",
    "url": "http://localhost:4310",
    "port": 4310,
    "cwd": ".",
    "env_script": true,
    "services": [
      { "name": "app", "url": "http://localhost:4310", "port": 4310 }
    ]
  }
}
```

## Keys

### Top level

| Key | Meaning |
| --- | --- |
| `project` | Stable name used by the CLI and dashboard |
| `base_branch` | Branch that receives squash merges and pushes |
| `worktree_root` | Where task worktrees live; `~` is expanded |
| `commit_type` | Conventional-commit type for merges (`feat`, `fix`, `chore`, …) |
| `commit_area` | Optional commit scope, rendered as `type(area): …` |

### `tasks`

| Key | Meaning |
| --- | --- |
| `adapter` | `markdown`, `files`, or `github` |
| `file` | Checklist file for `markdown`, or folder for `files` |
| `id_regex` | Pattern that identifies a task id |
| `done_marker` | Checklist marker for done (default `[x]`) |

Markdown tasks are `- [ ] ID Title — description` lines. Lines beginning with
`Accept:` or `Acceptance:` become the acceptance checklist shown to the builder
and verifier.

### `commands`

| Key | Meaning |
| --- | --- |
| `setup` | Commands run once in each new worktree, before research/builder |
| `checks` | Full checks run by the builder lane (lint, typecheck, tests) |
| `e2e` | Optional end-to-end command |
| `e2e_on` | Path prefixes that trigger `e2e` when changed |
| `pre_merge` | Commands run on the temporarily merged tree before a PASS. Defaults to the typecheck command |
| `setup_timeout_min` / `check_timeout_min` | Per-command timeouts |

Checks run in the worktree with `.agent/env.sh` sourced. A failed check sends the
task back to `fixing` with the captured logs.

### `isolation`

| Key | Meaning |
| --- | --- |
| `env_script` | File sourced before setup/checks/agents |
| `copy_env` | Env files copied into each worktree |
| `parallel_safe` | Informational flag for running concurrent tasks |

Use `$AR_RUN_ID`, `$AR_TASK`, `$AR_WORKTREE` inside `env.sh` to give each run its own
database, Redis index, and ports. Never share fixed dev ports across concurrent
worktrees.

### `agents`

One object per role: `builder`, `verifier`, `researcher`.

| Key | Meaning |
| --- | --- |
| `runner` | `claude`, `opencode`, or `mock` |
| `model` | Passed to the CLI; empty means the CLI default |
| `timeout_min` | Hard timeout for that role |

Different model families for builder and verifier are recommended. Per-run
overrides: `aroom run … --builder-model`, `--verifier-model`, `--researcher-model`
(and matching `--*-runner` flags).

### `limits`

| Key | Meaning |
| --- | --- |
| `fix_rounds` | Maximum builder/verifier rounds per task |
| `run_budget_usd` | Abort a run above this reported cost |
| `auto_merge` | Merge a PASS without a human |
| `max_tasks` | Tasks per finite loop |
| `async` | Use the async builder/verifier scheduler |
| `builders` | Concurrent builder lanes in async mode |
| `verifiers` | Concurrent verifier workers in async mode |

For projects whose e2e uses fixed ports or one shared database, keep
`builders: 1`. Raising it trades merge conflicts and resource contention for
throughput.

### `research`

| Key | Meaning |
| --- | --- |
| `auto` | Run the researcher automatically when a trigger matches |
| `required` | Fail the task if no research note exists |
| `triggers` | Regexes matched against the title/description with skill tags removed |
| `dir` | Where notes are written, relative to the worktree |
| `timeout_min` | Researcher timeout |

Notes are named `docs/research/<task>-<slug>.md` and committed on the task branch.
Skill tags such as `(ai)` or `(job, ai)` do not trigger research.

### `push`

| Key | Meaning |
| --- | --- |
| `enabled` | Push the base branch after merges |
| `remote` | Remote name (default `origin`) |
| `branch` | Branch to push; empty means `base_branch` |
| `no_verify` | Skip pre-push hooks (default `true`; checks already ran) |

Pushes are never forced. State is recorded in `.agent/push.json` and surfaced on
the dashboard.

### `preview`

| Key | Meaning |
| --- | --- |
| `command` | Shell command that starts the app |
| `url` / `port` | Primary clickable URL and port |
| `cwd` | Working directory, relative to the repo |
| `env_script` | Source `.agent/env.sh` before starting |
| `services` | Optional `{name, url, port}` links (app, API, queues) |

### `paths` and `tick`

| Key | Meaning |
| --- | --- |
| `paths.allow` / `paths.deny` | Extra guidance for the builder's allowed/denied files |
| `tick.suffix` | Text appended to a ticked task (supports `{date}`) |

## Environment hook

`.agent/env.sh` is copied/used inside every worktree:

```bash
export DATABASE_URL="postgres://postgres:postgres@localhost:5432/app_${AR_RUN_ID}"
export REDIS_DB=3
export WEB_PORT=4310
```

Keep per-project preview ports unique. Do not bind a shared 3000/3100 port across
concurrent worktrees.
