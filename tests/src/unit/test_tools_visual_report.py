"""Unit tests for visual report tools and chart/card renderers."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image as PILImage

from ha_mcp._vendor.fastmcp.tools import ToolResult
from ha_mcp._vendor.fastmcp.utilities.types import Image
from ha_mcp.client.s3_client import S3Client
from ha_mcp.tools.tools_visual_report import VisualReportTools
from ha_mcp.visual_reports.card_drawer import render_status_card
from ha_mcp.visual_reports.chart_drawer import render_sensor_chart
from ha_mcp.visual_reports.infographic_drawer import render_infographic


def _create_sample_snapshot() -> bytes:
    """Create a sample 100x100 PNG bytes for testing camera embeds."""
    im = PILImage.new("RGB", (100, 100), (40, 120, 200))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_render_sensor_chart_success():
    """Verify render_sensor_chart produces valid PNG bytes for time-series data."""
    now = datetime.now(UTC).timestamp()
    series = [
        {
            "name": "Suhu Ruang Tamu",
            "unit": "°C",
            "points": [
                (now - 3600, 24.0),
                (now - 1800, 24.8),
                (now, 25.2),
            ],
        },
        {
            "name": "Kelembapan",
            "unit": "%",
            "points": [
                (now - 3600, 55.0),
                (now - 1800, 53.0),
                (now, 50.0),
            ],
        },
    ]

    png_bytes = render_sensor_chart(series, title="Grafik Suhu & Kelembapan")
    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG")

    # Verify Pillow can open the generated image
    img = PILImage.open(io.BytesIO(png_bytes))
    assert img.size == (1000, 560)


def test_render_sensor_chart_empty():
    """Verify render_sensor_chart handles empty series gracefully."""
    png_bytes = render_sensor_chart([], title="Grafik Kosong")
    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG")


def test_render_status_card_success():
    """Verify render_status_card produces valid PNG bytes with metrics and camera snapshot."""
    sample_cam = _create_sample_snapshot()
    metrics = [
        {"label": "Suhu Kamar", "value": "24.5 °C", "status": "ok"},
        {"label": "AC Master", "value": "ON (Cool)", "status": "info"},
        {"label": "Pintu Depan", "value": "Terkunci", "status": "ok"},
        {"label": "Lampu Menyala", "value": "3 Ruangan", "status": "warning"},
    ]

    png_bytes = render_status_card(
        title="Laporan Rumah Malam Hari",
        metrics=metrics,
        summary="Semua sistem berjalan normal dan pintu terkunci.",
        camera_image_bytes=sample_cam,
    )

    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG")

    img = PILImage.open(io.BytesIO(png_bytes))
    assert img.width == 900
    assert img.height >= 450


@pytest.mark.anyio
async def test_ha_generate_sensor_chart_tool():
    """Test ha_generate_sensor_chart tool execution, MinIO upload, and 1h retention."""
    mock_ha_client = MagicMock()
    mock_ha_client.get_entity_state = AsyncMock(
        return_value={
            "attributes": {
                "friendly_name": "Suhu AC",
                "unit_of_measurement": "°C",
            }
        }
    )

    now_ts = datetime.now(UTC).timestamp()
    mock_ha_client.send_websocket_message = AsyncMock(
        return_value={
            "success": True,
            "result": {
                "sensor.ac_temp": [
                    {"s": "24.0", "lu": now_ts - 1800},
                    {"s": "23.5", "lu": now_ts},
                ]
            },
        }
    )

    mock_s3 = MagicMock(spec=S3Client)
    mock_s3.is_configured = True
    mock_s3.upload_bytes = AsyncMock(return_value={"etag": "mock-etag"})
    mock_s3.generate_presigned_url = MagicMock(
        return_value="https://minio.local:9000/captures/reports/charts/chart_123.png?token=xyz"
    )
    mock_s3.cleanup_expired_objects = AsyncMock(return_value=2)

    tools = VisualReportTools(mock_ha_client, mock_s3)
    result = await tools.ha_generate_sensor_chart(
        entity_ids=["sensor.ac_temp"],
        hours=6,
        title="Suhu AC 6 Jam Terakhir",
        expires_in_seconds=3600,
    )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/png"

    struct = result.structured_content
    assert struct["success"] is True
    assert struct["url"].startswith("https://minio.local:9000")
    assert struct["expires_in_seconds"] == 3600

    # Verify upload called
    assert mock_s3.upload_bytes.call_count == 1
    # Verify presigned URL generated with 3600s
    mock_s3.generate_presigned_url.assert_called_once()
    assert mock_s3.generate_presigned_url.call_args[1]["expires_in"] == 3600
    # Verify cleanup called to enforce 1-hour retention on stored objects
    mock_s3.cleanup_expired_objects.assert_called_once_with(
        prefix="reports/charts", max_age_seconds=3600
    )


@pytest.mark.anyio
async def test_ha_generate_status_card_tool():
    """Test ha_generate_status_card with auto-entity states and camera snapshot."""
    mock_ha_client = MagicMock()
    mock_ha_client.get_entity_state = AsyncMock(
        side_effect=lambda eid: {
            "state": "24.5" if "temp" in eid else "locked",
            "attributes": {
                "friendly_name": "Suhu" if "temp" in eid else "Pintu Depan",
                "unit_of_measurement": "°C" if "temp" in eid else "",
            },
        }
    )

    sample_cam = _create_sample_snapshot()
    mock_httpx = AsyncMock()
    mock_cam_resp = MagicMock()
    mock_cam_resp.status_code = 200
    mock_cam_resp.content = sample_cam
    mock_httpx.get = AsyncMock(return_value=mock_cam_resp)
    mock_ha_client.httpx_client = mock_httpx

    mock_s3 = MagicMock(spec=S3Client)
    mock_s3.is_configured = True
    mock_s3.upload_bytes = AsyncMock(return_value={"etag": "mock-etag"})
    mock_s3.generate_presigned_url = MagicMock(
        return_value="https://minio.local:9000/captures/reports/cards/card_123.png?token=xyz"
    )
    mock_s3.cleanup_expired_objects = AsyncMock(return_value=1)

    tools = VisualReportTools(mock_ha_client, mock_s3)
    result = await tools.ha_generate_status_card(
        title="Status Rumah Saat Ini",
        entity_ids=["sensor.living_room_temp", "lock.front_door"],
        camera_entity_id="camera.front_door",
        summary="Pintu terkunci dan suhu ruangan sejuk.",
        expires_in_seconds=3600,
    )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/png"

    struct = result.structured_content
    assert struct["success"] is True
    assert struct["metrics_count"] == 2
    assert struct["has_camera_snapshot"] is True
    assert struct["expires_in_seconds"] == 3600
    assert struct["url"].startswith("https://minio.local:9000")

    # Verify upload & 1h retention cleanup
    assert mock_s3.upload_bytes.call_count == 1
    mock_s3.cleanup_expired_objects.assert_called_once_with(
        prefix="reports/cards", max_age_seconds=3600
    )


def test_render_infographic_success():
    """Verify render_infographic produces valid PNG bytes with KPI and sections."""
    sample_cam = _create_sample_snapshot()
    kpis = [
        {"label": "Suhu Rata-rata", "value": "24.2 °C", "badge": "SEJUK", "status": "ok"},
        {"label": "Beban Listrik", "value": "520 W", "badge": "NORMAL", "status": "ok"},
    ]
    bars = [
        {"label": "Daya Listrik (Watt)", "value_text": "520W / 2200W (24%)", "percent": 23.6, "status": "info"}
    ]
    sections = [
        {
            "category": "Keamanan & Pintu",
            "items": [
                {"name": "Pintu Utama", "state": "Terkunci", "status": "locked"},
                {"name": "Pagar Depan", "state": "Tertutup", "status": "closed"},
            ],
        }
    ]

    png = render_infographic(
        title="LAPORAN STATUS RUMAH",
        kpi_highlights=kpis,
        progress_bars=bars,
        sections=sections,
        summary="Semua sistem berjalan normal.",
        camera_image_bytes=sample_cam,
    )

    assert isinstance(png, bytes)
    assert png.startswith(b"\x89PNG")
    img = PILImage.open(io.BytesIO(png))
    assert img.width == 1000
    assert img.height >= 500


@pytest.mark.anyio
async def test_ha_generate_infographic_tool():
    """Test ha_generate_infographic tool execution with mock S3 and HA."""
    mock_ha_client = MagicMock()
    mock_s3 = MagicMock(spec=S3Client)
    mock_s3.is_configured = True
    mock_s3.upload_bytes = AsyncMock(return_value={"etag": "mock-etag"})
    mock_s3.generate_presigned_url = MagicMock(
        return_value="https://minio.local:9000/captures/reports/infographics/info_123.png?token=xyz"
    )
    mock_s3.cleanup_expired_objects = AsyncMock(return_value=1)

    tools = VisualReportTools(mock_ha_client, mock_s3)
    result = await tools.ha_generate_infographic(
        title="DAILY HOME BRIEFING",
        kpi_highlights=[{"label": "Suhu", "value": "24°C", "badge": "OK", "status": "ok"}],
        progress_bars=[{"label": "Beban Listrik", "value_text": "500W", "percent": 25.0, "status": "ok"}],
        summary="Semua kondisi aman.",
        expires_in_seconds=3600,
    )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/png"

    struct = result.structured_content
    assert struct["success"] is True
    assert struct["kpis_count"] == 1
    assert struct["bars_count"] == 1
    assert struct["expires_in_seconds"] == 3600
    assert struct["url"].startswith("https://minio.local:9000")

    mock_s3.upload_bytes.assert_called_once()
    mock_s3.cleanup_expired_objects.assert_called_once_with(
        prefix="reports/infographics", max_age_seconds=3600
    )


def test_synthesize_home_overview():
    """Verify synthesize_home_overview correctly extracts climate, lighting, power, and security."""
    from ha_mcp.visual_reports.auto_summary import synthesize_home_overview

    mock_states = [
        {"entity_id": "sensor.living_room_temp", "state": "24.5", "attributes": {"friendly_name": "Suhu Ruang Tamu", "device_class": "temperature", "unit_of_measurement": "°C"}},
        {"entity_id": "sensor.living_room_humidity", "state": "60", "attributes": {"friendly_name": "Kelembaban", "device_class": "humidity", "unit_of_measurement": "%"}},
        {"entity_id": "light.living_room", "state": "on", "attributes": {"friendly_name": "Lampu Utama"}},
        {"entity_id": "light.bedroom", "state": "off", "attributes": {"friendly_name": "Lampu Kamar"}},
        {"entity_id": "sensor.home_power", "state": "450", "attributes": {"friendly_name": "Daya Total", "device_class": "power", "unit_of_measurement": "W"}},
        {"entity_id": "binary_sensor.front_door", "state": "off", "attributes": {"friendly_name": "Pintu Depan", "device_class": "door"}},
        {"entity_id": "sensor.door_lock_battery", "state": "85", "attributes": {"friendly_name": "Baterai Smartlock", "device_class": "battery", "unit_of_measurement": "%"}},
        {"entity_id": "camera.front_porch", "state": "idle", "attributes": {"friendly_name": "Kamera Teras"}},
    ]

    overview = synthesize_home_overview(mock_states)
    assert len(overview["kpi_highlights"]) >= 3
    assert any("Suhu" in k["label"] for k in overview["kpi_highlights"])
    assert any("Pencahayaan" in k["label"] for k in overview["kpi_highlights"])
    assert any("Konsumsi Daya" in k["label"] for k in overview["kpi_highlights"])
    assert len(overview["progress_bars"]) >= 1
    assert len(overview["sections"]) >= 2
    assert overview["suggested_camera"] == "camera.front_porch"
    assert "Laporan otomatis" in overview["summary"]
    assert len(overview["metrics_for_card"]) >= 3


@pytest.mark.anyio
async def test_ha_generate_infographic_auto_discovery():
    """Verify ha_generate_infographic automatically queries get_states and populates infographic when called with defaults."""
    mock_ha_client = MagicMock()
    mock_ha_client.get_states = AsyncMock(
        return_value=[
            {"entity_id": "sensor.temp", "state": "25.0", "attributes": {"friendly_name": "Suhu Ruangan", "device_class": "temperature", "unit_of_measurement": "°C"}},
            {"entity_id": "light.light_1", "state": "on", "attributes": {"friendly_name": "Lampu 1"}},
            {"entity_id": "binary_sensor.door", "state": "off", "attributes": {"friendly_name": "Pintu Utama", "device_class": "door"}},
        ]
    )
    mock_ha_client.httpx_client.get = AsyncMock(return_value=MagicMock(status_code=404, content=None))

    mock_s3 = MagicMock(spec=S3Client)
    mock_s3.is_configured = False

    tools = VisualReportTools(mock_ha_client, mock_s3)
    # Call without any parameters (mimicking user's 'buatkan laporan rumah dalam bentuk gambar')
    result = await tools.ha_generate_infographic()

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/png"

    struct = result.structured_content
    assert struct["success"] is True
    # Verify auto-discovery populated KPIs and sections
    assert struct["kpis_count"] >= 2
    assert struct["sections_count"] >= 1
    mock_ha_client.get_states.assert_called_once()

