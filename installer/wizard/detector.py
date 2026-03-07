"""
System state detection for the installer.
All functions return DetectResult namedtuples so the UI can display status cleanly.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


@dataclass
class DetectResult:
    found: bool
    version: Optional[str] = None
    path: Optional[str] = None
    note: Optional[str] = None


# ── Disk space ────────────────────────────────────────────────────────────────

def check_disk_space(path: str, min_gb: float = 10.0) -> tuple[bool, float]:
    """Return (ok, free_gb) for the drive containing `path`."""
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= min_gb, free_gb
    except Exception:
        return True, 0.0  # assume ok if we can't check


# ── Generic helpers ───────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


def _parse_version(text: str) -> Optional[str]:
    """Extract first x.y.z version string from text."""
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
    return m.group(1) if m else None


# ── Python ────────────────────────────────────────────────────────────────────

def detect_python() -> DetectResult:
    """Detect Python 3.11+ on PATH or common Windows locations."""
    candidates = ["python", "python3", "python3.11", "python3.12", "python3.13"]
    for cmd in candidates:
        path = shutil.which(cmd)
        if path:
            rc, out = _run([cmd, "--version"])
            if rc == 0:
                ver = _parse_version(out)
                if ver:
                    parts = ver.split(".")
                    major, minor = int(parts[0]), int(parts[1])
                    if major == 3 and minor >= 11:
                        return DetectResult(found=True, version=ver, path=path)
                    else:
                        return DetectResult(
                            found=False,
                            version=ver,
                            path=path,
                            note=f"Python {ver} found but 3.11+ required",
                        )

    # Check common Windows install paths
    for base in [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path("C:/Python311"),
        Path("C:/Python312"),
    ]:
        for sub in (base.glob("Python3*/python.exe") if base.exists() else []):
            rc, out = _run([str(sub), "--version"])
            if rc == 0:
                ver = _parse_version(out)
                if ver:
                    parts = ver.split(".")
                    major, minor = int(parts[0]), int(parts[1])
                    if major == 3 and minor >= 11:
                        return DetectResult(found=True, version=ver, path=str(sub))

    return DetectResult(found=False, note="Python 3.11+ not found")


# ── Node.js ───────────────────────────────────────────────────────────────────

def detect_node() -> DetectResult:
    path = shutil.which("node")
    if not path:
        return DetectResult(found=False, note="Node.js not found")
    rc, out = _run(["node", "--version"])
    if rc != 0:
        return DetectResult(found=False, note="node found but failed to run")
    ver = _parse_version(out)
    if ver:
        major = int(ver.split(".")[0])
        if major >= 18:
            return DetectResult(found=True, version=ver, path=path)
        return DetectResult(
            found=False,
            version=ver,
            path=path,
            note=f"Node {ver} found but 18+ required",
        )
    return DetectResult(found=False, note="Could not parse Node version")


# ── Git ───────────────────────────────────────────────────────────────────────

def detect_git() -> DetectResult:
    path = shutil.which("git")
    if not path:
        return DetectResult(found=False, note="Git not found")
    rc, out = _run(["git", "--version"])
    ver = _parse_version(out) if rc == 0 else None
    return DetectResult(found=rc == 0, version=ver, path=path)


# ── Docker ────────────────────────────────────────────────────────────────────

def detect_docker() -> DetectResult:
    """Detect Docker and whether the daemon is running."""
    path = shutil.which("docker")
    if not path:
        # Check common Windows install location
        default = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
        if default.exists():
            path = str(default)
        else:
            return DetectResult(found=False, note="Docker Desktop not found")

    rc, out = _run(["docker", "--version"])
    if rc != 0:
        return DetectResult(found=False, note="docker binary found but failed to run")

    ver = _parse_version(out)

    # Check if daemon is running
    rc2, _ = _run(["docker", "info"], timeout=8)
    if rc2 != 0:
        return DetectResult(
            found=True,
            version=ver,
            path=path,
            note="Docker installed but daemon is not running — please start Docker Desktop",
        )

    return DetectResult(found=True, version=ver, path=path)


# ── PostgreSQL ────────────────────────────────────────────────────────────────

def _find_pg_bin() -> Optional[Path]:
    """Find the PostgreSQL bin directory."""
    # Check PATH first
    if shutil.which("pg_ctl"):
        return Path(shutil.which("pg_ctl")).parent

    # Scan common Windows install paths
    pg_root = Path("C:/Program Files/PostgreSQL")
    if pg_root.exists():
        versions = sorted(pg_root.iterdir(), reverse=True)
        for v in versions:
            bin_dir = v / "bin"
            if (bin_dir / "pg_ctl.exe").exists():
                return bin_dir

    return None


def detect_postgres() -> DetectResult:
    bin_dir = _find_pg_bin()
    if not bin_dir:
        return DetectResult(found=False, note="PostgreSQL not found")

    pg_ctl = bin_dir / "pg_ctl.exe" if sys.platform == "win32" else bin_dir / "pg_ctl"
    rc, out = _run([str(pg_ctl), "--version"])
    ver = _parse_version(out) if rc == 0 else None

    # Check if service is running
    rc2, _ = _run(["pg_isready", "-q"] if shutil.which("pg_isready") else [str(bin_dir / "pg_isready"), "-q"])
    running = rc2 == 0

    note = None if running else "PostgreSQL installed but not running"
    return DetectResult(found=True, version=ver, path=str(bin_dir), note=note)


def detect_pgvector(pg_bin_dir: Optional[str] = None) -> DetectResult:
    """Check if pgvector extension files exist in the PostgreSQL installation."""
    if pg_bin_dir:
        bin_dir = Path(pg_bin_dir)
    else:
        result = detect_postgres()
        if not result.found or not result.path:
            return DetectResult(found=False, note="PostgreSQL not found; cannot check pgvector")
        bin_dir = Path(result.path)

    pg_root = bin_dir.parent
    # pgvector installs vector.so in lib/ and vector.control in share/extension/
    lib_file = pg_root / "lib" / "vector.dll"
    control_file = pg_root / "share" / "extension" / "vector.control"
    alt_lib = pg_root / "lib" / "vector.so"

    if (lib_file.exists() or alt_lib.exists()) and control_file.exists():
        return DetectResult(found=True, note="pgvector extension files present")

    return DetectResult(found=False, note="pgvector extension not installed")


# ── Hindsight Docker container ────────────────────────────────────────────────

class HindsightState(Enum):
    NOT_INSTALLED = "not_installed"      # image not pulled
    IMAGE_ONLY = "image_only"           # image exists but container not running
    RUNNING = "running"                  # container up and API responding
    CONTAINER_STOPPED = "container_stopped"  # container exists but stopped


_HINDSIGHT_IMAGE = "ghcr.io/vectorize-io/hindsight:latest"
_HINDSIGHT_CONTAINER = "hindsight"


def detect_hindsight() -> tuple[HindsightState, str]:
    """
    Detect Hindsight state.
    Returns (HindsightState, message) — message is a human-readable status line.
    """
    HINDSIGHT_IMAGE = _HINDSIGHT_IMAGE
    HINDSIGHT_CONTAINER = _HINDSIGHT_CONTAINER

    # Is Docker even available?
    rc_info, _ = _run(["docker", "info"], timeout=8)
    if rc_info != 0:
        return HindsightState.NOT_INSTALLED, "Docker daemon not running — cannot check Hindsight"

    # Check if image exists locally
    rc_img, out_img = _run(
        ["docker", "image", "inspect", HINDSIGHT_IMAGE, "--format", "{{.Id}}"],
        timeout=10,
    )
    image_present = rc_img == 0 and bool(out_img.strip())

    # Check container state
    rc_ctr, out_ctr = _run(
        ["docker", "inspect", HINDSIGHT_CONTAINER, "--format", "{{.State.Status}}"],
        timeout=10,
    )
    container_exists = rc_ctr == 0
    container_running = container_exists and out_ctr.strip() == "running"

    if container_running:
        # Verify the API actually responds
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:8888", timeout=4)
            return HindsightState.RUNNING, "Hindsight container is running and API is reachable"
        except Exception:
            return HindsightState.RUNNING, "Hindsight container is running (API not yet responding)"

    if container_exists and not container_running:
        return HindsightState.CONTAINER_STOPPED, f"Hindsight container exists but is stopped (status: {out_ctr.strip()})"

    if image_present:
        return HindsightState.IMAGE_ONLY, "Hindsight image is downloaded but container has not been started"

    return HindsightState.NOT_INSTALLED, "Hindsight image not found — needs to be downloaded"


# ── winget ────────────────────────────────────────────────────────────────────

def detect_winget() -> DetectResult:
    path = shutil.which("winget")
    if not path:
        return DetectResult(found=False, note="winget not available (Windows 10 1709+ required)")
    rc, out = _run(["winget", "--version"])
    ver = _parse_version(out) if rc == 0 else None
    return DetectResult(found=rc == 0, version=ver, path=path)


# ── npm ───────────────────────────────────────────────────────────────────────

def detect_npm() -> DetectResult:
    path = shutil.which("npm")
    if not path:
        return DetectResult(found=False, note="npm not found")
    rc, out = _run(["npm", "--version"])
    ver = _parse_version(out) if rc == 0 else None
    return DetectResult(found=rc == 0, version=ver, path=path)


# ── All-at-once snapshot ──────────────────────────────────────────────────────

@dataclass
class SystemSnapshot:
    python: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    node: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    npm: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    git: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    docker: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    postgres: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    pgvector: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    winget: DetectResult = field(default_factory=lambda: DetectResult(found=False))
    disk_ok: bool = True
    disk_free_gb: float = 0.0


def scan_system(install_path: str = "C:/") -> SystemSnapshot:
    disk_ok, free_gb = check_disk_space(install_path)
    snap = SystemSnapshot(disk_ok=disk_ok, disk_free_gb=free_gb)
    snap.winget = detect_winget()
    snap.python = detect_python()
    snap.node = detect_node()
    snap.npm = detect_npm()
    snap.git = detect_git()
    snap.docker = detect_docker()
    snap.postgres = detect_postgres()
    if snap.postgres.found:
        snap.pgvector = detect_pgvector(snap.postgres.path)
    return snap
