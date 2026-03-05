"""
Heartbeat schedule configuration.

Config is read from data/heartbeat_config.json (written by the dashboard).
Falls back to environment variables, then to hard-coded defaults.

Schema (all fields optional — missing keys fall back to env/defaults):
{
  "wonder_start": 22,   // hour (0-23) when Wonder window begins
  "wonder_end":   15,   // hour (0-23) when Wonder window ends (next day if < start)
  "work_start":   3,    // hour (0-23) when Work window begins
  "work_end":     6,    // hour (0-23) when Work window ends
  "day_interval": 60,   // minutes between heartbeats during waking hours
  "night_interval": 90  // minutes between heartbeats during overnight hours
}

Window logic:
  Night (Wonder) : wonder_start → wonder_end  (wraps midnight)
  Work           : work_start   → work_end    (inside the night window, pre-online)
  Day            : everything else (user likely online; skip logic via last_active.txt)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "heartbeat_config.json"

# Hard-coded defaults (used when neither config file nor env var is set)
_DEFAULTS = {
    "wonder_start":    22,   # 10 PM — overnight exploration begins
    "wonder_end":       3,   # 3 AM  — overnight window ends
    "work_start":       3,   # 3 AM  — work prep begins (inside night window)
    "work_end":         6,   # 6 AM  — work prep ends (user online by 6 AM)
    "day_interval":    60,   # every 60 min during day
    "night_interval":  90,   # every 90 min overnight
}


def load_config() -> dict:
    """
    Load heartbeat schedule config.

    Priority: data/heartbeat_config.json > env vars > hard-coded defaults.
    Always returns a complete dict with all keys present.
    """
    cfg = dict(_DEFAULTS)

    # Layer 1: env vars
    env_map = {
        "wonder_start":   "HEARTBEAT_WONDER_START_HOUR",
        "wonder_end":     "HEARTBEAT_WONDER_END_HOUR",
        "work_start":     "HEARTBEAT_WORK_START_HOUR",
        "work_end":       "HEARTBEAT_WORK_END_HOUR",
        "day_interval":   "HEARTBEAT_DAY_INTERVAL_MINUTES",
        "night_interval": "HEARTBEAT_NIGHT_INTERVAL_MINUTES",
    }
    # Legacy single-interval env var
    legacy_interval = os.environ.get("HEARTBEAT_INTERVAL_MINUTES")
    if legacy_interval:
        try:
            v = int(legacy_interval)
            cfg["day_interval"] = v
            cfg["night_interval"] = v
        except ValueError:
            pass

    for key, env_var in env_map.items():
        val = os.environ.get(env_var)
        if val:
            try:
                cfg[key] = int(val)
            except ValueError:
                pass

    # Layer 2: config file (highest priority)
    if _CONFIG_PATH.exists():
        try:
            file_cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            for key in _DEFAULTS:
                if key in file_cfg:
                    try:
                        cfg[key] = int(file_cfg[key])
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.warning("Could not read heartbeat_config.json: %s", e)

    return cfg


def save_config(cfg: dict) -> None:
    """Write schedule config to data/heartbeat_config.json (preserves prompt keys)."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Read existing file so we don't clobber prompt keys
    existing: dict = {}
    if _CONFIG_PATH.exists():
        try:
            existing = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    for key in _DEFAULTS:
        if key in cfg:
            try:
                existing[key] = int(cfg[key])
            except (ValueError, TypeError):
                existing[key] = _DEFAULTS[key]

    _CONFIG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info("Heartbeat config saved to %s", _CONFIG_PATH)


def load_prompts() -> dict[str, str | None]:
    """
    Return the custom wonder/work prompts stored in heartbeat_config.json.

    Keys: 'wonder_prompt', 'work_prompt'.
    Values are None when no custom prompt has been saved (built-in default is used).
    """
    if not _CONFIG_PATH.exists():
        return {"wonder_prompt": None, "work_prompt": None}
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return {
            "wonder_prompt": data.get("wonder_prompt") or None,
            "work_prompt":   data.get("work_prompt")   or None,
        }
    except Exception as e:
        logger.warning("Could not read prompts from heartbeat_config.json: %s", e)
        return {"wonder_prompt": None, "work_prompt": None}


def save_prompts(wonder_prompt: str | None, work_prompt: str | None) -> None:
    """
    Persist custom heartbeat prompts to data/heartbeat_config.json.

    Pass None (or empty string) to clear a custom prompt and revert to the built-in default.
    """
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if _CONFIG_PATH.exists():
        try:
            existing = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing["wonder_prompt"] = wonder_prompt.strip() if wonder_prompt and wonder_prompt.strip() else None
    existing["work_prompt"]   = work_prompt.strip()   if work_prompt   and work_prompt.strip()   else None

    _CONFIG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info("Heartbeat prompts saved to %s", _CONFIG_PATH)


def _in_window(hour: int, start: int, end: int) -> bool:
    """True if hour is in [start, end), with midnight-wrap support when start > end."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def get_mode_for_hour(hour: int, cfg: dict | None = None) -> str:
    """
    Return 'work', 'wonder', or 'day' for a given hour (0-23).

    Priority: work > wonder > day.
    Work and wonder are independent windows (work does not need to be inside wonder).

    'work'   — pre-online preparation window (e.g. 3 AM – 6 AM)
    'wonder' — overnight exploration window  (e.g. 10 PM – 3 AM)
    'day'    — everything else; heartbeats still run every day_interval minutes
    """
    if cfg is None:
        cfg = load_config()

    if _in_window(hour, cfg["work_start"], cfg["work_end"]):
        return "work"
    if _in_window(hour, cfg["wonder_start"], cfg["wonder_end"]):
        return "wonder"
    return "day"
