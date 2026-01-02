#!/usr/bin/env python3
"""
Local admin access proxy for HWP Agent.
Run on macOS and browse http://127.0.0.1:<port>/login then /admin.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None

DEFAULT_ENV = {
    "ADMIN_ACCESS_TOKEN": "5avD9wIGFW6Pdl-Oqhx3-vB03Ei4Xd6Jig0w1XWIEe8",
    "ADMIN_SIGNATURE_SECRET": "Y4hAErFTUX8ZSrkcqi13O3tpsALWN0PLAmuDfR3Xo1UPyylDrAKJXbxzdzC0cR9E",
    "ADMIN_APP_TOKEN": "G9zPjvkdeQQa3kLaJwlhHNamz0UgkN4lMBj-TWXrCxI",
}


HOP_BY_HOP_HEADERS = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
}


def _default_env_path() -> Path:
    env_root = os.getenv("HWP_AGENT_ROOT")
    if env_root:
        return Path(env_root).expanduser() / ".env"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    exe_env = Path(sys.executable).resolve().parent / ".env"
    if exe_env.exists():
        return exe_env
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    script_env = Path(__file__).resolve().parents[1] / ".env"
    if script_env.exists():
        return script_env
    return exe_env


def _load_dotenv(explicit_path: Optional[Path] = None) -> Path:
    env_path = explicit_path or _default_env_path()
    if env_path.exists():
        if load_dotenv:
            load_dotenv(env_path)
        else:
            _load_dotenv_fallback(env_path)
    return env_path


def _apply_default_env() -> None:
    for key, value in DEFAULT_ENV.items():
        if value and not os.getenv(key):
            os.environ[key] = value


def _load_dotenv_fallback(path: Path) -> None:
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        lines = []

    key_to_index: dict[str, int] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            key_to_index[key] = idx

    for key, value in updates.items():
        new_line = f"{key}={value}\n"
        if key in key_to_index:
            lines[key_to_index[key]] = new_line
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = lines[-1] + "\n"
            lines.append(new_line)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("".join(lines), encoding="utf-8")


def _sign(method: str, path: str, timestamp: int, token: str, secret: str) -> str:
    payload = f"{method}:{path}:{timestamp}:{token}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class AdminProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._proxy_request()

    def do_POST(self):
        self._proxy_request()

    def do_PUT(self):
        self._proxy_request()

    def do_DELETE(self):
        self._proxy_request()

    def do_PATCH(self):
        self._proxy_request()

    def do_OPTIONS(self):
        self._proxy_request()

    def log_message(self, fmt: str, *args):
        sys.stdout.write("[admin-proxy] " + fmt % args + "\n")

    def _proxy_request(self):
        target_base = self.server.target_base  # type: ignore[attr-defined]
        token = self.server.admin_token  # type: ignore[attr-defined]
        secret = self.server.admin_secret  # type: ignore[attr-defined]
        app_token = self.server.app_token  # type: ignore[attr-defined]
        sign_paths = self.server.sign_paths  # type: ignore[attr-defined]

        split = urlsplit(self.path)
        target = urlsplit(target_base)
        target_url = urlunsplit((target.scheme, target.netloc, split.path, split.query, ""))

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None

        headers: Dict[str, str] = {}
        for key, value in self.headers.items():
            key_lower = key.lower()
            if key_lower in HOP_BY_HOP_HEADERS or key_lower == "host":
                continue
            headers[key] = value

        original_host = self.headers.get("Host")
        if original_host:
            headers["Host"] = original_host
        headers["Accept-Encoding"] = "identity"

        # Inject App Token if present
        if app_token:
            headers["X-App-Token"] = app_token

        should_sign = any(split.path == path or split.path.startswith(path.rstrip("/") + "/") for path in sign_paths)
        if should_sign:
            timestamp = int(time.time())
            signature = _sign(self.command, split.path, timestamp, token, secret)
            headers["X-Admin-Token"] = token
            headers["X-Admin-Timestamp"] = str(timestamp)
            headers["X-Admin-Signature"] = signature

        try:
            resp = requests.request(
                self.command,
                target_url,
                headers=headers,
                data=body,
                allow_redirects=False,
                timeout=30,
            )
        except Exception as exc:
            self.send_error(502, f"Upstream error: {exc}")
            return

        content = resp.content or b""
        self.send_response(resp.status_code)

        # Forward headers, excluding hop-by-hop and length (we'll set it explicitly).
        for key, value in resp.headers.items():
            key_lower = key.lower()
            if key_lower in HOP_BY_HOP_HEADERS or key_lower == "content-length":
                continue
            if key_lower == "set-cookie":
                continue
            self.send_header(key, value)

        raw_headers = getattr(resp, "raw", None)
        raw_header_map = getattr(raw_headers, "headers", None) if raw_headers else None
        if raw_header_map and hasattr(raw_header_map, "getlist"):
            for cookie in raw_header_map.getlist("Set-Cookie"):
                self.send_header("Set-Cookie", cookie)
        elif "Set-Cookie" in resp.headers:
            self.send_header("Set-Cookie", resp.headers["Set-Cookie"])

        self.send_header("Content-Length", str(len(content)))
        self.end_headers()

        if content:
            self.wfile.write(content)


class AdminProxyServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, target_base: str, token: str, secret: str, app_token: str):
        super().__init__(server_address, handler_class)
        self.target_base = target_base
        self.admin_token = token
        self.admin_secret = secret
        self.app_token = app_token
        self.sign_paths = ["/admin"]


def main() -> int:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env", dest="env_path")
    pre_args, _ = pre_parser.parse_known_args()

    explicit_env_path = Path(pre_args.env_path).expanduser() if pre_args.env_path else None
    loaded_env_path = _load_dotenv(explicit_env_path)
    _apply_default_env()

    parser = argparse.ArgumentParser(description="Local admin access proxy for HWP Agent")
    parser.add_argument("--target", default=os.getenv("ADMIN_PROXY_TARGET", "http://127.0.0.1:8080"), help="Target base URL")
    parser.add_argument("--port", type=int, default=int(os.getenv("ADMIN_PROXY_PORT", "8787")), help="Local proxy port")
    parser.add_argument("--env", dest="env_path", default=pre_args.env_path, help="Path to a .env file to load for this session")
    parser.add_argument("--admin-token", help="Override ADMIN_ACCESS_TOKEN for this session")
    parser.add_argument("--admin-secret", help="Override ADMIN_SIGNATURE_SECRET for this session")
    parser.add_argument("--app-token", help="Override ADMIN_APP_TOKEN for this session")
    parser.add_argument("--write-env", dest="write_env", action="store_true", help="Persist the admin tokens into the .env file")
    parser.add_argument("--no-write-env", dest="write_env", action="store_false", help="Disable writing admin tokens to the .env file")
    parser.add_argument("--open", action="store_true", help="Open the login page in the default browser")
    parser.set_defaults(write_env=True)
    args = parser.parse_args()

    env_path = Path(args.env_path).expanduser() if args.env_path else loaded_env_path
    token = args.admin_token or os.getenv("ADMIN_ACCESS_TOKEN")
    secret = args.admin_secret or os.getenv("ADMIN_SIGNATURE_SECRET")
    app_token = args.app_token or os.getenv("ADMIN_APP_TOKEN", "")
    if not token or not secret:
        print("[admin-proxy] ADMIN_ACCESS_TOKEN and ADMIN_SIGNATURE_SECRET are required.")
        return 1

    if args.write_env:
        updates = {
            "ADMIN_ACCESS_TOKEN": token,
            "ADMIN_SIGNATURE_SECRET": secret,
        }
        if app_token:
            updates["ADMIN_APP_TOKEN"] = app_token
        _update_env_file(env_path, updates)
        print(f"[admin-proxy] Wrote admin tokens to {env_path}")

    server = AdminProxyServer(
        ("127.0.0.1", args.port), 
        AdminProxyHandler, 
        target_base=args.target, 
        token=token, 
        secret=secret, 
        app_token=app_token
    )
    url = f"http://127.0.0.1:{args.port}/login"
    print("[admin-proxy] Running on:", url)
    print("[admin-proxy] Admin page:", f"http://127.0.0.1:{args.port}/admin")

    if args.open:
        try:
            import subprocess

            subprocess.run(["open", url], check=False)
        except Exception as exc:
            print("[admin-proxy] Failed to open browser:", exc)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[admin-proxy] Shutting down.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
