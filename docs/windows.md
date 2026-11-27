# Windows

Agent Room runs natively on Windows 10 and 11, as well as inside WSL2. It uses
Git Bash, which ships with Git for Windows, to run project commands (`pnpm lint`,
preview servers) and the agent CLIs, so every project's commands behave the
same as on Linux and macOS.

## Install

In PowerShell (no admin needed):

```powershell
winget install Git.Git Python.Python.3.12     # if you don't have them yet
irm https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.ps1 | iex
```

Open a **new** terminal, then:

```powershell
aroom doctor          # python, git, bash (Git Bash), claude / opencode
aroom init C:\code\my-app
aroom ui              # http://127.0.0.1:4400
```

What the installer does:

- clones (or updates) the repo into `%LOCALAPPDATA%\aroom` (`AROOM_HOME` changes this)
- finds Python 3.10+ with the `py` launcher or on PATH, skipping the Microsoft
  Store `python.exe` stub
- writes `aroom.cmd` and `ar.cmd` to `%LOCALAPPDATA%\Programs\aroom` and adds that
  folder to your user PATH
- checks that it can find Git Bash

Install a specific version with `-Ref v1.3.0`. To pass options when installing
from the web:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.ps1))) -Service -Ref main
```

From a clone, run `.\install.ps1`. If PowerShell blocks local scripts, run
`powershell -ExecutionPolicy Bypass -File .\install.ps1`. Running `install.sh`
from Git Bash hands over to `install.ps1`.

## Run in the background

`-Service` registers two Task Scheduler tasks for your user, **Agent Room
dashboard** and **Agent Room supervisor**. They run with `pythonw.exe`, so no
console windows open. They start when you log in, and a trigger that repeats
every minute brings them back if the process dies. A running copy is never
started twice. Logs go to `%USERPROFILE%\.local\state\agent-room\ui.log` and
`supervisor.log`.

Because of the every-minute trigger, `Stop-ScheduledTask` alone only stops a
task until the next minute. To pause a task, disable it as well:

```powershell
Get-ScheduledTask 'Agent Room*'                                    # status
Disable-ScheduledTask 'Agent Room dashboard'; Stop-ScheduledTask 'Agent Room dashboard'   # pause
Enable-ScheduledTask  'Agent Room dashboard'                       # resume (starts within a minute)
Unregister-ScheduledTask 'Agent Room*' -Confirm:$false             # remove both
Get-Content $env:USERPROFILE\.local\state\agent-room\ui.log -Wait  # follow the log
```

If you also run Agent Room inside WSL, WSL forwards its dashboard to Windows
`localhost:4400`. Give the Windows one another port before installing the
service, e.g. `"ui": {"port": 4401}` in
`%USERPROFILE%\.config\agent-room\registry.json`; otherwise the Windows dashboard
cannot bind the port.

Re-run the installer with `-Service` after upgrading, or after installing new
tools, so the tasks pick them up.

## Git Bash

Agent Room looks for `bash.exe` next to your `git` install
(`C:\Program Files\Git\bin\bash.exe`), then in the usual Git for Windows folders.
It never uses `C:\Windows\System32\bash.exe`, which starts WSL instead. To use a
different bash, set `AROOM_BASH` to its full path.

Agent CLIs installed with npm (`claude`, `opencode`) work from Git Bash as-is.
`aroom doctor` shows what it found.

## Long paths

Worktrees live under `%USERPROFILE%\.local\share\agent-room\worktrees`, and
`node_modules` inside them can go past Windows' 260-character path limit. If git
reports `Filename too long`, enable long paths once:

```powershell
git config --global core.longpaths true
```

You can also move worktrees to a shorter folder per project with
`aroom config <project> worktree_root C:\wt`.

## Phone access

This works the same as on a VPS (see [remote.md](remote.md)). Install
Tailscale for Windows, run `tailscale serve --bg 4400` in an elevated terminal,
and sign in with `aroom token --link --url https://<pc>.<tailnet>.ts.net`.

## Differences from Linux and macOS

- Stopping a run uses `taskkill /T`, which ends the whole process tree.
- Agent Room does not hunt down leftover dev servers by working directory after
  a worktree is removed (Linux and macOS do). If a port stays busy, end the
  `node` process in Task Manager.
- WSL2 is still an option if you prefer a Linux environment. Inside WSL, follow
  the Linux instructions; `--service` uses systemd when `/etc/wsl.conf` has
  `systemd=true`.
