"""
Shared UI constants and helper widgets for the installer wizard.
"""
from __future__ import annotations

import customtkinter as ctk

# ── Appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Palette
COLOR_BG = "#1a1a2e"
COLOR_CARD = "#16213e"
COLOR_ACCENT = "#0f3460"
COLOR_BLUE = "#4a9eff"
COLOR_GREEN = "#4caf50"
COLOR_YELLOW = "#ffc107"
COLOR_RED = "#f44336"
COLOR_TEXT = "#e0e0e0"
COLOR_MUTED = "#9e9e9e"

FONT_TITLE = ("Segoe UI", 22, "bold")
FONT_HEADING = ("Segoe UI", 14, "bold")
FONT_BODY = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 10)

WINDOW_WIDTH = 860
WINDOW_HEIGHT = 640


def status_color(found: bool, has_note: bool = False) -> str:
    if found and not has_note:
        return COLOR_GREEN
    if found and has_note:
        return COLOR_YELLOW
    return COLOR_RED


def status_icon(found: bool, has_note: bool = False) -> str:
    if found and not has_note:
        return "✓"
    if found and has_note:
        return "⚠"
    return "✗"


class ScrollableFrame(ctk.CTkScrollableFrame):
    """A scrollable container with consistent styling."""
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", COLOR_CARD)
        kwargs.setdefault("corner_radius", 8)
        super().__init__(master, **kwargs)


class SectionLabel(ctk.CTkLabel):
    def __init__(self, master, text: str, **kwargs):
        kwargs.setdefault("font", FONT_HEADING)
        kwargs.setdefault("text_color", COLOR_BLUE)
        kwargs.setdefault("anchor", "w")
        super().__init__(master, text=text, **kwargs)


class BodyLabel(ctk.CTkLabel):
    def __init__(self, master, text: str, **kwargs):
        kwargs.setdefault("font", FONT_BODY)
        kwargs.setdefault("text_color", COLOR_TEXT)
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("justify", "left")
        kwargs.setdefault("wraplength", 700)
        super().__init__(master, text=text, **kwargs)


class MutedLabel(ctk.CTkLabel):
    def __init__(self, master, text: str, **kwargs):
        kwargs.setdefault("font", FONT_SMALL)
        kwargs.setdefault("text_color", COLOR_MUTED)
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("justify", "left")
        kwargs.setdefault("wraplength", 700)
        super().__init__(master, text=text, **kwargs)


class PrimaryButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", COLOR_BLUE)
        kwargs.setdefault("hover_color", "#3a8eef")
        kwargs.setdefault("font", FONT_BODY)
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


class SecondaryButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", COLOR_ACCENT)
        kwargs.setdefault("hover_color", "#1a4480")
        kwargs.setdefault("font", FONT_BODY)
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("height", 36)
        super().__init__(master, **kwargs)


class LogBox(ctk.CTkTextbox):
    """Scrollable log output box."""
    def __init__(self, master, **kwargs):
        kwargs.setdefault("font", FONT_MONO)
        kwargs.setdefault("fg_color", "#0d0d1a")
        kwargs.setdefault("text_color", "#c8c8c8")
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("state", "disabled")
        super().__init__(master, **kwargs)

    def append(self, text: str) -> None:
        self.configure(state="normal")
        self.insert("end", text + "\n")
        self.see("end")
        self.configure(state="disabled")

    def clear(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


class ProgressRow(ctk.CTkFrame):
    """A labeled progress bar row."""
    def __init__(self, master, label: str, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self.columnconfigure(1, weight=1)

        self._label = ctk.CTkLabel(self, text=label, font=FONT_BODY, text_color=COLOR_TEXT,
                                   anchor="w", width=220)
        self._label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self._bar = ctk.CTkProgressBar(self, height=14, corner_radius=4)
        self._bar.set(0)
        self._bar.grid(row=0, column=1, sticky="ew")

        self._status = ctk.CTkLabel(self, text="", font=FONT_SMALL, text_color=COLOR_MUTED,
                                    width=80, anchor="e")
        self._status.grid(row=0, column=2, sticky="e", padx=(10, 0))

    def set_progress(self, value: float, status_text: str = "") -> None:
        self._bar.set(value)
        self._status.configure(text=status_text)

    def set_done(self, ok: bool = True) -> None:
        self._bar.set(1.0)
        if ok:
            self._bar.configure(progress_color=COLOR_GREEN)
            self._status.configure(text="Done", text_color=COLOR_GREEN)
        else:
            self._bar.configure(progress_color=COLOR_RED)
            self._status.configure(text="Failed", text_color=COLOR_RED)
