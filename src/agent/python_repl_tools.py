"""
Python REPL tool: execute Python code in an isolated subprocess.

Runs in a child process so it cannot affect the agent's main process.
The agent's virtual environment is available, so any installed package works.

Env vars:
  CODE_EXEC_TIMEOUT   — max seconds per execution (default: 30)
  CODE_EXEC_WORKDIR   — working directory for scripts (default: project root)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TIMEOUT = int(os.environ.get("CODE_EXEC_TIMEOUT", "30"))
_WORKDIR = os.environ.get("CODE_EXEC_WORKDIR", str(_PROJECT_ROOT))


@tool
def python_repl(code: str) -> str:
    """
    Execute Python code and return the output.

    Use for calculations, data processing, generating files, reading CSVs,
    creating charts, running scripts, or any task that needs actual computation.
    Use print() to produce output — return values alone are not shown.

    The agent's virtual environment is active, so all installed packages work.
    Working directory is the project root. Runs in an isolated subprocess.

    Args:
        code: Valid Python code to execute. Use print() for output.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            cwd=_WORKDIR,
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"[stderr]\n{result.stderr.strip()}")
        if result.returncode != 0 and not parts:
            parts.append(f"[exit code {result.returncode}]")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: execution timed out after {_TIMEOUT}s. Use CODE_EXEC_TIMEOUT env var to increase."
    except Exception as e:
        return f"Error: {e}"
