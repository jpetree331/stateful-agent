"""
TTS tools: generate voice messages. Supports VibeVoice (local), KittenTTS (local), and Kokoro (Chutes AI).

Providers (TTS_PROVIDER env):
  vibevoice — Microsoft VibeVoice 1.5B, local subprocess, p254_collage voice (worked ~80% tool-call rate)
  kitten    — KittenML/KittenTTS, 80M, CPU-friendly, Apache 2.0
  kokoro    — Chutes AI Kokoro-82M, GPU-hosted, natural-sounding

Env (VibeVoice):
  VIBEVOICE_ROOT, VIBEVOICE_REFERENCE_VOICE, VIBEVOICE_DEVICE, VIBEVOICE_TIMEOUT

Env (Kitten):
  KITTENTTS_MODEL, KITTENTTS_DEFAULT_VOICE, KITTENTTS_PLAY_AFTER_GENERATE

Env (Kokoro):
  KOKORO_TTS_BASE_URL, KOKORO_TTS_API_KEY, KOKORO_TTS_DEFAULT_VOICE
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TTS_OUTPUT_DIR = _PROJECT_ROOT / "data" / "tts_output"
_SCRIPT_TTS = _PROJECT_ROOT / "scripts" / "tts_voice_message.py"
_TTS_PROVIDER = (os.environ.get("TTS_PROVIDER", "kitten") or "kitten").strip().lower()

# KittenTTS
_KITTENTTS_MODEL = os.environ.get("KITTENTTS_MODEL", "KittenML/kitten-tts-mini-0.8")
_KITTENTTS_DEFAULT_VOICE = os.environ.get("KITTENTTS_DEFAULT_VOICE", "Leo").strip()
_KITTENTTS_VOICES = frozenset(["Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"])

# Kokoro (Chutes) — default to Chutes-hosted kokoro chute
_KOKORO_BASE_URL = (
    os.environ.get("KOKORO_TTS_BASE_URL") or "https://chutes-kokoro.chutes.ai"
).strip().rstrip("/")
_KOKORO_API_KEY = (
    os.environ.get("KOKORO_TTS_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
).strip()
def _get_kokoro_default_voice() -> str:
    """Read at call time so .env is definitely loaded (handles api/heartbeat entry points)."""
    v = os.environ.get("KOKORO_TTS_DEFAULT_VOICE", "af_heart").strip()
    return v or "af_heart"


logger = logging.getLogger("rowan.tts")


@tool
def tts_generate_voice_message(text: str, voice: str | None = None) -> str:
    """
    Generate a TTS voice message. **You MUST call this tool to create audio — there is no other way.** Do not describe or simulate; invoke the tool with the exact text. Provider: VibeVoice (local), KittenTTS (local), or Kokoro (Chutes AI). Set TTS_PROVIDER in .env.

    Use this anytime you want to speak out loud to the user — a greeting, a thought, a reminder, or
    any message that would feel more personal as voice. Output: WAV file in data/tts_output/.
    The user can open the file to hear you.

    VibeVoice: single voice (p254_collage). Kitten: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo
    Kokoro: af_heart, af_bella, bm_lewis, am_adam, etc. Omit voice to use default from .env.

    Args:
        text: The exact text you want spoken. Keep it concise for best results (a few sentences).
        voice: Optional. Only pass if the user asks for a specific voice. Otherwise omit — default comes from KOKORO_TTS_DEFAULT_VOICE in .env.
    """
    if not text or not text.strip():
        logger.warning("tts_generate_voice_message called with empty text")
        return "Error: No text provided. Pass the message you want spoken."

    if _TTS_PROVIDER == "vibevoice":
        return _generate_vibevoice(text.strip())
    if _TTS_PROVIDER == "kokoro":
        return _generate_kokoro(text.strip(), voice)
    return _generate_kitten(text.strip(), voice)


def _generate_vibevoice(text_clean: str) -> str:
    """Run VibeVoice via scripts/tts_voice_message.py subprocess."""
    if not _SCRIPT_TTS.exists():
        return f"Error: VibeVoice script not found: {_SCRIPT_TTS}"

    VIBEVOICE_ROOT = Path(os.environ.get("VIBEVOICE_ROOT", r"E:\git\VibeVoice"))
    if not VIBEVOICE_ROOT.exists():
        return f"Error: VibeVoice not found at {VIBEVOICE_ROOT}. Set VIBEVOICE_ROOT in .env."

    timeout = int(os.environ.get("VIBEVOICE_TIMEOUT", "480"))  # 8 min default

    logger.info("TTS (vibevoice) text_len=%d", len(text_clean))
    try:
        result = subprocess.run(
            [os.environ.get("PYTHON", "python"), str(_SCRIPT_TTS), text_clean],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning("VibeVoice failed: %s", result.stderr)
            return f"Error: VibeVoice failed: {result.stderr[:500] if result.stderr else 'unknown'}"

        out_path = result.stdout.strip()
        if out_path and Path(out_path).exists():
            _play_after = os.environ.get("KITTENTTS_PLAY_AFTER_GENERATE", "true").lower() in ("1", "true", "yes")
            if _play_after:
                try:
                    os.startfile(out_path)
                except OSError as e:
                    logger.warning("Could not open TTS file for playback: %s", e)
            logger.info("TTS success (vibevoice): %s", out_path)
            return f"Voice message saved: {out_path}\n\nJess can open this file to hear it."
        return f"Error: VibeVoice script ran but output not found: {out_path}"
    except subprocess.TimeoutExpired:
        return f"Error: VibeVoice timed out after {timeout}s. Increase VIBEVOICE_TIMEOUT if needed."
    except Exception as e:
        logger.exception("TTS (vibevoice) failed: %s", e)
        return f"Error: TTS failed: {e}"


def _generate_kitten(text_clean: str, voice: str | None) -> str:
    voice_choice = (voice or _KITTENTTS_DEFAULT_VOICE).strip()
    if voice_choice not in _KITTENTTS_VOICES:
        return (
            f"Error: Invalid voice '{voice_choice}'. "
            f"Available: {', '.join(sorted(_KITTENTTS_VOICES))}"
        )

    logger.info("TTS (kitten) text_len=%d voice=%s", len(text_clean), voice_choice)
    try:
        from kittentts import KittenTTS
        import soundfile as sf
    except ImportError as e:
        logger.error("KittenTTS import failed: %s", e)
        return (
            "Error: KittenTTS not installed. Run: "
            "pip install https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl "
            "soundfile"
        )

    try:
        _TTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = _TTS_OUTPUT_DIR / f"rowan_{stamp}.wav"

        model = KittenTTS(_KITTENTTS_MODEL)
        audio = model.generate(text_clean, voice=voice_choice)
        sf.write(str(out_path), audio, 24000)

        _play_after = os.environ.get("KITTENTTS_PLAY_AFTER_GENERATE", "true").lower() in ("1", "true", "yes")
        if _play_after:
            try:
                os.startfile(str(out_path))
            except OSError as e:
                logger.warning("Could not open TTS file for playback: %s", e)

        logger.info("TTS success (kitten): %s", out_path)
        return f"Voice message saved: {out_path}\n\nJess can open this file to hear it."
    except Exception as e:
        logger.exception("TTS (kitten) failed: %s", e)
        return f"Error: TTS failed: {e}"


def _generate_kokoro(text_clean: str, voice: str | None) -> str:
    if not _KOKORO_API_KEY:
        return (
            "Error: Kokoro TTS requires KOKORO_TTS_API_KEY (or OPENAI_API_KEY) in .env. "
            "Get your Chutes API token at https://chutes.ai/app/api"
        )

    voice_choice = (voice or _get_kokoro_default_voice()).strip()
    if not voice_choice:
        voice_choice = _get_kokoro_default_voice()

    logger.info("TTS (kokoro) text_len=%d voice=%s", len(text_clean), voice_choice)
    try:
        import httpx
    except ImportError:
        return "Error: httpx required for Kokoro TTS. Run: pip install httpx"

    url = f"{_KOKORO_BASE_URL}/speak"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_KOKORO_API_KEY}",
    }
    speed = float(os.environ.get("KOKORO_TTS_SPEED", "1"))
    payload = {"text": text_clean, "voice": voice_choice, "speed": speed}

    try:
        _TTS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = _TTS_OUTPUT_DIR / f"rowan_{stamp}.wav"

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio_bytes = resp.content

        out_path.write_bytes(audio_bytes)

        _play_after = os.environ.get("KITTENTTS_PLAY_AFTER_GENERATE", "true").lower() in ("1", "true", "yes")
        if _play_after:
            try:
                os.startfile(str(out_path))
            except OSError as e:
                logger.warning("Could not open TTS file for playback: %s", e)

        logger.info("TTS success (kokoro): %s", out_path)
        return f"Voice message saved: {out_path}\n\nJess can open this file to hear it."
    except httpx.HTTPStatusError as e:
        logger.warning("Kokoro TTS HTTP error: %s %s", e.response.status_code, e.response.text)
        return f"Error: Kokoro TTS failed ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        logger.exception("TTS (kokoro) failed: %s", e)
        return f"Error: TTS failed: {e}"
