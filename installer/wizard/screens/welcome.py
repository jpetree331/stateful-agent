"""
Welcome screen — first thing the user sees.
Shows the agent name/logo, a brief description, the install path selector,
and a disk space check.
"""
from __future__ import annotations

import os
import shutil
import tkinter as tk
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from ..theme import (
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_SMALL,
    COLOR_BG, COLOR_CARD, COLOR_BLUE, COLOR_GREEN, COLOR_RED, COLOR_TEXT, COLOR_MUTED,
    BodyLabel, MutedLabel, PrimaryButton, SecondaryButton, SectionLabel,
)


class WelcomeScreen(ctk.CTkFrame):
    """
    Screen 1: Welcome + install path + disk check.
    Calls `on_next(install_path: str)` when the user clicks Continue.
    """

    def __init__(self, master, on_next: Callable[[str], None], **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._on_next = on_next
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Agent Installer",
            font=FONT_TITLE,
            text_color=COLOR_BLUE,
        ).grid(row=0, column=0, padx=32, pady=(24, 4), sticky="w")

        ctk.CTkLabel(
            header,
            text="Set up your local AI agent in a few easy steps.",
            font=FONT_BODY,
            text_color=COLOR_TEXT,
        ).grid(row=1, column=0, padx=32, pady=(0, 20), sticky="w")

        # ── Body ──────────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=32, pady=24)
        body.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # What this installer does
        SectionLabel(body, text="What this installer will do:").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        steps = [
            ("1", "Check your system and install missing dependencies (Python, Node.js, Git, Docker)"),
            ("2", "Set up your database (Railway cloud or local PostgreSQL)"),
            ("3", "Optionally set up Hindsight deep memory (requires Docker, 30+ min first run)"),
            ("4", "Configure your API keys and settings"),
            ("5", "Install the agent and launch it"),
        ]
        for num, text in steps:
            row_frame = ctk.CTkFrame(body, fg_color="transparent")
            row_frame.grid(sticky="ew", pady=2)
            row_frame.columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row_frame,
                text=num,
                font=FONT_BODY,
                text_color=COLOR_BLUE,
                width=24,
                fg_color=COLOR_CARD,
                corner_radius=12,
            ).grid(row=0, column=0, padx=(0, 10))
            BodyLabel(row_frame, text=text).grid(row=0, column=1, sticky="w")

        # ── Install path ──────────────────────────────────────────────────────
        ctk.CTkFrame(body, height=1, fg_color=COLOR_CARD).grid(
            row=10, column=0, sticky="ew", pady=20
        )

        SectionLabel(body, text="Installation folder:").grid(
            row=11, column=0, sticky="w", pady=(0, 6)
        )

        path_frame = ctk.CTkFrame(body, fg_color="transparent")
        path_frame.grid(row=12, column=0, sticky="ew")
        path_frame.columnconfigure(0, weight=1)

        # Default to the detected project root; empty string means not found — user must browse.
        default_path = self._default_install_path()
        self._path_var = tk.StringVar(value=default_path)

        self._path_entry = ctk.CTkEntry(
            path_frame,
            textvariable=self._path_var,
            font=FONT_BODY,
            height=36,
        )
        self._path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        SecondaryButton(
            path_frame,
            text="Browse",
            width=90,
            command=self._browse,
        ).grid(row=0, column=1)

        # ── Disk space indicator ──────────────────────────────────────────────
        self._disk_label = ctk.CTkLabel(
            body,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
        )
        self._disk_label.grid(row=13, column=0, sticky="w", pady=(6, 0))

        # ── Footer ────────────────────────────────────────────────────────────
        # IMPORTANT: footer and _next_btn must be created BEFORE the trace fires
        # (_update_disk_check references _next_btn, and the trace can fire immediately
        # when the StringVar is set).
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=32, pady=(0, 24))
        footer.columnconfigure(0, weight=1)

        MutedLabel(
            footer,
            text="The installer will not delete any existing files. You can re-run it at any time.",
        ).grid(row=0, column=0, sticky="w")

        self._next_btn = PrimaryButton(
            footer,
            text="Continue  →",
            width=160,
            command=self._on_continue,
        )
        self._next_btn.grid(row=0, column=1, sticky="e")

        # Hook up path validation AFTER _next_btn exists
        self._path_var.trace_add("write", lambda *_: self._update_disk_check())
        self._update_disk_check()

    def _default_install_path(self) -> str:
        """
        Return the project root — the folder containing requirements.txt and src/.

        Search strategy (frozen EXE):
          1. EXE's own directory (normal: user placed AgentInstaller.exe in the project root)
          2. One level down (GitHub zip double-nesting: outer/inner/)
          3. Walk up to 3 parent levels (user ran EXE from a subfolder)
          4. Return empty string — forces the user to browse, rather than silently
             picking the wrong folder.

        Running as a plain script: walk up from installer/wizard/screens/.
        """
        import sys

        def _looks_like_project_root(p: Path) -> bool:
            return (p / "requirements.txt").exists() and (p / "src").exists()

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent

            # 1. EXE's own directory (most common correct case)
            if _looks_like_project_root(exe_dir):
                return str(exe_dir)

            # 2. One level down (GitHub zip double-nesting: outer/inner/)
            try:
                for child in sorted(exe_dir.iterdir()):
                    if child.is_dir() and _looks_like_project_root(child):
                        return str(child)
            except Exception:
                pass

            # 3. Walk up the tree (EXE placed inside a subfolder of the project)
            for parent in exe_dir.parents:
                if _looks_like_project_root(parent):
                    return str(parent)
                # Don't walk past the drive root or more than 3 levels up
                if len(parent.parts) <= len(exe_dir.parts) - 3:
                    break

            # 4. Nothing found — return empty so the user must browse manually.
            #    This is safer than silently picking the wrong folder.
            return ""

        # Running as script — go up from installer/wizard/screens/ to project root
        return str(Path(__file__).resolve().parents[3])

    def _browse(self) -> None:
        from tkinter import filedialog
        chosen = filedialog.askdirectory(
            title="Select agent installation folder",
            initialdir=self._path_var.get(),
        )
        if chosen:
            self._path_var.set(chosen)

    def _update_disk_check(self) -> None:
        path = self._path_var.get().strip()
        if not path:
            self._disk_label.configure(
                text="Please click Browse and select the folder where you extracted the agent (it contains requirements.txt and a src/ folder).",
                text_color=COLOR_RED,
            )
            self._next_btn.configure(state="disabled")
            return

        # Validate that the selected folder actually looks like the agent project
        p = Path(path)
        if not ((p / "requirements.txt").exists() and (p / "src").exists()):
            self._disk_label.configure(
                text="This folder doesn't look like the agent project. Browse to the folder that contains requirements.txt and src/.",
                text_color=COLOR_RED,
            )
            self._next_btn.configure(state="disabled")
            return

        try:
            usage = shutil.disk_usage(path if p.exists() else p.anchor)
            free_gb = usage.free / (1024 ** 3)
            if free_gb >= 10:
                self._disk_label.configure(
                    text=f"✓  {free_gb:.1f} GB free on this drive — enough space",
                    text_color=COLOR_GREEN,
                )
                self._next_btn.configure(state="normal")
            else:
                self._disk_label.configure(
                    text=f"⚠  Only {free_gb:.1f} GB free — at least 10 GB recommended. Free up space before continuing.",
                    text_color=COLOR_RED,
                )
                self._next_btn.configure(state="normal")  # warn but don't block
        except Exception:
            self._disk_label.configure(text="Could not check disk space.", text_color=COLOR_MUTED)
            self._next_btn.configure(state="normal")

    def _on_continue(self) -> None:
        path = self._path_var.get().strip()
        if not path:
            return
        self._on_next(path)
