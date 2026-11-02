"""High-performance, pure-Python status report card drawer with 2x supersampling."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from .font_loader import get_font, truncate_text_to_width

# Status badge colors (high-contrast, vibrant, WCAG-legible)
STATUS_COLORS = {
    "ok": (52, 211, 153),      # Emerald 400
    "success": (52, 211, 153),
    "normal": (52, 211, 153),
    "info": (56, 189, 248),    # Sky 400
    "active": (56, 189, 248),
    "on": (56, 189, 248),
    "warning": (251, 191, 36), # Amber 400
    "alert": (251, 191, 36),
    "error": (248, 113, 113),  # Rose 400
    "critical": (248, 113, 113),
    "off": (186, 199, 214),    # Slate 250
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

    # Process camera snapshot with strict original aspect ratio preservation
    cam_img: Image.Image | None = None
    cam_target_w = 0
    cam_target_h = 0
    cam_x = 36 * scale

    if camera_image_bytes:
        try:
            raw_cam = Image.open(io.BytesIO(camera_image_bytes)).convert("RGBA")
            orig_w, orig_h = raw_cam.size
            if orig_w > 0 and orig_h > 0:
                max_w = sw - 72 * scale
                max_h = 420 * scale
                ratio = orig_w / orig_h

                cam_target_w = max_w
                cam_target_h = int(cam_target_w / ratio)
                if cam_target_h > max_h:
                    cam_target_h = max_h
                    cam_target_w = int(cam_target_h * ratio)

                cam_x = (sw - cam_target_w) // 2
                cam_img = raw_cam.resize((cam_target_w, cam_target_h), Image.Resampling.LANCZOS)
        except Exception:  # noqa: BLE001
            pass

    cam_h = (cam_target_h + 20 * scale) if cam_img else 0
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
    max_title_w = sw - 120 * scale - 36 * scale
    title_to_draw = truncate_text_to_width(draw, title, font_title, max_title_w)
    draw.text((36 * scale, 28 * scale), title_to_draw, fill=(255, 255, 255, 255), font=font_title)
    sub = subtitle or datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    sub_to_draw = truncate_text_to_width(draw, sub, font_subtitle, max_title_w)
    draw.text((36 * scale, 58 * scale), sub_to_draw, fill=(203, 213, 225, 255), font=font_subtitle)

    # LIVE pill badge
    draw.rounded_rectangle(
        [(sw - 110 * scale, 32 * scale), (sw - 36 * scale, 60 * scale)],
        radius=14 * scale,
        fill=(52, 211, 153, 35),
        outline=(52, 211, 153, 220),
        width=1 * scale,
    )
    draw.ellipse(
        [(sw - 98 * scale, 42 * scale), (sw - 90 * scale, 50 * scale)],
        fill=(52, 211, 153, 255),
    )
    draw.text(
        (sw - 82 * scale, 37 * scale),
        "LIVE",
        fill=(52, 211, 153, 255),
        font=get_font(12 * scale, bold=True),
    )

    curr_y = 96 * scale

    # 2. Camera Snapshot Hero (Aspect ratio strictly preserved)
    if cam_img:
        mask = Image.new("L", (cam_target_w, cam_target_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (cam_target_w, cam_target_h)], radius=12 * scale, fill=255)

        img.paste(cam_img, (cam_x, curr_y), mask)
        draw.rounded_rectangle(
            [(cam_x, curr_y), (cam_x + cam_target_w, curr_y + cam_target_h)],
            radius=12 * scale,
            outline=(51, 65, 85, 255),
            width=2 * scale,
        )
        curr_y += cam_target_h + 20 * scale

    # Empty State Notice if no items
    if not items and not summary and not cam_img:
        box_w = sw - 72 * scale
        box_h = 140 * scale
        draw.rounded_rectangle(
            [(36 * scale, curr_y), (36 * scale + box_w, curr_y + box_h)],
            radius=12 * scale,
            fill=(24, 32, 47, 255),
            outline=(51, 65, 85, 255),
            width=1 * scale,
        )
        draw.text(
            (sw // 2, curr_y + 50 * scale),
            "Tidak Ada Data Metrik",
            fill=(255, 255, 255, 255),
            font=get_font(16 * scale, bold=True),
            anchor="mm",
        )
        draw.text(
            (sw // 2, curr_y + 85 * scale),
            "Pilih entitas perangkat atau masukkan data metrik untuk ditampilkan.",
            fill=(203, 213, 225, 255),
            font=get_font(12 * scale),
            anchor="mm",
        )
        curr_y += box_h + 20 * scale

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
            outline=(45, 55, 72, 255),
            width=1 * scale,
        )

        draw.rounded_rectangle(
            [(tile_x + 12 * scale, tile_y + 14 * scale), (tile_x + 16 * scale, tile_y + 50 * scale)],
            radius=2 * scale,
            fill=(*color_rgb, 255),
        )

        max_tile_w = col_w - 40 * scale
        label_text = truncate_text_to_width(draw, str(m.get("label", "")), font_metric_label, max_tile_w)
        val_text = truncate_text_to_width(draw, str(m.get("value", "")), font_metric_val, max_tile_w)

        draw.text((tile_x + 28 * scale, tile_y + 12 * scale), label_text, fill=(203, 213, 225, 255), font=font_metric_label)
        draw.text((tile_x + 28 * scale, tile_y + 32 * scale), val_text, fill=(255, 255, 255, 255), font=font_metric_val)

    if items:
        curr_y += grid_rows * 76 * scale + 10 * scale

    # 4. Summary Note (Bottom)
    if summary:
        draw.rounded_rectangle(
            [(36 * scale, curr_y), (sw - 36 * scale, curr_y + 48 * scale)],
            radius=8 * scale,
            fill=(24, 32, 47, 240),
            outline=(56, 189, 248, 120),
            width=1 * scale,
        )
        max_sum_w = sw - 72 * scale - 40 * scale
        sum_text = truncate_text_to_width(draw, f"📌  {summary}", font_summary, max_sum_w)
        draw.text((52 * scale, curr_y + 15 * scale), sum_text, fill=(248, 250, 252, 255), font=font_summary)

    final_output = img.resize((width, total_height // scale), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    final_output.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
