"""
Clipboard tools: read from and write to the Windows clipboard.

Gated by the CLIPBOARD_ENABLED environment variable — set to "true" in .env
to activate these tools. When not enabled, CLIPBOARD_TOOLS is an empty list
and no clipboard tools are registered with the agent.

Usage in .env:
  CLIPBOARD_ENABLED=true   # enable clipboard access
  # (omit or set to false to disable)

Even when enabled, the agent should ONLY use clipboard tools when the user explicitly
asks — never speculatively or proactively. This is enforced by the system prompt.

Dependencies:
  pyperclip>=1.8  (add to requirements.txt)
"""
from __future__ import annotations

import os

from langchain_core.tools import tool

CLIPBOARD_ENABLED = os.environ.get("CLIPBOARD_ENABLED", "").lower() in ("1", "true", "yes")

if CLIPBOARD_ENABLED:
    @tool
    def clipboard_read() -> str:
        """
        Read the current contents of the Windows clipboard.

        Returns whatever text is currently copied. Only use when the user explicitly
        asks you to read or process something from her clipboard — never speculatively.

        Common uses: "summarise what I just copied", "translate this", "clean up this text".
        """
        try:
            import pyperclip
        except ImportError:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        try:
            text = pyperclip.paste()
            if not text:
                return "(Clipboard is empty)"
            return f"Clipboard contents ({len(text)} chars):\n\n{text}"
        except Exception as e:
            return f"Error reading clipboard: {e}"

    @tool
    def clipboard_write(text: str) -> str:
        """
        Write text to the Windows clipboard so the user can paste it anywhere.

        Use when the user asks you to prepare output they can paste directly into
        another app — code, a formatted message, a template, etc.
        Only use when explicitly asked.

        Args:
            text: The text to put on the clipboard.
        """
        try:
            import pyperclip
        except ImportError:
            return "Error: pyperclip not installed. Run: pip install pyperclip"
        try:
            pyperclip.copy(text)
            preview = text[:80].replace("\n", " ")
            if len(text) > 80:
                preview += "..."
            return f"Copied to clipboard ({len(text)} chars): {preview}"
        except Exception as e:
            return f"Error writing to clipboard: {e}"

    CLIPBOARD_TOOLS = [clipboard_read, clipboard_write]

else:
    CLIPBOARD_TOOLS = []
