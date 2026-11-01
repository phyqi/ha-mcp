"""
Camera tools for Home Assistant MCP server.

This module provides camera-related tools including snapshot retrieval
that returns images directly to the LLM for visual analysis, alongside a
short text block stating the served snapshot's size and retrieval time.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import Field

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp._vendor.fastmcp.tools import tool
from ha_mcp._vendor.fastmcp.utilities.types import Image
from ha_mcp.errors import (
    ErrorCode,
    create_auth_error,
    create_entity_not_found_error,
    create_error_response,
)
from ha_mcp.image_info import resolve_image_info

from .helpers import (
    exception_to_structured_error,
    log_tool_usage,
    raise_tool_error,
    register_tool_methods,
)
from .response_helpers import fetch_ha_timezone, resolve_local_timezone
from .storage_base import StorageConsumerMixin
from .tool_hints import read_only_hints

logger = logging.getLogger(__name__)


# Subtypes that denote JPEG under an alternate spelling. Every other
# image/* subtype is reported verbatim (image/webp -> "webp"); the JPEG
# default applies only when the header names no image subtype at all.
_JPEG_ALIASES = {"jpg": "jpeg", "jpe": "jpeg", "jif": "jpeg"}


def _detect_image_format(content_type: str) -> str:
    """Report the declared image format from a Content-Type header.

    Only the media type's subtype is relevant (``image/jpeg`` -> ``jpeg``);
    parameters such as ``; q=0.9`` are stripped and JPEG's alternate
    spellings are folded in. Unknown image subtypes pass through verbatim —
    relabelling ``image/webp`` as JPEG would misidentify the Image block.
    The JPEG default applies only when the header is missing, empty, or
    not an ``image/*`` type with a subtype (e.g. ``application/octet-stream``).
    """
    media_type = content_type.split(";", 1)[0].strip().lower()
    primary, _, subtype = media_type.partition("/")
    if primary != "image" or not subtype:
        return "jpeg"
    return _JPEG_ALIASES.get(subtype, subtype)


def _snapshot_info_text(
    image_format: str,
    image_size: tuple[int, int] | None,
    retrieved: datetime,
    timezone_fallback: bool = False,
    url: str | None = None,
    storage_error: str | None = None,
) -> str:
    """Build the text half of the camera image response.

    Reports the size of the image actually served (which may differ from
    the camera's native resolution when Home Assistant rescaled it) and
    when the snapshot was retrieved, in Home Assistant local time with
    UTC offset. When the timezone lookup fell back to UTC, the text says
    so, so the label cannot be mistaken for a genuine UTC install.
    When uploaded to object storage, the accessible URL is included.

    The block deliberately describes only the bytes that were served —
    never the entity's name or state. Home Assistant can mark an entity
    ``llm_exposure: hidden``, asking the LLM to know nothing about that
    entity; that setting does not un-expose this tool, so entity data in
    the text would keep reporting on the camera despite the setting.
    """
    prefix = f"Camera snapshot ({image_format.upper()}"
    if image_size is None:
        detail = f"{prefix})"
    else:
        width, height = image_size
        detail = f"{prefix}, {width}x{height})"
    url_text = f" URL: {url}." if url else ""
    error_text = f" (Storage upload failed: {storage_error})" if storage_error else ""
    note = (
        " (UTC — could not determine the Home Assistant timezone)"
        if timezone_fallback
        else ""
    )
    return f"{detail}.{url_text}{error_text} Retrieved: {retrieved:%Y-%m-%d %H:%M:%S %:z}{note}"


class CameraTools(StorageConsumerMixin):
    """Camera snapshot retrieval tools."""

    async def _upload_to_storage(
        self,
        entity_id: str,
        content: bytes,
        image_format: str,
        retrieved_at: datetime,
        storage_prefix: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Upload snapshot bytes to MinIO/S3 storage. Returns (url, error_message)."""
        if not self._s3_client.is_configured:
            return None, "Storage is not configured"
        try:
            timestamp_str = retrieved_at.strftime("%Y%m%d_%H%M%S")
            prefix = (
                storage_prefix
                if storage_prefix is not None
                else self._s3_client.default_prefix
            )
            clean_prefix = prefix.strip().strip("/") if prefix else ""
            safe_entity = entity_id.replace(".", "_")
            filename = f"{safe_entity}_{timestamp_str}.{image_format}"
            object_name = f"{clean_prefix}/{filename}" if clean_prefix else filename

            await self._s3_client.upload_bytes(
                content,
                object_name,
                content_type=f"image/{image_format}",
            )
            url = self._s3_client.generate_presigned_url(object_name)
            logger.info("Uploaded camera snapshot %s to storage: %s", entity_id, url)
            return url, None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to upload camera snapshot %s to storage: %s", entity_id, exc
            )
            return None, str(exc)

    @staticmethod
    def _check_response(response: Any, entity_id: str) -> None:
        """Validate a camera-proxy HTTP response, raising a structured ToolError.

        401 maps to an authentication error, 404 to a missing-entity error,
        any other 4xx/5xx to a service-call failure, and an empty 2xx body
        is a service failure too (HA answered but had no image to serve).
        """
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
                    entity_id,
                    details="Use ha_search to find available cameras",
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
                    f"Camera {entity_id} returned empty image data. The camera "
                    "may be offline or temporarily unavailable.",
                    context={"entity_id": entity_id},
                )
            )

    @tool(
        name="ha_get_camera_image",
        tags={"Camera"},
        annotations=read_only_hints("Get Camera Image", open_world=False),
    )
    @log_tool_usage
    async def ha_get_camera_image(
        self,
        entity_id: Annotated[
            str, Field(description="Camera entity ID (e.g., 'camera.front_door')")
        ],
        width: Annotated[
            int | None,
            Field(
                description="Width for the resized image. Home Assistant "
                "rescales only when both width and height are given and "
                "the camera serves JPEG."
            ),
        ] = None,
        height: Annotated[
            int | None,
            Field(
                description="Height for the resized image. Home Assistant "
                "rescales only when both width and height are given and "
                "the camera serves JPEG."
            ),
        ] = None,
        upload_to_storage: Annotated[
            bool | None,
            Field(
                description="Upload the snapshot to MinIO / S3 object storage. "
                "If None (default), automatically uploads when storage is configured in settings."
            ),
        ] = None,
        storage_prefix: Annotated[
            str | None,
            Field(
                description="Custom folder/prefix in the storage bucket for this snapshot. "
                "Defaults to configured MINIO_PREFIX (default: 'captures')."
            ),
        ] = None,
    ) -> tuple[str, Image]:
        """Get a snapshot image from a Home Assistant camera entity.

        Fetches the current camera image and returns it directly for
        visual analysis (security checks, delivery verification,
        confirming a garage door actually closed), in the format Home
        Assistant serves (JPEG, PNG, or GIF), alongside a short text
        block stating the served snapshot's size and retrieval time in
        Home Assistant local time.

        When MinIO / S3 object storage is configured in settings, the
        snapshot is automatically uploaded to the bucket and its accessible
        URL is returned in the text info block.

        Do not use it to inspect the camera's state or attributes — use
        ha_search or ha_get_state for those; it returns an image, not
        state. Use it when you need to see the current scene, and on
        high-resolution cameras pass width and height to reduce token
        usage.

        EXAMPLE: ha_get_camera_image(entity_id="camera.backyard", width=640, height=480)
        """
        if not entity_id or "." not in entity_id:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    f"Invalid entity_id format: {entity_id}. "
                    "Expected format: camera.entity_name",
                )
            )

        domain = entity_id.split(".", maxsplit=1)[0]
        if domain != "camera":
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    f"Entity {entity_id} is not a camera entity. "
                    f"Domain is '{domain}', expected 'camera'.",
                    context={"entity_id": entity_id},
                )
            )

        # Build the camera proxy URL with optional size parameters
        # Home Assistant camera proxy API: /api/camera_proxy/<entity_id>
        endpoint = f"/camera_proxy/{entity_id}"

        params = {}
        if width is not None:
            params["width"] = str(width)
        if height is not None:
            params["height"] = str(height)

        try:
            response = await self._client.httpx_client.get(
                endpoint, params=params or None
            )
            self._check_response(response, entity_id)
            # Sample the clock the moment HA handed us the bytes; the zone
            # is resolved separately so a slow timezone lookup only delays
            # the label, never the timestamp.
            retrieved_at = datetime.now(UTC)

            content_type = response.headers.get("content-type", "image/jpeg")
            # Cameras can mislabel their payload, so resolve the format
            # from the bytes: the reported label, size, and Image block
            # must all describe what was actually served.
            image_format, image_size = resolve_image_info(
                response.content, _detect_image_format(content_type)
            )
            ha_timezone, fetch_failed = await fetch_ha_timezone(self._client)
            local_tz, resolved_timezone = resolve_local_timezone(ha_timezone)
            # A failed fetch, or a zone name tzdata cannot resolve, both
            # fall back to UTC — the note keeps that distinct from a
            # genuine UTC install.
            timezone_fallback = fetch_failed or resolved_timezone != ha_timezone

            logger.info(
                f"Retrieved camera image from {entity_id} "
                f"({len(response.content)} bytes, format={image_format})"
            )

            # Upload to object storage if configured (or requested)
            uploaded_url: str | None = None
            storage_error: str | None = None
            should_upload = (
                upload_to_storage
                if upload_to_storage is not None
                else self._s3_client.is_configured
            )
            if should_upload:
                uploaded_url, storage_error = await self._upload_to_storage(
                    entity_id=entity_id,
                    content=response.content,
                    image_format=image_format,
                    retrieved_at=retrieved_at,
                    storage_prefix=storage_prefix,
                )

            # Return the info text plus a FastMCP Image object (auto-converted
            # to MCP TextContent and ImageContent, in this order)
            return (
                _snapshot_info_text(
                    image_format,
                    image_size,
                    retrieved_at.astimezone(local_tz),
                    timezone_fallback,
                    url=uploaded_url,
                    storage_error=storage_error,
                ),
                Image(data=response.content, format=image_format),
            )

        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving camera image from {entity_id}: {e}")
            # The default raise_error=True path raises inside the helper and
            # never returns; the surrounding raise keeps that termination
            # explicit so no path through this function falls off the end.
            raise exception_to_structured_error(
                e,
                context={"entity_id": entity_id},
                suggestions=["Ensure the camera is online and accessible"],
            ) from e


def register_camera_tools(mcp: Any, client: Any, **kwargs: Any) -> None:
    """Register Home Assistant camera tools."""
    register_tool_methods(mcp, CameraTools(client))
