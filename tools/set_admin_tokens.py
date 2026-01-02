#!/usr/bin/env python3
"""Update admin token/secret in the .env file (auto-discovered)."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ENV_KEYS = [
    "ADMIN_ACCESS_ENABLED",
    "ADMIN_ACCESS_TOKEN",
    "ADMIN_SIGNATURE_SECRET",
    "ADMIN_APP_TOKEN",
]

TOKEN_KEYS = [
    "ADMIN_ACCESS_TOKEN",
    "ADMIN_SIGNATURE_SECRET",
    "ADMIN_APP_TOKEN",
]

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


def _load_env_lines(env_path: Path) -> list[str]:
    return env_path.read_text(encoding="utf-8").splitlines(keepends=True)


def _extract_tokens(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in TOKEN_KEYS:
            values[key] = value.strip()
    return values


def _read_tokens_from_path(env_path: Path) -> dict[str, str]:
    try:
        lines = _load_env_lines(env_path)
    except OSError:
        return {}
    return _extract_tokens(lines)


def _has_all_tokens(tokens: dict[str, str]) -> bool:
    return all(tokens.get(key) for key in TOKEN_KEYS)


def _update_env(lines: list[str], updates: dict[str, str]) -> list[str]:
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

    return lines


def _candidate_env_paths() -> list[Path]:
    candidates: list[Path] = []
    env_root = os.getenv("HWP_AGENT_ROOT")
    if env_root:
        candidates.append(Path(env_root) / ".env")
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(sys.executable).resolve().parent / ".env")
    candidates.append(Path(__file__).resolve().parents[1] / ".env")
    seen = set()
    unique: list[Path] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _application_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.getenv("HWP_APP_ROOT") or os.getenv("HWP_ADMIN_APP_ROOT")
    if env_root:
        roots.append(Path(env_root))
    roots.extend(
        [
            Path("/Applications"),
            Path("/Volumes"),
            Path.home() / "Applications",
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path.cwd(),
            Path(sys.executable).resolve().parent,
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        unique.append(root)
    return unique


def _application_env_paths() -> list[Path]:
    candidates: list[Path] = []
    for root in _application_roots():
        if root.is_file() and root.suffix == ".app":
            app_path = root
            if "HWP" not in app_path.name and "hwp" not in app_path.name:
                continue
            candidates.append(app_path / "Contents" / "Resources" / ".env")
            continue
        if not root.exists():
            continue
        if root == Path("/Volumes"):
            for volume in sorted(root.iterdir()):
                if not volume.is_dir():
                    continue
                for app_path in sorted(volume.glob("*.app")):
                    if "HWP" not in app_path.name and "hwp" not in app_path.name:
                        continue
                    env_path = app_path / "Contents" / "Resources" / ".env"
                    candidates.append(env_path)
            continue
        for app_path in sorted(root.glob("*.app")):
            if "HWP" not in app_path.name and "hwp" not in app_path.name:
                continue
            env_path = app_path / "Contents" / "Resources" / ".env"
            candidates.append(env_path)
    return candidates


def _discover_project_env_paths() -> list[Path]:
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
            tokens = _read_tokens_from_path(env_path)
            if tokens:
                candidates.append(env_path)
    return candidates


def _is_app_env(path: Path) -> bool:
    return ".app/Contents/Resources/.env" in str(path)


def _select_source_tokens(env_paths: list[Path]) -> tuple[dict[str, str], Path | None]:
    source_mode = os.getenv("HWP_TOKEN_SOURCE", "newest").strip().lower()
    candidates: list[tuple[Path, dict[str, str], float, bool]] = []
    for env_path in env_paths:
        if not env_path.exists():
            continue
        tokens = _read_tokens_from_path(env_path)
        if not _has_all_tokens(tokens):
            continue
        try:
            mtime = env_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((env_path, tokens, mtime, _is_app_env(env_path)))

    if not candidates:
        return {}, None

    def sort_key(item: tuple[Path, dict[str, str], float, bool]) -> tuple[float, int]:
        _, _, mtime, is_app = item
        return (mtime, 0 if not is_app else -1)

    if source_mode == "server":
        server_candidates = [c for c in candidates if not c[3]]
        pool = server_candidates or candidates
    elif source_mode == "app":
        app_candidates = [c for c in candidates if c[3]]
        pool = app_candidates or candidates
    else:
        pool = candidates

    chosen = max(pool, key=sort_key)
    return chosen[1], chosen[0]


def _should_rotate() -> bool:
    args = set(sys.argv[1:])
    if "--rotate" in args:
        return True
    return os.getenv("HWP_ADMIN_ROTATE", "").strip().lower() in {"1", "true", "yes", "on"}


def _find_env_paths() -> list[Path]:
    paths: list[Path] = []
    for candidate in _candidate_env_paths():
        if candidate.exists():
            paths.append(candidate)
    for candidate in _discover_project_env_paths():
        if candidate.exists() and candidate not in paths:
            paths.append(candidate)
    app_candidates = _application_env_paths()
    for candidate in app_candidates:
        if candidate.exists():
            paths.append(candidate)
    if not paths:
        # allow creating .env inside installed apps if present
        paths.extend(app_candidates)
    return paths


def main() -> int:
    env_paths = _find_env_paths()
    if not env_paths:
        print(".env not found. Install the HWP app in /Applications or set HWP_AGENT_ROOT.")
        return 1

    rotate = _should_rotate()
    source_tokens, source_path = ({}, None)
    if not rotate:
        source_tokens, source_path = _select_source_tokens(env_paths)

    if source_tokens:
        token = source_tokens["ADMIN_ACCESS_TOKEN"]
        secret = source_tokens["ADMIN_SIGNATURE_SECRET"]
        app_token = source_tokens["ADMIN_APP_TOKEN"]
    else:
        token = secrets.token_urlsafe(32)
        secret = secrets.token_urlsafe(48)
        app_token = secrets.token_urlsafe(32)
    updates = {
        "ADMIN_ACCESS_ENABLED": "1",
        "ADMIN_ACCESS_TOKEN": token,
        "ADMIN_SIGNATURE_SECRET": secret,
        "ADMIN_APP_TOKEN": app_token,
    }

    updated_paths: list[Path] = []
    for env_path in env_paths:
        if env_path.exists():
            lines = _load_env_lines(env_path)
        else:
            lines = []
        updated = _update_env(lines, updates)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("".join(updated), encoding="utf-8")
        updated_paths.append(env_path)

    for path in updated_paths:
        print(f"Updated admin tokens in {path}")
    if source_path:
        print(f"Using tokens from {source_path}")
    elif rotate:
        print("Generated new tokens (--rotate).")
    else:
        print("Generated new tokens (no existing tokens found).")
    print(f"ADMIN_ACCESS_TOKEN={token}")
    print(f"ADMIN_SIGNATURE_SECRET={secret}")
    print(f"ADMIN_APP_TOKEN={app_token}")
    print("Restart the server and relaunch the Electron app to apply.")
    if sys.stdin.isatty():
        try:
            input("Press Enter to exit...")
        except EOFError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
