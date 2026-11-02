"""High-quality visual infographic drawer with 2x supersampling for Home Assistant."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from .font_loader import get_font, truncate_text_to_width

# Status colors for infographic elements (vibrant, high-contrast, WCAG-legible)
STATUS_COLORS = {
    "ok": (52, 211, 153),      # Emerald 400 (Vibrant, high contrast)
    "normal": (52, 211, 153),
    "safe": (52, 211, 153),
    "success": (52, 211, 153),
    "locked": (52, 211, 153),
    "closed": (52, 211, 153),
    "info": (56, 189, 248),    # Sky 400 (Vivid Cyan)
    "active": (56, 189, 248),
    "on": (56, 189, 248),
    "cool": (56, 189, 248),
    "warning": (251, 191, 36), # Amber 400 (Crisp Gold)
    "alert": (251, 191, 36),
    "caution": (251, 191, 36),
    "open": (251, 191, 36),
    "error": (248, 113, 113),  # Rose 400 (Vivid Red)
    "danger": (248, 113, 113),
    "unlocked": (248, 113, 113),
    "off": (186, 199, 214),    # Slate 250 (Clear silver, never blends into background)
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
                max_h = 460 * scale  # max hero height for visual balance
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

    # Group sections into 2-column rows for symmetrical alignment
    sec_rows: list[list[dict[str, Any]]] = []
    for i in range(0, len(secs), 2):
        sec_rows.append(secs[i : i + 2])

    # Dynamic canvas height calculation
    curr_y = 100 * scale

    # Camera hero height
    if cam_img:
        curr_y += cam_target_h + 24 * scale

    # KPI row height
    if kpis:
        curr_y += 105 * scale

    # Progress bars height
    if bars:
        curr_y += (len(bars) * 44 + 30) * scale

    # Section rows height (symmetrical per row)
    if secs:
        for row in sec_rows:
            row_max_items = max(len(s.get("items", [])) for s in row)
            row_h = (44 + row_max_items * 38 + 14) * scale
            curr_y += row_h + 16 * scale

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
    badge_w = 110 * scale
    badge_h = 30 * scale
    badge_x = sw - 36 * scale - badge_w
    badge_y = 34 * scale

    font_title = get_font(22 * scale, bold=True)
    font_sub = get_font(12 * scale)
    max_title_w = badge_x - 36 * scale - 20 * scale

    title_to_draw = truncate_text_to_width(draw, title, font_title, max_title_w)
    draw.text((36 * scale, 28 * scale), title_to_draw, fill=(255, 255, 255, 255), font=font_title)

    sub = subtitle or datetime.now(UTC).strftime("%A, %d %B %Y • %H:%M UTC")
    sub_to_draw = truncate_text_to_width(draw, sub, font_sub, max_title_w)
    draw.text((36 * scale, 60 * scale), sub_to_draw, fill=(203, 213, 225, 255), font=font_sub)

    # Live Status Badge
    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
        radius=15 * scale,
        fill=(52, 211, 153, 35),
        outline=(52, 211, 153, 200),
        width=1 * scale,
    )
    draw.ellipse(
        [(badge_x + 14 * scale, badge_y + 11 * scale), (badge_x + 22 * scale, badge_y + 19 * scale)],
        fill=(52, 211, 153, 255),
    )
    draw.text(
        (badge_x + 30 * scale, badge_y + 7 * scale),
        "LIVE HA",
        fill=(52, 211, 153, 255),
        font=get_font(12 * scale, bold=True),
    )

    y_pos = 96 * scale

    # 2. Camera Snapshot Hero (Aspect ratio strictly preserved)
    if cam_img:
        mask = Image.new("L", (cam_target_w, cam_target_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (cam_target_w, cam_target_h)], radius=14 * scale, fill=255)

        img.paste(cam_img, (cam_x, y_pos), mask)
        draw.rounded_rectangle(
            [(cam_x, y_pos), (cam_x + cam_target_w, y_pos + cam_target_h)],
            radius=14 * scale,
            outline=(55, 65, 81, 255),
            width=2 * scale,
        )
        # Camera banner label
        draw.rounded_rectangle(
            [(cam_x + 12 * scale, y_pos + 12 * scale), (cam_x + 148 * scale, y_pos + 36 * scale)],
            radius=6 * scale,
            fill=(0, 0, 0, 200),
            outline=(75, 85, 99, 200),
            width=1 * scale,
        )
        draw.text(
            (cam_x + 20 * scale, y_pos + 16 * scale),
            "📷 CAMERA SNAPSHOT",
            fill=(255, 255, 255, 255),
            font=get_font(10 * scale, bold=True),
        )
        y_pos += cam_target_h + 24 * scale

    # Empty State Notice if no content is provided
    if not kpis and not bars and not secs and not summary and not cam_img:
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
            fill=(255, 255, 255, 255),
            font=get_font(16 * scale, bold=True),
            anchor="mm",
        )
        draw.text(
            (sw // 2, y_pos + 100 * scale),
            "Hubungkan perangkat ke Home Assistant atau berikan parameter metrik ke tool.",
            fill=(203, 213, 225, 255),
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
                outline=(45, 55, 72, 255),
                width=1 * scale,
            )

            # Left accent stripe
            draw.rounded_rectangle(
                [(cx, cy + 12 * scale), (cx + 4 * scale, cy + card_h - 12 * scale)],
                radius=2 * scale,
                fill=(*color, 255),
            )

            # Label (Clear high contrast Slate 300)
            font_k_lbl = get_font(10 * scale, bold=True)
            k_lbl_txt = truncate_text_to_width(draw, str(k.get("label", "")).upper(), font_k_lbl, card_w - 28 * scale)
            draw.text(
                (cx + 16 * scale, cy + 12 * scale),
                k_lbl_txt,
                fill=(203, 213, 225, 255),
                font=font_k_lbl,
            )

            # Large Value (Pure White)
            font_k_val = get_font(18 * scale, bold=True)
            val_str = truncate_text_to_width(draw, str(k.get("value", "")), font_k_val, card_w - 28 * scale)
            draw.text(
                (cx + 16 * scale, cy + 32 * scale),
                val_str,
                fill=(255, 255, 255, 255),
                font=font_k_val,
            )

            # Badge pill
            badge_txt = str(k.get("badge", "")).upper()
            if badge_txt:
                font_badge_k = get_font(9 * scale, bold=True)
                bw = int(draw.textlength(badge_txt, font=font_badge_k)) + 16 * scale
                bw = min(bw, card_w - 32 * scale)
                badge_txt = truncate_text_to_width(draw, badge_txt, font_badge_k, bw - 16 * scale)
                draw.rounded_rectangle(
                    [(cx + 16 * scale, cy + 62 * scale), (cx + 16 * scale + bw, cy + 78 * scale)],
                    radius=8 * scale,
                    fill=(*color, 45),
                    outline=(*color, 180),
                    width=1 * scale,
                )
                draw.text(
                    (cx + 24 * scale, cy + 65 * scale),
                    badge_txt,
                    fill=(*color, 255),
                    font=font_badge_k,
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

            # Text row (High contrast labels, measured to avoid collision)
            font_bar_v = get_font(11 * scale, bold=True)
            font_bar_lbl = get_font(12 * scale, bold=True)
            v_w = int(draw.textlength(v_text, font=font_bar_v))
            v_x = sw - 36 * scale - v_w

            max_bar_lbl_w = v_x - 36 * scale - 16 * scale
            lbl_to_draw = truncate_text_to_width(draw, label, font_bar_lbl, max_bar_lbl_w)

            draw.text((36 * scale, y_pos), lbl_to_draw, fill=(248, 250, 252, 255), font=font_bar_lbl)
            draw.text(
                (v_x, y_pos),
                v_text,
                fill=(226, 232, 240, 255),
                font=font_bar_v,
            )

            # Track bar with subtle outline
            bar_y = y_pos + 18 * scale
            bar_h = 10 * scale
            draw.rounded_rectangle(
                [(36 * scale, bar_y), (36 * scale + pw, bar_y + bar_h)],
                radius=5 * scale,
                fill=(30, 41, 59, 255),
                outline=(51, 65, 85, 255),
                width=1 * scale,
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

    # 5. Grouped Category Sections (Symmetrical 2-column layout)
    if secs:
        col_w = (sw - 72 * scale - 16 * scale) // 2
        for row in sec_rows:
            row_max_items = max(len(s.get("items", [])) for s in row)
            row_h = (44 + row_max_items * 38 + 14) * scale

            for col_idx, sec in enumerate(row):
                col_x = 36 * scale + col_idx * (col_w + 16 * scale)
                cat_title = str(sec.get("category", "")).upper()
                items = sec.get("items", [])

                # Category container
                draw.rounded_rectangle(
                    [(col_x, y_pos), (col_x + col_w, y_pos + row_h)],
                    radius=12 * scale,
                    fill=(20, 27, 39, 255),
                    outline=(45, 55, 72, 255),
                    width=1 * scale,
                )

                # Category header (Sky 400)
                font_cat = get_font(11 * scale, bold=True)
                cat_title_to_draw = truncate_text_to_width(draw, cat_title, font_cat, col_w - 32 * scale)
                draw.text(
                    (col_x + 16 * scale, y_pos + 14 * scale),
                    cat_title_to_draw,
                    fill=(56, 189, 248, 255),
                    font=font_cat,
                )
                # Divider line under category header
                draw.line(
                    [(col_x + 14 * scale, y_pos + 36 * scale), (col_x + col_w - 14 * scale, y_pos + 36 * scale)],
                    fill=(37, 48, 67, 255),
                    width=1 * scale,
                )

                # Items inside category
                font_item_name = get_font(11 * scale)
                font_item_badge = get_font(10 * scale, bold=True)

                for j, item in enumerate(items):
                    iy = y_pos + (44 + j * 38) * scale
                    iname = str(item.get("name", ""))
                    istate = str(item.get("state", "")).strip()
                    istat = str(item.get("status", "ok")).lower()
                    icolor = STATUS_COLORS.get(istat, (186, 199, 214))

                    # State pill badge (Bordered, high contrast)
                    badge_w = int(draw.textlength(istate, font=font_item_badge)) + 16 * scale
                    badge_x = col_x + col_w - 16 * scale - badge_w

                    # Status indicator dot
                    draw.ellipse(
                        [(col_x + 16 * scale, iy + 6 * scale), (col_x + 24 * scale, iy + 14 * scale)],
                        fill=(*icolor, 255),
                    )

                    # Name (Pure crisp white, truncated to never overlap badge)
                    max_iname_w = badge_x - (col_x + 32 * scale) - 12 * scale
                    iname_to_draw = truncate_text_to_width(draw, iname, font_item_name, max_iname_w)
                    draw.text(
                        (col_x + 32 * scale, iy + 3 * scale),
                        iname_to_draw,
                        fill=(248, 250, 252, 255),
                        font=font_item_name,
                    )

                    draw.rounded_rectangle(
                        [(badge_x, iy), (badge_x + badge_w, iy + 20 * scale)],
                        radius=6 * scale,
                        fill=(*icolor, 35),
                        outline=(*icolor, 140),
                        width=1 * scale,
                    )
                    draw.text(
                        (badge_x + 8 * scale, iy + 3 * scale),
                        istate,
                        fill=(*icolor, 255),
                        font=font_item_badge,
                    )

            y_pos += row_h + 16 * scale

    # 6. Executive AI Summary Callout (Bottom)
    if summary:
        box_w = sw - 72 * scale
        box_h = 52 * scale
        draw.rounded_rectangle(
            [(36 * scale, y_pos), (36 * scale + box_w, y_pos + box_h)],
            radius=10 * scale,
            fill=(24, 32, 47, 240),
            outline=(56, 189, 248, 120),
            width=1 * scale,
        )
        # Accent bar
        draw.rounded_rectangle(
            [(36 * scale, y_pos), (42 * scale, y_pos + box_h)],
            radius=3 * scale,
            fill=(56, 189, 248, 255),
        )
        font_summary = get_font(12 * scale)
        max_sum_w = box_w - 48 * scale
        sum_to_draw = truncate_text_to_width(draw, f"💡  {summary}", font_summary, max_sum_w)
        draw.text(
            (56 * scale, y_pos + 16 * scale),
            sum_to_draw,
            fill=(248, 250, 252, 255),
            font=font_summary,
        )

    # 7. Supersample Downscale (Lanczos anti-aliasing)
    final_output = img.resize((width, final_h // scale), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    final_output.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

