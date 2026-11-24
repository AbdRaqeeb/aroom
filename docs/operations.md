# Operations

## Install

```bash
bash ~/apps/agent-room/install.sh
source ~/.bashrc
aroom --version
aroom doctor
```

`install.sh` links `~/.local/bin/aroom` and adds a shell alias `ar` (the GNU
archiver `/usr/bin/ar` is never shadowed).

## systemd user services

Copy the example units and adapt the paths if the repo is not at
`~/apps/agent-room`:

```bash
mkdir -p ~/.config/systemd/user
cp examples/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-room-supervisor.service agent-room-ui.service
loginctl enable-linger "$USER"
```

| Unit | Role |
| --- | --- |
| `agent-room-ui.service` | Dashboard at `http://127.0.0.1:4400` |
| `agent-room-supervisor.service` | Starts/recovers project loops and async pipelines |

Both use `Restart=always`, `RestartSec=5`, and `KillMode=process`. `KillMode` is
important: restarting the supervisor must not kill its child loops. `loginctl
enable-linger` is required for the units to start after a reboot without an
interactive login.

### Start, stop, status

```bash
systemctl --user status agent-room-ui.service agent-room-supervisor.service
systemctl --user restart agent-room-ui.service
systemctl --user restart agent-room-supervisor.service
systemctl --user stop agent-room-ui.service agent-room-supervisor.service
```

Restarting the **supervisor** does not stop project loops. To stop all work for one
project:

```bash
aroom stop aworin
```

`aroom stop` waits for an in-flight merge, then stops the scheduler and every
builder/verifier child. It is safe to run while the supervisor is active; the
supervisor will start a new scheduler on its next tick.

### Logs

```bash
journalctl --user -u agent-room-ui -n 100 --no-pager
journalctl --user -u agent-room-supervisor -n 100 --no-pager
tail -f ~/.local/state/agent-room/supervisor.log
tail -f ~/.local/state/agent-room/ui.log
```

Per-task logs live in `<repo>/.agent/runs/<task>/` (`builder.log`, `verifier.log`,
`daemon.log`, `checks/`). The dashboard shows the same events.

## Reboot recovery

Services start automatically when enabled with lingering.

The async scheduler recovers runs left in an active state:

| Interrupted state | Recovery |
| --- | --- |
| `building`, `checking`, `researching`, `fixing` | Requeued as `fixing`; builder resumes the existing worktree |
| `verifying` | Requeued as `built`; a verifier picks it up |
| `merging` | Base is reset if a merge marker exists; run goes back to `passed` |
| Active run with no worktree | Marked `failed` and blocked for a human |

Manual runs (`aroom run`) are not adopted; start them again if they were interrupted.

## Rolling scheduler restart (no work lost)

Normally use `systemctl --user restart agent-room-supervisor.service`; project
schedulers keep running. To load new scheduler code without killing builders or
verifiers:

1. Ensure no merge is in progress (`<repo>/.agent/merge.json` absent).
2. SIGKILL the `ar async <project>` scheduler process.
3. Start a new scheduler (`aroom async <project> --verifiers 2 --interval 10` or let
   the supervisor do it).

The new scheduler reads `.agent/scheduler.json` and adopts children whose PIDs are
still alive.

## Backups

Durable:

- the managed git repositories, including branches and remotes
- `.agent/config.json` and `.agent/env.sh` in each repo (commit them)
- `~/.config/agent-room/registry.json` and `config.json`

Disposable:

- `~/.local/share/agent-room/worktrees/`
- `<repo>/.agent/runs/`
- `~/.local/state/agent-room/` logs, PIDs and supervisor state

Back up the repositories with their remotes; that is the real work. Run artifacts
only help debugging a failed task.

## Upgrades

```bash
cd ~/apps/agent-room
git pull
./install.sh
systemctl --user restart agent-room-ui.service
systemctl --user restart agent-room-supervisor.service
```

Active async schedulers keep their loaded code until restarted; use the rolling
restart above or wait for a natural restart.

## Disk and worktrees

```bash
aroom clean aworin                 # remove finished/merged worktrees
aroom clean aworin M5.2.1          # remove one task's worktree/branch
git -C ~/apps/aworin worktree list
```

Never delete a worktree that still has uncommitted agent work unless you intend to
discard it.

## Security

- The dashboard binds `127.0.0.1`. Do not expose it publicly; use an SSH tunnel or
  Tailscale.
- Agent sessions run with unattended permissions inside disposable worktrees. Only
  manage trusted repositories.
- Keep `auto_merge` and `push.enabled` deliberate. Pushes are fast-forward only and
  never forced.
- The registry and configs may contain private repository paths. They stay outside
  the repos unless you choose to commit project config.
