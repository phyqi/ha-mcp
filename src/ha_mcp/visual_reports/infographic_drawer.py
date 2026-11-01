"""High-quality visual infographic drawer with 2x supersampling for Home Assistant."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from .font_loader import get_font

# Status colors for infographic elements
STATUS_COLORS = {
    "ok": (16, 185, 129),  # Emerald 500
    "normal": (16, 185, 129),
    "safe": (16, 185, 129),
    "success": (16, 185, 129),
    "locked": (16, 185, 129),
    "info": (56, 189, 248),  # Sky 400
    "active": (56, 189, 248),
    "on": (56, 189, 248),
    "cool": (56, 189, 248),
    "warning": (245, 158, 11),  # Amber 500
    "alert": (245, 158, 11),
    "caution": (245, 158, 11),
    "error": (239, 68, 68),  # Rose 500
    "danger": (239, 68, 68),
    "unlocked": (239, 68, 68),
    "open": (245, 158, 11),
    "off": (100, 116, 139),  # Slate 500
    "closed": (16, 185, 129),
}


def render_infographic(
    title: str = "INFOGRAFIS STATUS RUMAH",
    subtitle: str | None = None,
    kpi_highlights: list[dict[str, Any]] | None = None,
    progress_bars: list[dict[str, Any]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    camera_image_bytes: bytes | None = None,
    width: int = 1000,
) -> bytes:
    """Render a premium, modern dashboard infographic using 2x supersampling.

    Args:
        title: Main infographic header title.
        subtitle: Subtitle or timestamp line.
        kpi_highlights: 2-4 primary KPI boxes at top, each with:
            - 'label': str (e.g. 'Suhu Rata-rata')
            - 'value': str (e.g. '24.2 °C')
            - 'badge': str (e.g. 'SEJUK')
            - 'status': str ('ok', 'info', 'warning', 'error')
        progress_bars: List of gauge/progress bars, each with:
            - 'label': str (e.g. 'Beban Daya Listrik')
            - 'value_text': str (e.g. '650 W / 2200 W (30%)')
            - 'percent': float (0.0 to 100.0)
            - 'status': str
        sections: List of grouped category cards, each with:
            - 'category': str (e.g. 'Keamanan & Pintu', 'Klimat & Suhu')
            - 'items': list of {'name': str, 'state': str, 'status': str}
        summary: AI analysis note or briefing at bottom.
        camera_image_bytes: Optional snapshot bytes to display as hero preview.
        width: Final image width in pixels.

    Returns:
        PNG image bytes.
    """
    scale = 2  # 2x Retina Supersampling
    sw = width * scale

    kpis = kpi_highlights or []
    bars = progress_bars or []
    secs = sections or []

    # Calculate dynamic height
    curr_y = 100 * scale

    # Camera hero height
    cam_h = 240 * scale if camera_image_bytes else 0
    if camera_image_bytes:
        curr_y += cam_h + 24 * scale

    # KPI row height
    if kpis:
        curr_y += 105 * scale

    # Progress bars height
    if bars:
        curr_y += (len(bars) * 44 + 40) * scale

    # Section items height
    total_sec_items = sum(len(s.get("items", [])) for s in secs)
    if secs:
        curr_y += (len(secs) * 36 + total_sec_items * 38 + 20) * scale

    # Summary callout height
    if summary:
        curr_y += 75 * scale

    final_h = max(600 * scale, curr_y + 40 * scale)

    # Base canvas
    img = Image.new("RGBA", (sw, final_h), (11, 15, 23, 255))  # Deep Slate 950
    draw = ImageDraw.Draw(img)

    # Outer container border
    draw.rounded_rectangle(
        [(12 * scale, 12 * scale), (sw - 12 * scale, final_h - 12 * scale)],
        radius=20 * scale,
        fill=(17, 24, 39, 255),  # Gray 900
        outline=(31, 41, 55, 255),  # Gray 800
        width=2 * scale,
    )

    # 1. Header Banner
    draw.text((36 * scale, 28 * scale), title, fill=(248, 250, 252, 255), font=get_font(22 * scale, bold=True))
    sub = subtitle or datetime.now(UTC).strftime("%A, %d %B %Y • %H:%M UTC")
    draw.text((36 * scale, 60 * scale), sub, fill=(148, 163, 184, 255), font=get_font(12 * scale))

    # Live Status Badge
    badge_w = 110 * scale
    badge_h = 30 * scale
    badge_x = sw - 36 * scale - badge_w
    badge_y = 34 * scale
    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
        radius=15 * scale,
        fill=(16, 185, 129, 30),
        outline=(16, 185, 129, 200),
        width=1 * scale,
    )
    draw.ellipse(
        [(badge_x + 14 * scale, badge_y + 11 * scale), (badge_x + 22 * scale, badge_y + 19 * scale)],
        fill=(16, 185, 129, 255),
    )
    draw.text(
        (badge_x + 30 * scale, badge_y + 7 * scale),
        "LIVE HA",
        fill=(16, 185, 129, 255),
        font=get_font(12 * scale, bold=True),
    )

    y_pos = 96 * scale

    # 2. Camera Snapshot Hero (if present)
    if camera_image_bytes:
        try:
            cam_img = Image.open(io.BytesIO(camera_image_bytes)).convert("RGBA")
            target_w = sw - 72 * scale
            target_h = 230 * scale
            cam_img = cam_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

            mask = Image.new("L", (target_w, target_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (target_w, target_h)], radius=14 * scale, fill=255)

            img.paste(cam_img, (36 * scale, y_pos), mask)
            draw.rounded_rectangle(
                [(36 * scale, y_pos), (36 * scale + target_w, y_pos + target_h)],
                radius=14 * scale,
                outline=(55, 65, 81, 255),
                width=2 * scale,
            )
            # Camera banner label
            draw.rounded_rectangle(
                [(48 * scale, y_pos + 12 * scale), (180 * scale, y_pos + 36 * scale)],
                radius=6 * scale,
                fill=(0, 0, 0, 180),
            )
            draw.text(
                (58 * scale, y_pos + 16 * scale),
                "📷 CAMERA SNAPSHOT",
                fill=(248, 250, 252, 255),
                font=get_font(10 * scale, bold=True),
            )
            y_pos += target_h + 20 * scale
        except Exception:  # noqa: BLE001
            pass

    # Empty State Notice if no content is provided
    if not kpis and not bars and not secs and not summary and not camera_image_bytes:
        box_w = sw - 72 * scale
        box_h = 160 * scale
        draw.rounded_rectangle(
            [(36 * scale, y_pos), (36 * scale + box_w, y_pos + box_h)],
            radius=12 * scale,
            fill=(24, 32, 47, 255),
            outline=(51, 65, 85, 255),
            width=1 * scale,
        )
        draw.text(
            (sw // 2, y_pos + 60 * scale),
            "Tidak Ada Data Perangkat atau Sensor Ditemukan",
            fill=(248, 250, 252, 255),
            font=get_font(16 * scale, bold=True),
            anchor="mm",
        )
        draw.text(
            (sw // 2, y_pos + 100 * scale),
            "Hubungkan perangkat ke Home Assistant atau berikan parameter metrik ke tool.",
            fill=(148, 163, 184, 255),
            font=get_font(12 * scale),
            anchor="mm",
        )
        y_pos += box_h + 20 * scale

    # 3. KPI Highlights Cards (Row of 3-4 cards)
    if kpis:
        num_kpis = min(len(kpis), 4)
        gap = 14 * scale
        card_w = (sw - 72 * scale - (num_kpis - 1) * gap) // num_kpis
        card_h = 88 * scale

        for i in range(num_kpis):
            k = kpis[i]
            cx = 36 * scale + i * (card_w + gap)
            cy = y_pos

            status_key = str(k.get("status", "info")).lower()
            color = STATUS_COLORS.get(status_key, (56, 189, 248))

            # Card box
            draw.rounded_rectangle(
                [(cx, cy), (cx + card_w, cy + card_h)],
                radius=12 * scale,
                fill=(24, 32, 47, 255),  # Slate 850
                outline=(37, 48, 67, 255),
                width=1 * scale,
            )

            # Left accent stripe
            draw.rounded_rectangle(
                [(cx, cy + 12 * scale), (cx + 4 * scale, cy + card_h - 12 * scale)],
                radius=2 * scale,
                fill=(*color, 255),
            )

            # Label
            draw.text(
                (cx + 16 * scale, cy + 12 * scale),
                str(k.get("label", "")).upper(),
                fill=(148, 163, 184, 255),
                font=get_font(10 * scale, bold=True),
            )

            # Large Value
            val_str = str(k.get("value", ""))
            draw.text(
                (cx + 16 * scale, cy + 32 * scale),
                val_str,
                fill=(248, 250, 252, 255),
                font=get_font(18 * scale, bold=True),
            )

            # Badge pill
            badge_txt = str(k.get("badge", "")).upper()
            if badge_txt:
                bw = (len(badge_txt) * 7 + 16) * scale
                draw.rounded_rectangle(
                    [(cx + 16 * scale, cy + 62 * scale), (cx + 16 * scale + bw, cy + 78 * scale)],
                    radius=8 * scale,
                    fill=(*color, 35),
                )
                draw.text(
                    (cx + 24 * scale, cy + 65 * scale),
                    badge_txt,
                    fill=(*color, 255),
                    font=get_font(9 * scale, bold=True),
                )

        y_pos += card_h + 20 * scale

    # 4. Progress Bars / Gauge Section
    if bars:
        pw = sw - 72 * scale
        for b in bars:
            label = str(b.get("label", ""))
            v_text = str(b.get("value_text", ""))
            pct = max(0.0, min(100.0, float(b.get("percent", 0.0))))
            b_status = str(b.get("status", "ok")).lower()
            b_color = STATUS_COLORS.get(b_status, (56, 189, 248))

            # Text row
            draw.text((36 * scale, y_pos), label, fill=(226, 232, 240, 255), font=get_font(12 * scale, bold=True))
            draw.text(
                (sw - 36 * scale - len(v_text) * 7 * scale, y_pos),
                v_text,
                fill=(148, 163, 184, 255),
                font=get_font(11 * scale),
            )

            # Track bar
            bar_y = y_pos + 18 * scale
            bar_h = 10 * scale
            draw.rounded_rectangle(
                [(36 * scale, bar_y), (36 * scale + pw, bar_y + bar_h)],
                radius=5 * scale,
                fill=(30, 41, 59, 255),
            )
            # Filled bar
            if pct > 0:
                fill_w = int(pw * (pct / 100.0))
                draw.rounded_rectangle(
                    [(36 * scale, bar_y), (36 * scale + fill_w, bar_y + bar_h)],
                    radius=5 * scale,
                    fill=(*b_color, 255),
                )

            y_pos += 40 * scale

        y_pos += 8 * scale

    # 5. Grouped Category Sections (2-column layout)
    if secs:
        col_w = (sw - 72 * scale - 16 * scale) // 2
        for idx, sec in enumerate(secs):
            col = idx % 2
            row = idx // 2
            col_x = 36 * scale + col * (col_w + 16 * scale)
            sec_y = y_pos + row * 160 * scale

            cat_title = str(sec.get("category", "")).upper()
            items = sec.get("items", [])

            # Category container
            box_h = (36 + len(items) * 36) * scale
            draw.rounded_rectangle(
                [(col_x, sec_y), (col_x + col_w, sec_y + box_h)],
                radius=10 * scale,
                fill=(20, 27, 39, 255),
                outline=(31, 41, 55, 255),
                width=1 * scale,
            )

            # Category header
            draw.text(
                (col_x + 14 * scale, sec_y + 10 * scale),
                cat_title,
                fill=(56, 189, 248, 255),
                font=get_font(11 * scale, bold=True),
            )

            # Items inside category
            for j, item in enumerate(items):
                iy = sec_y + (32 + j * 34) * scale
                iname = str(item.get("name", ""))
                istate = str(item.get("state", ""))
                istat = str(item.get("status", "ok")).lower()
                icolor = STATUS_COLORS.get(istat, (148, 163, 184))

                # Item dot
                draw.ellipse(
                    [(col_x + 16 * scale, iy + 6 * scale), (col_x + 24 * scale, iy + 14 * scale)],
                    fill=(*icolor, 255),
                )
                # Name
                draw.text(
                    (col_x + 32 * scale, iy + 4 * scale),
                    iname,
                    fill=(241, 245, 249, 255),
                    font=get_font(11 * scale),
                )
                # State badge text
                draw.text(
                    (col_x + col_w - 16 * scale - len(istate) * 7 * scale, iy + 4 * scale),
                    istate,
                    fill=(*icolor, 255),
                    font=get_font(11 * scale, bold=True),
                )

        y_pos += ((len(secs) + 1) // 2 * 170) * scale

    # 6. Executive AI Summary Callout (Bottom)
    if summary:
        box_w = sw - 72 * scale
        box_h = 52 * scale
        draw.rounded_rectangle(
            [(36 * scale, y_pos), (36 * scale + box_w, y_pos + box_h)],
            radius=10 * scale,
            fill=(30, 41, 59, 160),
            outline=(51, 65, 85, 255),
            width=1 * scale,
        )
        # Accent bar
        draw.rounded_rectangle(
            [(36 * scale, y_pos), (42 * scale, y_pos + box_h)],
            radius=3 * scale,
            fill=(56, 189, 248, 255),
        )
        draw.text(
            (56 * scale, y_pos + 16 * scale),
            f"💡  {summary}",
            fill=(241, 245, 249, 255),
            font=get_font(12 * scale),
        )

    # 7. Supersample Downscale (Lanczos anti-aliasing)
    final_output = img.resize((width, final_h // scale), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    final_output.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

