"""
Database setup screen.
User chooses between Railway (paste a URL) or local PostgreSQL.
"""
from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

import customtkinter as ctk

from ..detector import detect_postgres, detect_pgvector, SystemSnapshot
from ..installer import (
    install_postgres, start_postgres_service,
    install_pgvector, create_local_database,
)
from ..env_writer import test_database_connection
from ..theme import (
    FONT_HEADING, FONT_BODY, FONT_SMALL,
    COLOR_BG, COLOR_CARD, COLOR_BLUE, COLOR_GREEN, COLOR_RED, COLOR_YELLOW,
    COLOR_TEXT, COLOR_MUTED,
    BodyLabel, MutedLabel, PrimaryButton, SecondaryButton, SectionLabel,
    LogBox, ProgressRow,
)


@dataclass
class DatabaseConfig:
    mode: str           # "railway" | "local"
    database_url: str
    knowledge_url: str  # local knowledge bank URL (may be empty)
    pg_password: str    # only for local mode
    pg_port: int = 5432
    db_name: str = "stateful-agent"        # main agent database name
    kb_name: str = "stateful-agent-kb"     # knowledge bank database name


class DatabaseScreen(ctk.CTkFrame):
    """
    Screen 3: Database configuration.
    Calls `on_next(config: DatabaseConfig)` when done.
    """

    def __init__(self, master, on_next: Callable[[DatabaseConfig], None],
                 on_back: Callable[[], None], snapshot: SystemSnapshot, **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._on_next = on_next
        self._on_back = on_back
        self._snapshot = snapshot
        self._mode = tk.StringVar(value="local")
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Database Setup", font=FONT_HEADING,
                     text_color=COLOR_BLUE).grid(row=0, column=0, padx=32, pady=(20, 4), sticky="w")
        BodyLabel(
            header,
            text="The agent needs a PostgreSQL database to store conversations and memory.",
        ).grid(row=1, column=0, padx=32, pady=(0, 16), sticky="w")

        # Mode selector
        mode_frame = ctk.CTkFrame(self, fg_color="transparent")
        mode_frame.grid(row=1, column=0, sticky="ew", padx=32, pady=(16, 0))
        mode_frame.columnconfigure(0, weight=1)
        mode_frame.columnconfigure(1, weight=1)

        self._railway_btn = self._mode_card(
            mode_frame, "railway",
            "Railway (Cloud)",
            "Use a free cloud database from Railway.\nNo local setup needed. Good for testing.",
            col=0,
        )
        self._local_btn = self._mode_card(
            mode_frame, "local",
            "Local PostgreSQL  (Recommended)",
            "Keep all data on your own PC.\nBest for privacy and long-term personal use.",
            col=1,
        )

        # Content area (swaps between railway/local panels)
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.grid(row=2, column=0, sticky="nsew", padx=32, pady=16)
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(0, weight=1)

        self._railway_panel = self._build_railway_panel(self._content)
        self._local_panel = self._build_local_panel(self._content)

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 24))
        footer.columnconfigure(1, weight=1)

        SecondaryButton(footer, text="← Back", width=100, command=self._on_back).grid(
            row=0, column=0, sticky="w"
        )
        self._db_error_label = ctk.CTkLabel(
            footer, text="", font=FONT_SMALL, text_color=COLOR_RED, anchor="w"
        )
        self._db_error_label.grid(row=0, column=1, padx=16, sticky="w")
        self._next_btn = PrimaryButton(
            footer, text="Continue  →", width=160, command=self._on_continue
        )
        self._next_btn.grid(row=0, column=2, sticky="e")

        self._mode.trace_add("write", lambda *_: self._switch_mode())
        self._switch_mode()

    def _mode_card(self, parent, mode_val: str, title: str, desc: str, col: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=8, cursor="hand2")
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=4)
        card.columnconfigure(0, weight=1)
        card.bind("<Button-1>", lambda _: self._mode.set(mode_val))

        rb = ctk.CTkRadioButton(
            card, text=title, variable=self._mode, value=mode_val,
            font=FONT_BODY, text_color=COLOR_TEXT,
        )
        rb.grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(card, text=desc, font=FONT_SMALL, text_color=COLOR_MUTED,
                     anchor="w", justify="left", wraplength=320).grid(
            row=1, column=0, padx=32, pady=(0, 14), sticky="w"
        )
        return card

    # ── Railway panel ─────────────────────────────────────────────────────────

    def _build_railway_panel(self, parent) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.columnconfigure(0, weight=1)

        SectionLabel(panel, text="Railway DATABASE_URL").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        BodyLabel(
            panel,
            text="1. Go to railway.app → New Project → Add PostgreSQL\n"
                 "2. Click the Postgres service → Connect tab → copy the 'Postgres URL'\n"
                 "3. Paste it below.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        ctk.CTkLabel(panel, text="DATABASE_URL *", font=FONT_SMALL,
                     text_color=COLOR_MUTED, anchor="w").grid(row=2, column=0, sticky="w")

        self._railway_url = ctk.CTkEntry(
            panel,
            placeholder_text="postgresql://postgres:password@host:port/railway",
            font=FONT_BODY,
            height=36,
        )
        self._railway_url.grid(row=3, column=0, sticky="ew", pady=(4, 8))

        test_row = ctk.CTkFrame(panel, fg_color="transparent")
        test_row.grid(row=4, column=0, sticky="ew")
        test_row.columnconfigure(1, weight=1)

        SecondaryButton(
            test_row, text="Test Connection", width=160, command=self._test_railway
        ).grid(row=0, column=0)

        self._railway_test_label = ctk.CTkLabel(
            test_row, text="", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w"
        )
        self._railway_test_label.grid(row=0, column=1, padx=12, sticky="w")

        MutedLabel(
            panel,
            text="Don't have a Railway account? Sign up free at railway.app (no credit card required for hobby plan).",
        ).grid(row=5, column=0, sticky="w", pady=(12, 0))

        return panel

    def _test_railway(self) -> None:
        url = self._railway_url.get().strip()
        if not url:
            self._railway_test_label.configure(text="Please enter a URL first.", text_color=COLOR_RED)
            return
        self._railway_test_label.configure(text="Testing…", text_color=COLOR_MUTED)

        def run():
            ok, msg = test_database_connection(url)
            color = COLOR_GREEN if ok else COLOR_RED
            self.after(0, lambda: self._railway_test_label.configure(text=msg, text_color=color))

        threading.Thread(target=run, daemon=True).start()

    # ── Local panel ───────────────────────────────────────────────────────────

    def _build_local_panel(self, parent) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.columnconfigure(0, weight=1)

        # PostgreSQL status
        pg = detect_postgres()
        pv = detect_pgvector(pg.path) if pg.found else None

        status_frame = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=6)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        status_frame.columnconfigure(1, weight=1)

        def _status_row(parent, row_idx, label, result):
            ok = result.found if result else False
            note = result.note if result else "Not checked"
            color = COLOR_GREEN if ok else (COLOR_YELLOW if result and result.note and result.found else COLOR_RED)
            icon = "✓" if ok else ("⚠" if result and result.note and result.found else "✗")
            ctk.CTkLabel(parent, text=icon, font=FONT_BODY, text_color=color, width=28).grid(
                row=row_idx, column=0, padx=(12, 4), pady=6
            )
            ctk.CTkLabel(parent, text=label, font=FONT_BODY, text_color=COLOR_TEXT, anchor="w").grid(
                row=row_idx, column=1, sticky="w"
            )
            ctk.CTkLabel(parent, text=note or ("Found" if ok else "Not found"),
                         font=FONT_SMALL, text_color=color, anchor="w").grid(
                row=row_idx, column=2, padx=(8, 12), sticky="w"
            )

        _status_row(status_frame, 0, "PostgreSQL", pg)
        _status_row(status_frame, 1, "pgvector extension", pv)

        # Install buttons
        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        if not pg.found:
            SecondaryButton(btn_row, text="Install PostgreSQL 16", width=200,
                            command=self._install_pg).pack(side="left", padx=(0, 8))
        elif pg.note:  # installed but not running
            SecondaryButton(btn_row, text="Start PostgreSQL Service", width=200,
                            command=self._start_pg).pack(side="left", padx=(0, 8))

        if pg.found and (not pv or not pv.found):
            SecondaryButton(btn_row, text="Install pgvector", width=160,
                            command=self._install_pgvector).pack(side="left", padx=(0, 8))

        # Log
        self._local_log = LogBox(panel, height=80)
        self._local_log.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        # Credentials
        SectionLabel(panel, text="PostgreSQL credentials").grid(row=3, column=0, sticky="w", pady=(0, 6))

        creds = ctk.CTkFrame(panel, fg_color="transparent")
        creds.grid(row=4, column=0, sticky="ew")
        creds.columnconfigure(1, weight=1)
        creds.columnconfigure(3, weight=1)

        ctk.CTkLabel(creds, text="Password:", font=FONT_BODY, text_color=COLOR_TEXT).grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self._pg_password = ctk.CTkEntry(creds, placeholder_text="postgres user password",
                                         show="*", font=FONT_BODY, height=32)
        self._pg_password.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        ctk.CTkLabel(creds, text="Port:", font=FONT_BODY, text_color=COLOR_TEXT).grid(
            row=0, column=2, padx=(0, 8), sticky="w"
        )
        self._pg_port = ctk.CTkEntry(creds, placeholder_text="5432", font=FONT_BODY,
                                     height=32, width=80)
        self._pg_port.insert(0, "5432")
        self._pg_port.grid(row=0, column=3, sticky="w")

        # Database names — let users choose to avoid collisions with existing installs
        SectionLabel(panel, text="Database names").grid(row=5, column=0, sticky="w", pady=(12, 4))

        db_names = ctk.CTkFrame(panel, fg_color="transparent")
        db_names.grid(row=6, column=0, sticky="ew")
        db_names.columnconfigure(1, weight=1)
        db_names.columnconfigure(3, weight=1)

        ctk.CTkLabel(db_names, text="Agent DB:", font=FONT_BODY, text_color=COLOR_TEXT).grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self._db_name = ctk.CTkEntry(db_names, placeholder_text="stateful-agent",
                                     font=FONT_BODY, height=32)
        self._db_name.insert(0, "stateful-agent")
        self._db_name.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        ctk.CTkLabel(db_names, text="Knowledge Bank DB:", font=FONT_BODY, text_color=COLOR_TEXT).grid(
            row=0, column=2, padx=(0, 8), sticky="w"
        )
        self._kb_name = ctk.CTkEntry(db_names, placeholder_text="stateful-agent-kb",
                                     font=FONT_BODY, height=32)
        self._kb_name.insert(0, "stateful-agent-kb")
        self._kb_name.grid(row=0, column=3, sticky="ew")

        MutedLabel(
            panel,
            text="Change these if you already have another agent installed — each install needs its own database names.",
        ).grid(row=7, column=0, sticky="w", pady=(6, 0))

        return panel

    def _install_pg(self) -> None:
        self._local_log.clear()
        self._run_local_task(install_postgres())

    def _start_pg(self) -> None:
        self._local_log.clear()
        self._run_local_task(start_postgres_service())

    def _install_pgvector(self) -> None:
        self._local_log.clear()
        pg = detect_postgres()
        self._run_local_task(install_pgvector(pg.path if pg.found else None))

    def _run_local_task(self, gen) -> None:
        def run():
            for msg, progress in gen:
                self.after(0, lambda m=msg: self._local_log.append(m))
        threading.Thread(target=run, daemon=True).start()

    # ── Mode switching ────────────────────────────────────────────────────────

    def _switch_mode(self) -> None:
        mode = self._mode.get()
        if mode == "railway":
            self._railway_panel.grid(row=0, column=0, sticky="nsew")
            self._local_panel.grid_remove()
        else:
            self._local_panel.grid(row=0, column=0, sticky="nsew")
            self._railway_panel.grid_remove()

    # ── Continue ──────────────────────────────────────────────────────────────

    def _on_continue(self) -> None:
        mode = self._mode.get()

        if mode == "railway":
            url = self._railway_url.get().strip()
            if not url:
                self._railway_test_label.configure(
                    text="Please enter your DATABASE_URL.", text_color=COLOR_RED
                )
                return
            config = DatabaseConfig(
                mode="railway",
                database_url=url,
                knowledge_url="",
                pg_password="",
            )
        else:
            password = self._pg_password.get().strip()
            if not password:
                self._db_error_label.configure(
                    text="Please enter your PostgreSQL password. This is required to connect to your local database."
                )
                return
            self._db_error_label.configure(text="")
            try:
                port = int(self._pg_port.get().strip() or "5432")
            except ValueError:
                port = 5432
            db_name = self._db_name.get().strip() or "stateful-agent"
            kb_name = self._kb_name.get().strip() or "stateful-agent-kb"
            db_url = f"postgresql://postgres:{password}@localhost:{port}/{db_name}"
            kb_url = f"postgresql://postgres:{password}@localhost:{port}/{kb_name}"
            config = DatabaseConfig(
                mode="local",
                database_url=db_url,
                knowledge_url=kb_url,
                pg_password=password,
                pg_port=port,
                db_name=db_name,
                kb_name=kb_name,
            )

        self._on_next(config)
