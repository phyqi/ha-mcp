"""High-performance, pure-Python status report card drawer using Pillow."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Status badge colors
STATUS_COLORS = {
    "ok": (16, 185, 129),  # Emerald 500
    "success": (16, 185, 129),
    "normal": (16, 185, 129),
    "info": (56, 189, 248),  # Sky 400
    "active": (56, 189, 248),
    "on": (56, 189, 248),
    "warning": (245, 158, 11),  # Amber 500
    "alert": (245, 158, 11),
    "error": (239, 68, 68),  # Red 500
    "critical": (239, 68, 68),
    "off": (100, 116, 139),  # Slate 500
}


def _get_font(size: int = 14) -> ImageFont.ImageFont:
    """Load default cross-platform font with specified size."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_status_card(
    title: str = "Status Laporan Rumah",
    subtitle: str | None = None,
    metrics: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    camera_image_bytes: bytes | None = None,
    width: int = 900,
) -> bytes:
    """Render a modern visual status card to PNG bytes.

    Args:
        title: Header title.
        subtitle: Subtitle or timestamp.
        metrics: List of metrics to show in a grid. Each item:
            - 'label': str (e.g. 'Suhu Kamar')
            - 'value': str (e.g. '24.5 °C')
            - 'status': str (e.g. 'ok', 'info', 'warning', 'error', 'off')
        summary: Optional summary note at the bottom.
        camera_image_bytes: Optional camera snapshot bytes to embed in card.
        width: Canvas width in pixels.

    Returns:
        PNG image bytes.
    """
    items = metrics or []

    # Dynamic height calculation
    cam_h = 240 if camera_image_bytes else 0
    grid_rows = (len(items) + 1) // 2  # 2 columns
    grid_h = grid_rows * 72 if items else 0
    summary_h = 60 if summary else 0
    total_height = max(450, 110 + cam_h + grid_h + summary_h + 40)

    img = Image.new("RGBA", (width, total_height), (15, 23, 42, 255))  # Slate 900
    draw = ImageDraw.Draw(img)

    # Outer rounded container
    draw.rounded_rectangle(
        [(10, 10), (width - 10, total_height - 10)],
        radius=16,
        fill=(17, 24, 39, 255),  # Gray 900
        outline=(30, 41, 59, 255),  # Slate 800
        width=2,
    )

    font_title = _get_font(20)
    font_subtitle = _get_font(12)
    font_metric_label = _get_font(12)
    font_metric_val = _get_font(16)
    font_summary = _get_font(13)

    # 1. Header
    draw.text((36, 28), title, fill=(248, 250, 252, 255), font=font_title)
    sub = subtitle or datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    draw.text((36, 56), sub, fill=(148, 163, 184, 255), font=font_subtitle)

    # "LIVE" pill badge
    draw.rounded_rectangle(
        [(width - 110, 32), (width - 36, 58)],
        radius=13,
        fill=(16, 185, 129, 35),
        outline=(16, 185, 129, 255),
        width=1,
    )
    draw.ellipse([(width - 98, 41), (width - 90, 49)], fill=(16, 185, 129, 255))
    draw.text((width - 82, 37), "LIVE", fill=(16, 185, 129, 255), font=font_subtitle)

    curr_y = 90

    # 2. Camera Snapshot Hero (if provided)
    if camera_image_bytes:
        try:
            cam_img = Image.open(io.BytesIO(camera_image_bytes)).convert("RGBA")
            target_w = width - 72
            target_h = 220
            cam_img = cam_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

            # Paste with rounded corners mask
            mask = Image.new("L", (target_w, target_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (target_w, target_h)], radius=12, fill=255)

            img.paste(cam_img, (36, curr_y), mask)
            # Outline around snapshot
            draw.rounded_rectangle(
                [(36, curr_y), (36 + target_w, curr_y + target_h)],
                radius=12,
                outline=(51, 65, 85, 255),
                width=1,
            )
            curr_y += target_h + 20
        except Exception:  # noqa: BLE001
            pass

    # 3. Metrics Grid (2 columns)
    col_w = (width - 72 - 20) // 2
    for idx, m in enumerate(items):
        row = idx // 2
        col = idx % 2
        tile_x = 36 + col * (col_w + 20)
        tile_y = curr_y + row * 72

        # Status color
        stat_key = str(m.get("status", "ok")).lower()
        color_rgb = STATUS_COLORS.get(stat_key, (56, 189, 248))

        # Tile background
        draw.rounded_rectangle(
            [(tile_x, tile_y), (tile_x + col_w, tile_y + 60)],
            radius=10,
            fill=(24, 32, 47, 255),  # Slate 850
            outline=(30, 41, 59, 255),
            width=1,
        )

        # Status bar pip
        draw.rounded_rectangle(
            [(tile_x + 12, tile_y + 14), (tile_x + 16, tile_y + 46)],
            radius=2,
            fill=(*color_rgb, 255),
        )

        # Label & Value
        label_text = str(m.get("label", ""))
        val_text = str(m.get("value", ""))

        draw.text((tile_x + 28, tile_y + 10), label_text, fill=(148, 163, 184, 255), font=font_metric_label)
        draw.text((tile_x + 28, tile_y + 28), val_text, fill=(248, 250, 252, 255), font=font_metric_val)

    if items:
        curr_y += grid_rows * 72 + 10

    # 4. Summary Note (Bottom)
    if summary:
        draw.rounded_rectangle(
            [(36, curr_y), (width - 36, curr_y + 48)],
            radius=8,
            fill=(30, 41, 59, 140),
            outline=(51, 65, 85, 255),
            width=1,
        )
        draw.text((52, curr_y + 15), f"📌  {summary}", fill=(226, 232, 240, 255), font=font_summary)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
