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
#   --service        Linux: install + start systemd user units for the dashboard
#                    and the supervisor, and enable lingering so they survive
#                    logout/reboot (what you want on a VPS).
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
        -h|--help) sed -n '2,27p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null || true; exit 0 ;;
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

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "note:      $BIN_DIR is not on PATH in this shell yet; open a new shell or source your rc file" ;;
esac

# --- optional: systemd user services (VPS / always-on Linux box) -----------

if [ "$WITH_SERVICE" = 1 ]; then
    if [ "$(uname -s)" != "Linux" ] || ! command -v systemctl >/dev/null 2>&1; then
        echo "warning: --service needs Linux with systemd; see examples/launchd for macOS" >&2
    else
        unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
        mkdir -p "$unit_dir" "$HOME/.local/state/agent-room"
        cp "$HERE/examples/systemd/agent-room-ui.service" "$HERE/examples/systemd/agent-room-supervisor.service" "$unit_dir/"

        # Services do not read shell rc files: keep the PATH that found
        # claude/opencode/node in this shell.
        svc_path="$BIN_DIR:$PATH"
        for unit in agent-room-ui agent-room-supervisor; do
            mkdir -p "$unit_dir/$unit.service.d"
            {
                echo "[Service]"
                echo "Environment=\"PATH=$svc_path\""
            } >"$unit_dir/$unit.service.d/10-install.conf"
        done
        listen="${LISTEN:-127.0.0.1}"
        {
            echo "[Service]"
            echo "ExecStart="
            echo "ExecStart=$LAUNCHER ui --no-open --host $listen"
        } >"$unit_dir/agent-room-ui.service.d/20-listen.conf"

        # A token is always created for the service: the dashboard can start,
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
        echo "token:     $("$LAUNCHER" token)"
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
