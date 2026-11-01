"""Unit tests for S3Client using official MinIO Python SDK."""

from unittest.mock import MagicMock

import pytest
from minio.error import S3Error
from urllib3.response import HTTPResponse

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.s3_client import S3Client


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
    assert "X-Amz-Signature=" in url


def test_generate_presigned_url_with_public_url() -> None:
    client = S3Client(
        endpoint="minio-internal:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="test-bucket",
        region="us-east-1",
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
    mock_minio = MagicMock()
    mock_minio.bucket_exists.return_value = True

    mock_result = MagicMock()
    mock_result.etag = '"abc123etag"'
    mock_result.object_name = "front.jpg"
    mock_result.version_id = None
    mock_minio.put_object.return_value = mock_result

    client = S3Client(
        endpoint="minio.local:9000",
        access_key="admin",
        secret_key="secret",
        bucket="captures",
        minio_client=mock_minio,
    )

    payload = b"\xff\xd8\xff\xe0testjpegcontent"
    res = await client.upload_bytes(payload, "front.jpg", content_type="image/jpeg")

    assert res["success"] is True
    assert res["bucket"] == "captures"
    assert res["object_key"] == "front.jpg"
    assert res["size_bytes"] == len(payload)
    assert res["content_type"] == "image/jpeg"
    assert res["etag"] == "abc123etag"

    mock_minio.put_object.assert_called_once()
    args, kwargs = mock_minio.put_object.call_args
    assert kwargs["bucket_name"] == "captures"
    assert kwargs["object_name"] == "front.jpg"
    assert kwargs["length"] == len(payload)
    assert kwargs["content_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_bytes_failure() -> None:
    mock_minio = MagicMock()
    mock_minio.bucket_exists.return_value = True

    response = HTTPResponse(status=403, reason="AccessDenied")
    s3_err = S3Error(
        code="AccessDenied",
        message="Access Denied",
        resource="/captures/test.jpg",
        request_id="123",
        host_id="456",
        response=response,
    )
    mock_minio.put_object.side_effect = s3_err

    client = S3Client(
        endpoint="minio.local:9000",
        access_key="admin",
        secret_key="secret",
        bucket="captures",
        minio_client=mock_minio,
    )

    with pytest.raises(ToolError, match="AccessDenied"):
        await client.upload_bytes(b"content", "test.jpg")
