import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
APP_PATH = ROOT_DIR / "app.py"
PID_FILE = ROOT_DIR / "app_background.pid"
LOG_FILE = ROOT_DIR / "app_background.log"


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except ValueError:
        return None


def _is_process_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start() -> int:
    if not APP_PATH.exists():
        print(f"app.py not found at {APP_PATH}")
        return 1

    existing_pid = _read_pid()
    if existing_pid and _is_process_running(existing_pid):
        print(f"app.py already seems to be running (pid {existing_pid}).")
        print(f"Logs: {LOG_FILE}")
        return 0

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with LOG_FILE.open("a") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(APP_PATH)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT_DIR),
            start_new_session=True,
        )

    PID_FILE.write_text(str(process.pid))
    print(f"Started app.py in background (pid {process.pid}).")
    print(f"Logs: {LOG_FILE}")
    return 0


def stop() -> int:
    pid = _read_pid()
    if not pid:
        print("No recorded pid file; nothing to stop.")
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to pid {pid}.")
    except ProcessLookupError:
        print(f"No process found with pid {pid}.")
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


def status() -> int:
    pid = _read_pid()
    if pid and _is_process_running(pid):
        print(f"app.py is running (pid {pid}).")
        print(f"Logs: {LOG_FILE}")
        return 0
    print("app.py is not running.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run app.py in the background without Docker."
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["start", "stop", "status"],
        default="start",
        help="start (default), stop, or show status",
    )
    args = parser.parse_args()

    if args.action == "start":
        return start()
    if args.action == "stop":
        return stop()
    return status()


if __name__ == "__main__":
    sys.exit(main())
