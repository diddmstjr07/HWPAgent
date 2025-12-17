#!/usr/bin/env python3
"""
Helper script to start/stop the HWP Agent Docker container in the background.

Usage:
  python docker_server.py start        # build (if needed) and run container
  python docker_server.py start --rebuild --port 5000
  python docker_server.py stop         # stop and remove container
  python docker_server.py status       # show current state
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent
IMAGE_NAME = os.environ.get("HWP_AGENT_IMAGE", "hwp-agent")
CONTAINER_NAME = os.environ.get("HWP_AGENT_CONTAINER", "hwp-agent-server")
ENV_FILE = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "output"
DB_FILE = PROJECT_ROOT / "hwp_agent.db"


def _default_port() -> int:
    try:
        return int(os.environ.get("HWP_AGENT_PORT", "8080"))
    except ValueError:
        return 8080


DEFAULT_PORT = _default_port()


def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and echo it for visibility."""
    print(f"$ {shlex.join(cmd)}")
    return subprocess.run(cmd, check=check, cwd=str(PROJECT_ROOT))


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _image_exists() -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode == 0


def _container_exists() -> bool:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^{CONTAINER_NAME}$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    return result.stdout.strip() == CONTAINER_NAME


def _container_running() -> bool:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"name=^{CONTAINER_NAME}$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    return result.stdout.strip() == CONTAINER_NAME


def build_image() -> None:
    print("Building Docker image (this may take a few minutes)...")
    _run(["docker", "build", "-t", IMAGE_NAME, "."], check=True)
    print(f"Image ready: {IMAGE_NAME}")


def start_container(port: int, rebuild: bool) -> None:
    if rebuild or not _image_exists():
        build_image()
    else:
        print(f"Image '{IMAGE_NAME}' already exists; skipping build.")

    if _container_running():
        print(f"Container '{CONTAINER_NAME}' is already running.")
        return

    if _container_exists():
        print(f"Removing existing stopped container '{CONTAINER_NAME}'...")
        _run(["docker", "rm", CONTAINER_NAME], check=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    volume_args: List[str] = ["-v", f"{OUTPUT_DIR}:/app/output"]
    if DB_FILE.exists():
        volume_args += ["-v", f"{DB_FILE}:/app/hwp_agent.db"]

    cmd: List[str] = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "--restart",
        "unless-stopped",
        "-p",
        f"{port}:5000",
    ]

    if ENV_FILE.exists():
        cmd += ["--env-file", str(ENV_FILE)]
    else:
        print("Warning: .env file not found; container will start without it.")

    cmd += volume_args
    cmd.append(IMAGE_NAME)

    _run(cmd, check=True)
    print(f"Container '{CONTAINER_NAME}' started on http://localhost:{port}")


def stop_container() -> None:
    if not _container_exists():
        print(f"Container '{CONTAINER_NAME}' is not present; nothing to stop.")
        return

    _run(["docker", "stop", CONTAINER_NAME], check=False)
    _run(["docker", "rm", CONTAINER_NAME], check=False)
    print(f"Container '{CONTAINER_NAME}' stopped and removed.")


def show_status() -> None:
    if _container_running():
        ports = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name=^{CONTAINER_NAME}$",
                "--format",
                "{{.Ports}}",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        ).stdout.strip()
        print(f"Container '{CONTAINER_NAME}' is running. Ports: {ports or 'n/a'}")
    elif _container_exists():
        print(f"Container '{CONTAINER_NAME}' exists but is stopped.")
    else:
        print(f"Container '{CONTAINER_NAME}' does not exist.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start or stop the HWP Agent Docker server."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Build (if needed) and start the container.")
    start.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Host port to expose (default: {DEFAULT_PORT})",
    )
    start.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a docker image rebuild before starting.",
    )

    sub.add_parser("stop", help="Stop and remove the container.")
    sub.add_parser("status", help="Show container status.")

    return parser.parse_args()


def main() -> None:
    if not _docker_available():
        print("Docker is not installed or not available in PATH.")
        sys.exit(1)

    args = parse_args()
    try:
        if args.command == "start":
            start_container(port=args.port, rebuild=args.rebuild)
        elif args.command == "stop":
            stop_container()
        elif args.command == "status":
            show_status()
        else:
            print("Unknown command. Use start | stop | status.")
            sys.exit(2)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed (exit {exc.returncode}): {exc}")
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
