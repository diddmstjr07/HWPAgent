#!/usr/bin/env python3
"""Sync the server .env file into installed HWP Electron app bundles."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SEARCH_ROOTS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Projects",
    Path.home() / "Developer",
    Path.home() / "Workspace",
]

SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "Library",
}

ADMIN_KEYS = {
    "ADMIN_ACCESS_TOKEN",
    "ADMIN_SIGNATURE_SECRET",
    "ADMIN_APP_TOKEN",
}

DEFAULT_APP_NAME = "HWP Admin Console"


def _has_admin_keys(env_path: Path) -> bool:
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    keys = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in ADMIN_KEYS:
            keys.add(key)
    return ADMIN_KEYS.issubset(keys)


def _default_source_env() -> Path | None:
    env_root = os.getenv("HWP_AGENT_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser() / ".env"
        if candidate.exists():
            return candidate

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env

    repo_env = Path(__file__).resolve().parents[1] / ".env"
    if repo_env.exists():
        return repo_env

    candidates: list[Path] = []
    max_depth = 4
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            rel_path = Path(dirpath).relative_to(root)
            if len(rel_path.parts) > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            if ".env" not in filenames:
                continue
            env_path = Path(dirpath) / ".env"
            if _has_admin_keys(env_path):
                candidates.append(env_path)

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _app_env_paths(app_name_hint: str) -> list[Path]:
    matches: list[Path] = []
    hint = app_name_hint.lower().strip()

    def accept(app_path: Path) -> bool:
        name = app_path.name.lower()
        return hint in name

    roots = [
        Path("/Applications"),
        Path.home() / "Applications",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path("/Volumes"),
    ]

    for root in roots:
        if not root.exists():
            continue
        if root == Path("/Volumes"):
            for volume in root.iterdir():
                if not volume.is_dir():
                    continue
                for app_path in volume.glob("*.app"):
                    if not accept(app_path):
                        continue
                    matches.append(app_path / "Contents" / "Resources" / ".env")
            continue

        for app_path in root.glob("*.app"):
            if not accept(app_path):
                continue
            matches.append(app_path / "Contents" / "Resources" / ".env")

    return matches


def _user_data_env_path(app_name: str) -> Path:
    name = app_name.strip() or DEFAULT_APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name / ".env"
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / name / ".env"
    return Path.home() / ".config" / name / ".env"


def _sync_env(source_path: Path, target_paths: list[Path]) -> int:
    content = source_path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"

    updated = 0
    for target_path in target_paths:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError:
            continue
        updated += 1
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync server .env into installed HWP Electron apps")
    parser.add_argument("--source", help="Path to the server .env file")
    parser.add_argument("--target", action="append", help="Explicit target .env path (can be repeated)")
    parser.add_argument("--app-hint", default="hwp", help="Substring to match app bundle names")
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME, help="App name used for the user-data .env path")
    args = parser.parse_args()

    source_path = Path(args.source).expanduser() if args.source else _default_source_env()
    if not source_path or not source_path.exists():
        print("[env-sync] Source .env not found. Use --source to specify it.")
        return 1

    if args.target:
        target_paths = [Path(p).expanduser() for p in args.target]
    else:
        target_paths = _app_env_paths(args.app_hint)
        target_paths.append(_user_data_env_path(args.app_name))

    target_paths = list(dict.fromkeys(target_paths))

    if not target_paths:
        print("[env-sync] No Electron app .env targets found.")
        return 1

    updated = _sync_env(source_path, target_paths)
    if not updated:
        print("[env-sync] Failed to update any target .env files.")
        return 1

    print(f"[env-sync] Source: {source_path}")
    print(f"[env-sync] Updated {updated} target(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
