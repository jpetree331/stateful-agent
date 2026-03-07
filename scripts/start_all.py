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
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable  # Inherits the venv Python from whichever Python runs this
LOG_DIR = PROJECT_ROOT / "logs" / "services"

_DEFAULT_DASHBOARD_PORT = 5173
_API_PORT = 8000


def _find_free_port(start: int, end: int = 65535) -> int:
    """Return the first TCP port in [start, end] that is not in use."""
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found between {start} and {end}")


# ── Kill helpers ──────────────────────────────────────────────────────────────


def _kill_port(port: int, label: str) -> None:
    """Kill any process currently listening on the given TCP port (IPv4 and IPv6)."""
    result = subprocess.run(
        f"netstat -ano",
        shell=True,
        capture_output=True,
        text=True,
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        # netstat columns: Proto  Local  Foreign  State  PID
        # Match ":PORT" at end of local address field (handles IPv4 and IPv6)
        if len(parts) >= 5 and parts[3] == "LISTENING":
            local = parts[1]
            if local.endswith(f":{port}"):
                pid = parts[4]
                if pid.isdigit() and int(pid) > 4:
                    pids.add(pid)
    for pid in pids:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
    if pids:
        print(f"  Killed {label} (port {port}, PID {', '.join(pids)})")


def _kill_cmdline(fragment: str, label: str) -> None:
    """Kill python.exe processes whose command line contains `fragment`."""
    result = subprocess.run(
        [
            "wmic",
            "process",
            "where",
            f"name='python.exe' and commandline like '%{fragment}%'",
            "get",
            "processid",
            "/format:value",
        ],
        capture_output=True,
        text=True,
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


def kill_old_services(dashboard_port: int) -> None:
    """Stop any services left over from a previous run."""
    print("Stopping any previously running services...")
    _kill_port(_API_PORT, "API")
    _kill_port(dashboard_port, "Dashboard")
    _kill_cmdline("run_heartbeat_scheduler", "Heartbeat")
    time.sleep(1)  # Give OS a moment to release ports


# ── Start helpers ─────────────────────────────────────────────────────────────


def start_background(dashboard_port: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    bg_services = [
        ("api",       f'"{PYTHON}" -m src.agent.api',                           PROJECT_ROOT),
        ("dashboard", f"npm run dev -- --port {dashboard_port}",                PROJECT_ROOT / "dashboard"),
        ("heartbeat", f'"{PYTHON}" -m scripts.run_heartbeat_scheduler',         PROJECT_ROOT),
    ]
    for name, cmd, cwd in bg_services:
        log = LOG_DIR / f"{name}.log"
        subprocess.Popen(
            cmd,
            cwd=str(cwd),
            shell=True,
            stdout=open(log, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"  {name:12} → logs/services/{name}.log")


# ── Main ──────────────────────────────────────────────────────────────────────


def _get_lan_ip() -> str:
    """Return the machine's LAN IP address (best-effort)."""
    try:
        # Connect to an external address to discover the outbound interface IP.
        # No data is actually sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Launch all agent services")
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Skip the interactive chat — just start background services and open browser",
    )
    args = parser.parse_args()

    # Find a free dashboard port starting at 5173 so multiple agents can run
    # side-by-side without overwriting each other's dashboard.
    dashboard_port = _find_free_port(_DEFAULT_DASHBOARD_PORT)
    if dashboard_port != _DEFAULT_DASHBOARD_PORT:
        print(f"Port {_DEFAULT_DASHBOARD_PORT} is in use — using port {dashboard_port} for this agent's dashboard.")

    kill_old_services(dashboard_port)

    print("Starting background services...")
    start_background(dashboard_port)

    lan_ip = _get_lan_ip()
    dashboard_local   = f"http://localhost:{dashboard_port}"
    dashboard_network = f"http://{lan_ip}:{dashboard_port}" if lan_ip != "unknown" else None

    print("Waiting for servers to start (API can take ~10s to load agent)...")
    time.sleep(5)
    webbrowser.open(dashboard_local)

    if args.no_chat:
        print("Done.")
        print(f"  Local:   {dashboard_local}")
        if dashboard_network:
            print(f"  Network: {dashboard_network}  (share this with devices on the same WiFi)")
        print("Logs: logs/services/")
        return

    print(f"\nDashboard:")
    print(f"  Local:   {dashboard_local}")
    if dashboard_network:
        print(f"  Network: {dashboard_network}  ← share this with other devices on the same WiFi/LAN")
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

    print(
        "\nChat ended. API / Dashboard / Heartbeat are still running in the background."
    )
    print("Logs: logs/services/api.log  dashboard.log  heartbeat.log")


if __name__ == "__main__":
    main()
