"""
Build the dashboard and start the API (serves dashboard + API from port 8000).
Use with ngrok for public access: run 'ngrok http 8000' in another terminal.

The API serves the built dashboard at / and API at /api. One ngrok tunnel to 8000
exposes everything. Kills any existing API or dev dashboard on 8000/5173 first.

Usage:
    python scripts/start_public_dashboard.py     # build + start API
    # In another terminal: ngrok http 8000
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
DIST_DIR = DASHBOARD_DIR / "dist"


def _kill_port(port: int, label: str) -> None:
    """Kill any process currently listening on the given TCP port."""
    result = subprocess.run(
        f'netstat -ano | findstr ":{port} "',
        shell=True,
        capture_output=True,
        text=True,
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and f":{port}" in parts[1]:
            pid = parts[-1]
            if pid.isdigit() and int(pid) > 4:
                pids.add(pid)
    for pid in pids:
        subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
    if pids:
        print(f"  Killed {label} (port {port}, PID {', '.join(pids)})")


def kill_old_services() -> None:
    """Stop any API or dev dashboard left over from a previous run."""
    print("Stopping any previously running services...")
    _kill_port(8000, "API")
    _kill_port(5173, "Dashboard (Vite dev)")
    time.sleep(1)


def main() -> None:
    kill_old_services()

    print("Building dashboard...")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=DASHBOARD_DIR,
        shell=True,
    )
    if result.returncode != 0:
        print("Dashboard build failed. Fix errors above and try again.")
        sys.exit(1)

    print("Dashboard built. Starting API (serves dashboard + API on port 8000)...")
    print("For public access, run in another terminal: ngrok http 8000")
    print()
    subprocess.run(
        [sys.executable, "-m", "src.agent.api"],
        cwd=PROJECT_ROOT,
    )


if __name__ == "__main__":
    main()
