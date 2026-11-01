"""High-performance, pure-Python sensor history chart drawer with 2x supersampling."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from .font_loader import get_font

# Curated modern palette for dark theme
PALETTE = [
    (56, 189, 248),  # Sky 400
    (52, 211, 153),  # Emerald 400
    (251, 191, 36),  # Amber 400
    (244, 114, 182),  # Pink 400
    (192, 132, 252),  # Purple 400
    (129, 140, 248),  # Indigo 400
]


def render_sensor_chart(
    series: list[dict[str, Any]],
    title: str = "Sensor History Chart",
    subtitle: str | None = None,
    width: int = 1000,
    height: int = 560,
) -> bytes:
    """Render a time-series line/area chart with 2x supersampling to PNG bytes."""
    scale = 2
    sw = width * scale
    sh = height * scale

    img = Image.new("RGBA", (sw, sh), (15, 23, 42, 255))  # Slate 900
    draw = ImageDraw.Draw(img)

    # Outer border / card
    draw.rounded_rectangle(
        [(10 * scale, 10 * scale), (sw - 10 * scale, sh - 10 * scale)],
        radius=16 * scale,
        fill=(17, 24, 39, 255),  # Gray 900
        outline=(30, 41, 59, 255),  # Slate 800
        width=2 * scale,
    )

    font_title = get_font(20 * scale, bold=True)
    font_subtitle = get_font(12 * scale)
    font_labels = get_font(11 * scale)
    font_stats = get_font(12 * scale, bold=True)

    # 1. Header (Title & Subtitle)
    draw.text((36 * scale, 28 * scale), title, fill=(248, 250, 252, 255), font=font_title)
    sub = subtitle or datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    draw.text((36 * scale, 58 * scale), sub, fill=(148, 163, 184, 255), font=font_subtitle)

    # Filter out series with empty points
    valid_series = [s for s in series if s.get("points")]

    # Plot margins
    plot_left = 75 * scale
    plot_top = 105 * scale
    plot_right = sw - 40 * scale
    plot_bottom = sh - 65 * scale
    plot_w = plot_right - plot_left
    plot_h = plot_bottom - plot_top

    if not valid_series:
        draw.text(
            (sw // 2 - 140 * scale, sh // 2 - 10 * scale),
            "Tidak ada data riwayat untuk ditampilkan",
            fill=(148, 163, 184, 255),
            font=get_font(16 * scale),
        )
        final_img = img.resize((width, height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        final_img.save(buf, format="PNG")
        return buf.getvalue()

    # Determine global min/max for timestamp and value
    all_ts: list[float] = []
    all_vals: list[float] = []
    for s in valid_series:
        for ts, v in s["points"]:
            all_ts.append(ts)
            all_vals.append(v)

    min_ts, max_ts = min(all_ts), max(all_ts)
    if min_ts == max_ts:
        min_ts -= 1800
        max_ts += 1800

    min_v, max_v = min(all_vals), max(all_vals)
    if min_v == max_v:
        min_v -= 1.0
        max_v += 1.0
    else:
        pad = (max_v - min_v) * 0.1
        min_v -= pad
        max_v += pad

    # 2. Draw Gridlines & Y-Axis Labels (5 horizontal lines)
    num_y_ticks = 5
    for i in range(num_y_ticks):
        y = plot_bottom - (i / (num_y_ticks - 1)) * plot_h
        val = min_v + (i / (num_y_ticks - 1)) * (max_v - min_v)

        for x in range(plot_left, plot_right, 14 * scale):
            draw.line([(x, y), (min(x + 7 * scale, plot_right), y)], fill=(30, 41, 59, 255), width=1 * scale)

        val_text = f"{val:.1f}" if abs(val) < 100 else f"{int(round(val))}"
        unit = valid_series[0].get("unit", "")
        if unit:
            val_text = f"{val_text} {unit}"
        draw.text((plot_left - 65 * scale, y - 8 * scale), val_text, fill=(100, 116, 139, 255), font=font_labels)

    # 3. Draw X-Axis Time Labels (5 ticks)
    num_x_ticks = 5
    for i in range(num_x_ticks):
        x = plot_left + (i / (num_x_ticks - 1)) * plot_w
        ts = min_ts + (i / (num_x_ticks - 1)) * (max_ts - min_ts)
        dt = datetime.fromtimestamp(ts, tz=UTC)
        time_text = dt.strftime("%H:%M")
        draw.text((x - 16 * scale, plot_bottom + 12 * scale), time_text, fill=(100, 116, 139, 255), font=font_labels)

    # 4. Plot each series (Area + Line + Points)
    primary_stats: dict[str, Any] = {}

    for idx, s in enumerate(valid_series):
        color_rgb = PALETTE[idx % len(PALETTE)]
        pts = s["points"]
        if not pts:
            continue

        screen_coords: list[tuple[float, float]] = []
        for ts, v in pts:
            px = plot_left + ((ts - min_ts) / (max_ts - min_ts)) * plot_w
            py = plot_bottom - ((v - min_v) / (max_v - min_v)) * plot_h
            screen_coords.append((px, py))

        # Fill semi-transparent area under first series
        if idx == 0 and len(screen_coords) >= 2:
            fill_overlay = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(fill_overlay)
            poly_coords = [
                (screen_coords[0][0], plot_bottom),
                *screen_coords,
                (screen_coords[-1][0], plot_bottom),
            ]
            overlay_draw.polygon(poly_coords, fill=(*color_rgb, 40))
            img = Image.alpha_composite(img, fill_overlay)
            draw = ImageDraw.Draw(img)

        # Draw anti-aliased line
        if len(screen_coords) >= 2:
            draw.line(screen_coords, fill=(*color_rgb, 255), width=3 * scale)
        elif len(screen_coords) == 1:
            px, py = screen_coords[0]
            draw.ellipse([(px - 5 * scale, py - 5 * scale), (px + 5 * scale, py + 5 * scale)], fill=(*color_rgb, 255))

        # Highlight last point
        last_x, last_y = screen_coords[-1]
        draw.ellipse([(last_x - 6 * scale, last_y - 6 * scale), (last_x + 6 * scale, last_y + 6 * scale)], fill=(*color_rgb, 255))
        draw.ellipse([(last_x - 3 * scale, last_y - 3 * scale), (last_x + 3 * scale, last_y + 3 * scale)], fill=(255, 255, 255, 255))

        if idx == 0:
            vals = [v for _, v in pts]
            primary_stats = {
                "current": vals[-1],
                "min": min(vals),
                "max": max(vals),
                "avg": sum(vals) / len(vals),
                "unit": s.get("unit", ""),
            }

    # 5. Header Summary Stats Pills (Top Right)
    if primary_stats:
        u = primary_stats["unit"]
        cur_str = f"Now: {primary_stats['current']:.1f}{u}"
        min_str = f"Min: {primary_stats['min']:.1f}{u}"
        max_str = f"Max: {primary_stats['max']:.1f}{u}"
        avg_str = f"Avg: {primary_stats['avg']:.1f}{u}"
        stat_text = f"{cur_str}   |   {min_str}   |   {max_str}   |   {avg_str}"
        draw.text((sw - 480 * scale, 34 * scale), stat_text, fill=(56, 189, 248, 255), font=font_stats)

    # 6. Legend at bottom
    legend_x = plot_left
    legend_y = sh - 32 * scale
    for idx, s in enumerate(valid_series):
        c_rgb = PALETTE[idx % len(PALETTE)]
        draw.rounded_rectangle(
            [(legend_x, legend_y), (legend_x + 14 * scale, legend_y + 14 * scale)],
            radius=4 * scale,
            fill=(*c_rgb, 255),
        )
        legend_label = s.get("name") or s.get("entity_id", f"Series {idx + 1}")
        draw.text((legend_x + 20 * scale, legend_y), legend_label, fill=(203, 213, 225, 255), font=font_labels)
        legend_x += (len(legend_label) * 8 + 40) * scale

    # Downscale for crisp anti-aliasing
    final_output = img.resize((width, height), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    final_output.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
