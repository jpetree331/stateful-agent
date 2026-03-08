"""
Environment configuration screen.
Collects API keys and settings, organized into Required / Recommended / Advanced sections.
Pre-fills values from database and hindsight screens where possible.
"""
from __future__ import annotations

import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field
from typing import Callable, Optional

import customtkinter as ctk

from ..screens.database import DatabaseConfig
from ..screens.hindsight import HindsightConfig
from ..theme import (
    FONT_HEADING, FONT_BODY, FONT_SMALL,
    COLOR_BG, COLOR_CARD, COLOR_BLUE, COLOR_GREEN, COLOR_RED, COLOR_YELLOW,
    COLOR_TEXT, COLOR_MUTED, COLOR_ACCENT,
    BodyLabel, MutedLabel, PrimaryButton, SecondaryButton, SectionLabel,
    ScrollableFrame,
)


@dataclass
class EnvConfig:
    values: dict[str, str] = field(default_factory=dict)


def _link(parent, text: str, url: str) -> ctk.CTkLabel:
    lbl = ctk.CTkLabel(parent, text=text, font=FONT_SMALL, text_color=COLOR_BLUE,
                       cursor="hand2", anchor="w")
    lbl.bind("<Button-1>", lambda _: webbrowser.open(url))
    return lbl


class _FormField:
    """A labeled entry with optional validation indicator."""

    def __init__(self, parent, row: int, label: str, placeholder: str = "",
                 show: str = "", required: bool = False, help_text: str = "",
                 default: str = ""):
        self._required = required
        self._var = tk.StringVar(value=default)

        # Label row
        lbl_frame = ctk.CTkFrame(parent, fg_color="transparent")
        lbl_frame.grid(row=row * 3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        req_marker = " *" if required else ""
        ctk.CTkLabel(lbl_frame, text=label + req_marker, font=FONT_SMALL,
                     text_color=COLOR_MUTED if not required else COLOR_TEXT,
                     anchor="w").pack(side="left")
        if required:
            ctk.CTkLabel(lbl_frame, text=" (required)", font=FONT_SMALL,
                         text_color=COLOR_RED, anchor="w").pack(side="left")

        # Entry
        self._entry = ctk.CTkEntry(
            parent,
            textvariable=self._var,
            placeholder_text=placeholder,
            font=FONT_BODY,
            height=32,
            show=show,
        )
        self._entry.grid(row=row * 3 + 1, column=0, sticky="ew", padx=(0, 8))

        # Validation icon
        self._valid_icon = ctk.CTkLabel(parent, text="", font=FONT_BODY, width=24)
        self._valid_icon.grid(row=row * 3 + 1, column=1)

        # Help text
        if help_text:
            ctk.CTkLabel(parent, text=help_text, font=FONT_SMALL, text_color=COLOR_MUTED,
                         anchor="w", wraplength=640).grid(
                row=row * 3 + 2, column=0, columnspan=2, sticky="w"
            )

        if required:
            self._var.trace_add("write", lambda *_: self._validate())

    def _validate(self) -> bool:
        val = self._var.get().strip()
        if not val:
            self._valid_icon.configure(text="✗", text_color=COLOR_RED)
            return False
        self._valid_icon.configure(text="✓", text_color=COLOR_GREEN)
        return True

    def get(self) -> str:
        return self._var.get().strip()

    def set(self, value: str) -> None:
        self._var.set(value)

    def is_valid(self) -> bool:
        if self._required:
            return bool(self._var.get().strip())
        return True


class EnvConfigScreen(ctk.CTkFrame):
    """
    Screen 5: API keys and environment configuration.
    Calls `on_next(config: EnvConfig)` when done.
    """

    def __init__(self, master, on_next: Callable[[EnvConfig], None],
                 on_back: Callable[[], None],
                 db_config: DatabaseConfig,
                 hindsight_config: HindsightConfig,
                 **kwargs):
        kwargs.setdefault("fg_color", COLOR_BG)
        super().__init__(master, **kwargs)
        self._on_next = on_next
        self._on_back = on_back
        self._db_config = db_config
        self._hindsight_config = hindsight_config
        self._advanced_visible = tk.BooleanVar(value=False)
        self._fields: dict[str, _FormField] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="API Keys & Configuration", font=FONT_HEADING,
                     text_color=COLOR_BLUE).grid(row=0, column=0, padx=32, pady=(20, 4), sticky="w")
        BodyLabel(
            header,
            text="Configure your API keys and preferences. Required fields are marked with *.",
        ).grid(row=1, column=0, padx=32, pady=(0, 16), sticky="w")

        # Scrollable body
        scroll = ScrollableFrame(self)
        scroll.grid(row=1, column=0, sticky="nsew", padx=32, pady=16)
        scroll.columnconfigure(0, weight=1)

        self._build_required_section(scroll)
        self._build_recommended_section(scroll)
        self._build_advanced_section(scroll)

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=32, pady=(0, 24))
        footer.columnconfigure(1, weight=1)

        SecondaryButton(footer, text="← Back", width=100, command=self._on_back).grid(
            row=0, column=0, sticky="w"
        )
        self._error_label = ctk.CTkLabel(footer, text="", font=FONT_SMALL,
                                         text_color=COLOR_RED, anchor="w")
        self._error_label.grid(row=0, column=1, padx=16, sticky="w")

        PrimaryButton(footer, text="Continue  →", width=160, command=self._on_continue).grid(
            row=0, column=2, sticky="e"
        )

    # ── Sections ──────────────────────────────────────────────────────────────

    def _section_header(self, parent, row: int, title: str, subtitle: str = "") -> int:
        ctk.CTkFrame(parent, height=1, fg_color=COLOR_ACCENT).grid(
            row=row, column=0, sticky="ew", pady=(16, 8)
        )
        SectionLabel(parent, text=title).grid(row=row + 1, column=0, sticky="w")
        if subtitle:
            MutedLabel(parent, text=subtitle).grid(row=row + 2, column=0, sticky="w", pady=(2, 0))
            return row + 3
        return row + 2

    def _build_required_section(self, parent) -> None:
        row = self._section_header(parent, 0, "Required", "The agent cannot start without these.")

        form = ctk.CTkFrame(parent, fg_color="transparent")
        form.grid(row=row, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        # DATABASE_URL (pre-filled from database screen)
        db_url = self._db_config.database_url
        is_local = self._db_config.mode == "local"
        db_help = (
            "Pre-filled from the Database screen. Go back to change it."
            if is_local else
            "Your PostgreSQL connection string from Railway or another cloud provider."
        )
        f = _FormField(form, 0, "DATABASE_URL", "postgresql://...", required=True,
                       default=db_url, help_text=db_help)
        f.set(db_url)
        if is_local:
            # Lock the field — password was entered on the Database screen.
            # Editing it here would break DB creation and migration.
            f._entry.configure(state="disabled", text_color="#888888")
        self._fields["DATABASE_URL"] = f

        # LLM API key
        f2 = _FormField(form, 1, "OPENAI_API_KEY", "sk-... or cpk-... or your provider key",
                        show="*", required=True,
                        help_text="Your LLM API key. Works with OpenAI, Chutes (cpk-...), synthetic.new, or any OpenAI-compatible provider.")
        self._fields["OPENAI_API_KEY"] = f2

        # Links
        links = ctk.CTkFrame(form, fg_color="transparent")
        links.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ctk.CTkLabel(links, text="Get a key: ", font=FONT_SMALL, text_color=COLOR_MUTED).pack(side="left")
        _link(links, "OpenAI", "https://platform.openai.com/api-keys").pack(side="left", padx=(0, 8))
        _link(links, "Chutes AI (free)", "https://chutes.ai").pack(side="left", padx=(0, 8))
        _link(links, "synthetic.new", "https://synthetic.new").pack(side="left")

    def _build_recommended_section(self, parent) -> None:
        row = self._section_header(
            parent, 10,
            "Recommended",
            "Core features work best with these set.",
        )

        form = ctk.CTkFrame(parent, fg_color="transparent")
        form.grid(row=row, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        self._fields["OPENAI_BASE_URL"] = _FormField(
            form, 0, "OPENAI_BASE_URL (custom provider)",
            "https://api.synthetic.new/openai/v1",
            help_text="Leave blank to use default OpenAI. Set this if using Chutes, synthetic.new, Kimi, etc. Include /v1 at the end.",
        )
        self._fields["OPENAI_MODEL_NAME"] = _FormField(
            form, 1, "OPENAI_MODEL_NAME",
            "gpt-4o  or  moonshotai/Kimi-K2.5-TEE  or  openai/gpt-oss-120b-TEE",
            help_text="Model name for your provider. Leave blank for default OpenAI (uses gpt-4o).",
        )
        self._fields["TAVILY_API_KEY"] = _FormField(
            form, 2, "TAVILY_API_KEY (web search)",
            "tvly-...",
            help_text="Enables web search tools. Free 1,000 searches/month.",
        )

        links = ctk.CTkFrame(form, fg_color="transparent")
        links.grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ctk.CTkLabel(links, text="Get Tavily key: ", font=FONT_SMALL, text_color=COLOR_MUTED).pack(side="left")
        _link(links, "app.tavily.com", "https://app.tavily.com").pack(side="left")

        self._fields["AGENT_TIMEZONE"] = _FormField(
            form, 3, "AGENT_TIMEZONE",
            "America/New_York",
            default="America/New_York",
            help_text="The agent's time awareness timezone. Use IANA format (e.g. America/Chicago, Europe/London).",
        )

        # Heartbeat
        ctk.CTkLabel(form, text="Heartbeat (autonomous background thinking)", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        heartbeat_row = ctk.CTkFrame(form, fg_color="transparent")
        heartbeat_row.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        heartbeat_row.columnconfigure(1, weight=1)

        ctk.CTkLabel(heartbeat_row, text="Enable heartbeat:", font=FONT_BODY,
                     text_color=COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self._heartbeat_var = tk.BooleanVar(value=True)
        ctk.CTkSwitch(heartbeat_row, text="", variable=self._heartbeat_var,
                      onvalue=True, offvalue=False).grid(row=0, column=1, sticky="w")

        self._fields["HEARTBEAT_INTERVAL_MINUTES"] = _FormField(
            form, 5, "Heartbeat interval (minutes)",
            "60",
            default="60",
            help_text="How often the agent runs an autonomous thinking cycle. 60 = once per hour. Minimum recommended: 30.",
        )

    def _build_advanced_section(self, parent) -> None:
        # Toggle button
        toggle_row = ctk.CTkFrame(parent, fg_color="transparent")
        toggle_row.grid(row=20, column=0, sticky="ew", pady=(16, 0))

        toggle_btn = SecondaryButton(
            toggle_row,
            text="▶  Show Advanced Settings",
            width=220,
            command=self._toggle_advanced,
        )
        toggle_btn.pack(side="left")
        self._advanced_toggle_btn = toggle_btn

        MutedLabel(
            toggle_row,
            text="  Backup LLM key, TTS, Discord/Telegram, LangSmith tracing, etc.",
        ).pack(side="left", padx=12)

        # Collapsible frame
        self._advanced_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._advanced_frame.grid(row=21, column=0, sticky="ew")
        self._advanced_frame.columnconfigure(0, weight=1)
        self._advanced_frame.grid_remove()

        form = ctk.CTkFrame(self._advanced_frame, fg_color="transparent")
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        # Backup LLM
        ctk.CTkLabel(form, text="Backup LLM (rate-limit fallback)", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(8, 4)
        )
        self._fields["OPENAI_API_KEY_BACKUP"] = _FormField(
            form, 1, "OPENAI_API_KEY_BACKUP", "sk-... backup key", show="*",
            help_text="When primary hits a 429 rate limit, the agent retries with this key.",
        )
        self._fields["OPENAI_BASE_URL_BACKUP"] = _FormField(
            form, 2, "OPENAI_BASE_URL_BACKUP", "https://api.kimi.com/coding/v1",
            help_text="Base URL for the backup provider (can differ from primary).",
        )
        self._fields["OPENAI_MODEL_NAME_BACKUP"] = _FormField(
            form, 3, "OPENAI_MODEL_NAME_BACKUP", "moonshotai/Kimi-K2.5-TEE",
            help_text="Model for the backup provider.",
        )

        # Search keys
        ctk.CTkLabel(form, text="Additional search providers", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        self._fields["BRAVE_API_KEY"] = _FormField(
            form, 5, "BRAVE_API_KEY", "BSA...",
            help_text="Brave Search API key (alternative to Tavily).",
        )
        self._fields["EXA_API_KEY"] = _FormField(
            form, 6, "EXA_API_KEY", "...",
            help_text="Exa search API key.",
        )

        # TTS
        ctk.CTkLabel(form, text="Text-to-Speech (TTS)", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=21, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        self._fields["TTS_PROVIDER"] = _FormField(
            form, 8, "TTS_PROVIDER", "kokoro  or  kitten  or  vibevoice",
            help_text="Leave blank to disable TTS. 'kokoro' uses Chutes-hosted GPU TTS (needs KOKORO_TTS_API_KEY).",
        )
        self._fields["KOKORO_TTS_API_KEY"] = _FormField(
            form, 9, "KOKORO_TTS_API_KEY", "cpk-...", show="*",
            help_text="Chutes API key for Kokoro TTS (can reuse OPENAI_API_KEY if using Chutes).",
        )

        # Discord
        ctk.CTkLabel(form, text="Discord integration", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=30, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        self._fields["DISCORD_BOT_TOKEN"] = _FormField(
            form, 11, "DISCORD_BOT_TOKEN", "...",
            help_text="Discord bot token from discord.com/developers/applications → Bot → Token.",
        )
        self._fields["DISCORD_CHANNEL_ID"] = _FormField(
            form, 12, "DISCORD_CHANNEL_ID", "123456789",
            help_text="Channel ID (right-click channel in Discord with Developer Mode on).",
        )

        # Telegram
        ctk.CTkLabel(form, text="Telegram integration", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=39, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        self._fields["TELEGRAM_BOT_TOKEN"] = _FormField(
            form, 14, "TELEGRAM_BOT_TOKEN", "...",
            help_text="Telegram bot token from @BotFather.",
        )
        self._fields["TELEGRAM_CHAT_ID"] = _FormField(
            form, 15, "TELEGRAM_CHAT_ID", "123456789",
            help_text="Your personal chat ID with the bot.",
        )

        # LangSmith
        ctk.CTkLabel(form, text="LangSmith tracing (debugging)", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=48, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        self._fields["LANGCHAIN_API_KEY"] = _FormField(
            form, 17, "LANGCHAIN_API_KEY", "ls__...", show="*",
            help_text="LangSmith API key for tracing agent runs. Get it at smith.langchain.com.",
        )

        # Dashboard password
        ctk.CTkLabel(form, text="Dashboard security", font=FONT_BODY,
                     text_color=COLOR_BLUE, anchor="w").grid(
            row=57, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        self._fields["DASHBOARD_PASSWORD"] = _FormField(
            form, 19, "DASHBOARD_PASSWORD", "leave blank for local-only use", show="*",
            help_text="Set a password if you expose the dashboard via ngrok. Leave blank for local use.",
        )

        # No additional fields needed — Hindsight values are injected in _on_continue

    def _toggle_advanced(self) -> None:
        visible = self._advanced_visible.get()
        if visible:
            self._advanced_frame.grid_remove()
            self._advanced_toggle_btn.configure(text="▶  Show Advanced Settings")
            self._advanced_visible.set(False)
        else:
            self._advanced_frame.grid()
            self._advanced_toggle_btn.configure(text="▼  Hide Advanced Settings")
            self._advanced_visible.set(True)

    # ── Continue ──────────────────────────────────────────────────────────────

    def _on_continue(self) -> None:
        # Validate required fields
        missing = []
        for key, fld in self._fields.items():
            if not fld.is_valid():
                missing.append(key)

        if missing:
            self._error_label.configure(
                text=f"Please fill in: {', '.join(missing)}"
            )
            return

        self._error_label.configure(text="")

        values: dict[str, str] = {}
        for key, fld in self._fields.items():
            val = fld.get()
            if val:
                values[key] = val

        # Heartbeat toggle (switch widget, not a _FormField)
        values["HEARTBEAT_ENABLED"] = "true" if self._heartbeat_var.get() else "false"

        # Inject pre-collected values
        values["DATABASE_URL"] = self._db_config.database_url
        if self._db_config.knowledge_url:
            values["KNOWLEDGE_DATABASE_URL"] = self._db_config.knowledge_url

        if self._hindsight_config.enabled:
            values["HINDSIGHT_BASE_URL"] = "http://localhost:8888"
            values["HINDSIGHT_BANK_ID"] = self._hindsight_config.bank_id
            values["HINDSIGHT_ENABLED"] = "true"
            if self._hindsight_config.llm_api_key:
                values["HINDSIGHT_API_LLM_PROVIDER"] = self._hindsight_config.llm_provider
                values["HINDSIGHT_API_LLM_BASE_URL"] = self._hindsight_config.llm_base_url
                values["HINDSIGHT_API_LLM_MODEL"] = self._hindsight_config.llm_model
                values["HINDSIGHT_API_LLM_API_KEY"] = self._hindsight_config.llm_api_key

        self._on_next(EnvConfig(values=values))
