# Troubleshooting

Start here:

```bash
aroom --version
aroom doctor
aroom status
systemctl --user status agent-room-ui.service agent-room-supervisor.service
```

## The UI does not load

1. Is the service active?

   ```bash
   systemctl --user restart agent-room-ui.service
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4400/
   ```

2. Run it in the foreground to see the error:

   ```bash
   aroom ui --no-open
   ```

3. Port already in use? Start elsewhere:

   ```bash
   aroom ui --port 4401
   ```

4. If it worked before and a hard refresh does not help, the inline dashboard asset
   changed; restart the UI service.

The UI is local-only by default. From another machine use:

```bash
ssh -L 4400:127.0.0.1:4400 you@host
```

## Services are inactive after reboot

```bash
loginctl enable-linger "$USER"
systemctl --user enable agent-room-ui.service agent-room-supervisor.service
systemctl --user start agent-room-ui.service agent-room-supervisor.service
```

## A project is not moving

```bash
aroom status
aroom next <project>
aroom blocked <project>
```

- `blocked.json` holds tasks the supervisor/scheduler will not retry. Inspect the
  reason, then `aroom unblock <project> <task>`.
- Existing non-merged runs are skipped by task selection. If a run is `needs-human`,
  resume/verify/re-verify or clean it.
- A stale `loop.json` or a dead scheduler is handled by the supervisor within a
  minute. Force it:

  ```bash
  aroom stop <project>
  systemctl --user restart agent-room-supervisor.service
  ```

## “a loop is already running”

A scheduler or loop holds `.agent/loop.json`. Check the PID:

```bash
cat <repo>/.agent/loop.json
ps -p <pid>
```

If it is dead, `aroom stop <project>` removes the stale file; otherwise stop it
first. Never delete a live scheduler's loop file.

## A task is stuck in “building” or “verifying”

The scheduler marks a child stalled after 20 minutes without writes and retries it
once. To intervene:

```bash
aroom stop <project>
aroom status
aroom resume <project> <task>      # keep the worktree and continue
aroom clean <project> <task>       # discard the worktree/branch
```

Check the run logs first:

```bash
tail -50 <repo>/.agent/runs/<task>/builder.log
tail -50 <repo>/.agent/runs/<task>/verifier.log
```

## Merge conflict

The scheduler requeues one conflict fix automatically (there is only one `main`).
After that it becomes `needs-human` and blocked.

```bash
# inspect the branch/worktree
aroom verify <project> <task>
# or resolve by hand in the worktree, commit, then:
aroom adopt <project> <task>
```

The base checkout is reset to its pre-merge commit on conflict, so it should not be
left with staged or conflicted files. If it is, confirm with `git status` and reset
only if you are sure those changes belong to the failed squash.

## Checks fail only in the verifier / integration gate

The verifier merges the current base into the worktree and runs
`commands.pre_merge`. A failure means the branch is stale relative to base.

- Let the builder fix it: the next build prompt contains the gate output.
- Or lower the gate cost with `commands.pre_merge` (default: typecheck).
- For genuine integration failures, rebase/merge base into the branch and rerun
  `aroom verify`.

## Push fails

Inspect `.agent/push.json` and the card’s git section.

- `remote origin is not configured`: `git remote add origin <url>`
- Authentication: test `git ls-remote origin`; SSH keys/agent must work without a
  prompt. Aroom sets `GIT_TERMINAL_PROMPT=0`.
- `origin/main has commits that are not in the local branch`: the remote diverged.
  Pull/rebase deliberately; aroom never force-pushes.
- Pre-push hooks are skipped by default (`push.no_verify: true`) because checks
  already ran. Set it to `false` if you want hooks.

Pushes retry every couple of minutes, so a temporary network failure catches up.

## Model or quota errors

Transient failures rotate through the configured fallbacks
(`deepseek-v4.1-flash` → `sonnet` → `gemini-3.5-flash`). When all are exhausted the
task waits 15 minutes and retries the primary. Check:

```bash
tail -50 ~/.local/state/agent-room/supervisor.log
```

If a task was blocked, fix the model in the dashboard’s **⚙ models** dialog or
`aroom config <project> agents.verifier.model …`, then unblock it.

## Worktrees and disk

```bash
git -C <repo> worktree list
du -sh ~/.local/share/agent-room/worktrees/<project>
aroom clean <project>
```

`aroom clean` refuses to remove a task that still holds a live lock. Stop the run
first. Removing a worktree with uncommitted work discards that work.

## Dashboard shows stale data

The dashboard polls `<repo>/.agent/runs/*/run.json`. If a card is stale:

1. Hard-refresh the page.
2. Check the run file directly.
3. Restart the UI service if the inline JavaScript changed.

## Reset the dashboard without touching projects

```bash
systemctl --user restart agent-room-ui.service
```

This never stops builders, verifiers, merges, or previews.
