"""
Hindsight setup screen.
Detects whether Hindsight is already running, installed but stopped,
has the image but no container, or is completely absent — and shows
the appropriate action for each state.

States handled:
  RUNNING          → show green status, let user set bank ID and continue
  CONTAINER_STOPPED→ offer "Start container" button, skip download
  IMAGE_ONLY       → offer "Create container" button, skip download
  NOT_INSTALLED    → offer full download + create flow (30+ min warning)
"""
from __future__ import annotations

import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

import customtkinter as ctk

from ..detector import detect_docker, detect_hindsight, HindsightState, SystemSnapshot
from ..installer import (
    pull_hindsight_image, start_hindsight_container, wait_for_docker_daemon,
    HINDSIGHT_IMAGE, HINDSIGHT_CONTAINER,
)
from ..theme import (
    FONT_HEADING, FONT_BODY, FONT_SMALL,
    COLOR_BG, COLOR_CARD, COLOR_BLUE, COLOR_GREEN, COLOR_RED, COLOR_YELLOW,
    COLOR_TEXT, COLOR_MUTED,
    BodyLabel, MutedLabel, PrimaryButton, SecondaryButton, SectionLabel,
    LogBox,
)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if __import__("sys").platform == "win32" else 0


@dataclass
class HindsightConfig:
    enabled: bool
    bank_id: str = "stateful-agent"
    llm_provider: str = "openai"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""


def _restart_container(
    llm_base_url: str, llm_model: str, llm_api_key: str
) -> None:
    """Start (or restart) the Hindsight container — blocking, call from thread."""
    subprocess.run(
        ["docker", "start", HINDSIGHT_CONTAINER],
        capture_output=True,
        creationflags=_NO_WINDOW,
    )


class HindsightScreen(ctk.CTkFrame):
    """
    Screen 4: Hindsight episodic memory setup.
    Calls `on_next(config: HindsightConfig)` when done.
    """

    def __init__(self, master, on_next: Callable[[HindsightConfig], None],
                 on_back: Callable[[], None], snapshot: SystemSnapshot, **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._on_next = on_next
        self._on_back = on_back
        self._snapshot = snapshot
        self._choice = tk.StringVar(value="recommended")
        self._pull_running = False
        self._pull_done = False
        self._elapsed_seconds = 0
        self._hindsight_state: Optional[HindsightState] = None
        self._hindsight_msg: str = ""
        self._build_ui()
        # Detect Hindsight in background so the screen draws first
        threading.Thread(target=self._detect_hindsight, daemon=True).start()

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Hindsight Memory (Optional)", font=FONT_HEADING,
                     text_color=COLOR_BLUE).grid(row=0, column=0, padx=32, pady=(20, 4), sticky="w")
        BodyLabel(
            header,
            text="Hindsight gives your agent long-term episodic memory — it remembers lived experiences "
                 "across sessions and can recall and reflect on them.",
        ).grid(row=1, column=0, padx=32, pady=(0, 16), sticky="w")

        # Choice cards
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew", padx=32, pady=(16, 0))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        self._rec_card = self._choice_card(
            cards, "recommended",
            "✓  Set up Hindsight  (Recommended)",
            "Requires Docker. First-time image download takes 30+ minutes.\n"
            "The agent will remember experiences across all sessions.",
            col=0,
        )
        self._skip_card = self._choice_card(
            cards, "skip",
            "Skip for now",
            "You can set up Hindsight later by running the installer again\n"
            "or following the README instructions.",
            col=1,
        )

        # Body (scrollable)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=32, pady=16)
        body.columnconfigure(0, weight=1)
        self._body = body

        # ── Hindsight status card (populated by _apply_hindsight_state) ──────
        self._status_card = ctk.CTkFrame(body, fg_color=COLOR_CARD, corner_radius=6)
        self._status_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._status_card.columnconfigure(1, weight=1)

        self._status_icon_lbl = ctk.CTkLabel(
            self._status_card, text="…", font=("Segoe UI", 16),
            text_color=COLOR_MUTED, width=32
        )
        self._status_icon_lbl.grid(row=0, column=0, padx=12, pady=10)

        self._status_text_lbl = ctk.CTkLabel(
            self._status_card, text="Checking Hindsight status…",
            font=FONT_BODY, text_color=COLOR_MUTED, anchor="w"
        )
        self._status_text_lbl.grid(row=0, column=1, sticky="w", padx=(0, 12))

        # ── Docker status ─────────────────────────────────────────────────────
        docker = detect_docker()
        docker_color = COLOR_GREEN if (docker.found and not docker.note) else (
            COLOR_YELLOW if docker.found else COLOR_RED
        )
        docker_icon = "✓" if (docker.found and not docker.note) else ("⚠" if docker.found else "✗")
        docker_note = docker.note or (f"Docker {docker.version} — daemon running" if docker.found else "Docker not found")

        docker_card = ctk.CTkFrame(body, fg_color=COLOR_CARD, corner_radius=6)
        docker_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(docker_card, text=docker_icon, font=("Segoe UI", 16),
                     text_color=docker_color, width=32).grid(row=0, column=0, padx=12, pady=8)
        ctk.CTkLabel(docker_card, text=f"Docker Desktop: {docker_note}",
                     font=FONT_BODY, text_color=docker_color, anchor="w").grid(
            row=0, column=1, sticky="w", padx=(0, 12)
        )

        # ── LLM config for Hindsight container ────────────────────────────────
        SectionLabel(body, text="Hindsight LLM configuration").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        MutedLabel(
            body,
            text="Hindsight needs an LLM to process memories. Use the same provider as your agent, "
                 "or a cheaper model like gpt-4o-mini.",
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))

        form = ctk.CTkFrame(body, fg_color="transparent")
        form.grid(row=4, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        def _field(parent, row, col_label, col_entry, label, placeholder, show=""):
            ctk.CTkLabel(parent, text=label, font=FONT_SMALL, text_color=COLOR_MUTED,
                         anchor="w").grid(row=row * 2, column=col_label, sticky="w", pady=(6, 0))
            entry = ctk.CTkEntry(parent, placeholder_text=placeholder, font=FONT_BODY,
                                 height=32, show=show)
            entry.grid(row=row * 2 + 1, column=col_entry, sticky="ew", padx=(0, 12))
            return entry

        self._llm_base_url = _field(form, 0, 0, 1, "Base URL", "https://api.openai.com/v1")
        self._llm_model    = _field(form, 0, 2, 3, "Model", "gpt-4o-mini")
        self._llm_api_key  = _field(form, 1, 0, 1, "API Key", "sk-...", show="*")
        self._bank_id      = _field(form, 1, 2, 3, "Memory Bank ID", "stateful-agent")
        self._bank_id.insert(0, "stateful-agent")

        # ── Warning banner (shown only for full download) ──────────────────
        self._warn_frame = ctk.CTkFrame(body, fg_color="#2a1a00", corner_radius=6)
        self._warn_frame.grid(row=5, column=0, sticky="ew", pady=(16, 8))
        ctk.CTkLabel(
            self._warn_frame,
            text="⏱  First-time setup: Docker will download the Hindsight image (~2 GB).\n"
                 "   This takes 30+ minutes depending on your internet speed.\n"
                 "   The installer will show live progress — your agent is NOT broken!",
            font=FONT_BODY, text_color=COLOR_YELLOW,
            justify="left", anchor="w", wraplength=740,
        ).grid(padx=16, pady=12, sticky="w")

        # ── Progress area ─────────────────────────────────────────────────────
        self._progress_frame = ctk.CTkFrame(body, fg_color="transparent")
        self._progress_frame.grid(row=6, column=0, sticky="ew")
        self._progress_frame.columnconfigure(0, weight=1)

        self._progress_bar = ctk.CTkProgressBar(self._progress_frame, height=18, corner_radius=6)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self._progress_label = ctk.CTkLabel(
            self._progress_frame, text="", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w"
        )
        self._progress_label.grid(row=1, column=0, sticky="w")

        self._elapsed_label = ctk.CTkLabel(
            self._progress_frame, text="", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e"
        )
        self._elapsed_label.grid(row=1, column=1, sticky="e")

        self._progress_frame.grid_remove()

        # ── Log ───────────────────────────────────────────────────────────────
        self._log = LogBox(body, height=120)
        self._log.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        self._log.grid_remove()

        # ── Action button (label changes depending on state) ──────────────────
        self._action_btn = PrimaryButton(
            body, text="Checking…", width=240,
            command=self._on_action_btn, state="disabled",
        )
        self._action_btn.grid(row=8, column=0, sticky="w", pady=(12, 0))

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 24))
        footer.columnconfigure(1, weight=1)

        SecondaryButton(footer, text="← Back", width=100, command=self._on_back).grid(
            row=0, column=0, sticky="w"
        )
        self._next_btn = PrimaryButton(
            footer, text="Continue  →", width=160, command=self._on_continue
        )
        self._next_btn.grid(row=0, column=2, sticky="e")

        self._choice.trace_add("write", lambda *_: self._on_choice_changed())
        self._on_choice_changed()

    def _choice_card(self, parent, val: str, title: str, desc: str, col: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=8, cursor="hand2")
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=4)
        card.columnconfigure(0, weight=1)
        card.bind("<Button-1>", lambda _: self._choice.set(val))

        rb = ctk.CTkRadioButton(
            card, text=title, variable=self._choice, value=val,
            font=FONT_BODY, text_color=COLOR_TEXT,
        )
        rb.grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(card, text=desc, font=FONT_SMALL, text_color=COLOR_MUTED,
                     anchor="w", justify="left", wraplength=320).grid(
            row=1, column=0, padx=32, pady=(0, 14), sticky="w"
        )
        return card

    # ── Hindsight state detection ─────────────────────────────────────────────

    def _detect_hindsight(self) -> None:
        """Run in background thread — detects state and updates UI."""
        state, msg = detect_hindsight()
        self._hindsight_state = state
        self._hindsight_msg = msg
        self.after(0, lambda: self._apply_hindsight_state(state, msg))

    def _apply_hindsight_state(self, state: HindsightState, msg: str) -> None:
        """Update the status card and action button based on detected state."""
        if state == HindsightState.RUNNING:
            self._status_icon_lbl.configure(text="✓", text_color=COLOR_GREEN)
            self._status_text_lbl.configure(
                text="Hindsight is already running! Just confirm your Bank ID below and continue.",
                text_color=COLOR_GREEN,
            )
            self._action_btn.configure(text="Already Running ✓", state="disabled")
            # Auto-select recommended and allow immediate continue (no download needed)
            self._choice.set("recommended")
            self._pull_done = True

        elif state == HindsightState.CONTAINER_STOPPED:
            self._status_icon_lbl.configure(text="⚠", text_color=COLOR_YELLOW)
            self._status_text_lbl.configure(
                text="Hindsight container exists but is stopped. Click 'Start Container' to restart it — no re-download needed.",
                text_color=COLOR_YELLOW,
            )
            self._action_btn.configure(text="Start Container", state="normal")

        elif state == HindsightState.IMAGE_ONLY:
            self._status_icon_lbl.configure(text="⚠", text_color=COLOR_YELLOW)
            self._status_text_lbl.configure(
                text="Hindsight image is already downloaded. Click 'Create Container' to start it — no re-download needed.",
                text_color=COLOR_YELLOW,
            )
            self._action_btn.configure(text="Create Container", state="normal")

        else:  # NOT_INSTALLED
            self._status_icon_lbl.configure(text="✗", text_color=COLOR_MUTED)
            self._status_text_lbl.configure(
                text="Hindsight not found. Click 'Download & Install' to set it up (30+ min first time).",
                text_color=COLOR_MUTED,
            )
            self._action_btn.configure(text="Download & Install Hindsight", state="normal")

        # Refresh the choice UI now that we know the real state
        self._on_choice_changed()

    # ── Action button dispatcher ──────────────────────────────────────────────

    def _on_action_btn(self) -> None:
        state = self._hindsight_state
        if state == HindsightState.CONTAINER_STOPPED:
            self._do_start_stopped_container()
        elif state == HindsightState.IMAGE_ONLY:
            self._do_create_container()
        else:
            self._do_full_download()

    def _do_start_stopped_container(self) -> None:
        """Start the existing stopped container."""
        self._action_btn.configure(state="disabled", text="Starting…")
        self._log.grid()

        def run():
            self.after(0, lambda: self._log.append("Starting Hindsight container…"))
            rc = subprocess.run(
                ["docker", "start", HINDSIGHT_CONTAINER],
                capture_output=True, text=True,
                creationflags=_NO_WINDOW,
            )
            if rc.returncode == 0:
                self.after(0, lambda: (
                    self._log.append("Container started successfully."),
                    self._log.append("Waiting for API to become available…"),
                ))
                # Give it a few seconds to come up
                time.sleep(5)
                self.after(0, lambda: (
                    self._status_icon_lbl.configure(text="✓", text_color=COLOR_GREEN),
                    self._status_text_lbl.configure(
                        text="Hindsight container started. Set your Bank ID and continue.",
                        text_color=COLOR_GREEN,
                    ),
                    self._action_btn.configure(text="Running ✓", state="disabled"),
                    self._log.append("Hindsight is ready."),
                ))
                self._pull_done = True
            else:
                err = rc.stderr.strip() or rc.stdout.strip()
                self.after(0, lambda: (
                    self._log.append(f"ERROR starting container: {err}"),
                    self._action_btn.configure(text="Retry", state="normal"),
                ))

        threading.Thread(target=run, daemon=True).start()

    def _do_create_container(self) -> None:
        """Image is present — just spin up the container."""
        self._action_btn.configure(state="disabled", text="Creating…")
        self._log.grid()

        def run():
            base_url = self._llm_base_url.get().strip() or "https://api.openai.com/v1"
            model    = self._llm_model.get().strip() or "gpt-4o-mini"
            api_key  = self._llm_api_key.get().strip()

            if not api_key:
                self.after(0, lambda: (
                    self._log.append("ERROR: Please enter an API key above before creating the container."),
                    self._action_btn.configure(state="normal", text="Create Container"),
                ))
                return

            for msg, _ in start_hindsight_container(
                llm_provider="openai",
                llm_base_url=base_url,
                llm_model=model,
                llm_api_key=api_key,
            ):
                self.after(0, lambda m=msg: self._log.append(m))

            self._pull_done = True
            self.after(0, lambda: (
                self._status_icon_lbl.configure(text="✓", text_color=COLOR_GREEN),
                self._status_text_lbl.configure(
                    text="Hindsight container created and running. Set your Bank ID and continue.",
                    text_color=COLOR_GREEN,
                ),
                self._action_btn.configure(text="Running ✓", state="disabled"),
            ))

        threading.Thread(target=run, daemon=True).start()

    def _do_full_download(self) -> None:
        """Full path: pull image then create container."""
        if self._pull_running:
            return
        docker = detect_docker()
        if not docker.found:
            self._log.grid()
            self._log.append("ERROR: Docker Desktop is not installed. Please install it on the Dependencies screen first.")
            return
        if docker.note and "not running" in docker.note.lower():
            self._log.grid()
            self._log.append("ERROR: Docker daemon is not running. Please start Docker Desktop and wait for it to say 'Docker Desktop is running', then try again.")
            return

        api_key = self._llm_api_key.get().strip()
        if not api_key:
            self._log.grid()
            self._log.append("ERROR: Please enter an API key in the Hindsight LLM configuration above before downloading.")
            return

        self._pull_running = True
        self._action_btn.configure(state="disabled", text="Downloading…")
        self._log.grid()
        self._progress_frame.grid()
        self._elapsed_seconds = 0
        self._start_elapsed_timer()

        def run():
            for msg, progress in pull_hindsight_image():
                self.after(0, lambda m=msg, p=progress: (
                    self._log.append(m),
                    self._progress_bar.set(p),
                    self._progress_label.configure(text=m[:100] if m else ""),
                ))

            # Create container
            base_url = self._llm_base_url.get().strip() or "https://api.openai.com/v1"
            model    = self._llm_model.get().strip() or "gpt-4o-mini"
            key      = self._llm_api_key.get().strip()
            for msg, _ in start_hindsight_container(
                llm_provider="openai",
                llm_base_url=base_url,
                llm_model=model,
                llm_api_key=key,
            ):
                self.after(0, lambda m=msg: self._log.append(m))

            self._pull_running = False
            self._pull_done = True
            self.after(0, lambda: (
                self._progress_bar.set(1.0),
                self._progress_bar.configure(progress_color=COLOR_GREEN),
                self._progress_label.configure(
                    text="Hindsight downloaded and started!", text_color=COLOR_GREEN
                ),
                self._action_btn.configure(text="Done ✓", state="disabled"),
                self._status_icon_lbl.configure(text="✓", text_color=COLOR_GREEN),
                self._status_text_lbl.configure(
                    text="Hindsight is ready. Set your Bank ID and continue.",
                    text_color=COLOR_GREEN,
                ),
            ))

        threading.Thread(target=run, daemon=True).start()

    def _start_elapsed_timer(self) -> None:
        def tick():
            if not self._pull_running:
                return
            self._elapsed_seconds += 1
            mins = self._elapsed_seconds // 60
            secs = self._elapsed_seconds % 60
            self._elapsed_label.configure(text=f"Elapsed: {mins}m {secs:02d}s")
            self.after(1000, tick)
        self.after(1000, tick)

    # ── Choice toggle ─────────────────────────────────────────────────────────

    def _on_choice_changed(self) -> None:
        choice = self._choice.get()
        if choice == "recommended":
            self._action_btn.grid()
            needs_download = (
                self._hindsight_state is None
                or self._hindsight_state == HindsightState.NOT_INSTALLED
            )
            if needs_download:
                self._warn_frame.grid()
                self._progress_frame.grid()
            else:
                # Already installed in some form — no download warning or progress bar needed
                self._warn_frame.grid_remove()
                self._progress_frame.grid_remove()
        else:
            self._action_btn.grid_remove()
            self._warn_frame.grid_remove()
            self._progress_frame.grid_remove()
            self._log.grid_remove()

    # ── Continue ──────────────────────────────────────────────────────────────

    def _on_continue(self) -> None:
        choice = self._choice.get()
        if choice == "skip":
            self._on_next(HindsightConfig(enabled=False))
            return

        config = HindsightConfig(
            enabled=True,
            bank_id=self._bank_id.get().strip() or "stateful-agent",
            llm_provider="openai",
            llm_base_url=self._llm_base_url.get().strip(),
            llm_model=self._llm_model.get().strip(),
            llm_api_key=self._llm_api_key.get().strip(),
        )
        self._on_next(config)
