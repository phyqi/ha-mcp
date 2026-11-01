"""Unit tests for S3Client (pure Python SigV4 MinIO/S3 object storage client)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.s3_client import S3Client, _get_signature_key


def test_sigv4_key_derivation() -> None:
    """Verify that AWS SigV4 key derivation produces a 32-byte hash."""
    signing_key = _get_signature_key(
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "20130524",
        "us-east-1",
        "s3",
    )
    assert len(signing_key) == 32


@pytest.mark.parametrize(
    ("raw_endpoint", "secure", "expected_scheme", "expected_netloc", "expected_path"),
    [
        ("minio.local:9000", False, "http", "minio.local:9000", ""),
        ("minio.local:9000", True, "https", "minio.local:9000", ""),
        ("http://192.168.1.100:9000", False, "http", "192.168.1.100:9000", ""),
        ("https://s3.amazonaws.com", False, "https", "s3.amazonaws.com", ""),
        (
            "http://minio.local:9000/custom/path",
            False,
            "http",
            "minio.local:9000",
            "/custom/path",
        ),
        (None, False, "http", "", ""),
    ],
)
def test_parse_endpoint(
    raw_endpoint: str | None,
    secure: bool,
    expected_scheme: str,
    expected_netloc: str,
    expected_path: str,
) -> None:
    client = S3Client(
        endpoint=raw_endpoint,
        access_key="test_key",
        secret_key="test_secret",
        secure=secure,
    )
    assert client._scheme == expected_scheme
    assert client._netloc == expected_netloc
    assert client._base_path == expected_path


def test_ensure_configured_raises_on_missing_config() -> None:
    # Missing endpoint
    client1 = S3Client(endpoint="", access_key="key", secret_key="sec")
    with pytest.raises(ToolError, match="endpoint is not configured"):
        client1._ensure_configured("bucket")

    # Missing credentials
    client2 = S3Client(endpoint="localhost:9000", access_key="", secret_key="")
    with pytest.raises(ToolError, match="credentials are missing"):
        client2._ensure_configured("bucket")

    # Missing bucket
    client3 = S3Client(
        endpoint="localhost:9000", access_key="key", secret_key="sec", bucket=""
    )
    with pytest.raises(ToolError, match="No MinIO / S3 bucket specified"):
        client3._ensure_configured(None)


def test_generate_presigned_url() -> None:
    client = S3Client(
        endpoint="minio.local:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="test-bucket",
        region="us-east-1",
        secure=False,
    )

    url = client.generate_presigned_url("captures/cam1.jpg", expires_in=1800)
    assert url.startswith("http://minio.local:9000/test-bucket/captures/cam1.jpg?")
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
    assert "X-Amz-Credential=minioadmin" in url
    assert "X-Amz-Expires=1800" in url
    assert "X-Amz-SignedHeaders=host" in url
    assert "X-Amz-Signature=" in url


def test_generate_presigned_url_with_public_url() -> None:
    client = S3Client(
        endpoint="minio-internal:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="test-bucket",
        public_url="https://s3.example.com",
    )

    url = client.generate_presigned_url("captures/cam1.jpg")
    assert url.startswith("https://s3.example.com/test-bucket/captures/cam1.jpg?")
    assert "X-Amz-Signature=" in url


def test_get_public_url() -> None:
    client = S3Client(
        endpoint="minio.local:9000",
        access_key="key",
        secret_key="sec",
        bucket="test-bucket",
        secure=False,
    )
    assert (
        client.get_public_url("images/test.png")
        == "http://minio.local:9000/test-bucket/images/test.png"
    )

    client_pub = S3Client(
        endpoint="minio.local:9000",
        access_key="key",
        secret_key="sec",
        bucket="test-bucket",
        public_url="https://s3.example.com",
    )
    assert (
        client_pub.get_public_url("images/test.png")
        == "https://s3.example.com/test-bucket/images/test.png"
    )


@pytest.mark.asyncio
async def test_upload_bytes_success() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"etag": '"abc123etag"'}

    mock_httpx = AsyncMock(spec=httpx.AsyncClient)
    mock_httpx.put.return_value = mock_resp

    client = S3Client(
        endpoint="minio.local:9000",
        access_key="admin",
        secret_key="secret",
        bucket="captures",
        httpx_client=mock_httpx,
    )

    payload = b"\xff\xd8\xff\xe0testjpegcontent"
    res = await client.upload_bytes(payload, "front.jpg", content_type="image/jpeg")

    assert res["success"] is True
    assert res["bucket"] == "captures"
    assert res["object_key"] == "front.jpg"
    assert res["size_bytes"] == len(payload)
    assert res["content_type"] == "image/jpeg"
    assert res["etag"] == "abc123etag"

    mock_httpx.put.assert_called_once()
    call_args = mock_httpx.put.call_args
    assert call_args[0][0] == "http://minio.local:9000/captures/front.jpg"
    headers = call_args[1]["headers"]
    assert "Authorization" in headers
    assert headers["Content-Type"] == "image/jpeg"
    assert headers["Content-Length"] == str(len(payload))


@pytest.mark.asyncio
async def test_upload_bytes_failure() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "<Error><Code>AccessDenied</Code></Error>"

    mock_httpx = AsyncMock(spec=httpx.AsyncClient)
    mock_httpx.put.return_value = mock_resp

    client = S3Client(
        endpoint="minio.local:9000",
        access_key="admin",
        secret_key="secret",
        bucket="captures",
        httpx_client=mock_httpx,
    )

    with pytest.raises(ToolError, match="HTTP 403"):
        await client.upload_bytes(b"content", "test.jpg")
