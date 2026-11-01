"""High-performance, pure-Python status report card drawer with 2x supersampling."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from .font_loader import get_font

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


def render_status_card(
    title: str = "Status Laporan Rumah",
    subtitle: str | None = None,
    metrics: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    camera_image_bytes: bytes | None = None,
    width: int = 900,
) -> bytes:
    """Render a modern visual status card with 2x supersampling to PNG bytes."""
    scale = 2
    sw = width * scale
    items = metrics or []

    cam_h = 240 * scale if camera_image_bytes else 0
    grid_rows = (len(items) + 1) // 2
    grid_h = grid_rows * 76 * scale if items else 0
    summary_h = 60 * scale if summary else 0
    total_height = max(450 * scale, 120 * scale + cam_h + grid_h + summary_h + 30 * scale)

    img = Image.new("RGBA", (sw, total_height), (15, 23, 42, 255))
    draw = ImageDraw.Draw(img)

    # Outer container
    draw.rounded_rectangle(
        [(10 * scale, 10 * scale), (sw - 10 * scale, total_height - 10 * scale)],
        radius=16 * scale,
        fill=(17, 24, 39, 255),
        outline=(30, 41, 59, 255),
        width=2 * scale,
    )

    font_title = get_font(20 * scale, bold=True)
    font_subtitle = get_font(12 * scale)
    font_metric_label = get_font(12 * scale, bold=True)
    font_metric_val = get_font(16 * scale, bold=True)
    font_summary = get_font(12 * scale)

    # 1. Header
    draw.text((36 * scale, 28 * scale), title, fill=(248, 250, 252, 255), font=font_title)
    sub = subtitle or datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    draw.text((36 * scale, 58 * scale), sub, fill=(148, 163, 184, 255), font=font_subtitle)

    # LIVE pill badge
    draw.rounded_rectangle(
        [(sw - 110 * scale, 32 * scale), (sw - 36 * scale, 60 * scale)],
        radius=14 * scale,
        fill=(16, 185, 129, 30),
        outline=(16, 185, 129, 220),
        width=1 * scale,
    )
    draw.ellipse(
        [(sw - 98 * scale, 42 * scale), (sw - 90 * scale, 50 * scale)],
        fill=(16, 185, 129, 255),
    )
    draw.text(
        (sw - 82 * scale, 37 * scale),
        "LIVE",
        fill=(16, 185, 129, 255),
        font=get_font(12 * scale, bold=True),
    )

    curr_y = 96 * scale

    # 2. Camera Snapshot Hero (if provided)
    if camera_image_bytes:
        try:
            cam_img = Image.open(io.BytesIO(camera_image_bytes)).convert("RGBA")
            target_w = sw - 72 * scale
            target_h = 220 * scale
            cam_img = cam_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

            mask = Image.new("L", (target_w, target_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (target_w, target_h)], radius=12 * scale, fill=255)

            img.paste(cam_img, (36 * scale, curr_y), mask)
            draw.rounded_rectangle(
                [(36 * scale, curr_y), (36 * scale + target_w, curr_y + target_h)],
                radius=12 * scale,
                outline=(51, 65, 85, 255),
                width=2 * scale,
            )
            curr_y += target_h + 20 * scale
        except Exception:  # noqa: BLE001
            pass

    # 3. Metrics Grid (2 columns)
    col_w = (sw - 72 * scale - 20 * scale) // 2
    for idx, m in enumerate(items):
        row = idx // 2
        col = idx % 2
        tile_x = 36 * scale + col * (col_w + 20 * scale)
        tile_y = curr_y + row * 76 * scale

        stat_key = str(m.get("status", "ok")).lower()
        color_rgb = STATUS_COLORS.get(stat_key, (56, 189, 248))

        draw.rounded_rectangle(
            [(tile_x, tile_y), (tile_x + col_w, tile_y + 64 * scale)],
            radius=10 * scale,
            fill=(24, 32, 47, 255),
            outline=(37, 48, 67, 255),
            width=1 * scale,
        )

        draw.rounded_rectangle(
            [(tile_x + 12 * scale, tile_y + 14 * scale), (tile_x + 16 * scale, tile_y + 50 * scale)],
            radius=2 * scale,
            fill=(*color_rgb, 255),
        )

        label_text = str(m.get("label", ""))
        val_text = str(m.get("value", ""))

        draw.text((tile_x + 28 * scale, tile_y + 12 * scale), label_text, fill=(148, 163, 184, 255), font=font_metric_label)
        draw.text((tile_x + 28 * scale, tile_y + 32 * scale), val_text, fill=(248, 250, 252, 255), font=font_metric_val)

    if items:
        curr_y += grid_rows * 76 * scale + 10 * scale

    # 4. Summary Note (Bottom)
    if summary:
        draw.rounded_rectangle(
            [(36 * scale, curr_y), (sw - 36 * scale, curr_y + 48 * scale)],
            radius=8 * scale,
            fill=(30, 41, 59, 140),
            outline=(51, 65, 85, 255),
            width=1 * scale,
        )
        draw.text((52 * scale, curr_y + 15 * scale), f"📌  {summary}", fill=(226, 232, 240, 255), font=font_summary)

    final_output = img.resize((width, total_height // scale), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    final_output.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
