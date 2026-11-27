# Changelog

## v1.3.1 — 2026-11-27

Found by running the installer and a full pipeline on native Windows.

- A command that is not installed (for example `claude` on a machine that only
  has OpenCode) now returns exit code 127 instead of raising. Before, a missing
  `claude` made `/api/state` fail, so the dashboard showed no projects.
- Command output is decoded as UTF-8 with replacement, so an unexpected byte
  from a tool cannot crash a request.


## v1.3.0 — 2026-11-27

### Native Windows

- `install.ps1` installs from PowerShell (`irm …/install.ps1 | iex`). It checks
  for Git for Windows and Python 3.10+ (skipping the Microsoft Store stub),
  clones or updates `%LOCALAPPDATA%\aroom`, writes `aroom.cmd` and `ar.cmd`,
  and adds them to the user PATH. `-Service` registers Task Scheduler tasks for
  the dashboard and the supervisor (start at logon, restart on failure, no
  console windows, logs in `~\.local\state\agent-room`). Running `install.sh`
  from Git Bash hands over to it.
- New `agentroom/osutil.py` holds the platform differences. Project commands
  and agent CLIs run through Git Bash (never the WSL `bash.exe`). Background
  processes get their own process group without a console. Process trees stop
  with `taskkill /T`, and liveness uses the Windows API: `os.kill(pid, 0)`
  would send Ctrl+C on Windows. `.cmd` shims (`claude`, `gh`) resolve through
  PATHEXT, and UTF-8 is forced.
- The agent runner reads output on a thread instead of `select()`, which only
  works on sockets on Windows.
- State files retry their atomic replace briefly on Windows while another
  process has them open.
- `aroom doctor` reports the bash it will use. The launcher accepts
  `--log=FILE` for services without a terminal.


## v1.2.1 — 2026-11-27

- `install.sh --service` now works on macOS: it writes launchd agents for the
  dashboard and the supervisor (start at login, restart on crash, your current
  `PATH`, logs in `~/.local/state/agent-room/`) and loads them. On a Mac the
  dashboard stays open on 127.0.0.1; `--listen` with any other address creates
  the access token.
- `install.sh --help` prints the full option list.


## v1.2.0 — 2026-11-27

### New dashboard

- Rewritten as a React app (`web/`: React 19, TypeScript, Vite, Tailwind v4,
  TanStack Router/Query, Radix). The build is committed to `agentroom/assets/app/`,
  so `curl | bash` installs still need no Node.
- Pages: **Overview** (needs-you first, then the timing tower), **Needs you**
  (filterable inbox; problems with one cause are grouped, with "do it for all"
  actions), **Activity** (cross-project timeline), **Projects** and a page per
  project (overview, tasks, git, preview console, chat). The run detail sheet
  and every fix panel deep-link (`?run=project/task`).
- Timing tower: every live, waiting, queued and ready task with a five-sector
  pipeline bar. State reads by line form as well as colour.
- Light and dark themes (system by default), phone layout with a bottom tab bar,
  unread count in the tab title, optional browser notifications.

### Server

- `/api/state` is served from a snapshot rebuilt in the background, so requests
  return immediately even when building state takes seconds on a busy machine.
  Git existence probes are batched per repo; live session detection is cached 15s.
- `GET /api/activity`: notable pipeline events across projects (cached per file).
- Diagnosis: billing/subscription failures get their own explanation; "builder
  produced no commits" is explained; queued tasks are only flagged when no loop
  is running.
- Fixed the git branch list (`for-each-ref` separator).
- Chat and run documents render markdown (tables, code, lists; raw HTML is never rendered). A page error no longer blanks the app.


## v1.1.0 — 2026-11-26

Install with one command; use the dashboard from your phone.

### Install

- `install.sh` works piped from curl: with no checkout next to it, it clones
  or updates the repo in `~/.local/share/aroom` and installs from there. It
  reaches the private repo over public HTTPS, `gh`, an SSH key, or
  `GITHUB_TOKEN`, in that order. The token is never written to `.git/config`.
- `--service` installs and starts systemd user units for the dashboard and the
  supervisor, carries the current `PATH` into them, enables lingering, and
  creates an access token.
- `--listen ADDR`, `--ref REF`, plus the `AROOM_HOME`, `AROOM_REPO`, `AROOM_REF`
  and `AROOM_GIT_URL` environment variables.

### Fixing stuck work from the dashboard

- **Needs you** inbox at the top of the dashboard lists everything waiting on a
  person, across all projects: merge conflicts, verifier rejections, failing
  checks, crashes, quota limits, blocked tasks, stalled runs, an uncommitted
  main checkout, and failed pushes. Each item states what happened, why, and
  what to do, plus the actions that fit that case. It no longer says only
  "needs a human".
- **Fix panel** shows everything recorded for the problem: the full block
  reason (no longer cut at 500 characters), verifier findings and `verify.md`,
  failing check logs, the agent's own notes or question, conflicted files,
  builder/verifier log errors, recent events, and run facts. Every section can
  be copied.
- **Conflict resolver**: merges the base into the task's worktree (the main
  checkout is never touched), then for each file you keep the task's version,
  keep the base's version, or edit the combined file. It refuses to finish while
  conflict markers remain. **Finish & merge** lands the task;
  **finish & re-verify** checks it first; **abort** undoes the merge.
- One-tap fixes: answer the agent's question, send the task back with guidance
  (conflict and failing-check context is added for you), resume, re-verify,
  retry merge, unblock, start over, discard work, stash or commit the main
  checkout, and retry the push.
- Cards show their open problems with a **fix** button. Blocked tasks in the
  task list show their full reason and a **fix** button too.
- New endpoints: `GET /api/problem`, `POST /api/fix`, `GET|POST /api/conflict`,
  `GET /api/conflict/file`.

### Remote access

- Dashboard access token, stored in `~/.config/agent-room/ui-token` (0600) or
  `AROOM_TOKEN`. When set, the dashboard needs a sign-in (session cookie lasting
  90 days), a `Bearer` header, or a one-time `?token=` link.
  Cross-origin POSTs are refused.
- `aroom ui --host 0.0.0.0` creates a token if none exists. It never serves an
  open dashboard off loopback.
- `aroom token [--new | --create | --link [--url URL] | --off]`.
- Phone layout: single column, larger tap targets, bottom-sheet modals,
  safe-area insets, no iOS zoom on inputs, home-screen app meta tags, and a
  sign-out button.
- Preview links that point at `localhost` are rewritten to the dashboard's host
  when the dashboard is opened from another device.
- New guide: `docs/remote.md` (VPS, Tailscale, Caddy).

## v1.0.2 — 2026-11-26

Quota failures no longer block the queue.

- Model-unavailable, rate-limit and weekly/5-hour quota errors are treated as
  transient in `auto_requeue`: they rotate models or wait 15 minutes instead of
  spending the task's `requeue_attempts` and blocking it.
- A verifier that exits nonzero without writing `verify.md` is now an error
  (transient handling applies), not a FAIL verdict.
- Rotation clears `retry_after`, so a task starts immediately on the next model.
- Dropped `google/gemini-3.5-flash` from the rotation (provider has no route);
  fallbacks are now DeepSeek V4.1 Flash → Claude Sonnet → wait.

## v1.0.1 — 2026-11-26

Install and recovery fixes.

### Install

- `install.sh` no longer assumes the checkout is at `~/apps/agent-room`; it
  installs from wherever the repo was cloned.
- The launcher is a small wrapper around a real Python 3.10+ interpreter, so it
  works on macOS where the system `python3` is 3.9 (Homebrew `python3.12` is
  picked up automatically).
- The installer adds `~/.local/bin` to `PATH` as well as the `ar` alias, creates
  `~/.zshrc` when zsh has no rc file yet, and verifies the launcher starts.
- README and operations docs now start with an explicit clone step for the
  private repo and cover upgrades and moving the checkout.
- Added launchd agents for macOS (`examples/launchd`) with start/stop/status
  commands; systemd docs are marked Linux-only.

### Recovery

- Bounded automatic requeue (`limits.requeue_attempts`, default 1 informed retry)
  and an `aroom requeue` command for manual recovery.
- Project-level merge lock prevents a manual merge and the scheduler from racing
  and leaving code merged but the task unticked.
- After a merge, aroom verifies the task actually reads `[x]` and records
  `tick_error` otherwise.
- Zombie PIDs are treated as dead, so loop locks recover after a reboot.
- Restart recovery no longer overwrites queued targeted fixes; requeued tasks get
  priority over the older backlog.
- Verifiers never run the project-wide e2e suite; only task-specific specs. The
  verifier timeout default is 60 minutes.
- `kill_cwd_processes` falls back to `lsof` on macOS, so worktree cleanup also
  stops leaked dev servers there.

## v1.0.0 — 2026-11-24

First stable release.

### Orchestration

- One `aroom` CLI and one dashboard for every registered git repo.
- Per-task git worktrees and branches, with resumable worktrees.
- Markdown checklist, folder-of-files, and GitHub issue task adapters.
- Builder → checks → verifier → fix loop, with acceptance criteria in the brief.
- Separate verifier sessions and optional researcher notes for vendor/LLM work.
- Async scheduler: configurable builder pool and verifier pool, with a serialized
  merge queue and automatic fix-round requeueing.
- Pre-merge integration gate: temporarily merges the current base, runs
  `commands.pre_merge`, and rejects stale branches before they land.
- Per-task locks, manual-run coexistence, merge marker, and push lock.
- Conflict handling: base reset on squash conflict, one automatic builder fix, then
  `needs-human`.
- Stall detection based on actual file activity, model rotation on quota errors, and
  a 15-minute all-models wait.
- Reboot recovery for active builds, verifications and merges.

### Dashboard and operations

- Wide project cards with runs, async lanes, checks, preview links and chat.
- Git detail per card: branch, origin link, upstream ahead/behind, HEAD, push state.
- Git details modal: worktrees, branches, tracking, remotes.
- Task board grouped by status, resume/merge/re-verify/clean actions.
- Preview lifecycle with service links and an OTP/console log view.
- GitHub push after merge (opt-in, never forced, retried by the scheduler).
- systemd user units for the UI and supervisor, with lingering and reboot recovery.

### Quality

- Deterministic `mock` runner for free end-to-end pipeline tests.
- Event streams, run artifacts, diffs and check logs under `.agent/runs/`.
- Documentation for configuration, architecture, operations and troubleshooting.

### Known limitations

- A single project-wide merge queue means merges are serialized.
- Concurrent builders can conflict when tasks edit the same files; keep
  `limits.builders` at 1 for projects with shared ports, databases or migrations.
- The dashboard is local-only by default.
- GitHub task sync is one-way (reads open issues; does not comment back).
