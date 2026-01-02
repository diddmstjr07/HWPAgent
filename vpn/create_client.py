#!/usr/bin/env python3
"""Create a WireGuard client via wg-easy API and save config."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


def _load_env(env_path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _pick_latest_client(clients: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matched = [client for client in clients if client.get("name") == name]
    if not matched:
        return None
    def _parse_ts(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return datetime.min
    matched.sort(key=lambda c: _parse_ts(str(c.get("createdAt") or "")), reverse=True)
    return matched[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a WireGuard client via wg-easy")
    parser.add_argument("--name", default="admin-mac", help="Client display name")
    parser.add_argument("--output", default=None, help="Path to save .conf")
    parser.add_argument("--api", default="http://127.0.0.1:51821", help="wg-easy API base URL")
    args = parser.parse_args()

    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        print("vpn/.env not found.")
        return 1

    env = _load_env(env_path)
    password = env.get("UI_PASSWORD")
    if not password:
        print("UI_PASSWORD is not set in vpn/.env")
        return 1

    headers = {
        "Authorization": password,
        "Content-Type": "application/json",
    }

    api_base = args.api.rstrip("/")
    create_url = f"{api_base}/api/wireguard/client"
    list_url = f"{api_base}/api/wireguard/client"

    create_res = requests.post(create_url, headers=headers, data=json.dumps({"name": args.name}), timeout=10)
    if create_res.status_code not in {200, 201}:
        print(f"Failed to create client: {create_res.status_code} {create_res.text}")
        return 1

    list_res = requests.get(list_url, headers=headers, timeout=10)
    if list_res.status_code != 200:
        print(f"Failed to list clients: {list_res.status_code} {list_res.text}")
        return 1

    clients = list_res.json() or []
    client = _pick_latest_client(clients, args.name)
    if not client:
        print("Client not found after creation.")
        return 1

    client_id = client.get("id")
    config_url = f"{api_base}/api/wireguard/client/{client_id}/configuration"
    config_res = requests.get(config_url, headers=headers, timeout=10)
    if config_res.status_code != 200:
        print(f"Failed to fetch config: {config_res.status_code} {config_res.text}")
        return 1

    output_path = args.output
    if not output_path:
        output_path = str(Path(__file__).resolve().parent / "clients" / f"{args.name}.conf")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(config_res.text, encoding="utf-8")
    print(f"Saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
