#!/usr/bin/env python3
"""One-command launcher. Works the same on Windows, macOS and Linux, and needs nothing installed first.

    python run.py            set everything up on the first run, start the dashboard, open your browser
    python run.py --check    set everything up, start the dashboard briefly to prove it works, then exit
    python run.py --test     set everything up and run the self-checks

On Windows you may need `py run.py`; on macOS/Linux `python3 run.py`.
"""
import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
MIN_PYTHON = (3, 10)


def ensure_environment():
    """Create a private Python environment on the first run and keep its packages in step with requirements.txt."""
    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required (you have {sys.version.split()[0]}).\n"
                 "Get it from https://www.python.org/downloads/ and run this again.")
    if not PYTHON.exists():
        print("Creating a private Python environment in .venv (first run only)...")
        try:
            venv.create(VENV, with_pip=True)
        except Exception as e:
            shutil.rmtree(VENV, ignore_errors=True)
            sys.exit(f"Couldn't create the environment: {e}\n"
                     "On Debian/Ubuntu, install the missing piece first: sudo apt install python3-venv")
    wanted = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    stamp = VENV / ".requirements.sha256"
    if not stamp.exists() or stamp.read_text() != wanted:
        print("Installing packages (about a minute the first time)...")
        result = subprocess.run([str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                                 "-r", str(ROOT / "requirements.txt")])
        if result.returncode:
            sys.exit("Installing the packages failed. Check your internet connection and try again.\n"
                     "If the message above mentions a compiler or a missing wheel, use Python 3.10 to 3.13.")
        stamp.write_text(wanted)


def free_port(start=8420):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    sys.exit(f"Couldn't find a free port between {start} and {start + 49}.")


def wait_until_up(url, server, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline and server.poll() is None:
        try:
            for path in ("/", "/api/state"):
                urllib.request.urlopen(url + path, timeout=2).read()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def stop(server):
    server.terminate()
    try:
        server.wait(timeout=8)
    except subprocess.TimeoutExpired:
        server.kill()


def start_dashboard(check):
    port = free_port()
    url = f"http://localhost:{port}"
    server = subprocess.Popen([str(PYTHON), "webapp.py"], cwd=ROOT, env={**os.environ, "PORT": str(port)})
    try:
        if not wait_until_up(url, server):
            print("The dashboard didn't start. Its own error message is above.", file=sys.stderr)
            return 1
        if check:
            print(f"OK: the dashboard started at {url}")
            return 0
        print(f"\nSummit is running at {url}\nPress Ctrl+C in this window to stop it.\n")
        webbrowser.open(url)
        server.wait()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop(server)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Set up and start the Summit dashboard.")
    parser.add_argument("--check", action="store_true", help="prove the setup works, then exit")
    parser.add_argument("--test", action="store_true", help="run the self-checks, then exit")
    args = parser.parse_args()

    ensure_environment()
    if args.test:
        return subprocess.run([str(PYTHON), "test_bot.py"], cwd=ROOT).returncode
    return start_dashboard(args.check)


if __name__ == "__main__":
    sys.exit(main())
