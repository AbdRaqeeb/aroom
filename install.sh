#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$HERE/ar"
mkdir -p "$HOME/.local/bin"
ln -sfn "$HERE/ar" "$HOME/.local/bin/aroom"

# `/usr/bin/ar` is the GNU archiver. Never shadow it with a binary; alias it
# for interactive shells only, so build toolchains still get GNU ar.
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] || continue
    if ! grep -q '>>> agent-room >>>' "$rc"; then
        printf '\n# >>> agent-room >>>\nalias ar="aroom"\n# <<< agent-room <<<\n' >> "$rc"
    fi
done

if ! printf '%s' "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
    echo "note: add $HOME/.local/bin to PATH"
fi

echo "installed: aroom → $HOME/.local/bin/aroom"
echo "alias:     ar (new shells; or run: source ~/.bashrc)"
echo
echo "next:"
echo "  aroom init /path/to/repo"
echo "  aroom ui"
