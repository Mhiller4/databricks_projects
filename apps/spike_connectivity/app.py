"""WP0 spike: can a Databricks Free Edition app reach LiveKit Cloud and Gemini Live?

Stdlib only (no pip installs) so it deploys fast. Serves one page at / that reports, per target:
  - DNS resolution, TCP connect, TLS handshake, and an HTTP GET status code
  - a raw WebSocket upgrade attempt (RFC 6455) over TLS, and the HTTP status the server answered with
  - informational: whether the Databricks Files API (UC volume) answers from inside the app

Any HTTP status (101, 400, 401, 404 ...) counts as REACHABLE: egress to the host works.
Connection errors, DNS failures or timeouts count as BLOCKED. Delete this app once the
result is recorded in tasks.md (WP0).
"""

import base64
import http.client
import json
import os
import socket
import ssl
from urllib.parse import urlparse

GEMINI_HOST = "generativelanguage.googleapis.com"


def https_probe(host: str) -> dict:
    """DNS + TCP + TLS + HTTP GET over 443."""
    try:
        conn = http.client.HTTPSConnection(host, timeout=10)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read(200).decode("utf-8", "replace")
        conn.close()
        return {"reachable": True, "http_status": resp.status, "note": body[:80]}
    except Exception as e:  # noqa: BLE001 - the whole point of the spike is catching every failure
        return {"reachable": False, "error": f"{type(e).__name__}: {e}"}


def websocket_probe(wss_url: str) -> dict:
    """Send a real RFC 6455 upgrade over TLS and record what comes back."""
    try:
        u = urlparse(wss_url if "://" in wss_url else f"wss://{wss_url}")
        host, port, path = u.hostname, u.port or 443, u.path or "/"
        raw = socket.create_connection((host, port), timeout=10)
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        tls.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        status = tls.recv(1024).decode("utf-8", "replace").split("\r\n", 1)[0]
        tls.close()
        return {"reachable": True, "ws_upgrade_response": status}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "error": f"{type(e).__name__}: {e}"}


def volume_probe() -> dict:
    """Informational: does the Files API answer from inside the app (ambient auth)?"""
    try:
        from databricks.sdk import WorkspaceClient
        n = len(list(WorkspaceClient().files.list_directory_contents("/Volumes/workspace/hc_gold/serving")))
        return {"reachable": True, "entries_listed": n}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}


def run_checks() -> dict:
    livekit_url = os.environ.get("LIVEKIT_URL", "").strip()
    livekit_host = urlparse(livekit_url).hostname if livekit_url else ""
    return {
        "gemini_https": {"host": GEMINI_HOST, **https_probe(GEMINI_HOST)},
        "livekit_https": ({"host": livekit_host, **https_probe(livekit_host)} if livekit_host
                          else {"skipped": "set LIVEKIT_URL in app.yaml (it is not a secret)"}),
        "livekit_websocket": (websocket_probe(livekit_url) if livekit_url
                              else {"skipped": "set LIVEKIT_URL in app.yaml (it is not a secret)"}),
        "databricks_files_api_informational": volume_probe(),
    }


def render(checks: dict) -> str:
    verdict = all(v.get("reachable") for k, v in checks.items() if k != "databricks_files_api_informational")
    return ("<!doctype html><title>WP0 spike</title>"
            f"<h1 style='font-family:sans-serif'>WP0 spike: outbound egress</h1>"
            f"<h2 style='font-family:sans-serif;color:{'#0a7' if verdict else '#c33'}'>"
            f"{'REACHABLE - the worker can run inside the app' if verdict else 'BLOCKED - see details'}</h2>"
            f"<pre style='font-family:monospace'>{json.dumps(checks, indent=2)}</pre>")


if __name__ == "__main__":
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            checks = run_checks()
            body = render(checks).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass  # keep app logs quiet

    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    print(f"spike listening on {port}", flush=True)
    HTTPServer(("0.0.0.0", port), H).serve_forever()