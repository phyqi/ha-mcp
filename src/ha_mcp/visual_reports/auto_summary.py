"""Automatic synthesis of home status overview for visual reports and infographics."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def synthesize_home_overview(states: list[dict[str, Any]]) -> dict[str, Any]:
    """Synthesize home status overview from raw Home Assistant states.

    Extracts climate, lighting, power, security, and battery metrics to
    automatically populate visual infographic reports and status cards when
    callers do not provide explicit structured data.

    Args:
        states: List of entity state dictionaries from Home Assistant.

    Returns:
        Dictionary containing:
            - 'title': Suggested main title
            - 'kpi_highlights': List of 2-4 KPI metric tiles
            - 'progress_bars': List of gauge/progress bars
            - 'sections': Grouped device category sections
            - 'summary': Text briefing of home status
            - 'suggested_camera': Camera entity ID if any active camera found
            - 'metrics_for_card': Flat list of metric tiles for status cards
    """
    if not states:
        return {
            "title": "RINGKASAN STATUS RUMAH",
            "kpi_highlights": [],
            "progress_bars": [],
            "sections": [],
            "summary": "Belum ada entitas perangkat yang terdeteksi di Home Assistant.",
            "suggested_camera": None,
            "metrics_for_card": [],
        }

    # 1. Categorize entities
    cameras: list[str] = []
    temp_sensors: list[tuple[str, float, str]] = []  # (name, val, unit)
    humidity_sensors: list[tuple[str, float]] = []  # (name, val)
    power_sensors: list[tuple[str, float, str]] = []  # (name, val, unit)
    lights: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    security_entities: list[dict[str, Any]] = []
    battery_sensors: list[tuple[str, float]] = []

    for s in states:
        eid: str = s.get("entity_id", "")
        state_val: str = str(s.get("state", "")).strip().lower()
        attrs: dict[str, Any] = s.get("attributes", {})
        friendly_name: str = str(attrs.get("friendly_name") or eid)
        dev_class: str = str(attrs.get("device_class") or "").lower()
        unit: str = str(attrs.get("unit_of_measurement") or "").strip()

        # Cameras
        if eid.startswith("camera."):
            if state_val != "unavailable":
                cameras.append(eid)
            continue

        # Lights
        if eid.startswith("light."):
            if state_val not in ("unavailable", "unknown"):
                lights.append({"name": friendly_name, "state": state_val, "eid": eid})
            continue

        # Switches
        if eid.startswith("switch."):
            if state_val not in ("unavailable", "unknown"):
                switches.append({"name": friendly_name, "state": state_val, "eid": eid})
            continue

        # Security & Doors / Windows / Locks
        if (
            eid.startswith("lock.")
            or dev_class in ("door", "garage_door", "window", "opening", "lock", "motion", "presence", "smoke", "gas")
            or any(w in eid.lower() for w in ("pintu", "door", "jendela", "window", "kunci", "lock"))
        ):
            if state_val not in ("unavailable", "unknown"):
                is_alert = state_val in ("on", "open", "unlocked", "problem")
                status = "warning" if is_alert else "ok"
                state_text = "Terbuka" if is_alert else ("Terkunci" if "lock" in eid else "Aman")
                security_entities.append({
                    "name": friendly_name,
                    "state": state_text,
                    "status": status,
                    "eid": eid,
                    "is_alert": is_alert,
                })
            continue

        # Temperature
        if (
            dev_class == "temperature"
            or unit in ("°C", "°F", "K")
            or any(w in eid.lower() for w in ("temperature", "suhu", "temp_"))
        ):
            try:
                val_float = float(state_val)
                temp_sensors.append((friendly_name, val_float, unit or "°C"))
            except (ValueError, TypeError):
                pass
            continue

        # Humidity
        if (
            dev_class == "humidity"
            or (unit == "%" and any(w in eid.lower() for w in ("humidity", "kelembaban", "rh")))
        ):
            try:
                val_float = float(state_val)
                humidity_sensors.append((friendly_name, val_float))
            except (ValueError, TypeError):
                pass
            continue

        # Power / Energy
        if (
            dev_class == "power"
            or unit in ("W", "kW", "VA")
            or any(w in eid.lower() for w in ("power", "daya", "watt"))
        ):
            try:
                val_float = float(state_val)
                power_sensors.append((friendly_name, val_float, unit or "W"))
            except (ValueError, TypeError):
                pass
            continue

        # Battery
        if dev_class == "battery" or (unit == "%" and "bat" in eid.lower()):
            try:
                val_float = float(state_val)
                battery_sensors.append((friendly_name, val_float))
            except (ValueError, TypeError):
                pass
            continue

    # 2. Build KPI Highlights (2-4 tiles)
    kpis: list[dict[str, Any]] = []

    # KPI 1: Climate / Temperature
    avg_temp_val: float | None = None
    temp_unit_str = "°C"
    if temp_sensors:
        avg_temp_val = sum(t[1] for t in temp_sensors) / len(temp_sensors)
        temp_unit_str = temp_sensors[0][2]
        badge = "SEJUK" if avg_temp_val < 26.0 else ("NORMAL" if avg_temp_val < 29.0 else "HANGAT")
        status = "info" if avg_temp_val < 28.0 else "warning"
        kpis.append({
            "label": "Suhu Rata-rata",
            "value": f"{avg_temp_val:.1f} {temp_unit_str}",
            "badge": badge,
            "status": status,
        })
    elif humidity_sensors:
        avg_hum = sum(h[1] for h in humidity_sensors) / len(humidity_sensors)
        kpis.append({
            "label": "Kelembaban",
            "value": f"{avg_hum:.0f} %",
            "badge": "NORMAL",
            "status": "info",
        })

    # KPI 2: Lighting
    lights_on = [l for l in lights if l["state"] == "on"]
    if lights:
        on_cnt = len(lights_on)
        tot_cnt = len(lights)
        kpis.append({
            "label": "Pencahayaan",
            "value": f"{on_cnt} / {tot_cnt} Menyala",
            "badge": f"{on_cnt} AKTIF" if on_cnt > 0 else "PADAM",
            "status": "info" if on_cnt > 0 else "ok",
        })
    elif switches:
        sw_on = [sw for sw in switches if sw["state"] == "on"]
        kpis.append({
            "label": "Saklar / Switch",
            "value": f"{len(sw_on)} / {len(switches)} Aktif",
            "badge": "AKTIF" if sw_on else "OFF",
            "status": "info" if sw_on else "ok",
        })

    # KPI 3: Power Consumption
    total_watts: float = 0.0
    for _, val, u in power_sensors:
        if u.lower() == "kw":
            total_watts += val * 1000.0
        else:
            total_watts += val

    if power_sensors:
        if total_watts < 1000.0:
            val_str = f"{total_watts:.0f} W"
        else:
            val_str = f"{total_watts / 1000.0:.2f} kW"
        badge = "HEMAT" if total_watts < 900.0 else ("NORMAL" if total_watts < 2200.0 else "TINGGI")
        status = "ok" if total_watts < 2200.0 else "warning"
        kpis.append({
            "label": "Konsumsi Daya",
            "value": val_str,
            "badge": badge,
            "status": status,
        })

    # KPI 4: Security Status
    sec_alerts = [s for s in security_entities if s.get("is_alert")]
    if security_entities:
        if sec_alerts:
            kpis.append({
                "label": "Status Keamanan",
                "value": f"{len(sec_alerts)} Perlu Dicek",
                "badge": "PERIKSA",
                "status": "warning",
            })
        else:
            kpis.append({
                "label": "Status Keamanan",
                "value": "Semua Aman",
                "badge": "TERKUNCI",
                "status": "ok",
            })

    # Fallback to make sure we have at least 2 KPIs
    if len(kpis) < 2:
        active_cnt = len([s for s in states if s.get("state") not in ("unavailable", "unknown", "off")])
        kpis.append({
            "label": "Entitas Terpantau",
            "value": f"{active_cnt} / {len(states)} Aktif",
            "badge": "ONLINE",
            "status": "ok",
        })

    # 3. Build Progress / Gauge Bars
    bars: list[dict[str, Any]] = []

    # Bar 1: Power load
    if power_sensors and total_watts > 0:
        pct = min(100.0, (total_watts / 3500.0) * 100.0)
        bars.append({
            "label": "Beban Kapasitas Listrik Rumah",
            "value_text": f"{total_watts:.0f} W / 3500 W ({pct:.0f}%)",
            "percent": round(pct, 1),
            "status": "ok" if pct < 70.0 else ("warning" if pct < 90.0 else "error"),
        })

    # Bar 2: Lowest Battery
    if battery_sensors:
        battery_sensors.sort(key=lambda b: b[1])
        low_name, low_val = battery_sensors[0]
        b_status = "ok" if low_val > 40.0 else ("warning" if low_val > 20.0 else "error")
        bars.append({
            "label": f"Baterai Terendah: {low_name[:24]}",
            "value_text": f"{low_val:.0f}%",
            "percent": round(low_val, 1),
            "status": b_status,
        })

    # Bar 3: Lights on ratio (if no power sensor bar)
    if not power_sensors and lights:
        on_ratio = (len(lights_on) / len(lights)) * 100.0
        bars.append({
            "label": "Rasio Lampu Menyala",
            "value_text": f"{len(lights_on)} dari {len(lights)} ({on_ratio:.0f}%)",
            "percent": round(on_ratio, 1),
            "status": "info" if on_ratio > 0 else "ok",
        })

    # 4. Grouped Device Sections
    sections: list[dict[str, Any]] = []

    # Section 1: Climate & Sensors
    sec_climate_items: list[dict[str, Any]] = []
    for name, val, u in temp_sensors[:3]:
        sec_climate_items.append({
            "name": name,
            "state": f"{val:.1f} {u}",
            "status": "info" if val < 28.0 else "warning",
        })
    for name, val in humidity_sensors[:2]:
        sec_climate_items.append({
            "name": name,
            "state": f"{val:.0f} %",
            "status": "ok",
        })
    if sec_climate_items:
        sections.append({
            "category": "Klimat & Lingkungan",
            "items": sec_climate_items[:4],
        })

    # Section 2: Lighting & Electronics
    sec_light_items: list[dict[str, Any]] = []
    # Show ON lights first
    sorted_lights = sorted(lights, key=lambda l: 0 if l["state"] == "on" else 1)
    for l in sorted_lights[:4]:
        is_on = l["state"] == "on"
        sec_light_items.append({
            "name": l["name"],
            "state": "Menyala (ON)" if is_on else "Padam (OFF)",
            "status": "info" if is_on else "off",
        })
    if sec_light_items:
        sections.append({
            "category": "Pencahayaan Rumah",
            "items": sec_light_items,
        })

    # Section 3: Security & Access
    sec_sec_items: list[dict[str, Any]] = []
    for s in security_entities[:4]:
        sec_sec_items.append({
            "name": s["name"],
            "state": s["state"],
            "status": s["status"],
        })
    if sec_sec_items:
        sections.append({
            "category": "Keamanan & Pintu",
            "items": sec_sec_items,
        })

    # 5. Executive AI Summary
    summary_parts: list[str] = []
    if lights:
        summary_parts.append(f"{len(lights_on)} dari {len(lights)} lampu menyala")
    if avg_temp_val is not None:
        summary_parts.append(f"suhu rata-rata ruangan {avg_temp_val:.1f}{temp_unit_str}")
    if total_watts > 0:
        summary_parts.append(f"total beban daya {total_watts:.0f} W")
    if sec_alerts:
        summary_parts.append(f"{len(sec_alerts)} perangkat keamanan membutuhkan perhatian")
    else:
        summary_parts.append("seluruh sensor keamanan terpantau normal")

    summary_text = "Laporan otomatis status rumah: " + ", ".join(summary_parts) + "."

    # 6. Metrics for Status Card (ha_generate_status_card)
    card_metrics: list[dict[str, Any]] = []
    for k in kpis:
        card_metrics.append({
            "label": k["label"],
            "value": k["value"],
            "status": k["status"],
        })
    # Add extra items if needed
    if len(card_metrics) < 4:
        for item in (sec_climate_items + sec_light_items)[: (4 - len(card_metrics))]:
            card_metrics.append({
                "label": item["name"],
                "value": item["state"],
                "status": item["status"],
            })

    suggested_camera = cameras[0] if cameras else None

    return {
        "title": "RINGKASAN STATUS RUMAH",
        "kpi_highlights": kpis[:4],
        "progress_bars": bars[:3],
        "sections": sections[:3],
        "summary": summary_text,
        "suggested_camera": suggested_camera,
        "metrics_for_card": card_metrics[:6],
    }

