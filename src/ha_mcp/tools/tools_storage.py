"""Storage tools for Home Assistant MCP Server.

Provides tools to capture images from cameras or dashboards and upload them to
MinIO or S3-compatible object storage, returning accessible URLs (presigned or public).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from ha_mcp._vendor.fastmcp.tools import ToolResult, tool
from ha_mcp._vendor.fastmcp.utilities.types import Image
from ha_mcp.dashboard_screenshot.capture import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    capture_dashboard_images,
)
from ha_mcp.errors import (
    ErrorCode,
    create_auth_error,
    create_entity_not_found_error,
    create_error_response,
)
from ha_mcp.image_info import resolve_image_info
from ha_mcp.tools.helpers import (
    exception_to_structured_error,
    log_tool_usage,
    raise_tool_error,
    register_tool_methods,
)
from ha_mcp.tools.storage_base import StorageConsumerMixin
from ha_mcp.tools.tool_hints import write_hints
from ha_mcp.tools.tools_camera import _detect_image_format

logger = logging.getLogger(__name__)


class StorageTools(StorageConsumerMixin):
    """Tools for capturing and uploading media to object storage."""

    async def _capture_camera(
        self,
        entity_id: str,
        width: int | None = None,
        height: int | None = None,
    ) -> tuple[bytes, str, str]:
        """Capture image bytes, format, and content type from a camera entity."""
        if not entity_id or "." not in entity_id or not entity_id.startswith("camera."):
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    f"Invalid camera entity_id format: '{entity_id}'. Expected 'camera.<name>'.",
                    context={"entity_id": entity_id},
                )
            )

        endpoint = f"/camera_proxy/{entity_id}"
        params: dict[str, str] = {}
        if width is not None:
            params["width"] = str(width)
        if height is not None:
            params["height"] = str(height)

        try:
            response = await self._client.httpx_client.get(
                endpoint, params=params or None
            )
        except Exception as exc:
            raise exception_to_structured_error(
                exc,
                context={"entity_id": entity_id},
                suggestions=["Check Home Assistant connection and camera state."],
            ) from exc

        if response.status_code == 401:
            raise_tool_error(
                create_auth_error(
                    "Invalid authentication token for camera access",
                    context={"entity_id": entity_id},
                )
            )
        if response.status_code == 404:
            raise_tool_error(
                create_entity_not_found_error(
                    entity_id, details="Use ha_search to find available cameras."
                )
            )
        if response.status_code >= 400:
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    f"Failed to retrieve camera image: HTTP {response.status_code}",
                    context={"entity_id": entity_id},
                )
            )
        if not response.content:
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    f"Camera {entity_id} returned empty image data. It may be offline.",
                    context={"entity_id": entity_id},
                )
            )

        raw_ct = response.headers.get("content-type", "image/jpeg")
        fmt, _ = resolve_image_info(response.content, _detect_image_format(raw_ct))
        content_type = (
            f"image/{fmt}" if "/" not in raw_ct else raw_ct.split(";")[0].strip()
        )
        return response.content, fmt, content_type

    async def _capture_dashboard(
        self,
        dashboard_path: str,
        dashboard_view: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> tuple[bytes, str, str]:
        """Capture screenshot image bytes, format, and content type from a dashboard."""
        clean_path = dashboard_path.strip().strip("/")
        if not clean_path:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "dashboard_path cannot be empty.",
                )
            )

        target = clean_path
        if dashboard_view:
            clean_view = dashboard_view.strip().strip("/")
            target = f"{clean_path}/{clean_view}"

        w = width if width is not None else DEFAULT_WIDTH
        h = height if height is not None else DEFAULT_HEIGHT

        captures = await capture_dashboard_images(
            target,
            width=w,
            height=h,
            client=self._client,
        )
        if not captures:
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    f"No screenshot captured for dashboard '{target}'.",
                    context={"dashboard_path": target},
                )
            )

        first = captures[0]
        return first.data, first.image_format, first.mime_type

    @tool(
        name="ha_upload_capture",
        tags={"Storage", "Camera", "Dashboard"},
        annotations=write_hints(
            "Upload Capture to Object Storage",
            destructive=False,
            idempotent=False,
            open_world=True,
        ),
    )
    @log_tool_usage
    async def ha_upload_capture(
        self,
        source: Annotated[
            Literal["camera", "dashboard"],
            Field(description="Media capture source: 'camera' or 'dashboard'."),
        ],
        camera_entity_id: Annotated[
            str | None,
            Field(
                description="Camera entity ID (e.g. 'camera.front_door'), required when source is 'camera'."
            ),
        ] = None,
        dashboard_path: Annotated[
            str | None,
            Field(
                description="Lovelace dashboard path (e.g. 'lovelace' or 'lovelace-security'), required when source is 'dashboard'."
            ),
        ] = None,
        dashboard_view: Annotated[
            str | None,
            Field(
                description="Optional sub-view path or index within the dashboard (e.g. 'cameras' or '1')."
            ),
        ] = None,
        bucket: Annotated[
            str | None,
            Field(
                description="Target MinIO / S3 bucket name. Defaults to MINIO_BUCKET setting."
            ),
        ] = None,
        prefix: Annotated[
            str | None,
            Field(
                description="Custom folder/directory path prefix inside the bucket (e.g. 'cctv' or 'security/front_door'). If omitted, defaults to MINIO_PREFIX setting (default: 'captures')."
            ),
        ] = None,
        object_name: Annotated[
            str | None,
            Field(
                description="Custom object key/path in the bucket. Overrides prefix and automatic filename generation if provided."
            ),
        ] = None,
        expires_in: Annotated[
            int,
            Field(
                ge=0,
                le=604800,
                description="Expiration in seconds for the presigned URL (default: 3600 = 1 hour, max: 604800 = 7 days). Set to 0 for a direct public URL.",
            ),
        ] = 3600,
        width: Annotated[
            int | None,
            Field(
                ge=64,
                le=4096,
                description="Optional width for resizing camera image or dashboard viewport.",
            ),
        ] = None,
        height: Annotated[
            int | None,
            Field(
                ge=64,
                le=4096,
                description="Optional height for resizing camera image or dashboard viewport.",
            ),
        ] = None,
        include_image_content: Annotated[
            bool,
            Field(
                description="Whether to also include the raw image block in the MCP response. Default is False to return only the URL and save token context.",
            ),
        ] = False,
    ) -> dict[str, Any] | ToolResult:
        """Capture an image from a camera or dashboard and upload it to MinIO / S3 object storage.

        Takes a snapshot of a camera or renders a Lovelace dashboard, uploads
        the image to the configured MinIO / S3-compatible object storage, and
        returns an accessible URL (presigned GET URL with configurable expiry,
        or direct public URL).

        EXAMPLE:
        - Camera: ha_upload_capture(source="camera", camera_entity_id="camera.front_door")
        - Dashboard: ha_upload_capture(source="dashboard", dashboard_path="lovelace", dashboard_view="security")
        """
        now = datetime.now(UTC)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")

        clean_prefix = (
            prefix.strip().strip("/")
            if prefix is not None
            else self._s3_client.default_prefix
        )

        source_info: dict[str, Any]
        if source == "camera":
            if not camera_entity_id:
                raise_tool_error(
                    create_error_response(
                        ErrorCode.VALIDATION_INVALID_PARAMETER,
                        "camera_entity_id is required when source is 'camera'.",
                    )
                )
            image_bytes, image_format, content_type = await self._capture_camera(
                camera_entity_id, width=width, height=height
            )
            base_filename = (
                f"{camera_entity_id.replace('.', '_')}_{timestamp_str}.{image_format}"
            )
            default_key = (
                f"{clean_prefix}/{base_filename}" if clean_prefix else base_filename
            )
            source_info = {"type": "camera", "target": camera_entity_id}

        elif source == "dashboard":
            if not dashboard_path:
                raise_tool_error(
                    create_error_response(
                        ErrorCode.VALIDATION_INVALID_PARAMETER,
                        "dashboard_path is required when source is 'dashboard'.",
                    )
                )
            image_bytes, image_format, content_type = await self._capture_dashboard(
                dashboard_path,
                dashboard_view=dashboard_view,
                width=width,
                height=height,
            )
            safe_dash = dashboard_path.replace("/", "_")
            if dashboard_view:
                safe_dash += f"_{dashboard_view.replace('/', '_')}"
            base_filename = f"{safe_dash}_{timestamp_str}.{image_format}"
            default_key = (
                f"{clean_prefix}/{base_filename}" if clean_prefix else base_filename
            )
            source_info = {
                "type": "dashboard",
                "target": dashboard_path,
                "view": dashboard_view,
            }
        else:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    f"Unknown source '{source}'. Expected 'camera' or 'dashboard'.",
                )
            )

        effective_key = object_name.strip().lstrip("/") if object_name else default_key

        upload_result = await self._s3_client.upload_bytes(
            image_bytes, effective_key, content_type=content_type, bucket=bucket
        )

        if expires_in > 0:
            access_url = self._s3_client.generate_presigned_url(
                effective_key, bucket=bucket, expires_in=expires_in
            )
        else:
            access_url = self._s3_client.get_public_url(effective_key, bucket=bucket)

        structured_content: dict[str, Any] = {
            "success": True,
            "url": access_url,
            "bucket": upload_result["bucket"],
            "object_key": upload_result["object_key"],
            "size_bytes": upload_result["size_bytes"],
            "content_type": content_type,
            "etag": upload_result["etag"],
            "expires_in": expires_in,
            "source": source_info,
            "timestamp": now.isoformat(),
            "message": f"Successfully captured from {source} and uploaded to MinIO/S3 object storage.",
        }

        if include_image_content:
            return ToolResult(
                content=[Image(data=image_bytes, format=image_format)],
                structured_content=structured_content,
            )

        return structured_content


def register_storage_tools(mcp: Any, client: Any, **kwargs: Any) -> None:
    """Register Home Assistant storage tools."""
    register_tool_methods(mcp, StorageTools(client))
