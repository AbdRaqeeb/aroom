# Operations

## Install

Agent Room runs from a checkout; nothing is published to PyPI or Homebrew. The
clone can live anywhere — these docs use `~/.local/share/aroom`.

```bash
# private repo: SSH key or `gh auth login` required
gh repo clone AbdRaqeeb/aroom ~/.local/share/aroom
# or: git clone git@github.com:AbdRaqeeb/aroom.git ~/.local/share/aroom

~/.local/share/aroom/install.sh
exec zsh                    # bash: exec bash --login
aroom --version
aroom doctor
```

`install.sh` writes `~/.local/bin/aroom` (a wrapper around a Python 3.10+
interpreter), adds `~/.local/bin` to `PATH`, and adds `alias ar="aroom"` once
(the GNU archiver `/usr/bin/ar` is never shadowed). It is safe to re-run after
moving the clone.

On macOS the system `python3` may be 3.9; install a newer one with
`brew install python@3.12`. The installer prefers `python3.13` … `python3.10`
over `python3`.

## systemd user services (Linux)

Copy the example units. They call `~/.local/bin/aroom`, so they do not depend on
where the checkout lives:

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

## launchd agents (macOS)

macOS has no systemd. Copy the templates in `examples/launchd`, replacing
`__HOME__` with your home directory:

```bash
mkdir -p ~/Library/LaunchAgents ~/.local/state/agent-room
for f in examples/launchd/*.plist; do
    sed "s#__HOME__#$HOME#g" "$f" > "$HOME/Library/LaunchAgents/$(basename "$f")"
done
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agentroom.ui.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.agentroom.supervisor.plist
```

Both agents use `RunAtLoad` and `KeepAlive`, so they start at login and restart on
failure. Logs go to `~/.local/state/agent-room/`.

```bash
launchctl print gui/$(id -u)/com.agentroom.supervisor   # status
launchctl kickstart -k gui/$(id -u)/com.agentroom.supervisor
launchctl bootout gui/$(id -u)/com.agentroom.supervisor
```

Without launchd, the same two processes can run in a terminal:

```bash
aroom ui --no-open &
aroom supervise --interval 60
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
journalctl --user -u agent-room-ui -n 100 --no-pager          # Linux
journalctl --user -u agent-room-supervisor -n 100 --no-pager  # Linux
tail -f ~/.local/state/agent-room/supervisor.log              # both
tail -f ~/.local/state/agent-room/ui.log                      # both
```

Per-task logs live in `<repo>/.agent/runs/<task>/` (`builder.log`, `verifier.log`,
`daemon.log`, `checks/`). The dashboard shows the same events.

## Reboot recovery

Services start automatically when enabled (systemd lingering, or launchd
`RunAtLoad`).

The async scheduler recovers runs left in an active state:

| Interrupted state | Recovery |
| --- | --- |
| `building`, `checking`, `researching`, `fixing` | Requeued as `fixing`; builder resumes the existing worktree |
| `verifying` | Requeued as `built`; a verifier picks it up |
| `merging` | Base is reset if a merge marker exists; run goes back to `passed` |
| Active run with no worktree | Marked `failed` and blocked for a human |

Manual runs (`aroom run`) are not adopted; start them again if they were interrupted.

## Rolling scheduler restart (no work lost)

Normally use `systemctl --user restart agent-room-supervisor.service` (Linux) or
`launchctl kickstart -k gui/$(id -u)/com.agentroom.supervisor` (macOS); project
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
git -C ~/.local/share/aroom pull --ff-only
~/.local/share/aroom/install.sh
```

Then restart the services:

```bash
systemctl --user restart agent-room-ui.service agent-room-supervisor.service  # Linux
launchctl kickstart -k gui/$(id -u)/com.agentroom.ui                         # macOS
launchctl kickstart -k gui/$(id -u)/com.agentroom.supervisor
```

Active async schedulers keep their loaded code until restarted; use the rolling
restart above or wait for a natural restart.

## Disk and worktrees

```bash
aroom clean aworin                 # remove finished/merged worktrees
aroom clean aworin M5.2.1          # remove one task's worktree/branch
git -C /path/to/aworin worktree list
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
