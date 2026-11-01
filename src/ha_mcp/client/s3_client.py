"""S3 and MinIO-compatible object storage client for Home Assistant MCP Server.

Provides async object upload and presigned GET URL generation using AWS
Signature Version 4 (SigV4) with zero external dependencies (pure Python
hashlib/hmac + httpx). Compatible with MinIO, AWS S3, Cloudflare R2, Ceph,
and other S3-compliant object storage services.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from ha_mcp.config import get_settings
from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tools.helpers import raise_tool_error

logger = logging.getLogger(__name__)

_DEFAULT_REGION = "us-east-1"
_DEFAULT_PRESIGNED_TTL = 3600  # 1 hour


def _sign(key: bytes, msg: str) -> bytes:
    """Compute HMAC-SHA256 signature."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(
    key: str, date_stamp: str, region_name: str, service_name: str
) -> bytes:
    """Derive AWS SigV4 signing key."""
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    return _sign(k_service, "aws4_request")


class S3Client:
    """Async S3 / MinIO client for uploading objects and generating URLs."""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        prefix: str | None = None,
        region: str | None = None,
        secure: bool | None = None,
        public_url: str | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._endpoint_raw = endpoint or settings.minio_endpoint
        self._access_key = access_key or settings.minio_access_key
        self._secret_key = secret_key or settings.minio_secret_key
        self._default_bucket = bucket or settings.minio_bucket
        raw_prefix = prefix if prefix is not None else settings.minio_prefix
        self._default_prefix = raw_prefix.strip().strip("/") if raw_prefix else ""
        self._region = region or settings.minio_region or _DEFAULT_REGION
        self._secure = secure if secure is not None else settings.minio_secure
        self._public_url_raw = public_url or settings.minio_public_url
        self._httpx_client = httpx_client

        # Normalize endpoint
        self._scheme, self._netloc, self._base_path = self._parse_endpoint(
            self._endpoint_raw, self._secure
        )

    @property
    def default_prefix(self) -> str:
        """Default directory / path prefix for uploaded objects."""
        return self._default_prefix

    @staticmethod
    def _parse_endpoint(endpoint: str | None, secure: bool) -> tuple[str, str, str]:
        """Normalize endpoint URL into scheme, netloc (host:port), and base_path."""
        if not endpoint:
            return ("https" if secure else "http", "", "")
        trimmed = endpoint.strip()
        if not trimmed.startswith(("http://", "https://")):
            scheme = "https" if secure else "http"
            trimmed = f"{scheme}://{trimmed}"
        parsed = urlparse(trimmed)
        scheme = parsed.scheme or ("https" if secure else "http")
        netloc = parsed.netloc or parsed.path.split("/")[0]
        base_path = parsed.path if parsed.netloc else ""
        return (scheme, netloc, base_path.rstrip("/"))

    @property
    def is_configured(self) -> bool:
        """Check whether basic connection credentials are provided."""
        return bool(self._netloc and self._access_key and self._secret_key)

    def _ensure_configured(self, bucket: str | None = None) -> str:
        """Verify client configuration and return effective bucket name."""
        if not self._netloc:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "MinIO / S3 endpoint is not configured. Set MINIO_ENDPOINT or configure in Settings.",
                    suggestions=[
                        "Set MINIO_ENDPOINT in .env or Settings UI (e.g., 'minio.local:9000')"
                    ],
                )
            )
        if not self._access_key or not self._secret_key:
            raise_tool_error(
                create_error_response(
                    ErrorCode.AUTH_INVALID_TOKEN,
                    "MinIO / S3 credentials are missing. Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY.",
                    suggestions=[
                        "Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY in .env or Settings UI"
                    ],
                )
            )
        effective_bucket = bucket or self._default_bucket
        if not effective_bucket:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "No MinIO / S3 bucket specified. Provide 'bucket' parameter or set MINIO_BUCKET.",
                    suggestions=[
                        "Provide 'bucket' parameter in tool call or configure MINIO_BUCKET"
                    ],
                )
            )
        return effective_bucket

    def _canonical_uri(self, bucket: str, object_key: str) -> str:
        """Construct RFC 3986 canonical URI for bucket and object key."""
        clean_key = object_key.lstrip("/")
        # Encode key segments safely
        encoded_segments = [
            quote(segment, safe="-_.~") for segment in clean_key.split("/")
        ]
        key_path = "/".join(encoded_segments)
        base = f"{self._base_path}/{quote(bucket, safe='-_.~')}/{key_path}"
        # Ensure single leading slash
        return "/" + base.lstrip("/")

    async def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str = "application/octet-stream",
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Upload raw bytes to MinIO / S3 object storage using SigV4."""
        effective_bucket = self._ensure_configured(bucket)
        clean_key = object_key.lstrip("/")
        canonical_uri = self._canonical_uri(effective_bucket, clean_key)

        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        payload_hash = hashlib.sha256(data).hexdigest()

        # Build headers
        host_header = self._netloc
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{host_header}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"

        # Canonical request
        canonical_request = (
            f"PUT\n"
            f"{canonical_uri}\n"
            f"\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        # String to sign
        credential_scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(
            self._secret_key or "", date_stamp, self._region, "s3"
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        authorization_header = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        req_headers = {
            "Host": host_header,
            "Content-Type": content_type,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization_header,
            "Content-Length": str(len(data)),
        }

        target_url = f"{self._scheme}://{self._netloc}{canonical_uri}"

        client = self._httpx_client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.put(target_url, headers=req_headers, content=data)
            if response.status_code not in (200, 201, 204):
                error_body = response.text[:300]
                logger.error(
                    f"MinIO/S3 upload failed: HTTP {response.status_code} - {error_body}"
                )
                raise_tool_error(
                    create_error_response(
                        ErrorCode.SERVICE_CALL_FAILED,
                        f"Failed to upload object to MinIO/S3: HTTP {response.status_code}",
                        details=error_body,
                        context={"bucket": effective_bucket, "object_key": clean_key},
                    )
                )

            etag = response.headers.get("etag", "").strip('"')
            logger.info(
                f"Successfully uploaded {clean_key} ({len(data)} bytes) to bucket {effective_bucket}"
            )
            return {
                "success": True,
                "bucket": effective_bucket,
                "object_key": clean_key,
                "size_bytes": len(data),
                "content_type": content_type,
                "etag": etag,
            }
        finally:
            if self._httpx_client is None:
                await client.aclose()

    def generate_presigned_url(
        self,
        object_key: str,
        bucket: str | None = None,
        expires_in: int = _DEFAULT_PRESIGNED_TTL,
    ) -> str:
        """Generate a presigned GET URL for an object valid for expires_in seconds."""
        effective_bucket = self._ensure_configured(bucket)
        clean_key = object_key.lstrip("/")
        canonical_uri = self._canonical_uri(effective_bucket, clean_key)

        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        credential_scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        credential_value = f"{self._access_key}/{credential_scope}"

        # If custom public URL is configured, use its host/scheme for accessible client URL
        if self._public_url_raw:
            pub_scheme, pub_netloc, _ = self._parse_endpoint(
                self._public_url_raw, self._secure
            )
            host_header = pub_netloc
            scheme = pub_scheme
        else:
            host_header = self._netloc
            scheme = self._scheme

        query_params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": credential_value,
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires_in),
            "X-Amz-SignedHeaders": "host",
        }

        # Canonical query string: sorted by key and percent-encoded
        sorted_params = sorted(query_params.items())
        canonical_query_string = urlencode(sorted_params, quote_via=quote)

        # Canonical request
        canonical_headers = f"host:{host_header}\n"
        signed_headers = "host"
        payload_hash = "UNSIGNED-PAYLOAD"

        canonical_request = (
            f"GET\n"
            f"{canonical_uri}\n"
            f"{canonical_query_string}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(
            self._secret_key or "", date_stamp, self._region, "s3"
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        return f"{scheme}://{host_header}{canonical_uri}?{canonical_query_string}&X-Amz-Signature={signature}"

    def get_public_url(self, object_key: str, bucket: str | None = None) -> str:
        """Construct direct public URL without signature parameters."""
        effective_bucket = self._ensure_configured(bucket)
        clean_key = object_key.lstrip("/")
        canonical_uri = self._canonical_uri(effective_bucket, clean_key)

        if self._public_url_raw:
            pub_scheme, pub_netloc, _ = self._parse_endpoint(
                self._public_url_raw, self._secure
            )
            return f"{pub_scheme}://{pub_netloc}{canonical_uri}"

        return f"{self._scheme}://{self._netloc}{canonical_uri}"
