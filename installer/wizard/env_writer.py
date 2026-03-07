"""
Writes the .env file from collected installer values.
Reads .env.example as a template and substitutes user-provided values,
preserving all comments and structure.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def write_env(project_root: str, values: dict[str, Any]) -> None:
    """
    Write a .env file to `project_root/.env`.

    `values` is a flat dict mapping env var names to their string values.
    Keys with empty-string values are written as KEY= (blank, not commented out).
    Keys not in `values` are left as they appear in .env.example.
    """
    project_path = Path(project_root)
    example_path = project_path / ".env.example"
    env_path = project_path / ".env"

    if example_path.exists():
        template = example_path.read_text(encoding="utf-8")
    else:
        template = ""

    output_lines: list[str] = []

    # Track which keys we've written so we can append any extras at the end
    written_keys: set[str] = set()

    for line in template.splitlines():
        stripped = line.strip()

        # Comment or blank line — keep as-is
        if not stripped or stripped.startswith("#"):
            output_lines.append(line)
            continue

        # Match KEY=value or KEY= lines (not commented-out)
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", stripped)
        if m:
            key = m.group(1)
            written_keys.add(key)
            if key in values and values[key] is not None:
                val = str(values[key]).strip()
                output_lines.append(f"{key}={val}")
            else:
                # Keep original line unchanged
                output_lines.append(line)
        else:
            output_lines.append(line)

    # Append any extra keys from `values` that weren't in the template
    extras = {k: v for k, v in values.items() if k not in written_keys and v}
    if extras:
        output_lines.append("")
        output_lines.append("# Additional settings configured during install")
        for key, val in extras.items():
            output_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")


def read_env(project_root: str) -> dict[str, str]:
    """Read an existing .env file and return a dict of key->value pairs."""
    env_path = Path(project_root) / ".env"
    result: dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", stripped)
        if m:
            result[m.group(1)] = m.group(2)
    return result


def test_database_connection(database_url: str) -> tuple[bool, str]:
    """
    Test a PostgreSQL connection string.
    Returns (success, message).
    """
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                row = cur.fetchone()
                version = row[0] if row else "unknown"
        return True, f"Connected successfully. {version[:60]}"
    except ImportError:
        return False, "psycopg not installed yet — connection will be verified after package install."
    except Exception as e:
        return False, f"Connection failed: {e}"
