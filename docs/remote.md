# Running on a VPS and using it from your phone

Agent Room has no cloud part. To reach it from a phone, run it on an always-on
machine (a VPS, a home server) and open the dashboard over a private network or
HTTPS. The dashboard can start, stop and merge runs, so it is always behind an
access token once it leaves `127.0.0.1`.

## 1. Install on the VPS

Ubuntu/Debian with a normal (non-root) user:

```bash
sudo apt update && sudo apt install -y git python3 curl
```

Install an agent CLI and sign it in **on the VPS** (agents run there, not on your
phone):

```bash
npm install -g @anthropic-ai/claude-code && claude      # Claude Code
# or
curl -fsSL https://opencode.ai/install | bash && opencode auth login
```

Install Agent Room as a service:

```bash
curl -fsSL https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.sh | bash -s -- --service
```

While the repo is private, fetching the script needs a token too.
[Create a fine-grained token](https://github.com/settings/personal-access-tokens/new)
with **Contents: read** on `AbdRaqeeb/aroom`, then:

```bash
export GITHUB_TOKEN=github_pat_...
curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github.raw" \
  https://api.github.com/repos/AbdRaqeeb/aroom/contents/install.sh | bash -s -- --service
```

(`gh auth login` or an SSH key on GitHub also work; the installer tries
public HTTPS, `gh`, SSH and `GITHUB_TOKEN` in that order. The token is used for
the clone only and is never written to disk.)

`--service` does the following:

- installs `agent-room-ui` and `agent-room-supervisor` as systemd **user** units
- copies your current `PATH` into the units, so they find `claude`/`opencode`/`node`
- runs `loginctl enable-linger` so the units keep running after you log out and
  start again after a reboot (if that fails, run `sudo loginctl enable-linger $USER`)
- creates the dashboard access token and prints it

The dashboard listens on `127.0.0.1:4400` by default. Leave it there and
pick one of the options below to reach it.

Add your projects on the VPS (clone them there first):

```bash
git clone git@github.com:you/your-app.git ~/code/your-app
aroom init ~/code/your-app
```

## 2. Reach it from the phone

### Option A: Tailscale (recommended)

This needs no domain, opens no public port, and gives you real HTTPS. Only your
own devices can connect.

On the VPS:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 4400
tailscale serve status        # shows https://<vps>.<tailnet>.ts.net
```

On the phone, install the Tailscale app, sign in with the same account, then open
`https://<vps>.<tailnet>.ts.net`. Sign in once with the token. The session
lasts 90 days.

### Option B: your own domain with Caddy

Point a DNS `A` record (for example `aroom.example.com`) at the VPS, open ports 80
and 443, then:

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
aroom.example.com {
    reverse_proxy 127.0.0.1:4400
}
EOF
sudo systemctl reload caddy
```

Caddy gets the certificate on its own. The dashboard is now on the public
internet behind the token, so use a long token (the default is 32 characters)
and rotate it if it leaks (`aroom token --new`).

### Option C: direct port (LAN or quick test only)

```bash
~/.local/share/aroom/install.sh --service --listen 0.0.0.0
```

This is plain HTTP, so the token travels unencrypted. Use it only on a trusted
network.

## 3. Sign in on the phone

```bash
aroom token                                              # the token
aroom token --link --url https://<vps>.<tailnet>.ts.net  # a one-tap sign-in link
```

Open the link on the phone, or paste the token into the sign-in page. Then use
**Share → Add to Home Screen** (iOS) or **⋮ → Add to Home screen** (Android) to
get a full-screen app icon.

`aroom token --new` rotates the token and signs out every device.
**sign out** in the header ends the session on one device.

## Preview links from the phone

Preview URLs are configured as `http://localhost:<port>`. When you open the
dashboard from another device, it rewrites them to the dashboard's host, for
example `http://<vps>.<tailnet>.ts.net:4310`. For those links to load:

- the dev server must listen on all interfaces, not only on localhost
  (Vite: `--host`, Next.js: `-H 0.0.0.0`, set in `preview.command`)
- on Tailscale this works over the tailnet as-is (plain HTTP on the tailnet IP);
  for HTTPS use `sudo tailscale serve --bg --https=4310 4310`
- on a public VPS, do **not** open preview ports to the internet. Put them behind
  Caddy with their own hostname and auth, or use Tailscale.

## Operating the service

```bash
systemctl --user status agent-room-ui agent-room-supervisor
journalctl --user -u agent-room-ui -f            # or ~/.local/state/agent-room/ui.log
systemctl --user restart agent-room-ui

# upgrade: re-run the same curl command, or
git -C ~/.local/share/aroom pull --ff-only && systemctl --user restart agent-room-ui agent-room-supervisor
```

Running the installer again is safe. It updates the checkout, rewrites the
launcher and units, and keeps your token.
