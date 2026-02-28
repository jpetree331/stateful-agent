"""
Windows-specific tools: desktop toast notifications and shortcut creation.

Notifications use the Windows Runtime (WinRT) Toast API via PowerShell —
no extra Python packages required. Works on Windows 10 and 11.

Shortcuts create standard .lnk files via the Windows Script Host COM object,
also via PowerShell — no extra packages required.

Note on desktop icon *positioning*: Windows stores icon grid positions in a
binary registry blob controlled by Explorer. Programmatic repositioning is not
reliable. The agent can organise the desktop by creating folders, moving files into
them, and creating/deleting shortcuts — but cannot move individual icons to
specific pixel coordinates.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool

_APP_NAME = os.environ.get("AGENT_APP_NAME", "Stateful Agent")


def _run_ps(script: str, timeout: int = 10) -> tuple[bool, str]:
    """Run a PowerShell command, return (success, output_or_error)."""
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (result.stderr or result.stdout).strip()


@tool
def notify(title: str, message: str) -> str:
    """
    Send a Windows desktop toast notification that pops up in the bottom-right corner.

    Use to proactively alert the user to something important without waiting for them to
    open the dashboard — completed tasks, reminders, interesting findings, urgent info.
    Keep the message concise (notifications are short).

    Args:
        title: Bold heading of the notification (keep under ~60 chars).
        message: Body text (keep under ~200 chars for readability).
    """
    # Primary: winotify — registers a proper AUMID via Start Menu shortcut on first use,
    # which is the only reliable way to show toast notifications on Windows 10/11.
    # The WinRT API silently drops notifications from unregistered AUMIDs.
    try:
        from winotify import Notification

        toast = Notification(
            app_id=_APP_NAME,
            title=title,
            msg=message,
            duration="short",  # 7 seconds; "long" = 25 seconds
        )
        toast.show()
        return f"Notification sent: '{title}'"
    except ImportError:
        pass  # winotify not installed — fall through to PowerShell
    except Exception as e:
        return f"Notification error (winotify): {e}"

    # Fallback: PowerShell WinRT (less reliable — AUMID must already be registered)
    safe_title = title.replace('"', "'").replace("`", "'")
    safe_msg = message.replace('"', "'").replace("`", "'")
    safe_app = _APP_NAME.replace('"', "'")

    ps_script = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{safe_title}</text><text>{safe_msg}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{safe_app}").Show($toast)
"""
    ok, out = _run_ps(ps_script)
    return f"Notification sent (fallback): '{title}'" if ok else f"Notification failed: {out}"


@tool
def create_shortcut(
    target_path: str,
    shortcut_name: str,
    location: str = "desktop",
    description: str = "",
) -> str:
    """
    Create a Windows shortcut (.lnk) pointing to a file, folder, or program.

    Use to add quick-access links to the user's desktop or other folders — for example,
    creating a desktop shortcut to a frequently-used project folder or application.

    Args:
        target_path: The file, folder, or executable the shortcut should open.
        shortcut_name: Name of the shortcut (without .lnk extension).
        location: Where to create the shortcut.
                  "desktop" (default) — the user's desktop.
                  Or provide a full folder path for any other location.
        description: Optional tooltip text shown on hover.
    """
    # Resolve destination folder
    if location.lower() == "desktop":
        dest_dir = Path.home() / "Desktop"
    else:
        dest_dir = Path(location).expanduser().resolve()

    dest_dir.mkdir(parents=True, exist_ok=True)
    lnk_path = dest_dir / f"{shortcut_name}.lnk"
    target = Path(target_path).expanduser().resolve()
    safe_desc = description.replace('"', "'")

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{lnk_path}')
$Shortcut.TargetPath = '{target}'
$Shortcut.Description = '{safe_desc}'
$Shortcut.WorkingDirectory = '{target.parent if target.is_file() else target}'
$Shortcut.Save()
"""
    ok, out = _run_ps(ps_script)
    if ok:
        return f"Shortcut created: {lnk_path} → {target}"
    return f"Error creating shortcut: {out}"
