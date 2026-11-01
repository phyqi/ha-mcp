"""Font loader providing high-quality TrueType fonts with robust cross-platform fallbacks."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import ImageFont

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
