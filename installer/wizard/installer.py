"""
Silent installation runners for all dependencies.
Each function yields (message: str, progress: float 0-1) tuples so the UI
can display live progress without blocking.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Generator, Optional

# ── Helpers ───────────────────────────────────────────────────────────────────

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run_stream(cmd: list[str], timeout: int = 600) -> Generator[tuple[str, bool], None, None]:
    """Run a command and yield (line, is_error) as output arrives."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=_NO_WINDOW,
        )
        for line in proc.stdout:
            yield line.rstrip(), False
        proc.wait(timeout=timeout)
        if proc.returncode != 0:
            yield f"Process exited with code {proc.returncode}", True
    except FileNotFoundError as e:
        yield f"Command not found: {e}", True
    except Exception as e:
        yield f"Error: {e}", True


def _winget_install(package_id: str, display_name: str) -> Generator[tuple[str, float], None, None]:
    """Install a package via winget, yielding (message, progress) tuples."""
    yield f"Installing {display_name}...", 0.05
    cmd = [
        "winget", "install",
        "--id", package_id,
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    steps = 0
    for line, is_err in _run_stream(cmd, timeout=300):
        if line.strip():
            steps += 1
            progress = min(0.1 + steps * 0.03, 0.9)
            yield line, progress
    yield f"{display_name} installation complete.", 1.0


# ── Python ────────────────────────────────────────────────────────────────────

def install_python() -> Generator[tuple[str, float], None, None]:
    yield "Checking winget availability...", 0.02
    if not shutil.which("winget"):
        yield "ERROR: winget is not available. Please install Python 3.11 manually from https://python.org/downloads", 1.0
        return
    yield from _winget_install("Python.Python.3.11", "Python 3.11")
    yield "NOTE: You may need to restart the installer after Python installs.", 1.0


# ── Node.js ───────────────────────────────────────────────────────────────────

def install_node() -> Generator[tuple[str, float], None, None]:
    if not shutil.which("winget"):
        yield "ERROR: winget not available. Install Node.js 20 LTS from https://nodejs.org", 1.0
        return
    yield from _winget_install("OpenJS.NodeJS.LTS", "Node.js LTS")


# ── Git ───────────────────────────────────────────────────────────────────────

def install_git() -> Generator[tuple[str, float], None, None]:
    if not shutil.which("winget"):
        yield "ERROR: winget not available. Install Git from https://git-scm.com", 1.0
        return
    yield from _winget_install("Git.Git", "Git")


# ── Docker Desktop ────────────────────────────────────────────────────────────

def install_docker() -> Generator[tuple[str, float], None, None]:
    if not shutil.which("winget"):
        yield "ERROR: winget not available. Install Docker Desktop from https://docker.com/products/docker-desktop", 1.0
        return
    yield "Installing Docker Desktop — this may take several minutes...", 0.02
    yield from _winget_install("Docker.DockerDesktop", "Docker Desktop")
    yield "IMPORTANT: Docker Desktop requires a system restart to complete setup.", 1.0
    yield "After restarting, launch Docker Desktop and wait for it to say 'Docker Desktop is running', then re-run this installer.", 1.0


def wait_for_docker_daemon(timeout_seconds: int = 120) -> Generator[tuple[str, float], None, None]:
    """Wait for Docker daemon to become ready, yielding progress updates."""
    yield "Waiting for Docker daemon to start...", 0.0
    start = time.time()
    while time.time() - start < timeout_seconds:
        rc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            creationflags=_NO_WINDOW,
        ).returncode
        if rc == 0:
            yield "Docker daemon is running.", 1.0
            return
        elapsed = time.time() - start
        yield f"Waiting for Docker... ({int(elapsed)}s)", elapsed / timeout_seconds
        time.sleep(3)
    yield "ERROR: Docker daemon did not start within the timeout. Please start Docker Desktop manually.", 1.0


# ── Hindsight Docker image ────────────────────────────────────────────────────

HINDSIGHT_IMAGE = "ghcr.io/vectorize-io/hindsight:latest"
HINDSIGHT_CONTAINER = "hindsight"


def pull_hindsight_image() -> Generator[tuple[str, float], None, None]:
    """Pull the Hindsight Docker image, parsing layer progress."""
    yield f"Pulling {HINDSIGHT_IMAGE}...", 0.0
    yield "This step can take 30+ minutes on first run — your agent is NOT broken!", 0.01

    cmd = ["docker", "pull", HINDSIGHT_IMAGE]
    layer_totals: dict[str, int] = {}
    layer_done: dict[str, int] = {}

    for line, is_err in _run_stream(cmd, timeout=3600):
        if not line.strip():
            continue

        # Parse Docker pull output: "abc123: Downloading [===>  ]  50MB/200MB"
        layer_match = re.match(r"^([a-f0-9]+):\s+(\w+)", line)
        if layer_match:
            layer_id = layer_match.group(1)
            status = layer_match.group(2).lower()

            # Extract bytes if present
            bytes_match = re.search(r"([\d.]+)\s*[kKmMgG]?B\s*/\s*([\d.]+)\s*([kKmMgG]?)B", line)
            if bytes_match:
                def parse_size(val: str, unit: str) -> int:
                    n = float(val)
                    u = unit.upper()
                    if u == "K":
                        return int(n * 1024)
                    if u == "M":
                        return int(n * 1024 * 1024)
                    if u == "G":
                        return int(n * 1024 * 1024 * 1024)
                    return int(n)
                layer_done[layer_id] = parse_size(bytes_match.group(1), bytes_match.group(3))
                layer_totals[layer_id] = parse_size(bytes_match.group(2), bytes_match.group(3))

            if status in ("pull", "complete", "already"):
                layer_done[layer_id] = layer_totals.get(layer_id, 1)
                layer_totals[layer_id] = layer_totals.get(layer_id, 1)

        total_bytes = sum(layer_totals.values())
        done_bytes = sum(layer_done.values())
        progress = (done_bytes / total_bytes) if total_bytes > 0 else 0.0

        yield line, min(progress, 0.98)

    yield "Hindsight image downloaded successfully.", 1.0


def start_hindsight_container(
    llm_provider: str,
    llm_base_url: str,
    llm_model: str,
    llm_api_key: str,
    data_dir: Optional[str] = None,
) -> Generator[tuple[str, float], None, None]:
    """Start the Hindsight container with the given LLM configuration."""
    yield "Starting Hindsight container...", 0.1

    if data_dir is None:
        data_dir = str(Path.home() / ".hindsight-docker")
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    # Stop existing container if present
    subprocess.run(
        ["docker", "rm", "-f", HINDSIGHT_CONTAINER],
        capture_output=True,
        creationflags=_NO_WINDOW,
    )

    cmd = [
        "docker", "run", "-d",
        "--name", HINDSIGHT_CONTAINER,
        "--restart", "unless-stopped",
        "-p", "8888:8888",
        "-p", "9999:9999",
        "-e", f"HINDSIGHT_API_LLM_PROVIDER={llm_provider}",
        "-e", f"HINDSIGHT_API_LLM_BASE_URL={llm_base_url}",
        "-e", f"HINDSIGHT_API_LLM_MODEL={llm_model}",
        "-e", f"HINDSIGHT_API_LLM_API_KEY={llm_api_key}",
        "-v", f"{data_dir}:/home/hindsight/.pg0",
        HINDSIGHT_IMAGE,
    ]

    for line, is_err in _run_stream(cmd, timeout=60):
        yield line, 0.5

    yield "Hindsight container started. API: http://localhost:8888  UI: http://localhost:9999", 1.0


# ── PostgreSQL local setup ────────────────────────────────────────────────────

def install_postgres() -> Generator[tuple[str, float], None, None]:
    if not shutil.which("winget"):
        yield "ERROR: winget not available. Install PostgreSQL from https://postgresql.org/download/windows", 1.0
        return
    yield from _winget_install("PostgreSQL.PostgreSQL.16", "PostgreSQL 16")
    yield "PostgreSQL installed. You may need to set a password for the 'postgres' user.", 1.0


def start_postgres_service() -> Generator[tuple[str, float], None, None]:
    """Start the PostgreSQL Windows service."""
    yield "Starting PostgreSQL service...", 0.1

    # Try common service names
    for service_name in ["postgresql-x64-16", "postgresql-x64-15", "postgresql-x64-14", "postgresql"]:
        rc = subprocess.run(
            ["net", "start", service_name],
            capture_output=True,
            creationflags=_NO_WINDOW,
        ).returncode
        if rc == 0:
            yield f"PostgreSQL service '{service_name}' started.", 1.0
            return
        # Already running is also ok
        out = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            creationflags=_NO_WINDOW,
        ).stdout
        if "RUNNING" in out:
            yield f"PostgreSQL service '{service_name}' is already running.", 1.0
            return

    yield "Could not start PostgreSQL service automatically. Please start it manually via Services (services.msc).", 1.0


def install_pgvector(pg_bin_dir: Optional[str] = None) -> Generator[tuple[str, float], None, None]:
    """Download and install pgvector extension files for the detected PostgreSQL."""
    from .detector import detect_postgres

    yield "Detecting PostgreSQL installation...", 0.05

    if not pg_bin_dir:
        result = detect_postgres()
        if not result.found or not result.path:
            yield "ERROR: PostgreSQL not found. Install PostgreSQL first.", 1.0
            return
        pg_bin_dir = result.path

    bin_dir = Path(pg_bin_dir)
    pg_root = bin_dir.parent

    # Detect PG major version for the right pgvector release
    pg_ctl = bin_dir / "pg_ctl.exe"
    rc = subprocess.run([str(pg_ctl), "--version"], capture_output=True, text=True, creationflags=_NO_WINDOW)
    ver_match = re.search(r"(\d+)\.", rc.stdout)
    pg_major = ver_match.group(1) if ver_match else "16"

    yield f"Downloading pgvector for PostgreSQL {pg_major}...", 0.1

    # Download prebuilt Windows zip from pgvector releases
    # The zip contains lib/vector.dll and share/extension/vector.*
    zip_url = (
        f"https://github.com/pgvector/pgvector/releases/latest/download/"
        f"pgvector-pg{pg_major}-windows-x64.zip"
    )

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "pgvector.zip"
        try:
            yield f"Downloading from {zip_url}...", 0.2
            urllib.request.urlretrieve(zip_url, zip_path)
        except Exception as e:
            yield f"ERROR downloading pgvector: {e}", 1.0
            yield "Manual install: https://github.com/pgvector/pgvector#windows", 1.0
            return

        yield "Extracting pgvector files...", 0.6
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)

        # Copy files into PG installation
        extract_dir = Path(tmp)
        errors = []
        for src in extract_dir.rglob("vector.dll"):
            dest = pg_root / "lib" / "vector.dll"
            try:
                shutil.copy2(src, dest)
                yield f"Copied {src.name} -> {dest}", 0.75
            except Exception as e:
                errors.append(str(e))

        for src in extract_dir.rglob("vector.*"):
            if src.suffix in (".control", ".sql"):
                dest = pg_root / "share" / "extension" / src.name
                try:
                    shutil.copy2(src, dest)
                    yield f"Copied {src.name} -> {dest}", 0.85
                except Exception as e:
                    errors.append(str(e))

        if errors:
            yield f"WARNING: Some files could not be copied (may need admin rights): {'; '.join(errors)}", 0.9
        else:
            yield "pgvector files installed successfully.", 0.95

    yield "pgvector installation complete. The extension will be enabled when the database is created.", 1.0


def create_local_database(
    pg_bin_dir: str,
    db_name: str,
    pg_password: str,
    pg_user: str = "postgres",
    pg_port: int = 5432,
) -> Generator[tuple[str, float], None, None]:
    """Create a local PostgreSQL database and enable pgvector."""
    bin_dir = Path(pg_bin_dir)
    psql = bin_dir / "psql.exe"

    env = os.environ.copy()
    env["PGPASSWORD"] = pg_password

    yield f"Creating database '{db_name}'...", 0.1

    # Create database
    rc = subprocess.run(
        [str(psql), "-U", pg_user, "-p", str(pg_port), "-c", f"CREATE DATABASE \"{db_name}\";"],
        capture_output=True,
        text=True,
        env=env,
        creationflags=_NO_WINDOW,
    )
    stderr = rc.stderr.strip()
    if rc.returncode != 0 and "already exists" not in stderr:
        # FATAL means authentication failed or server unreachable — hard error
        if "FATAL" in stderr or "authentication failed" in stderr.lower() or "could not connect" in stderr.lower():
            yield f"ERROR: {stderr}", 0.3
            return
        yield f"WARNING: {stderr}", 0.3

    yield f"Enabling pgvector extension in '{db_name}'...", 0.5

    rc2 = subprocess.run(
        [str(psql), "-U", pg_user, "-p", str(pg_port), "-d", db_name, "-c", "CREATE EXTENSION IF NOT EXISTS vector;"],
        capture_output=True,
        text=True,
        env=env,
        creationflags=_NO_WINDOW,
    )
    if rc2.returncode != 0:
        stderr2 = rc2.stderr.strip()
        if "FATAL" in stderr2 or "authentication failed" in stderr2.lower():
            yield f"ERROR: {stderr2}", 0.8
            return
        yield f"WARNING: Could not enable pgvector: {stderr2}", 0.8
    else:
        yield "pgvector extension enabled.", 0.9

    # Verify the connection actually works using psql
    yield f"Verifying connection to '{db_name}'...", 0.95
    rc3 = subprocess.run(
        [str(psql), "-U", pg_user, "-p", str(pg_port), "-d", db_name, "-c", "SELECT 1;"],
        capture_output=True,
        text=True,
        env=env,
        creationflags=_NO_WINDOW,
    )
    if rc3.returncode != 0:
        yield f"ERROR: Could not connect to '{db_name}' after creation: {rc3.stderr.strip()}", 1.0
    else:
        yield f"Database '{db_name}' ready and verified.", 1.0


# ── Agent Python environment ──────────────────────────────────────────────────

def _find_system_python() -> Optional[str]:
    """
    Find the real system Python 3.11+ executable.
    When running as a frozen PyInstaller EXE, sys.executable points to the EXE
    itself — NOT to Python. We must search PATH and common install locations.
    """
    # If not frozen, sys.executable is the real Python
    if not getattr(sys, "frozen", False):
        return sys.executable

    # Search PATH for python / python3
    for name in ["python", "python3", "python3.12", "python3.11"]:
        path = shutil.which(name)
        if path:
            rc, out = subprocess.run(
                [path, "--version"], capture_output=True, text=True,
                creationflags=_NO_WINDOW,
            ).returncode, ""
            try:
                result = subprocess.run(
                    [path, "--version"], capture_output=True, text=True,
                    creationflags=_NO_WINDOW,
                )
                ver_match = re.search(r"3\.(\d+)", result.stdout + result.stderr)
                if ver_match and int(ver_match.group(1)) >= 11:
                    return path
            except Exception:
                continue

    # Check common Windows install locations
    for base in [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path("C:/Python312"),
        Path("C:/Python311"),
    ]:
        if not base.exists():
            continue
        for sub in sorted(base.glob("Python3*/python.exe"), reverse=True):
            return str(sub)
        if (base / "python.exe").exists():
            return str(base / "python.exe")

    return None


def create_venv(project_root: str) -> Generator[tuple[str, float], None, None]:
    """Create .venv in the project root."""
    venv_path = Path(project_root) / ".venv"
    yield f"Creating virtual environment at {venv_path}...", 0.05

    if venv_path.exists():
        yield "Virtual environment already exists, skipping creation.", 0.1
        return

    python = _find_system_python()
    if not python:
        yield "ERROR: Python 3.11+ not found on this system. Please install it from https://python.org and re-run the installer.", 1.0
        return

    yield f"Using Python: {python}", 0.08

    rc = subprocess.run(
        [python, "-m", "venv", str(venv_path)],
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )
    if rc.returncode != 0:
        yield f"ERROR creating venv: {rc.stderr}", 1.0
        return
    yield "Virtual environment created.", 0.2


def pip_install(project_root: str) -> Generator[tuple[str, float], None, None]:
    """Install requirements.txt into the project venv."""
    venv_path = Path(project_root) / ".venv"
    pip = venv_path / "Scripts" / "pip.exe"
    req_file = Path(project_root) / "requirements.txt"

    if not pip.exists():
        yield "ERROR: pip not found in venv. Virtual environment may be broken.", 1.0
        return
    if not req_file.exists():
        yield "ERROR: requirements.txt not found.", 1.0
        return

    yield "Installing Python packages (this may take a few minutes)...", 0.05
    cmd = [str(pip), "install", "-r", str(req_file), "--no-warn-script-location"]

    steps = 0
    total_estimate = 60  # rough estimate of packages
    for line, is_err in _run_stream(cmd, timeout=600):
        if line.strip():
            steps += 1
            progress = min(0.05 + (steps / total_estimate) * 0.9, 0.95)
            yield line, progress

    yield "Python packages installed.", 1.0


def npm_install(project_root: str) -> Generator[tuple[str, float], None, None]:
    """Run npm install in the dashboard directory."""
    dashboard_dir = Path(project_root) / "dashboard"
    if not dashboard_dir.exists():
        yield "Dashboard directory not found, skipping npm install.", 1.0
        return

    if not (dashboard_dir / "package.json").exists():
        yield f"ERROR: package.json not found in {dashboard_dir}. Check your install path.", 1.0
        return

    npm = shutil.which("npm")
    if not npm:
        yield "ERROR: npm not found. Install Node.js first.", 1.0
        return

    yield "Installing dashboard npm packages...", 0.05
    steps = 0
    # Run npm install from within the dashboard/ directory.
    # --legacy-peer-deps avoids conflicts from packages with strict peer dep declarations.
    proc = subprocess.Popen(
        [npm, "install", "--legacy-peer-deps"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(dashboard_dir),
        creationflags=_NO_WINDOW,
    )
    for line in proc.stdout:
        line = line.rstrip()
        if line.strip():
            steps += 1
            progress = min(0.05 + steps * 0.01, 0.95)
            yield line, progress
    proc.wait(timeout=300)
    if proc.returncode != 0:
        yield f"ERROR: npm install exited with code {proc.returncode}", 1.0
        return

    yield "Dashboard npm packages installed.", 1.0


def run_db_migration(
    project_root: str,
    venv_python: Optional[str] = None,
    database_url: Optional[str] = None,
) -> Generator[tuple[str, float], None, None]:
    """Run the living logs migration script."""
    if venv_python is None:
        venv_python = str(Path(project_root) / ".venv" / "Scripts" / "python.exe")

    migrate_script = Path(project_root) / "scripts" / "migrate_living_logs.py"
    if not migrate_script.exists():
        yield "Migration script not found, skipping.", 1.0
        return

    # Pass DATABASE_URL explicitly so the script doesn't fall back to a default
    env = os.environ.copy()
    if database_url:
        env["DATABASE_URL"] = database_url

    yield "Running database migration (migrate_living_logs)...", 0.1
    try:
        proc = subprocess.Popen(
            [venv_python, str(migrate_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(project_root),
            creationflags=_NO_WINDOW,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line.strip():
                yield line, 0.5
        proc.wait(timeout=60)
        if proc.returncode != 0:
            yield f"ERROR: Migration exited with code {proc.returncode}", 1.0
            return
    except Exception as e:
        yield f"ERROR: Migration failed: {e}", 1.0
        return

    yield "Database migration complete.", 1.0
