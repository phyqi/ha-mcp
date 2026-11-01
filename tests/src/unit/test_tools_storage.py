"""Unit tests for StorageTools and ha_upload_capture."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp._vendor.fastmcp.tools import ToolResult
from ha_mcp.client.s3_client import S3Client
from ha_mcp.dashboard_screenshot.capture import DashboardImageCapture
from ha_mcp.tools.tools_storage import StorageTools


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.httpx_client = AsyncMock()
    return client


@pytest.fixture
def mock_s3() -> MagicMock:
    s3 = MagicMock(spec=S3Client)
    s3.upload_bytes = AsyncMock(
        return_value={
            "success": True,
            "bucket": "test-bucket",
            "object_key": "captures/cameras/camera_front_door_20261101_120000.jpeg",
            "size_bytes": 1024,
            "content_type": "image/jpeg",
            "etag": "123etag",
        }
    )
    s3.generate_presigned_url.return_value = "http://minio.local:9000/test-bucket/captures/cameras/camera_front_door_20261101_120000.jpeg?X-Amz-Signature=abc"
    s3.get_public_url.return_value = "http://minio.local:9000/test-bucket/captures/cameras/camera_front_door_20261101_120000.jpeg"
    return s3


@pytest.mark.asyncio
async def test_camera_capture_and_upload_success(
    mock_client: MagicMock, mock_s3: MagicMock
) -> None:
    # 1x1 valid JPEG bytes
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = jpeg_bytes
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_client.httpx_client.get.return_value = mock_resp

    tools = StorageTools(mock_client, s3_client=mock_s3)
    result = await tools.ha_upload_capture(
        source="camera",
        camera_entity_id="camera.front_door",
        bucket="my-bucket",
        expires_in=3600,
    )

    assert isinstance(result, dict)
    assert result["success"] is True
    assert result["url"].startswith("http://minio.local:9000/")
    assert result["source"]["type"] == "camera"
    assert result["source"]["target"] == "camera.front_door"

    mock_client.httpx_client.get.assert_called_once_with(
        "/camera_proxy/camera.front_door", params=None
    )
    mock_s3.upload_bytes.assert_called_once()
    mock_s3.generate_presigned_url.assert_called_once()


@pytest.mark.asyncio
async def test_camera_capture_include_image_content(
    mock_client: MagicMock, mock_s3: MagicMock
) -> None:
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = jpeg_bytes
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_client.httpx_client.get.return_value = mock_resp

    tools = StorageTools(mock_client, s3_client=mock_s3)
    result = await tools.ha_upload_capture(
        source="camera",
        camera_entity_id="camera.backyard",
        include_image_content=True,
    )

    assert isinstance(result, ToolResult)
    assert result.structured_content["success"] is True
    assert len(result.content) == 1  # Contains Image


@pytest.mark.asyncio
async def test_dashboard_capture_and_upload_success(
    mock_client: MagicMock, mock_s3: MagicMock
) -> None:
    mock_capture = MagicMock(spec=DashboardImageCapture)
    mock_capture.data = b"\x89PNG\r\n\x1a\nfake_png_data"
    mock_capture.image_format = "png"
    mock_capture.mime_type = "image/png"

    with patch(
        "ha_mcp.tools.tools_storage.capture_dashboard_images",
        new=AsyncMock(return_value=[mock_capture]),
    ):
        tools = StorageTools(mock_client, s3_client=mock_s3)
        result = await tools.ha_upload_capture(
            source="dashboard",
            dashboard_path="lovelace",
            dashboard_view="living_room",
            expires_in=0,  # Test direct public URL
        )

        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["source"]["type"] == "dashboard"
        assert result["source"]["target"] == "lovelace"
        assert result["source"]["view"] == "living_room"
        mock_s3.get_public_url.assert_called_once()


@pytest.mark.asyncio
async def test_camera_validation_failures(
    mock_client: MagicMock, mock_s3: MagicMock
) -> None:
    tools = StorageTools(mock_client, s3_client=mock_s3)

    # Missing camera_entity_id
    with pytest.raises(ToolError, match="camera_entity_id is required"):
        await tools.ha_upload_capture(source="camera", camera_entity_id=None)

    # Invalid camera entity format
    with pytest.raises(ToolError, match=r"Expected 'camera\.<name>'"):
        await tools.ha_upload_capture(
            source="camera", camera_entity_id="light.living_room"
        )


@pytest.mark.asyncio
async def test_custom_prefix_and_object_name(
    mock_client: MagicMock, mock_s3: MagicMock
) -> None:
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = jpeg_bytes
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_client.httpx_client.get.return_value = mock_resp

    tools = StorageTools(mock_client, s3_client=mock_s3)

    # 1. Custom prefix
    await tools.ha_upload_capture(
        source="camera",
        camera_entity_id="camera.gate",
        prefix="security/cctv",
    )
    call_key = mock_s3.upload_bytes.call_args[0][1]
    assert call_key.startswith("security/cctv/camera_gate_")

    # 2. Custom explicit object_name (overrides prefix)
    await tools.ha_upload_capture(
        source="camera",
        camera_entity_id="camera.gate",
        object_name="archive/manual_snapshot.jpg",
    )
    call_key_explicit = mock_s3.upload_bytes.call_args[0][1]
    assert call_key_explicit == "archive/manual_snapshot.jpg"


@pytest.mark.asyncio
async def test_dashboard_validation_failures(
    mock_client: MagicMock, mock_s3: MagicMock
) -> None:
    tools = StorageTools(mock_client, s3_client=mock_s3)

    # Missing dashboard_path
    with pytest.raises(ToolError, match="dashboard_path is required"):
        await tools.ha_upload_capture(source="dashboard", dashboard_path="")
