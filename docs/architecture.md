# Architecture

Agent Room is a Python-stdlib orchestrator. It has no database and no long-running
agent runtime: every run is a git worktree plus JSON/JSONL files, and the dashboard
is a read-mostly HTTP view over those files.

## Components

| Module | Responsibility |
| --- | --- |
| `agentroom/cli.py` | Argument parsing and every user-facing command |
| `agentroom/config.py` | Global registry, per-project config, detection, ignore rules |
| `agentroom/tasks.py` | Markdown / files / GitHub task adapters, tick and blocked state |
| `agentroom/gitops.py` | Worktrees, branches, squash merges, push, git inventory |
| `agentroom/pipeline.py` | Sync run lifecycle, build/verify phases, checks, merge, push |
| `agentroom/async_loop.py` | Async scheduler: builder pool, verifier pool, merge queue, recovery |
| `agentroom/supervisor.py` | Keeps loops alive, detects stalls, rotates models, retries/blocks |
| `agentroom/runners.py` | Claude Code / OpenCode / mock subprocess adapters and event streaming |
| `agentroom/preview.py` | Preview app lifecycle, service links, OTP/console log highlighting |
| `agentroom/chat.py` | Per-project conversational agent session |
| `agentroom/sessions.py` | Read-only view of Claude Code sessions Agent Room did not start |
| `agentroom/ui.py` + `assets/` | HTTP server, state builder, dashboard |
| `agentroom/util.py` | Time, process, JSON, slug, activity and kill helpers |

## Run state machine

```
queued → briefing → researching? → building → checking
                                      ↑          │
                                      │       fixing
                                      │          │
                                      └──────────┘
                                   built (async only)
                                      │
                                   verifying
                                      │
                            pass ─────┴───── fail
                              │                │
                           passed           fixing / needs-human
                              │
                           merging → merged
```

Terminal or human states are `needs-human`, `failed`, and `stopped`. A sync run does
`verifying` inline; an async build stops at `built` and hands the run to a verifier
worker.

## Task selection

`tasks.load_tasks` parses the configured adapter. `next_task` picks the first open,
non-blocked task. Runs with an existing non-merged/non-stopped run record are skipped
so a task is not started twice. The async scheduler additionally skips tasks whose
per-task lock is held by a manual `aroom run`.

## Worktrees and branches

Every task gets:

- branch `agent/<task-id>` (slugged)
- worktree `<worktree_root>/<task-id>` (slugged)
- run directory `<repo>/.agent/runs/<task-id>/`

The worktree is created from the current base branch. The builder commits there;
checks, verifier, integration gate and merge all use that isolated tree. On a
successful merge the worktree and branch are removed.

## Build phase

1. Acquire the per-task lock.
2. Create/resume the worktree and copy env files.
3. Run `commands.setup`.
4. Optionally research, then write `brief.md`.
5. Run the builder with the brief, acceptance criteria, round issues and resume note.
6. Run the checks.
7. On failure: record issues and return to `fixing` (async) or retry inline (sync).
8. On success: write `diff.patch`; async stops at `built`, sync continues.

## Verify phase

The verifier is a fresh agent session that did not write the code. It reads the
brief, diff and surrounding code, runs targeted tests, and writes `verify.md` with a
PASS/FAIL verdict and evidence.

Before a PASS is accepted:

- the verifier's test commits are checked if it changed the tree;
- the current base branch is merged into the worktree temporarily;
- `commands.pre_merge` runs on that merged tree (typecheck by default);
- the temporary merge is aborted.

A conflict or failure is sent back to the builder with the exact reason. This
prevents a branch that was built against an older base from silently breaking
`main`/`master`.

A FAIL with rounds left becomes `fixing`; the next build prompt contains only the
verifier's findings. Exhausting `limits.fix_rounds` yields `needs-human` and blocks
the task.

## Async scheduler

`async_loop.run_async` owns lanes for one project:

- `builders`: up to `limits.builders` build/fix children, one worktree each.
- `verifiers`: up to `limits.verifiers` verify children.
- merge queue: passes are merged one at a time in the scheduler process.

The scheduler writes `.agent/scheduler.json` after every tick. Children are started
in their own session and write to the run's `daemon.log`. If the scheduler is
restarted, it adopts children whose PIDs are still alive instead of duplicating
them.

Every tick:

1. Reload config (pools can change without a restart).
2. Recover orphaned active runs left by a reboot or dead scheduler.
3. Reap dead/silent children and retry or block their tasks.
4. Merge one passed run.
5. Fill verifier slots from `built` runs.
6. Fill builder slots from `fixing` runs, then new tasks.
7. Persist lanes, then retry the push if enabled.

## Locks and ownership

| File | Meaning |
| --- | --- |
| `.agent/loop.json` | Single loop/scheduler owner |
| `.agent/locks/<task>.lock` | One process owns a task |
| `.agent/merge.json` | A merge is in progress; `aroom stop` waits for it |
| `.agent/push.lock` | One push at a time |

`run_task` claims the lock before writing `run.json`, so a losing child cannot
overwrite a manual run's state. `aroom stop` kills the scheduler, waits briefly for
an in-flight merge, then stops every lane.

## Merge and push

`merge_run` requires a clean base, squash-merges the branch, ticks the task, commits
the tick, and only then removes the worktree. On conflict it resets the base to its
pre-merge state (a squash merge has no `MERGE_HEAD`, so `merge --abort` is a no-op)
and, in async mode, requeues the task once for the builder to resolve. A second
conflict becomes `needs-human`.

When `push.enabled` is true, the base branch is pushed after the tick commit.
Pushes are fast-forward only and retried by the scheduler; divergence is reported,
never forced.

## Liveness and quota

A run is stalled when its process died or its run directory has had no writes for
20 minutes. The supervisor/async scheduler kills it and requeues or blocks it.
Transient model errors (quota, rate limit, connection) rotate models through the
configured fallbacks and eventually wait 15 minutes before retrying the primary.

## State on disk

```
~/.config/agent-room/registry.json      projects
~/.config/agent-room/config.json        dashboard defaults
~/.local/share/agent-room/worktrees/    task worktrees
~/.local/state/agent-room/              supervisor/UI logs and PIDs
<repo>/.agent/config.json               committed configuration
<repo>/.agent/env.sh                    optional committed hook
<repo>/.agent/runs/<task>/              gitignored run artifacts
<repo>/.agent/blocked.json              gitignored blocked-task reasons
<repo>/.agent/push.json                 gitignored push state
```

The repository's commits, branches and remotes are the durable output. Run
artifacts are disposable; see [operations.md](operations.md) for backup guidance.
