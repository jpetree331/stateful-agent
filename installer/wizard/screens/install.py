"""
Final installation screen.
Runs all install steps with per-step progress bars and a live log.
Offers to launch the agent when done.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from ..installer import create_venv, pip_install, npm_install, run_db_migration, create_local_database
from ..env_writer import write_env
from ..screens.database import DatabaseConfig
from ..screens.hindsight import HindsightConfig
from ..screens.env_config import EnvConfig
from ..theme import (
    FONT_HEADING, FONT_BODY, FONT_SMALL,
    COLOR_BG, COLOR_CARD, COLOR_BLUE, COLOR_GREEN, COLOR_RED, COLOR_YELLOW,
    COLOR_TEXT, COLOR_MUTED,
    BodyLabel, MutedLabel, PrimaryButton, SecondaryButton, SectionLabel,
    LogBox, ProgressRow,
)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class InstallScreen(ctk.CTkFrame):
    """
    Screen 6 (final): Runs all installation steps and shows progress.
    """

    def __init__(self, master,
                 on_back: Callable[[], None],
                 install_path: str,
                 db_config: DatabaseConfig,
                 hindsight_config: HindsightConfig,
                 env_config: EnvConfig,
                 **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._on_back = on_back
        self._install_path = install_path
        self._db_config = db_config
        self._hindsight_config = hindsight_config
        self._env_config = env_config
        self._running = False
        self._done = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Installing Agent", font=FONT_HEADING,
                     text_color=COLOR_BLUE).grid(row=0, column=0, padx=32, pady=(20, 4), sticky="w")
        BodyLabel(
            header,
            text="The installer is setting up your agent. This may take several minutes.",
        ).grid(row=1, column=0, padx=32, pady=(0, 16), sticky="w")

        # Steps
        steps_frame = ctk.CTkFrame(self, fg_color="transparent")
        steps_frame.grid(row=1, column=0, sticky="nsew", padx=32, pady=16)
        steps_frame.columnconfigure(0, weight=1)

        self._steps: dict[str, ProgressRow] = {}
        step_defs = [
            ("env",     "Write .env configuration file"),
            ("venv",    "Create Python virtual environment"),
            ("pip",     "Install Python packages"),
            ("npm",     "Install dashboard packages (npm)"),
            ("db",      "Set up database"),
            ("migrate", "Run database migrations"),
            ("memory",  "Seed initial memory & heartbeat config"),
        ]
        for i, (step_id, label) in enumerate(step_defs):
            row = ProgressRow(steps_frame, label)
            row.grid(row=i, column=0, sticky="ew", pady=4)
            self._steps[step_id] = row

        # Log
        self._log = LogBox(self, height=180)
        self._log.grid(row=2, column=0, sticky="ew", padx=32, pady=(0, 8))

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 24))
        footer.columnconfigure(1, weight=1)

        self._back_btn = SecondaryButton(footer, text="← Back", width=100, command=self._on_back)
        self._back_btn.grid(row=0, column=0, sticky="w")

        self._status_label = ctk.CTkLabel(footer, text="Ready to install.", font=FONT_SMALL,
                                          text_color=COLOR_MUTED, anchor="w")
        self._status_label.grid(row=0, column=1, padx=16, sticky="w")

        self._install_btn = PrimaryButton(
            footer, text="Install Now", width=160, command=self._start_install
        )
        self._install_btn.grid(row=0, column=2, sticky="e")

        self._launch_btn = PrimaryButton(
            footer, text="Launch Agent  →", width=180, command=self._launch_agent,
            state="disabled"
        )
        self._launch_btn.grid(row=0, column=3, sticky="e", padx=(8, 0))

    def _start_install(self) -> None:
        if self._running:
            return
        self._running = True
        self._install_btn.configure(state="disabled", text="Installing…")
        self._back_btn.configure(state="disabled")
        threading.Thread(target=self._run_install, daemon=True).start()

    def _run_install(self) -> None:
        project = self._install_path
        success = True

        # Sanity-check the install path before doing anything
        from pathlib import Path as _Path
        if not (_Path(project) / "requirements.txt").exists():
            self._log_line(f"ERROR: requirements.txt not found in: {project}")
            self._log_line("This doesn't look like the agent's project folder.")
            self._log_line("Go back to the Welcome screen and select the correct folder.")
            for step_id in self._steps:
                self._set_step_done(step_id, ok=False)
            self.after(0, lambda: (
                self._status_label.configure(
                    text="Wrong install folder — go back and fix the path.",
                    text_color=COLOR_RED,
                ),
                self._install_btn.configure(text="Retry", state="normal"),
                self._back_btn.configure(state="normal"),
            ))
            self._running = False
            return

        # ── Step 1: Write .env ────────────────────────────────────────────────
        self._set_step("env", 0.1, "Writing…")
        try:
            write_env(project, self._env_config.values)
            self._set_step_done("env", ok=True)
            self._log_line("✓ .env file written.")
        except Exception as e:
            self._set_step_done("env", ok=False)
            self._log_line(f"ERROR writing .env: {e}")
            success = False

        # ── Step 2: Create venv ───────────────────────────────────────────────
        self._set_step("venv", 0.1, "Creating…")
        venv_ok = True
        for msg, progress in create_venv(project):
            self._log_line(msg)
            self._set_step("venv", progress, "")
            if "ERROR" in msg.upper():
                venv_ok = False
        self._set_step_done("venv", ok=venv_ok)
        if not venv_ok:
            success = False

        # ── Step 3: pip install ───────────────────────────────────────────────
        self._set_step("pip", 0.05, "Installing packages…")
        pip_ok = True
        for msg, progress in pip_install(project):
            self._log_line(msg)
            self._set_step("pip", progress, "")
            if "ERROR" in msg.upper():
                pip_ok = False
        self._set_step_done("pip", ok=pip_ok)
        if not pip_ok:
            success = False

        # ── Step 4: npm install ───────────────────────────────────────────────
        self._set_step("npm", 0.05, "Installing npm packages…")
        npm_ok = True
        for msg, progress in npm_install(project):
            self._log_line(msg)
            self._set_step("npm", progress, "")
            if "ERROR" in msg.upper():
                npm_ok = False
        self._set_step_done("npm", ok=npm_ok)

        # ── Step 5: Local DB setup (if local mode) ────────────────────────────
        self._set_step("db", 0.1, "Setting up database…")
        db_ok = True
        if self._db_config.mode == "local" and self._db_config.pg_password:
            from ..detector import detect_postgres
            pg = detect_postgres()
            if pg.found and pg.path:
                for db_name in [self._db_config.db_name, self._db_config.kb_name]:
                    for msg, progress in create_local_database(
                        pg.path,
                        db_name,
                        self._db_config.pg_password,
                        pg_port=self._db_config.pg_port,
                    ):
                        self._log_line(msg)
                        self._set_step("db", progress, "")
                        if "ERROR" in msg.upper():
                            db_ok = False
            else:
                self._log_line("WARNING: PostgreSQL not found for local DB setup. Skipping.")
        elif self._db_config.mode == "local" and not self._db_config.pg_password:
            self._log_line("WARNING: No PostgreSQL password provided — skipping local DB creation.")
            self._log_line("Go back to the Database screen and enter your postgres password.")
            db_ok = False
        else:
            self._log_line("Using cloud/Railway database — no local DB setup needed.")
        self._set_step_done("db", ok=db_ok)
        if not db_ok:
            success = False

        # ── Step 6: DB migration ──────────────────────────────────────────────
        # Creates Living Logs tables (tension_log, loose_threads, etc.).
        # Only run for LOCAL mode where we just set up the DB and know it's
        # reachable with the credentials we have. For Railway/cloud, the agent's
        # db.py calls setup_schema() on first startup, which handles this.
        self._set_step("migrate", 0.1, "Running migrations…")
        migrate_ok = True
        venv_python = str(Path(project) / ".venv" / "Scripts" / "python.exe")

        is_local_mode = (self._db_config.mode == "local")

        if not pip_ok:
            self._log_line("Skipping migration — Python packages did not install successfully.")
            self._set_step_done("migrate", ok=True)
        elif not Path(venv_python).exists():
            self._log_line("Skipping migration — venv Python not found.")
            self._set_step_done("migrate", ok=True)
        elif not is_local_mode:
            self._log_line("Skipping migration — using cloud database. The agent will run migrations automatically on first start.")
            self._set_step_done("migrate", ok=True)
        elif not db_ok:
            self._log_line("Skipping migration — local database setup did not complete successfully.")
            self._set_step_done("migrate", ok=True)
        else:
            # Build the DATABASE_URL from what we just created so migration uses the right DB
            _db_url = (
                f"postgresql://postgres:"
                f"{self._db_config.pg_password}@localhost:"
                f"{self._db_config.pg_port or 5432}/{self._db_config.db_name}"
            )
            for msg, progress in run_db_migration(project, venv_python, database_url=_db_url):
                self._log_line(msg)
                self._set_step("migrate", progress, "")
                if "ERROR" in msg.upper():
                    migrate_ok = False
            self._set_step_done("migrate", ok=migrate_ok)
            if not migrate_ok:
                success = False

        # ── Step 7: Seed memory blocks + heartbeat config ─────────────────────
        self._set_step("memory", 0.1, "Seeding…")
        memory_ok = True
        try:
            import json as _json
            from datetime import date as _date

            # Write heartbeat_config.json with user's chosen interval
            interval_str = self._env_config.values.get("HEARTBEAT_INTERVAL_MINUTES", "60")
            try:
                interval_val = int(interval_str)
            except ValueError:
                interval_val = 60
            heartbeat_enabled = self._env_config.values.get("HEARTBEAT_ENABLED", "true") == "true"
            hb_config = {
                "wonder_start": 22,
                "wonder_end": 3,
                "work_start": 3,
                "work_end": 6,
                "day_interval": interval_val,
                "night_interval": max(interval_val, 60),
                "enabled": heartbeat_enabled,
            }
            data_dir = Path(project) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "heartbeat_config.json").write_text(
                _json.dumps(hb_config, indent=2), encoding="utf-8"
            )
            status = "enabled" if heartbeat_enabled else "disabled"
            self._log_line(f"Heartbeat config written ({status}, every {interval_val} min).")
            self._set_step("memory", 0.3, "")

            # Seed core memory blocks from examples/memory/ if DB is ready
            if db_ok and pip_ok and Path(venv_python).exists():
                examples_dir = Path(project) / "examples" / "memory"
                block_files = {
                    "identity":   "IDENTITY.txt",
                    "user":       "USER.txt",
                    "ideaspace":  "IDEASPACE.txt",
                    "principles": "PRINCIPLES.txt",
                }
                sysinstruct_file = examples_dir / "SYSINSTRUCT_EXAMPLE.txt"

                seed_script = _build_memory_seed_script(
                    block_files={k: str(examples_dir / v) for k, v in block_files.items()},
                    sysinstruct_path=str(sysinstruct_file) if sysinstruct_file.exists() else None,
                    today=str(_date.today()),
                )
                seed_path = Path(project) / "data" / "_installer_seed_memory.py"
                seed_path.write_text(seed_script, encoding="utf-8")

                _db_url = (
                    f"postgresql://postgres:{self._db_config.pg_password}@localhost:"
                    f"{self._db_config.pg_port or 5432}/{self._db_config.db_name}"
                    if self._db_config.mode == "local"
                    else self._db_config.database_url
                )
                import os as _os
                env = _os.environ.copy()
                env["DATABASE_URL"] = _db_url

                proc = subprocess.run(
                    [venv_python, str(seed_path)],
                    capture_output=True, text=True, env=env,
                    cwd=project, creationflags=_NO_WINDOW,
                )
                if proc.returncode == 0:
                    self._log_line("Core memory blocks seeded from examples/memory/.")
                    self._log_line("System instructions loaded from SYSINSTRUCT_EXAMPLE.txt.")
                else:
                    self._log_line(f"WARNING: Memory seed returned code {proc.returncode}: {proc.stderr.strip()[:200]}")
                seed_path.unlink(missing_ok=True)
            else:
                self._log_line("Skipping memory seed — DB not ready (will use blank defaults).")

            self._set_step("memory", 1.0, "")
        except Exception as e:
            self._log_line(f"WARNING: Memory/heartbeat setup error: {e}")
            memory_ok = False
        self._set_step_done("memory", ok=memory_ok)

        # ── Done ──────────────────────────────────────────────────────────────
        self._running = False
        self._done = True

        if success:
            self._log_line("")
            self._log_line("=" * 56)
            self._log_line("NEXT STEPS — please read before launching:")
            self._log_line("")
            self._log_line("1. SYSTEM INSTRUCTIONS are pre-loaded from")
            self._log_line("   examples/memory/SYSINSTRUCT_EXAMPLE.txt.")
            self._log_line("   Review and personalise them in the dashboard")
            self._log_line("   Core tab once the agent is running.")
            self._log_line("")
            self._log_line("2. SET UP 3 CRON JOBS in the dashboard Cron tab")
            self._log_line("   for memory maintenance (copy prompts from")
            self._log_line("   examples/CRON_JOBS_EXAMPLE.md):")
            self._log_line("   - daily_summary     55 23 * * *  (11:55 PM daily)")
            self._log_line("   - weekly_synthesis_phase1  0 1 * * 0  (Sun 1 AM)")
            self._log_line("   - weekly_synthesis_phase2  0 2 * * 0  (Sun 2 AM)")
            self._log_line("")
            self._log_line("   Without these, the agent cannot maintain its")
            self._log_line("   long-term memory or do weekly self-reflection.")
            self._log_line("=" * 56)
            self.after(0, lambda: (
                self._status_label.configure(
                    text="Installation complete! Click 'Launch Agent' to start.",
                    text_color=COLOR_GREEN,
                ),
                self._launch_btn.configure(state="normal"),
                self._install_btn.configure(text="Reinstall", state="normal"),
            ))
        else:
            self.after(0, lambda: (
                self._status_label.configure(
                    text="Some steps had errors. Check the log above. You can retry or continue.",
                    text_color=COLOR_YELLOW,
                ),
                self._install_btn.configure(text="Retry", state="normal"),
                self._launch_btn.configure(state="normal"),
            ))

    def _set_step(self, step_id: str, progress: float, status: str) -> None:
        self.after(0, lambda: self._steps[step_id].set_progress(progress, status))

    def _set_step_done(self, step_id: str, ok: bool) -> None:
        self.after(0, lambda: self._steps[step_id].set_done(ok))

    def _log_line(self, msg: str) -> None:
        self.after(0, lambda: self._log.append(msg))

    def _launch_agent(self) -> None:
        """Launch the agent using start_all.py --no-chat (starts services + opens browser).

        start_all.py automatically finds a free port starting at 5173, so multiple
        agents can run side-by-side without overwriting each other's dashboard.
        The chosen port is printed to stdout and captured here so we can show the
        correct URL in the log.
        """
        project = self._install_path
        venv_python = Path(project) / ".venv" / "Scripts" / "python.exe"
        start_script = Path(project) / "scripts" / "start_all.py"

        if not start_script.exists():
            self._log_line("ERROR: scripts/start_all.py not found. Is the install path correct?")
            return

        if not venv_python.exists():
            self._log_line("ERROR: Virtual environment not found — Python packages may not have installed.")
            self._log_line("Try clicking Retry to re-run the installation, then Launch Agent again.")
            return

        self._log_line("Launching agent services and opening dashboard in browser…")
        threading.Thread(target=self._run_launch, args=(str(venv_python), str(start_script), project), daemon=True).start()

    def _run_launch(self, venv_python: str, start_script: str, project: str) -> None:
        """Run start_all.py in a thread, capture its port output, update the UI."""
        import re
        try:
            proc = subprocess.Popen(
                [venv_python, start_script, "--no-chat"],
                cwd=project,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=_NO_WINDOW,
            )

            dashboard_url = "http://localhost:5173"  # fallback
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._log_line(line)
                # start_all.py prints "  Local:   http://localhost:PORT"
                m = re.search(r"Local:\s+(http://localhost:\d+)", line)
                if m:
                    dashboard_url = m.group(1)

            proc.wait(timeout=30)
            self._log_line(f"Agent started! Dashboard: {dashboard_url}")
            self.after(0, lambda url=dashboard_url: self._status_label.configure(
                text=f"Agent is starting! Dashboard: {url}",
                text_color=COLOR_GREEN,
            ))
        except Exception as e:
            self._log_line(f"ERROR launching agent: {e}")


def _build_memory_seed_script(
    block_files: dict[str, str],
    sysinstruct_path: str | None,
    today: str,
) -> str:
    """Return a Python script string that seeds core memory blocks and system instructions."""
    lines = [
        "import sys, os",
        "from pathlib import Path",
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))",
        "from dotenv import load_dotenv",
        "load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=True)",
        "from src.agent.core_memory import update_block, update_system_instructions",
        "",
    ]
    for block_type, path in block_files.items():
        lines += [
            f"_path = Path({repr(path)})",
            f"if _path.exists():",
            f"    _content = _path.read_text(encoding='utf-8').replace('{{date}}', {repr(today)})",
            f"    ok, msg = update_block({repr(block_type)}, _content)",
            f"    print(f'  {block_type}: {{msg}}')",
            f"else:",
            f"    print(f'  {block_type}: example file not found, skipping')",
            "",
        ]
    if sysinstruct_path:
        lines += [
            f"_si_path = Path({repr(sysinstruct_path)})",
            "if _si_path.exists():",
            "    update_system_instructions(_si_path.read_text(encoding='utf-8'))",
            "    print('  system_instructions: loaded from SYSINSTRUCT_EXAMPLE.txt')",
            "else:",
            "    print('  system_instructions: example file not found, skipping')",
        ]
    return "\n".join(lines)
