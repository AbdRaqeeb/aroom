"""Access token for the dashboard when it is reachable from other devices.

The token lives in ``~/.config/agent-room/ui-token`` (mode 0600) or in the
``AROOM_TOKEN`` environment variable. When a token exists every dashboard
request needs it, either as a session cookie (set by the login page), an
``Authorization: Bearer`` header, or a one-time ``?token=`` link that sets the
cookie and redirects. Without a token the dashboard stays open, which is only
allowed on a loopback address.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets

from . import util

TOKEN_FILE = os.path.join(os.path.dirname(util.REGISTRY), "ui-token")
COOKIE = "aroom_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 90


def load_token() -> str:
    env = (os.environ.get("AROOM_TOKEN") or "").strip()
    if env:
        return env
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def new_token() -> str:
    token = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    os.chmod(TOKEN_FILE, 0o600)
    return token


def clear_token() -> bool:
    try:
        os.remove(TOKEN_FILE)
        return True
    except FileNotFoundError:
        return False


def ensure_token() -> str:
    return load_token() or new_token()


def session_value(token: str) -> str:
    # Derived from the token so rotating the token logs every device out.
    return hmac.new(token.encode(), b"aroom-session-v1", hashlib.sha256).hexdigest()


def is_loopback(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check(token: str, *, cookie: str = "", bearer: str = "", query: str = "") -> bool:
    if not token:
        return True
    if bearer and hmac.compare_digest(bearer, token):
        return True
    if query and hmac.compare_digest(query, token):
        return True
    if cookie and hmac.compare_digest(cookie, session_value(token)):
        return True
    return False


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b0f15">
<title>agent room · sign in</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: #0b0f15; color: #e6edf6; font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; }
  form { width: min(360px, calc(100vw - 40px)); display: grid; gap: 12px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  p { margin: 0; color: #8b98aa; font-size: 13px; }
  input, button { font: inherit; padding: 12px 14px; border-radius: 10px; border: 1px solid #263041; }
  input { background: #111823; color: inherit; }
  button { background: #3a7bfd; border-color: #3a7bfd; color: #fff; font-weight: 600; }
  .err { color: #ff9b9b; }
</style></head>
<body><form method="post" action="/login">
  <h1>agent room</h1>
  <p>Paste the access token. Print it on the server with <code>aroom token</code>.</p>
  __ERROR__
  <input name="token" type="password" autocomplete="current-password" autofocus required placeholder="access token">
  <input type="hidden" name="next" value="__NEXT__">
  <button type="submit">Sign in</button>
</form></body></html>
"""
