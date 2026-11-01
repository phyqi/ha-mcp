"""High-performance, pure-Python sensor history chart drawer using Pillow."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Curated modern palette for dark theme
PALETTE = [
    (56, 189, 248),  # Sky 400
    (52, 211, 153),  # Emerald 400
    (251, 191, 36),  # Amber 400
    (244, 114, 182),  # Pink 400
    (192, 132, 252),  # Purple 400
    (129, 140, 248),  # Indigo 400
]


def _get_font(size: int = 14) -> ImageFont.ImageFont:
    """Load default cross-platform font with specified size."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_sensor_chart(
    series: list[dict[str, Any]],
    title: str = "Sensor History Chart",
    subtitle: str | None = None,
    width: int = 1000,
    height: int = 560,
) -> bytes:
    """Render a time-series line/area chart for one or more sensor series to PNG bytes.

    Args:
        series: List of dicts, each with keys:
            - 'name': Display name (e.g., 'Suhu Ruang Tamu')
            - 'unit': Unit of measurement (e.g., '°C')
            - 'points': List of (timestamp_seconds, float_value) tuples, sorted by timestamp.
        title: Chart title.
        subtitle: Optional subtitle (e.g., '24 Jam Terakhir').
        width: Canvas width in pixels.
        height: Canvas height in pixels.

    Returns:
        PNG image bytes.
    """
    img = Image.new("RGBA", (width, height), (15, 23, 42, 255))  # Slate 900
    draw = ImageDraw.Draw(img)

    # Outer border / card
    draw.rounded_rectangle(
        [(10, 10), (width - 10, height - 10)],
        radius=16,
        fill=(17, 24, 39, 255),  # Gray 900
        outline=(30, 41, 59, 255),  # Slate 800
        width=2,
    )

    font_title = _get_font(20)
    font_subtitle = _get_font(12)
    font_labels = _get_font(11)
    font_stats = _get_font(12)

    # 1. Header (Title & Subtitle)
    draw.text((36, 28), title, fill=(248, 250, 252, 255), font=font_title)
    sub = subtitle or datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    draw.text((36, 56), sub, fill=(148, 163, 184, 255), font=font_subtitle)

    # Filter out series with empty points
    valid_series = [s for s in series if s.get("points")]

    # Plot margins
    plot_left = 70
    plot_top = 100
    plot_right = width - 40
    plot_bottom = height - 60
    plot_w = plot_right - plot_left
    plot_h = plot_bottom - plot_top

    if not valid_series:
        # Empty state
        draw.text(
            (width // 2 - 120, height // 2 - 10),
            "Tidak ada data riwayat untuk ditampilkan",
            fill=(148, 163, 184, 255),
            font=_get_font(16),
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
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
        min_ts -= 1800  # -30min
        max_ts += 1800  # +30min

    min_v, max_v = min(all_vals), max(all_vals)
    if min_v == max_v:
        min_v -= 1.0
        max_v += 1.0
    else:
        # Add 10% vertical padding
        pad = (max_v - min_v) * 0.1
        min_v -= pad
        max_v += pad

    # 2. Draw Gridlines & Y-Axis Labels (5 horizontal lines)
    num_y_ticks = 5
    for i in range(num_y_ticks):
        y = plot_bottom - (i / (num_y_ticks - 1)) * plot_h
        val = min_v + (i / (num_y_ticks - 1)) * (max_v - min_v)

        # Dotted line
        for x in range(plot_left, plot_right, 8):
            draw.line([(x, y), (min(x + 4, plot_right), y)], fill=(30, 41, 59, 255), width=1)

        val_text = f"{val:.1f}" if abs(val) < 100 else f"{int(round(val))}"
        unit = valid_series[0].get("unit", "")
        if unit:
            val_text = f"{val_text} {unit}"
        draw.text((plot_left - 62, y - 7), val_text, fill=(100, 116, 139, 255), font=font_labels)

    # 3. Draw X-Axis Time Labels (4-5 ticks)
    num_x_ticks = 5
    for i in range(num_x_ticks):
        x = plot_left + (i / (num_x_ticks - 1)) * plot_w
        ts = min_ts + (i / (num_x_ticks - 1)) * (max_ts - min_ts)
        dt = datetime.fromtimestamp(ts, tz=UTC)
        time_text = dt.strftime("%H:%M")
        draw.text((x - 14, plot_bottom + 10), time_text, fill=(100, 116, 139, 255), font=font_labels)

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

        # Fill semi-transparent area under the first series
        if idx == 0 and len(screen_coords) >= 2:
            fill_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(fill_overlay)
            poly_coords = [
                (screen_coords[0][0], plot_bottom),
                *screen_coords,
                (screen_coords[-1][0], plot_bottom),
            ]
            fill_color = (*color_rgb, 35)  # 14% opacity
            overlay_draw.polygon(poly_coords, fill=fill_color)
            img = Image.alpha_composite(img, fill_overlay)
            draw = ImageDraw.Draw(img)

        # Draw line
        if len(screen_coords) >= 2:
            draw.line(screen_coords, fill=(*color_rgb, 255), width=3)
        elif len(screen_coords) == 1:
            px, py = screen_coords[0]
            draw.ellipse([(px - 4, py - 4), (px + 4, py + 4)], fill=(*color_rgb, 255))

        # Highlight last point
        last_x, last_y = screen_coords[-1]
        draw.ellipse([(last_x - 5, last_y - 5), (last_x + 5, last_y + 5)], fill=(*color_rgb, 255))
        draw.ellipse([(last_x - 2, last_y - 2), (last_x + 2, last_y + 2)], fill=(255, 255, 255, 255))

        # Gather stats for first series (top header pills)
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
        draw.text((width - 450, 34), stat_text, fill=(56, 189, 248, 255), font=font_stats)

    # 6. Legend at bottom
    legend_x = plot_left
    legend_y = height - 26
    for idx, s in enumerate(valid_series):
        c_rgb = PALETTE[idx % len(PALETTE)]
        draw.rounded_rectangle(
            [(legend_x, legend_y), (legend_x + 14, legend_y + 14)],
            radius=4,
            fill=(*c_rgb, 255),
        )
        legend_label = s.get("name") or s.get("entity_id", f"Series {idx + 1}")
        draw.text((legend_x + 20, legend_y), legend_label, fill=(203, 213, 225, 255), font=font_labels)
        legend_x += len(legend_label) * 8 + 40

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
