"""
Agent Installer — main entry point.
Launches the CustomTkinter wizard and manages screen transitions.
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Optional

import customtkinter as ctk

# Make the installer/ directory importable as a package root
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from wizard.theme import (
    COLOR_BG, WINDOW_WIDTH, WINDOW_HEIGHT,
)
from wizard.screens.welcome import WelcomeScreen
from wizard.screens.dependencies import DependenciesScreen
from wizard.screens.database import DatabaseScreen, DatabaseConfig
from wizard.screens.hindsight import HindsightScreen, HindsightConfig
from wizard.screens.env_config import EnvConfigScreen, EnvConfig
from wizard.screens.install import InstallScreen
from wizard.detector import SystemSnapshot


class InstallerApp(ctk.CTk):
    """Main application window — hosts the wizard screens."""

    def __init__(self):
        super().__init__()
        self.title("Agent Installer")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(720, 560)
        self.configure(fg_color=COLOR_BG)

        # Try to set window icon
        icon_path = Path(__file__).parent / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        # State carried between screens
        self._install_path: str = ""
        self._snapshot: Optional[SystemSnapshot] = None
        self._db_config: Optional[DatabaseConfig] = None
        self._hindsight_config: Optional[HindsightConfig] = None
        self._env_config: Optional[EnvConfig] = None

        self._current_screen: Optional[ctk.CTkFrame] = None

        # Step indicator bar
        self._build_step_bar()

        # Container for screen content
        self._container = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self._container.pack(fill="both", expand=True)
        self._container.columnconfigure(0, weight=1)
        self._container.rowconfigure(0, weight=1)

        self._show_welcome()

    # ── Step bar ──────────────────────────────────────────────────────────────

    _STEPS = ["Welcome", "System", "Database", "Hindsight", "Config", "Install"]

    def _build_step_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="#0d0d1a", height=36, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.columnconfigure(list(range(len(self._STEPS))), weight=1, uniform="step")

        self._step_labels: list[ctk.CTkLabel] = []
        for i, name in enumerate(self._STEPS):
            lbl = ctk.CTkLabel(
                bar, text=f"{i + 1}. {name}",
                font=("Segoe UI", 10),
                text_color="#555577",
            )
            lbl.grid(row=0, column=i, padx=4, pady=8)
            self._step_labels.append(lbl)

    def _highlight_step(self, index: int) -> None:
        for i, lbl in enumerate(self._step_labels):
            if i == index:
                lbl.configure(text_color="#4a9eff", font=("Segoe UI", 10, "bold"))
            elif i < index:
                lbl.configure(text_color="#4caf50", font=("Segoe UI", 10))
            else:
                lbl.configure(text_color="#555577", font=("Segoe UI", 10))

    # ── Screen transitions ────────────────────────────────────────────────────

    def _swap(self, screen: ctk.CTkFrame) -> None:
        if self._current_screen:
            self._current_screen.grid_forget()
            self._current_screen.destroy()
        self._current_screen = screen
        screen.grid(row=0, column=0, sticky="nsew", in_=self._container)

    def _show_welcome(self) -> None:
        self._highlight_step(0)
        self._swap(WelcomeScreen(self._container, on_next=self._on_welcome_next))

    def _on_welcome_next(self, install_path: str) -> None:
        self._install_path = install_path
        self._show_dependencies()

    def _show_dependencies(self) -> None:
        self._highlight_step(1)
        self._swap(DependenciesScreen(
            self._container,
            on_next=self._on_deps_next,
            on_back=self._show_welcome,
            install_path=self._install_path,
        ))

    def _on_deps_next(self, snapshot: SystemSnapshot) -> None:
        self._snapshot = snapshot
        self._show_database()

    def _show_database(self) -> None:
        self._highlight_step(2)
        self._swap(DatabaseScreen(
            self._container,
            on_next=self._on_db_next,
            on_back=self._show_dependencies,
            snapshot=self._snapshot,
        ))

    def _on_db_next(self, config: DatabaseConfig) -> None:
        self._db_config = config
        self._show_hindsight()

    def _show_hindsight(self) -> None:
        self._highlight_step(3)
        self._swap(HindsightScreen(
            self._container,
            on_next=self._on_hindsight_next,
            on_back=self._show_database,
            snapshot=self._snapshot,
        ))

    def _on_hindsight_next(self, config: HindsightConfig) -> None:
        self._hindsight_config = config
        self._show_env_config()

    def _show_env_config(self) -> None:
        self._highlight_step(4)
        self._swap(EnvConfigScreen(
            self._container,
            on_next=self._on_env_next,
            on_back=self._show_hindsight,
            db_config=self._db_config,
            hindsight_config=self._hindsight_config,
        ))

    def _on_env_next(self, config: EnvConfig) -> None:
        self._env_config = config
        self._show_install()

    def _show_install(self) -> None:
        self._highlight_step(5)
        self._swap(InstallScreen(
            self._container,
            on_back=self._show_env_config,
            install_path=self._install_path,
            db_config=self._db_config,
            hindsight_config=self._hindsight_config,
            env_config=self._env_config,
        ))


def main() -> None:
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
