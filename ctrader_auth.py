"""
TIMETOSHINE — cTrader Open API OAuth helper (run ONCE).

Walks Daniel through the OAuth dance:
  1. Prints the authorization URL
  2. Spins up a tiny web server on localhost:8000 to catch the redirect
  3. (Backup) Also accepts a pasted redirect URL if the local server isn't reachable
  4. Exchanges the code for access + refresh tokens
  5. Saves tokens to bot_log/ctrader_tokens.json

After this runs once successfully, read_ctrader_state.py uses the saved tokens
(auto-refreshes when expired) — you should never need to re-run this unless
the refresh token is invalidated.
"""

from __future__ import annotations
import json
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

CONFIG  = Path(r"C:\TradingBots\TIMETOSHINE\bot_log\ctrader_config.json")
TOKENS  = Path(r"C:\TradingBots\TIMETOSHINE\bot_log\ctrader_tokens.json")

AUTH_URL  = "https://connect.spotware.com/apps/auth"
TOKEN_URL = "https://connect.spotware.com/apps/token"


def load_config():
    if not CONFIG.exists():
        sys.exit(f"Config not found: {CONFIG}")
    with open(CONFIG, "r", encoding="utf-8-sig") as f:
        return json.load(f)


# Tiny HTTP server that captures the OAuth callback
_captured_code = {"code": None, "error": None}

class _CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k): pass  # silence

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            _captured_code["code"] = qs["code"][0]
            body = b"<html><body style='font-family:sans-serif;background:#0a0e14;color:#d4af37;text-align:center;padding-top:80px'><h1>Authorized! &check;</h1><p style='color:#8b9bb0'>You can close this window and return to the terminal.</p></body></html>"
        elif "error" in qs:
            _captured_code["error"] = qs["error"][0]
            body = f"<html><body><h1>Error</h1><p>{_captured_code['error']}</p></body></html>".encode()
        else:
            body = b"<html><body><h1>Unexpected callback</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_local_server():
    try:
        srv = HTTPServer(("127.0.0.1", 8000), _CallbackHandler)
        srv.timeout = 1
        # Run until we capture a code OR 5 minutes pass
        deadline = time.time() + 300
        while time.time() < deadline and _captured_code["code"] is None and _captured_code["error"] is None:
            srv.handle_request()
        srv.server_close()
    except Exception as e:
        print(f"  [local-server] {e}")


def exchange_code_for_tokens(client_id, client_secret, code, redirect_uri):
    data = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  redirect_uri,
        "client_id":     client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # server has self-signed cert in chain (corporate proxy)
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_tokens(tokens, extra=None):
    payload = {
        "access_token":  tokens.get("accessToken")  or tokens.get("access_token"),
        "refresh_token": tokens.get("refreshToken") or tokens.get("refresh_token"),
        "expires_in":    tokens.get("expiresIn")    or tokens.get("expires_in"),
        "obtained_at":   int(time.time()),
        "token_type":    tokens.get("tokenType")    or tokens.get("token_type"),
    }
    if extra: payload.update(extra)
    TOKENS.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKENS, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"  -> tokens saved to {TOKENS}")


def main():
    cfg = load_config()
    client_id     = cfg["client_id"]
    client_secret = cfg["client_secret"]
    redirect_uri  = cfg.get("redirect_uri", "http://localhost:8000/callback")
    scope         = "accounts"   # read-only

    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "scope":         scope,
        "response_type": "code",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("=" * 70)
    print("TIMETOSHINE — cTrader Open API authorization")
    print("=" * 70)
    print()
    print("STEP 1: Open this URL in your browser and log in:")
    print()
    print(f"  {auth_url}")
    print()
    print("STEP 2: After approving, Spotware will redirect to:")
    print(f"  {redirect_uri}?code=SOMETHING")
    print()
    print("If you're running THIS script on the same machine as your browser,")
    print("the page will say 'Authorized!' and you're done.")
    print()
    print("If your browser is elsewhere (laptop, phone) and the redirect")
    print("page fails to connect to localhost — that's fine. Just copy the")
    print("'code=...' value from your browser's URL bar and paste it below.")
    print()

    # Try opening browser (works if running on server with desktop)
    try: webbrowser.open(auth_url)
    except Exception: pass

    # Start local server in a thread, also wait for paste
    t = Thread(target=run_local_server, daemon=True)
    t.start()

    # Wait either for code via server OR user paste
    code = None
    print("Waiting for OAuth callback (or paste the code/URL below):")
    print("> ", end="", flush=True)

    # Non-blocking poll for either input or captured code
    import select, msvcrt  # msvcrt is Windows-only
    user_input = ""
    while True:
        if _captured_code["code"]:
            code = _captured_code["code"]
            print(f"\nCallback received automatically: ...{code[-12:]}")
            break
        if _captured_code["error"]:
            sys.exit(f"\nOAuth error: {_captured_code['error']}")
        # Check for keyboard input (Windows-only kbhit)
        if msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch in ("\r", "\n"):
                print()
                pasted = user_input.strip()
                # Accept either bare code or full URL
                if "code=" in pasted:
                    code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [None])[0]
                elif pasted:
                    code = pasted
                if code: break
                user_input = ""
                print("> ", end="", flush=True)
            elif ch == "\b" or ch == "\x08":
                user_input = user_input[:-1]
            else:
                user_input += ch
        time.sleep(0.05)

    if not code:
        sys.exit("No auth code captured.")

    print(f"\nSTEP 3: Exchanging code for tokens...")
    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, code, redirect_uri)
        if "errorCode" in tokens or "error" in tokens:
            sys.exit(f"Token exchange failed: {tokens}")
        save_tokens(tokens)
        print()
        print("=" * 70)
        print("SUCCESS — cTrader Open API is now authorized")
        print("=" * 70)
        print("Next: schedule read_ctrader_state.py to poll your account every 10 min.")
    except Exception as e:
        sys.exit(f"Token exchange failed: {e}")


if __name__ == "__main__":
    main()
