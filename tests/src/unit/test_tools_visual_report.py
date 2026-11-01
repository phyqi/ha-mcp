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
