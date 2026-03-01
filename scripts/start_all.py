"""
Start all agent services, then run the agent chat in this terminal.

API, Dashboard, and Heartbeat run silently in the background (logs → logs/services/).
Any previously running services on the same ports are killed first.
The interactive agent chat runs in the foreground here.
Background services keep running even after you exit the chat.

Usage:
    python scripts/start_all.py           # kill old + start all + open chat here
    python scripts/start_all.py --no-chat # kill old + start all + open browser, then exit

Manual kill commands (if you ever need them without this script):
    # Kill API (port 8000):
    for /f "tokens=5" %a in ('netstat -ano ^| findstr :8000') do taskkill /PID %a /F
    # Kill Dashboard (port 5173):
    for /f "tokens=5" %a in ('netstat -ano ^| findstr :5173') do taskkill /PID %a /F
    # Kill heartbeat scheduler:
    wmic process where "commandline like '%run_heartbeat_scheduler%'" delete
    # Nuclear — kill all Python + Node:
    taskkill /IM python.exe /F && taskkill /IM node.exe /F
"""
import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable  # Inherits the venv Python from whichever Python runs this
LOG_DIR = PROJECT_ROOT / "logs" / "services"

BG_SERVICES = [
    ("api",       f'"{PYTHON}" -m src.agent.api',                    PROJECT_ROOT),
    ("dashboard", "npm run dev",                                       PROJECT_ROOT / "dashboard"),
    ("heartbeat", f'"{PYTHON}" -m scripts.run_heartbeat_scheduler',   PROJECT_ROOT),
]


# ── Kill helpers ──────────────────────────────────────────────────────────────

def _kill_port(port: int, label: str) -> None:
    """Kill any process currently listening on the given TCP port."""
    result = subprocess.run(
        f'netstat -ano | findstr ":{port} "',
        shell=True, capture_output=True, text=True,
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        # netstat columns: Proto  Local  Foreign  State  PID
        if len(parts) >= 2 and f":{port}" in parts[1]:
            pid = parts[-1]
            if pid.isdigit() and int(pid) > 4:  # skip PID 0/4 (System)
                pids.add(pid)
    for pid in pids:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
    if pids:
        print(f"  Killed {label} (port {port}, PID {', '.join(pids)})")


def _kill_cmdline(fragment: str, label: str) -> None:
    """Kill python.exe processes whose command line contains `fragment`."""
    result = subprocess.run(
        ["wmic", "process", "where",
         f"name='python.exe' and commandline like '%{fragment}%'",
         "get", "processid", "/format:value"],
        capture_output=True, text=True,
    )
    pids = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("ProcessId="):
            pid = line.split("=", 1)[1].strip()
            if pid.isdigit() and int(pid) > 4:
                pids.add(pid)
    for pid in pids:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
    if pids:
        print(f"  Killed {label} (PID {', '.join(pids)})")


def kill_old_services() -> None:
    """Stop any services left over from a previous run."""
    print("Stopping any previously running services...")
    _kill_port(8000, "API")
    _kill_port(5173, "Dashboard")
    _kill_cmdline("run_heartbeat_scheduler", "Heartbeat")
    time.sleep(1)  # Give OS a moment to release ports


# ── Start helpers ─────────────────────────────────────────────────────────────

def start_background() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name, cmd, cwd in BG_SERVICES:
        log = LOG_DIR / f"{name}.log"
        subprocess.Popen(
            cmd,
            cwd=str(cwd),
            shell=True,
            stdout=open(log, "w"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"  {name:12} → logs/services/{name}.log")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Launch all agent services")
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Skip the interactive chat — just start background services and open browser",
    )
    args = parser.parse_args()

    kill_old_services()

    print("Starting background services...")
    start_background()

    print("Waiting for servers to start...")
    time.sleep(4)
    webbrowser.open("http://localhost:5173")

    if args.no_chat:
        print("Done. Dashboard: http://localhost:5173")
        print("Logs: logs/services/")
        return

    print(f"\nDashboard: http://localhost:5173")
    print("API, Dashboard, and Heartbeat running in the background.\n")
    print("─" * 60)
    print("Agent chat starting below. Type 'quit' or Ctrl+C to exit.")
    print("─" * 60 + "\n")

    # Run the interactive chat in the foreground of this terminal.
    # Background services are separate processes — they keep running after this exits.
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.agent.graph import run_local
    try:
        run_local(thread_id="main")
    except KeyboardInterrupt:
        pass

    print("\nChat ended. API / Dashboard / Heartbeat are still running in the background.")
    print("Logs: logs/services/api.log  dashboard.log  heartbeat.log")


if __name__ == "__main__":
    main()
