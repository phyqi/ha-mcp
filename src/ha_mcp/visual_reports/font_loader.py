"""Font loader providing high-quality TrueType fonts with robust cross-platform fallbacks."""

from __future__ import annotations

import os
from pathlib import Path

from typing import Any

from PIL import ImageDraw, ImageFont

_BUNDLED_FONTS_DIR = Path(__file__).parent / "fonts"

_CANDIDATE_REGULAR_PATHS = [
    _BUNDLED_FONTS_DIR / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
]

_CANDIDATE_BOLD_PATHS = [
    _BUNDLED_FONTS_DIR / "DejaVuSans-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"),
]


def get_font(size: int = 14, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a crisp TrueType font with scalable point size, falling back gracefully."""
    candidates = _CANDIDATE_BOLD_PATHS if bold else _CANDIDATE_REGULAR_PATHS
    for p in candidates:
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:  # noqa: BLE001
                continue

    # Fallback
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def truncate_text_to_width(
    draw: ImageDraw.ImageDraw,
    text: str | None,
    font: Any,
    max_width: int | float,
    ellipsis: str = "...",
) -> str:
    """Measure text and truncate with ellipsis if it exceeds max_width in pixels."""
    if not text:
        return ""
    if max_width <= 0:
        return ""

    try:
        current_len = draw.textlength(text, font=font)
    except Exception:  # noqa: BLE001
        current_len = len(text) * 10
    if current_len <= max_width:
        return text

    try:
        ellipsis_len = draw.textlength(ellipsis, font=font)
    except Exception:  # noqa: BLE001
        ellipsis_len = len(ellipsis) * 10
    if ellipsis_len >= max_width:
        return ellipsis if ellipsis_len == max_width else ""

    low = 1
    high = len(text)
    best = ellipsis

    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid] + ellipsis
        try:
            cand_len = draw.textlength(candidate, font=font)
        except Exception:  # noqa: BLE001
            cand_len = len(candidate) * 10

        if cand_len <= max_width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1

    return best


