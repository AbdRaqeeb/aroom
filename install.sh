#!/usr/bin/env bash
# Install Agent Room (`aroom`).
#
# From a checkout:   ./install.sh [--service] [--listen ADDR]
# From anywhere:     curl -fsSL <raw url>/install.sh | bash -s -- [options]
#
# Piped through curl there is no checkout next to the script, so it clones (or
# updates) the repo into $AROOM_HOME and re-runs the installer from there.
#
# Options:
#   --service        Run the dashboard and the supervisor in the background:
#                    Linux: systemd user units with lingering (survive logout
#                    and reboot; what you want on a VPS). macOS: launchd agents
#                    (start at login, restart on crash).
#   --listen ADDR    Address the dashboard service binds (default 127.0.0.1).
#                    Anything other than loopback requires the access token.
#   --ref REF        Branch or tag to install (default: main).
#
# Environment:
#   AROOM_HOME   where the checkout lives   (default ~/.local/share/aroom)
#   AROOM_REPO   GitHub owner/name          (default AbdRaqeeb/aroom)
#   AROOM_REF    branch or tag              (default main)
#   AROOM_GIT_URL clone from this URL instead (fork, mirror, local path)
#   GITHUB_TOKEN token with read access, used when the repo is private and
#                neither `gh` nor an SSH key is set up. Never stored on disk.
#
# Safe to re-run: it rewrites the launcher and only touches shell rc files once.
set -euo pipefail

AROOM_REPO="${AROOM_REPO:-AbdRaqeeb/aroom}"
AROOM_REF="${AROOM_REF:-main}"
AROOM_HOME="${AROOM_HOME:-$HOME/.local/share/aroom}"
WITH_SERVICE=0
LISTEN=""

while [ $# -gt 0 ]; do
    case "$1" in
        --service) WITH_SERVICE=1 ;;
        --listen) LISTEN="${2:?--listen needs an address}"; shift ;;
        --listen=*) LISTEN="${1#*=}" ;;
        --ref) AROOM_REF="${2:?--ref needs a branch or tag}"; shift ;;
        --ref=*) AROOM_REF="${1#*=}" ;;
        -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null || true; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# --- bootstrap: running from curl, not from a checkout ----------------------

script="${BASH_SOURCE[0]:-}"
if [ -n "$script" ] && [ -f "$script" ] && [ -f "$(dirname "$script")/ar" ] && [ -d "$(dirname "$script")/agentroom" ]; then
    HERE="$(cd "$(dirname "$script")" && pwd)"
else
    command -v git >/dev/null 2>&1 || {
        echo "error: git is required. Install it (apt install git / brew install git) and re-run." >&2
        exit 1
    }
    export GIT_TERMINAL_PROMPT=0

    # Pick a way to reach the repo: public HTTPS, gh, SSH key, or a token.
    remote=""
    auth_remote=""
    https="https://github.com/$AROOM_REPO.git"
    if [ -n "${AROOM_GIT_URL:-}" ]; then
        remote="$AROOM_GIT_URL"
    elif git ls-remote --exit-code "$https" HEAD >/dev/null 2>&1; then
        remote="$https"
    elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        gh auth setup-git >/dev/null 2>&1 || true
        remote="$https"
    elif ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
        remote="git@github.com:$AROOM_REPO.git"
    elif [ -n "${GITHUB_TOKEN:-}" ]; then
        remote="$https"
        auth_remote="https://x-access-token:${GITHUB_TOKEN}@github.com/$AROOM_REPO.git"
    else
        cat >&2 <<MSG
error: cannot read github.com/$AROOM_REPO (it is private).

Use one of:
  gh auth login                         then re-run the curl command
  an SSH key added to GitHub            then re-run the curl command
  GITHUB_TOKEN=<token with repo read>   in front of 'bash' in the curl command
MSG
        exit 1
    fi
    fetch_from="${auth_remote:-$remote}"

    if [ -d "$AROOM_HOME/.git" ]; then
        echo "updating:  $AROOM_HOME ($AROOM_REF)"
        git -C "$AROOM_HOME" fetch --quiet --tags "$fetch_from" "+refs/heads/*:refs/remotes/origin/*"
        if git -C "$AROOM_HOME" rev-parse --verify --quiet "refs/remotes/origin/$AROOM_REF" >/dev/null; then
            git -C "$AROOM_HOME" checkout --quiet -B "$AROOM_REF" "origin/$AROOM_REF"
        else
            git -C "$AROOM_HOME" checkout --quiet "$AROOM_REF"
        fi
    else
        if [ -e "$AROOM_HOME" ] && [ -n "$(ls -A "$AROOM_HOME" 2>/dev/null)" ]; then
            echo "error: $AROOM_HOME exists and is not a git checkout; move it or set AROOM_HOME" >&2
            exit 1
        fi
        echo "cloning:   $AROOM_REPO ($AROOM_REF) → $AROOM_HOME"
        mkdir -p "$(dirname "$AROOM_HOME")"
        git clone --quiet --branch "$AROOM_REF" "$fetch_from" "$AROOM_HOME"
    fi
    # Never leave a token in .git/config.
    git -C "$AROOM_HOME" remote set-url origin "$remote"

    args=()
    [ "$WITH_SERVICE" = 1 ] && args+=(--service)
    [ -n "$LISTEN" ] && args+=(--listen "$LISTEN")
    exec bash "$AROOM_HOME/install.sh" ${args[@]+"${args[@]}"}
fi

# Git Bash / MSYS / Cygwin on Windows: the native Windows installer does the
# work (launcher .cmd files, user PATH, Task Scheduler for --service).
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        echo "windows:   handing over to install.ps1"
        ps_args=()
        [ "$WITH_SERVICE" = 1 ] && ps_args+=(-Service)
        [ -n "$LISTEN" ] && ps_args+=(-Listen "$LISTEN")
        exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/install.ps1")" ${ps_args[@]+"${ps_args[@]}"}
        ;;
esac

BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/aroom"

find_python() {
    # Prefer a real 3.10+ interpreter. macOS still ships Python 3.9 as
    # /usr/bin/python3, so `python3` alone is not enough.
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
                command -v "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    cat >&2 <<'MSG'
error: Agent Room needs Python 3.10 or newer.

  macOS:  brew install python@3.12     (or https://www.python.org/downloads/)
  Debian: sudo apt install python3
  Fedora: sudo dnf install python3

Then run this script again.
MSG
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "warning: git is not on PATH; Agent Room needs it to run tasks" >&2
fi

chmod +x "$HERE/ar"
mkdir -p "$BIN_DIR"

# Write a small wrapper instead of a symlink so the launcher keeps working when
# the default `python3` is too old for the package.
tmp="$LAUNCHER.$$"
{
    echo '#!/bin/sh'
    echo '# Generated by agent-room install.sh — points at this checkout.'
    echo "exec \"$PYTHON\" \"$HERE/ar\" \"\$@\""
} >"$tmp"
chmod +x "$tmp"
mv -f "$tmp" "$LAUNCHER"

# Shell integration: PATH entry plus `ar` alias (GNU ar lives at /usr/bin/ar and
# must never be shadowed by a binary).
block='# >>> agent-room >>>
export PATH="$HOME/.local/bin:$PATH"
alias ar="aroom"
# <<< agent-room <<<'

targets=""
case "${SHELL:-}" in
    */zsh) targets="$HOME/.zshrc" ;;
    */bash)
        targets="$HOME/.bashrc"
        if [ "$(uname -s)" = "Darwin" ]; then
            # macOS login shells read .bash_profile, not .bashrc.
            targets="$targets $HOME/.bash_profile"
        fi
        ;;
esac
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    [ -f "$rc" ] || continue
    case " $targets " in
        *" $rc "*) ;;
        *) targets="$targets $rc" ;;
    esac
done
[ -n "$targets" ] || targets="$HOME/.profile"

for rc in $targets; do
    [ -f "$rc" ] || : >"$rc"
    if ! grep -q '>>> agent-room >>>' "$rc"; then
        printf '\n%s\n' "$block" >>"$rc"
        echo "updated:   $rc"
    elif ! grep -qF 'export PATH="$HOME/.local/bin:$PATH"' "$rc"; then
        # Older installs only had the alias; rewrite the block to add PATH.
        tmp="$rc.agentroom.$$"
        awk '
            /# >>> agent-room >>>/ { skip = 1; next }
            /# <<< agent-room <<</ { skip = 0; next }
            !skip
        ' "$rc" >"$tmp"
        printf '\n%s\n' "$block" >>"$tmp"
        mv -f "$tmp" "$rc"
        echo "updated:   $rc"
    fi
done

echo "installed: $LAUNCHER → $HERE/ar"
echo "python:    $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"
echo "alias:     ar (new shells only)"

if ! "$LAUNCHER" --version >/dev/null 2>&1; then
    echo "error: the launcher failed to start; run: $LAUNCHER --version" >&2
    exit 1
fi

# Optional: setproctitle names the processes (aroom-ui, aroom-supervisor)
# instead of "Python". Agent Room runs without it, so failures are only noted.
# It goes into the user site; on a PEP 668 Python (Homebrew, Debian) that needs
# --break-system-packages, which still leaves the system site-packages alone.
if "$PYTHON" -c 'import setproctitle' >/dev/null 2>&1; then
    echo "titles:    setproctitle present"
elif "$PYTHON" -m pip install --user --quiet --disable-pip-version-check setproctitle >/dev/null 2>&1 ||
    "$PYTHON" -m pip install --user --quiet --disable-pip-version-check --break-system-packages setproctitle >/dev/null 2>&1; then
    echo "titles:    installed setproctitle (processes show as aroom-ui, aroom-supervisor)"
else
    echo "note:      could not install setproctitle; processes will show as \"Python\" (optional)"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "note:      $BIN_DIR is not on PATH in this shell yet; open a new shell or source your rc file" ;;
esac

# --- optional: background services -----------------------------------------
# Linux: systemd user units (survive logout/reboot with lingering).
# macOS: launchd agents in ~/Library/LaunchAgents (start at login, restart on crash).

xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

write_launchd_agent() {
    # write_launchd_agent <label> <log name> <arg>...
    label="$1"; log="$2"; shift 2
    plist="$HOME/Library/LaunchAgents/$label.plist"
    {
        echo '<?xml version="1.0" encoding="UTF-8"?>'
        echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        echo '<!-- Generated by the agent-room installer (service option); re-run it to regenerate. -->'
        echo '<plist version="1.0">'
        echo '<dict>'
        echo "    <key>Label</key><string>$label</string>"
        echo '    <key>ProgramArguments</key>'
        echo '    <array>'
        for arg in "$@"; do
            echo "        <string>$(xml_escape "$arg")</string>"
        done
        echo '    </array>'
        echo "    <key>WorkingDirectory</key><string>$(xml_escape "$HOME")</string>"
        echo '    <key>EnvironmentVariables</key>'
        echo '    <dict>'
        echo "        <key>PATH</key><string>$(xml_escape "$svc_path")</string>"
        echo "        <key>HOME</key><string>$(xml_escape "$HOME")</string>"
        echo '    </dict>'
        echo '    <key>RunAtLoad</key><true/>'
        echo '    <key>KeepAlive</key><true/>'
        echo '    <key>ThrottleInterval</key><integer>5</integer>'
        echo '    <key>ProcessType</key><string>Background</string>'
        echo "    <key>StandardOutPath</key><string>$(xml_escape "$HOME/.local/state/agent-room/$log")</string>"
        echo "    <key>StandardErrorPath</key><string>$(xml_escape "$HOME/.local/state/agent-room/$log")</string>"
        echo '</dict>'
        echo '</plist>'
    } >"$plist"
    if command -v plutil >/dev/null 2>&1 && ! plutil -lint "$plist" >/dev/null; then
        echo "error: generated $plist is not a valid plist" >&2
        exit 1
    fi
    domain="gui/$(id -u)"
    # Reload: bootout is a no-op error when it was not loaded yet.
    if launchctl bootout "$domain/$label" >/dev/null 2>&1; then
        sleep 1  # bootout returns before the old process has fully exited
    fi
    if ! launchctl bootstrap "$domain" "$plist" 2>/dev/null; then
        # Older macOS, or a shell without a GUI session (e.g. over ssh).
        launchctl unload "$plist" >/dev/null 2>&1 || true
        launchctl load -w "$plist"
    fi
}

if [ "$WITH_SERVICE" = 1 ]; then
    # Services do not read shell rc files: keep the PATH that found
    # claude/opencode/node in this shell.
    svc_path="$BIN_DIR:$PATH"
    listen="${LISTEN:-127.0.0.1}"
    mkdir -p "$HOME/.local/state/agent-room"
    case "$(uname -s)" in
    Darwin)
        mkdir -p "$HOME/Library/LaunchAgents"
        # Off loopback the dashboard must be locked; on 127.0.0.1 it stays open
        # for this Mac (add one later with `aroom token --new`).
        case "$listen" in
            127.0.0.1|localhost|::1) ;;
            *) "$LAUNCHER" token --create >/dev/null ;;
        esac
        write_launchd_agent com.agentroom.ui ui.log "$LAUNCHER" ui --no-open --host "$listen"
        write_launchd_agent com.agentroom.supervisor supervisor.log "$LAUNCHER" supervise --interval 60
        echo "service:   com.agentroom.ui + com.agentroom.supervisor loaded (dashboard on http://$listen:4400)"
        echo "           start at login, restart on crash; logs in ~/.local/state/agent-room/"
        echo "           stop:    launchctl bootout gui/\$(id -u)/com.agentroom.ui"
        echo "           restart: launchctl kickstart -k gui/\$(id -u)/com.agentroom.ui"
        ;;
    Linux)
        if ! command -v systemctl >/dev/null 2>&1; then
            echo "warning: --service needs systemd on Linux; run \`aroom ui\` and \`aroom supervise --detach\` instead" >&2
        else
            unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
            mkdir -p "$unit_dir"
            cp "$HERE/examples/systemd/agent-room-ui.service" "$HERE/examples/systemd/agent-room-supervisor.service" "$unit_dir/"
            for unit in agent-room-ui agent-room-supervisor; do
                mkdir -p "$unit_dir/$unit.service.d"
                {
                    echo "[Service]"
                    echo "Environment=\"PATH=$svc_path\""
                } >"$unit_dir/$unit.service.d/10-install.conf"
            done
            {
                echo "[Service]"
                echo "ExecStart="
                echo "ExecStart=$LAUNCHER ui --no-open --host $listen"
            } >"$unit_dir/agent-room-ui.service.d/20-listen.conf"

            # A token is always created on Linux servers: the dashboard can start,
            # stop and merge runs, and a reverse proxy makes every client look local.
            "$LAUNCHER" token --create >/dev/null

            if ! loginctl enable-linger "$USER" 2>/dev/null; then
                echo "note:      could not enable lingering; run: sudo loginctl enable-linger $USER"
            fi
            if systemctl --user daemon-reload 2>/dev/null; then
                systemctl --user enable --now agent-room-ui.service agent-room-supervisor.service
                systemctl --user restart agent-room-ui.service
                echo "service:   agent-room-ui + agent-room-supervisor enabled (dashboard on $listen:4400)"
            else
                echo "warning: no systemd user session (try: sudo loginctl enable-linger $USER, then log in again and re-run)" >&2
            fi
        fi
        ;;
    *)
        echo "warning: --service supports Linux (systemd) and macOS (launchd)" >&2
        ;;
    esac
    if token="$("$LAUNCHER" token 2>/dev/null)"; then
        echo "token:     $token"
        echo "           (aroom token --link prints a one-tap sign-in link)"
    fi
fi

echo
echo "next:"
echo "  aroom doctor"
echo "  aroom init /path/to/repo"
if [ "$WITH_SERVICE" = 1 ]; then
    echo "  phone access: see docs/remote.md (tailscale serve 4400, or caddy + domain)"
else
    echo "  aroom ui"
fi
