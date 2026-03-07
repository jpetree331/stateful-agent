"""
Dependencies screen — detects and installs system prerequisites.
Shows a grid of dependency status indicators and lets the user install
missing ones with per-item progress bars.
"""
from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from ..detector import DetectResult, SystemSnapshot, scan_system
from ..installer import install_python, install_node, install_git, install_docker
from ..theme import (
    FONT_HEADING, FONT_BODY, FONT_SMALL,
    COLOR_BG, COLOR_CARD, COLOR_BLUE, COLOR_GREEN, COLOR_YELLOW, COLOR_RED,
    COLOR_TEXT, COLOR_MUTED,
    BodyLabel, MutedLabel, PrimaryButton, SecondaryButton, SectionLabel,
    LogBox, status_color, status_icon,
)


_DEPS = [
    ("python",  "Python 3.11+",   "Required to run the agent"),
    ("node",    "Node.js 18+",    "Required for the web dashboard"),
    ("npm",     "npm",            "Installed with Node.js"),
    ("git",     "Git",            "Required to clone/update the agent"),
    ("docker",  "Docker Desktop", "Required for Hindsight memory (optional)"),
]

_INSTALLERS = {
    "python": install_python,
    "node":   install_node,
    "git":    install_git,
    "docker": install_docker,
}


class DependencyRow(ctk.CTkFrame):
    """One row in the dependency grid."""

    def __init__(self, master, dep_id: str, name: str, description: str,
                 on_install: Callable[[str], None], **kwargs):
        kwargs.setdefault("fg_color", COLOR_CARD)
        kwargs.setdefault("corner_radius", 6)
        super().__init__(master, **kwargs)
        self._dep_id = dep_id
        self._on_install = on_install
        self.columnconfigure(2, weight=1)

        # Status icon
        self._icon = ctk.CTkLabel(self, text="…", font=("Segoe UI", 16),
                                  text_color=COLOR_MUTED, width=32)
        self._icon.grid(row=0, column=0, padx=(12, 8), pady=10)

        # Name + description
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", padx=(0, 12))
        ctk.CTkLabel(info, text=name, font=FONT_BODY, text_color=COLOR_TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=description, font=FONT_SMALL, text_color=COLOR_MUTED,
                     anchor="w").pack(anchor="w")

        # Version / note label
        self._version_label = ctk.CTkLabel(self, text="Checking…", font=FONT_SMALL,
                                           text_color=COLOR_MUTED, anchor="w")
        self._version_label.grid(row=0, column=2, sticky="w")

        # Progress bar (hidden until install starts)
        self._progress = ctk.CTkProgressBar(self, height=8, corner_radius=4)
        self._progress.set(0)
        self._progress.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))
        self._progress.grid_remove()

        # Install button (shown only when missing)
        self._install_btn = SecondaryButton(
            self, text="Install", width=90,
            command=lambda: self._on_install(self._dep_id),
        )
        self._install_btn.grid(row=0, column=3, padx=12)
        self._install_btn.grid_remove()

    def set_result(self, result: DetectResult) -> None:
        is_warning = result.found and result.note
        color = status_color(result.found, bool(result.note))
        icon = status_icon(result.found, bool(result.note))
        self._icon.configure(text=icon, text_color=color)

        if result.found:
            ver_text = f"v{result.version}" if result.version else "Found"
            if result.note:
                ver_text += f"  —  {result.note}"
            self._version_label.configure(text=ver_text, text_color=color)
            self._install_btn.grid_remove()
        else:
            note = result.note or "Not found"
            self._version_label.configure(text=note, text_color=COLOR_RED)
            if self._dep_id in _INSTALLERS:
                self._install_btn.grid()

    def set_installing(self) -> None:
        self._install_btn.configure(state="disabled", text="Installing…")
        self._progress.grid()
        self._progress.set(0)

    def set_progress(self, value: float) -> None:
        self._progress.set(value)

    def set_install_done(self, ok: bool) -> None:
        self._progress.set(1.0)
        if ok:
            self._progress.configure(progress_color=COLOR_GREEN)
            self._icon.configure(text="✓", text_color=COLOR_GREEN)
            self._version_label.configure(text="Installed — restart may be needed", text_color=COLOR_GREEN)
            self._install_btn.grid_remove()
        else:
            self._progress.configure(progress_color=COLOR_RED)
            self._icon.configure(text="✗", text_color=COLOR_RED)
            self._install_btn.configure(state="normal", text="Retry")


class DependenciesScreen(ctk.CTkFrame):
    """
    Screen 2: Dependency detection and installation.
    Calls `on_next(snapshot)` when the user clicks Continue.
    """

    def __init__(self, master, on_next: Callable[[SystemSnapshot], None],
                 on_back: Callable[[], None], install_path: str, **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._on_next = on_next
        self._on_back = on_back
        self._install_path = install_path
        self._snapshot: SystemSnapshot | None = None
        self._rows: dict[str, DependencyRow] = {}
        self._build_ui()
        # Start scan in background
        threading.Thread(target=self._scan, daemon=True).start()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="System Check", font=FONT_HEADING,
                     text_color=COLOR_BLUE).grid(row=0, column=0, padx=32, pady=(20, 4), sticky="w")
        BodyLabel(header, text="The installer is checking your system for required software.").grid(
            row=1, column=0, padx=32, pady=(0, 16), sticky="w"
        )

        # Scrollable body
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=32, pady=16)
        body.columnconfigure(0, weight=1)

        for i, (dep_id, name, desc) in enumerate(_DEPS):
            row = DependencyRow(body, dep_id, name, desc, on_install=self._start_install)
            row.grid(row=i, column=0, sticky="ew", pady=4)
            self._rows[dep_id] = row

        # Log box (collapsed by default, expands on install)
        self._log = LogBox(self, height=120)
        self._log.grid(row=2, column=0, sticky="ew", padx=32, pady=(0, 8))
        self._log.grid_remove()

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 24))
        footer.columnconfigure(1, weight=1)

        SecondaryButton(footer, text="← Back", width=100, command=self._on_back).grid(
            row=0, column=0, sticky="w"
        )

        self._status_label = MutedLabel(footer, text="Scanning system…")
        self._status_label.grid(row=0, column=1, padx=16, sticky="w")

        self._next_btn = PrimaryButton(
            footer, text="Continue  →", width=160,
            command=self._on_continue, state="disabled"
        )
        self._next_btn.grid(row=0, column=2, sticky="e")

    def _scan(self) -> None:
        self.after(0, lambda: self._status_label.configure(text="Scanning system…"))
        snap = scan_system(self._install_path)
        self._snapshot = snap
        self.after(0, lambda: self._apply_snapshot(snap))

    def _apply_snapshot(self, snap: SystemSnapshot) -> None:
        attr_map = {
            "python": snap.python,
            "node":   snap.node,
            "npm":    snap.npm,
            "git":    snap.git,
            "docker": snap.docker,
        }
        for dep_id, result in attr_map.items():
            if dep_id in self._rows:
                self._rows[dep_id].set_result(result)

        # Determine if we can proceed (python, node, git required; docker optional)
        required_ok = snap.python.found and snap.node.found and snap.git.found
        if required_ok:
            self._status_label.configure(
                text="Required dependencies found. You may continue.",
                text_color=COLOR_GREEN,
            )
            self._next_btn.configure(state="normal")
        else:
            missing = []
            if not snap.python.found:
                missing.append("Python 3.11+")
            if not snap.node.found:
                missing.append("Node.js 18+")
            if not snap.git.found:
                missing.append("Git")
            self._status_label.configure(
                text=f"Missing required: {', '.join(missing)}. Install them to continue.",
                text_color=COLOR_RED,
            )
            self._next_btn.configure(state="disabled")

    def _start_install(self, dep_id: str) -> None:
        installer_fn = _INSTALLERS.get(dep_id)
        if not installer_fn:
            return
        row = self._rows[dep_id]
        row.set_installing()
        self._log.grid()
        self._log.append(f"--- Installing {dep_id} ---")
        self._next_btn.configure(state="disabled")

        def run():
            ok = True
            for msg, progress in installer_fn():
                self.after(0, lambda m=msg, p=progress: (
                    self._log.append(m),
                    row.set_progress(p),
                ))
                if "ERROR" in msg.upper():
                    ok = False
            self.after(0, lambda: self._install_finished(dep_id, ok))

        threading.Thread(target=run, daemon=True).start()

    def _install_finished(self, dep_id: str, ok: bool) -> None:
        row = self._rows[dep_id]
        row.set_install_done(ok)
        # Re-scan to pick up newly installed tools
        threading.Thread(target=self._scan, daemon=True).start()

    def _on_continue(self) -> None:
        if self._snapshot:
            self._on_next(self._snapshot)
