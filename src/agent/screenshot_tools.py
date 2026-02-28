"""
Screenshot + vision tools.

Takes a screenshot of the current screen, then analyzes it with a vision-capable
LLM. The analysis is performed inside the tool (returns text), so the agent's
main context doesn't need to handle raw image data.

Configuration:
  VISION_MODEL_NAME  — model to use for image analysis (default: same as OPENAI_MODEL_NAME).
                       Override if your main model doesn't support vision.
                       E.g. "gpt-4o-mini" or "gpt-4o" on standard OpenAI.
  VISION_BASE_URL    — base URL for vision calls (default: same as OPENAI_BASE_URL).
  OPENAI_API_KEY     — used for both the main model and vision calls.

Dependencies:
  Pillow>=10.0  (add to requirements.txt) — provides PIL.ImageGrab for Windows screenshots
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from langchain_core.tools import tool

_SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "screenshots"

# Max dimension for screenshot sent to vision model.
# Full 4K screenshots (~35 MB PNG) are unnecessarily large for analysis.
# 1920-wide is plenty of detail for most tasks while keeping token cost low.
_MAX_WIDTH = 1920
_MAX_HEIGHT = 1200


def _capture_screenshot() -> "PIL.Image.Image":  # type: ignore[name-defined]
    """Capture the full screen (all monitors combined on Windows)."""
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)


def _resize_for_vision(img: "PIL.Image.Image") -> "PIL.Image.Image":  # type: ignore[name-defined]
    """Downscale to fit within _MAX_WIDTH x _MAX_HEIGHT, maintaining aspect ratio."""
    w, h = img.size
    if w <= _MAX_WIDTH and h <= _MAX_HEIGHT:
        return img
    scale = min(_MAX_WIDTH / w, _MAX_HEIGHT / h)
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, resample=1)  # LANCZOS = 1


def _image_to_base64(img: "PIL.Image.Image") -> str:  # type: ignore[name-defined]
    """Encode a PIL image to base64 PNG string."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _call_vision(b64_image: str, prompt: str) -> str:
    """Call the configured vision model with the screenshot."""
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    model = (
        os.environ.get("VISION_MODEL_NAME")
        or os.environ.get("OPENAI_MODEL_NAME")
        or "gpt-4o-mini"
    )
    base_url = os.environ.get("VISION_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    kwargs: dict = {"model": model, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    llm = ChatOpenAI(**kwargs)

    message = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
    ])
    response = llm.invoke([message])
    return str(response.content)


@tool
def analyze_screenshot(
    prompt: str = "Describe in detail what you see on the screen. Note any text, UI elements, open applications, and anything important.",
    save: bool = False,
) -> str:
    """
    Take a screenshot of the current screen and analyze it with vision AI.

    Captures the full screen (all monitors), sends it to the vision model, and
    returns a detailed text description. Use to:
    - See what the user is currently working on
    - Help debug a UI issue or error message on screen
    - Read content from apps that don't have APIs (PDFs in a viewer, etc.)
    - Describe what's on screen without the user having to describe it

    Works best with a vision-capable model. Configure VISION_MODEL_NAME in .env
    if your main model doesn't support vision (e.g. set it to "gpt-4o-mini").

    Args:
        prompt: What to focus on or ask about the screenshot.
                Default: general description of everything visible.
        save: If True, also save the screenshot as a PNG to data/screenshots/
              so you can reference it later or send it somewhere.
    """
    try:
        from PIL import ImageGrab  # noqa: F401
    except ImportError:
        return "Error: Pillow not installed. Run: pip install Pillow"

    try:
        img = _capture_screenshot()
    except Exception as e:
        return f"Error capturing screenshot: {e}"

    original_size = img.size
    img = _resize_for_vision(img)
    resized_size = img.size

    save_path_str = ""
    if save:
        try:
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            fname = datetime.now().strftime("screenshot_%Y%m%d_%H%M%S.png")
            save_path = _SCREENSHOT_DIR / fname
            img.save(save_path, format="PNG")
            save_path_str = f"\nSaved to: {save_path}"
        except Exception as e:
            save_path_str = f"\n(Save failed: {e})"

    b64 = _image_to_base64(img)

    size_info = f"{original_size[0]}x{original_size[1]}"
    if resized_size != original_size:
        size_info += f" → resized to {resized_size[0]}x{resized_size[1]} for analysis"

    try:
        analysis = _call_vision(b64, prompt)
    except Exception as e:
        return (
            f"Screenshot captured ({size_info}) but vision analysis failed: {e}\n"
            f"Tip: Set VISION_MODEL_NAME in .env to a vision-capable model (e.g. gpt-4o-mini)."
            + save_path_str
        )

    return f"=== Screenshot Analysis ===\nCapture size: {size_info}\n\n{analysis}{save_path_str}"
