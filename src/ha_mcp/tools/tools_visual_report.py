"""Visual reporting tools for Home Assistant MCP Server.

Provides tools to generate pure-Python charts and status cards, upload them to MinIO,
and return them as native MCP images and accessible 1-hour presigned URLs.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import Field

from ha_mcp._vendor.fastmcp.tools import ToolResult, tool
from ha_mcp._vendor.fastmcp.utilities.types import Image
from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tools.coercion import JSON_STRING_COERCION, parse_string_list_param
from ha_mcp.tools.helpers import (
    log_tool_usage,
    raise_tool_error,
    register_tool_methods,
)
from ha_mcp.tools.storage_base import StorageConsumerMixin
from ha_mcp.tools.tool_hints import read_only_hints
from ha_mcp.visual_reports.auto_summary import synthesize_home_overview
from ha_mcp.visual_reports.card_drawer import render_status_card
from ha_mcp.visual_reports.chart_drawer import render_sensor_chart
from ha_mcp.visual_reports.infographic_drawer import render_infographic

logger = logging.getLogger(__name__)

_DEFAULT_RETENTION_SECONDS = 3600  # 1 hour


class VisualReportTools(StorageConsumerMixin):
    """Tools for generating visual charts and report cards with MinIO retention."""

    async def _fetch_camera_snapshot(self, camera_entity_id: str) -> bytes | None:
        """Fetch camera image bytes via camera_proxy."""
        try:
            resp = await self._client.httpx_client.get(
                f"/camera_proxy/{camera_entity_id}",
                timeout=10.0,
            )
            if resp.status_code == 200 and resp.content:
                return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Camera snapshot fetch failed for {camera_entity_id}: {exc}")
        return None

    async def _fetch_history_points(
        self, entity_id: str, start_dt: datetime, end_dt: datetime
    ) -> tuple[str, str, list[tuple[float, float]]]:
        """Fetch history points for an entity, returning (name, unit, points)."""
        name = entity_id
        unit = ""
        try:
            state_obj = await self._client.get_entity_state(entity_id)
            attrs = state_obj.get("attributes", {})
            name = attrs.get("friendly_name", entity_id)
            unit = attrs.get("unit_of_measurement", "")
        except Exception:  # noqa: BLE001
            pass

        points: list[tuple[float, float]] = []
        try:
            cmd = {
                "type": "history/history_during_period",
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "entity_ids": [entity_id],
                "minimal_response": True,
                "significant_changes_only": True,
                "no_attributes": True,
            }
            res = await self._client.send_websocket_message(cmd)
            if res.get("success"):
                rows = res.get("result", {}).get(entity_id, [])
                for r in rows:
                    raw_val = r.get("s")
                    ts = r.get("lu")
                    if raw_val is None or ts is None:
                        continue
                    try:
                        val = float(raw_val)
                        points.append((float(ts), val))
                    except (ValueError, TypeError):
                        continue
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"History fetch error for {entity_id}: {exc}")

        return (name, unit, points)

    @tool(
        name="ha_generate_sensor_chart",
        tags={"History & Statistics", "Media & Storage"},
        annotations=read_only_hints("Generate Sensor Chart Image", open_world=False),
    )
    @log_tool_usage
    async def ha_generate_sensor_chart(
        self,
        entity_ids: Annotated[
            str | list[str],
            JSON_STRING_COERCION,
            Field(
                description="One or more sensor entity IDs to plot (e.g. 'sensor.room_temperature' or ['sensor.temp', 'sensor.humidity'])."
            ),
        ],
        hours: Annotated[
            int,
            Field(
                description="Lookback duration in hours (e.g. 1, 6, 12, 24, 48). Default: 24.",
                ge=1,
                le=168,
            ),
        ] = 24,
        title: Annotated[
            str | None,
            Field(description="Custom title for the chart. Default: Auto-generated."),
        ] = None,
        storage_prefix: Annotated[
            str,
            Field(description="Directory/prefix path in MinIO storage."),
        ] = "reports/charts",
        expires_in_seconds: Annotated[
            int,
            Field(description="Presigned URL expiration in seconds (default: 3600 = 1 hour)."),
        ] = _DEFAULT_RETENTION_SECONDS,
        upload_to_storage: Annotated[
            bool,
            Field(description="Whether to upload to MinIO storage if configured."),
        ] = True,
    ) -> ToolResult:
        """Generate a visual dark-themed time-series chart for sensors, auto-uploaded to MinIO with 1-hour retention."""
        entity_list = parse_string_list_param(entity_ids)
        if not entity_list:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "entity_ids must contain at least one valid entity ID.",
                )
            )

        now = datetime.now(UTC)
        start_time = now - timedelta(hours=hours)

        series_data: list[dict[str, Any]] = []
        for eid in entity_list[:5]:  # Bound to max 5 entities per chart
            name, unit, points = await self._fetch_history_points(eid, start_time, now)
            series_data.append({
                "entity_id": eid,
                "name": name,
                "unit": unit,
                "points": points,
            })

        chart_title = title or f"Sensor History ({hours}h Terakhir)"
        subtitle = f"{now.strftime('%d %b %Y, %H:%M UTC')} • {hours} Hours Lookback"
        png_bytes = render_sensor_chart(series_data, title=chart_title, subtitle=subtitle)

        storage_url: str | None = None
        if upload_to_storage and self._s3_client.is_configured:
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            object_name = f"chart_{timestamp_str}.png"
            prefix_clean = storage_prefix.strip().strip("/")
            full_key = f"{prefix_clean}/{object_name}" if prefix_clean else object_name

            await self._s3_client.upload_bytes(
                png_bytes, full_key, content_type="image/png"
            )
            storage_url = self._s3_client.generate_presigned_url(
                full_key, expires_in=expires_in_seconds
            )
            # Prune old chart images (> expires_in_seconds) to enforce storage retention
            await self._s3_client.cleanup_expired_objects(
                prefix=prefix_clean, max_age_seconds=expires_in_seconds
            )

        structured_content: dict[str, Any] = {
            "success": True,
            "title": chart_title,
            "entity_ids": entity_list,
            "hours": hours,
            "url": storage_url,
            "expires_in_seconds": expires_in_seconds if storage_url else None,
            "size_bytes": len(png_bytes),
            "timestamp": now.isoformat(),
        }

        return ToolResult(
            content=[
                Image(data=png_bytes, format="png"),
                f"Generated chart for {len(entity_list)} sensor(s). "
                + (f"URL (valid {expires_in_seconds // 60}m): {storage_url}" if storage_url else ""),
            ],
            structured_content=structured_content,
        )

    @tool(
        name="ha_generate_status_card",
        tags={"Control & State", "Media & Storage"},
        annotations=read_only_hints("Generate Status Card Image", open_world=False),
    )
    @log_tool_usage
    async def ha_generate_status_card(
        self,
        title: Annotated[
            str,
            Field(description="Header title for the status card (e.g. 'Status Rumah Pagi Hari')."),
        ] = "Status Laporan Rumah",
        metrics: Annotated[
            str | list[dict[str, Any]] | None,
            JSON_STRING_COERCION,
            Field(
                description="List of metric items with 'label', 'value', and 'status' ('ok', 'info', 'warning', 'error', 'off')."
            ),
        ] = None,
        entity_ids: Annotated[
            str | list[str] | None,
            JSON_STRING_COERCION,
            Field(
                description="Optional list of entity IDs to auto-populate metrics from Home Assistant current states."
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Field(description="Summary insight or briefing text displayed at the bottom of the card."),
        ] = None,
        camera_entity_id: Annotated[
            str | None,
            Field(description="Optional camera entity ID (e.g. 'camera.front_door') to embed snapshot in the card."),
        ] = None,
        storage_prefix: Annotated[
            str,
            Field(description="Directory/prefix path in MinIO storage."),
        ] = "reports/cards",
        expires_in_seconds: Annotated[
            int,
            Field(description="Presigned URL expiration in seconds (default: 3600 = 1 hour)."),
        ] = _DEFAULT_RETENTION_SECONDS,
        upload_to_storage: Annotated[
            bool,
            Field(description="Whether to upload to MinIO storage if configured."),
        ] = True,
    ) -> ToolResult:
        """Generate a visual status infographic card with optional camera snapshot, auto-uploaded with 1-hour retention.

        When called without 'metrics' or 'entity_ids', this tool automatically scans active Home Assistant entities (climate, lights, security) to generate a complete visual status card.
        """
        items: list[dict[str, Any]] = []

        # Parse metrics if provided
        if metrics:
            if isinstance(metrics, str):
                try:
                    parsed = json.loads(metrics)
                    if isinstance(parsed, list):
                        items.extend(parsed)
                except Exception:  # noqa: BLE001
                    pass
            elif isinstance(metrics, list):
                items.extend(metrics)

        # Auto-fetch entity states if entity_ids are provided
        if entity_ids:
            parsed_entities = parse_string_list_param(entity_ids)
            for eid in parsed_entities:
                try:
                    st = await self._client.get_entity_state(eid)
                    state_val = st.get("state", "unknown")
                    attrs = st.get("attributes", {})
                    label = attrs.get("friendly_name", eid)
                    unit = attrs.get("unit_of_measurement", "")
                    val_str = f"{state_val} {unit}".strip()

                    status_tag = "ok"
                    if state_val in ("unavailable", "unknown"):
                        status_tag = "error"
                    elif state_val in ("on", "open", "unlocked"):
                        status_tag = "info"
                    elif state_val in ("off", "closed", "locked"):
                        status_tag = "ok"

                    items.append({
                        "label": label,
                        "value": val_str,
                        "status": status_tag,
                    })
                except Exception:  # noqa: BLE001
                    continue

        # Auto-discover states if neither metrics nor entity_ids were provided
        if not items and not entity_ids:
            try:
                states = await self._client.get_states()
                overview = synthesize_home_overview(states)
                items.extend(overview.get("metrics_for_card", []))
                if not summary and overview.get("summary"):
                    summary = overview["summary"]
                if not camera_entity_id and overview.get("suggested_camera"):
                    camera_entity_id = overview["suggested_camera"]
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Auto-discovery for status card skipped: {exc}")

        cam_bytes: bytes | None = None
        if camera_entity_id:
            cam_bytes = await self._fetch_camera_snapshot(camera_entity_id)

        now = datetime.now(UTC)
        subtitle = now.strftime("%d %b %Y, %H:%M UTC")
        png_bytes = render_status_card(
            title=title,
            subtitle=subtitle,
            metrics=items,
            summary=summary,
            camera_image_bytes=cam_bytes,
        )

        storage_url: str | None = None
        if upload_to_storage and self._s3_client.is_configured:
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            object_name = f"status_{timestamp_str}.png"
            prefix_clean = storage_prefix.strip().strip("/")
            full_key = f"{prefix_clean}/{object_name}" if prefix_clean else object_name

            await self._s3_client.upload_bytes(
                png_bytes, full_key, content_type="image/png"
            )
            storage_url = self._s3_client.generate_presigned_url(
                full_key, expires_in=expires_in_seconds
            )
            # Prune old card images (> expires_in_seconds) to enforce storage retention
            await self._s3_client.cleanup_expired_objects(
                prefix=prefix_clean, max_age_seconds=expires_in_seconds
            )

        structured_content: dict[str, Any] = {
            "success": True,
            "title": title,
            "metrics_count": len(items),
            "has_camera_snapshot": bool(cam_bytes),
            "url": storage_url,
            "expires_in_seconds": expires_in_seconds if storage_url else None,
            "size_bytes": len(png_bytes),
            "timestamp": now.isoformat(),
        }

        return ToolResult(
            content=[
                Image(data=png_bytes, format="png"),
                f"Generated status card '{title}' with {len(items)} metric(s). "
                + (f"URL (valid {expires_in_seconds // 60}m): {storage_url}" if storage_url else ""),
            ],
            structured_content=structured_content,
        )

    @tool(
        name="ha_generate_infographic",
        tags={"Control & State", "Media & Storage"},
        annotations=read_only_hints("Generate Status Infographic Image", open_world=False),
    )
    @log_tool_usage
    async def ha_generate_infographic(
        self,
        title: Annotated[
            str,
            Field(description="Main infographic title (e.g. 'RINGKASAN STATUS RUMAH' or 'LAPORAN ENERGI & SUHU')."),
        ] = "INFOGRAFIS STATUS RUMAH",
        subtitle: Annotated[
            str | None,
            Field(description="Optional subtitle or time descriptor."),
        ] = None,
        kpi_highlights: Annotated[
            str | list[dict[str, Any]] | None,
            JSON_STRING_COERCION,
            Field(
                description="List of 2-4 highlight tiles with 'label', 'value', 'badge', and 'status' ('ok', 'info', 'warning', 'error')."
            ),
        ] = None,
        progress_bars: Annotated[
            str | list[dict[str, Any]] | None,
            JSON_STRING_COERCION,
            Field(
                description="List of gauge/progress bars with 'label', 'value_text', 'percent' (0-100), and 'status'."
            ),
        ] = None,
        sections: Annotated[
            str | list[dict[str, Any]] | None,
            JSON_STRING_COERCION,
            Field(
                description="Grouped device categories with 'category' (title) and 'items' (list of {'name', 'state', 'status'})."
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Field(description="Briefing notes or AI analysis displayed in the bottom callout."),
        ] = None,
        camera_entity_id: Annotated[
            str | None,
            Field(description="Optional camera entity ID (e.g. 'camera.front_door') to display snapshot hero preview."),
        ] = None,
        storage_prefix: Annotated[
            str,
            Field(description="Directory/prefix path in MinIO storage."),
        ] = "reports/infographics",
        expires_in_seconds: Annotated[
            int,
            Field(description="Presigned URL expiration in seconds (default: 3600 = 1 hour)."),
        ] = _DEFAULT_RETENTION_SECONDS,
        upload_to_storage: Annotated[
            bool,
            Field(description="Whether to upload to MinIO storage if configured."),
        ] = True,
    ) -> ToolResult:
        """Generate a rich, visual home status infographic with KPI metric tiles, gauge bars, grouped device sections, and optional camera snapshot.

        When called without 'kpi_highlights', 'progress_bars', or 'sections' (e.g. general requests like 'buatkan laporan rumah dalam bentuk gambar'), this tool automatically discovers and aggregates active Home Assistant states (climate, lights, power, security sensors, cameras) into a complete, beautiful visual infographic report.
        """
        def _parse_list(val: Any) -> list[dict[str, Any]]:
            if not val:
                return []
            if isinstance(val, str):
                try:
                    res = json.loads(val)
                    return res if isinstance(res, list) else []
                except Exception:  # noqa: BLE001
                    return []
            if isinstance(val, list):
                return val
            return []

        parsed_kpis = _parse_list(kpi_highlights)
        parsed_bars = _parse_list(progress_bars)
        parsed_secs = _parse_list(sections)

        # Auto-discover home overview if no explicit KPI highlights, bars, or sections provided
        if not parsed_kpis and not parsed_bars and not parsed_secs:
            try:
                states = await self._client.get_states()
                overview = synthesize_home_overview(states)
                if not parsed_kpis:
                    parsed_kpis = overview.get("kpi_highlights", [])
                if not parsed_bars:
                    parsed_bars = overview.get("progress_bars", [])
                if not parsed_secs:
                    parsed_secs = overview.get("sections", [])
                if not summary and overview.get("summary"):
                    summary = overview["summary"]
                if not camera_entity_id and overview.get("suggested_camera"):
                    camera_entity_id = overview["suggested_camera"]
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Auto-discovery for infographic skipped: {exc}")

        cam_bytes: bytes | None = None
        if camera_entity_id:
            cam_bytes = await self._fetch_camera_snapshot(camera_entity_id)

        now = datetime.now(UTC)
        sub = subtitle or now.strftime("%A, %d %B %Y • %H:%M UTC")

        png_bytes = render_infographic(
            title=title,
            subtitle=sub,
            kpi_highlights=parsed_kpis,
            progress_bars=parsed_bars,
            sections=parsed_secs,
            summary=summary,
            camera_image_bytes=cam_bytes,
        )

        storage_url: str | None = None
        if upload_to_storage and self._s3_client.is_configured:
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            object_name = f"infographic_{timestamp_str}.png"
            prefix_clean = storage_prefix.strip().strip("/")
            full_key = f"{prefix_clean}/{object_name}" if prefix_clean else object_name

            await self._s3_client.upload_bytes(
                png_bytes, full_key, content_type="image/png"
            )
            storage_url = self._s3_client.generate_presigned_url(
                full_key, expires_in=expires_in_seconds
            )
            # Prune old infographic images (> expires_in_seconds) to enforce storage retention
            await self._s3_client.cleanup_expired_objects(
                prefix=prefix_clean, max_age_seconds=expires_in_seconds
            )

        structured_content: dict[str, Any] = {
            "success": True,
            "title": title,
            "kpis_count": len(parsed_kpis),
            "bars_count": len(parsed_bars),
            "sections_count": len(parsed_secs),
            "has_camera_snapshot": bool(cam_bytes),
            "url": storage_url,
            "expires_in_seconds": expires_in_seconds if storage_url else None,
            "size_bytes": len(png_bytes),
            "timestamp": now.isoformat(),
        }

        return ToolResult(
            content=[
                Image(data=png_bytes, format="png"),
                f"Generated infographic '{title}'. "
                + (f"URL (valid {expires_in_seconds // 60}m): {storage_url}" if storage_url else ""),
            ],
            structured_content=structured_content,
        )


def register_visual_report_tools(mcp: Any, client: Any, **kwargs: Any) -> None:
    """Register Home Assistant visual report and charting tools."""
    register_tool_methods(mcp, VisualReportTools(client))
