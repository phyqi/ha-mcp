"""S3 and MinIO-compatible object storage client for Home Assistant MCP Server.

Provides async object upload and presigned GET URL generation using the official
MinIO Python SDK. Compatible with MinIO, AWS S3, Cloudflare R2, Ceph,
and other S3-compliant object storage services.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import anyio
from minio import Minio
from minio.error import S3Error

from ha_mcp.config import get_settings
from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tools.helpers import raise_tool_error

logger = logging.getLogger(__name__)

_DEFAULT_REGION = "us-east-1"
_DEFAULT_PRESIGNED_TTL = 604800  # 7 days (1 week)


class S3Client:
    """Async S3 / MinIO client for uploading objects and generating URLs using MinIO SDK."""

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
        minio_client: Minio | None = None,
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
        self._minio_client = minio_client

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

    def _get_minio_client(self) -> Minio:
        """Instantiate or return the underlying Minio client."""
        if self._minio_client is not None:
            return self._minio_client
        return Minio(
            endpoint=self._netloc,
            access_key=self._access_key or "",
            secret_key=self._secret_key or "",
            secure=self._secure,
            region=self._region or _DEFAULT_REGION,
        )

    async def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str = "application/octet-stream",
        bucket: str | None = None,
    ) -> dict[str, Any]:
        """Upload raw bytes to MinIO / S3 object storage."""
        effective_bucket = self._ensure_configured(bucket)
        clean_key = object_key.lstrip("/")
        client = self._get_minio_client()

        def _sync_put() -> Any:
            try:
                if not client.bucket_exists(effective_bucket):
                    client.make_bucket(effective_bucket)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Bucket existence check/create ignored: {exc}")

            return client.put_object(
                bucket_name=effective_bucket,
                object_name=clean_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        try:
            res = await anyio.to_thread.run_sync(_sync_put)
            etag = res.etag.strip('"') if getattr(res, "etag", None) else ""
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
        except S3Error as err:
            logger.error(f"MinIO upload failed: {err.code} - {err.message}")
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    f"Failed to upload object to MinIO: {err.code}",
                    details=err.message,
                    context={"bucket": effective_bucket, "object_key": clean_key},
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"MinIO upload failed: {exc}")
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    "Failed to upload object to MinIO",
                    details=str(exc),
                    context={"bucket": effective_bucket, "object_key": clean_key},
                )
            )

    def generate_presigned_url(
        self,
        object_key: str,
        bucket: str | None = None,
        expires_in: int = _DEFAULT_PRESIGNED_TTL,
    ) -> str:
        """Generate a presigned GET URL for an object valid for expires_in seconds."""
        effective_bucket = self._ensure_configured(bucket)
        clean_key = object_key.lstrip("/")

        if expires_in == 0:
            return self.get_public_url(clean_key, bucket=effective_bucket)

        client = self._get_minio_client()
        url = client.presigned_get_object(
            bucket_name=effective_bucket,
            object_name=clean_key,
            expires=timedelta(seconds=expires_in),
        )

        if self._public_url_raw:
            raw = self._public_url_raw.strip()
            if not raw.startswith(("http://", "https://")):
                raw = f"{'https' if self._secure else 'http'}://{raw}"
            parsed_pub = urlparse(raw)
            parsed_url = urlparse(url)
            scheme = parsed_pub.scheme or ("https" if self._secure else "http")
            netloc = parsed_pub.netloc or parsed_pub.path
            url = parsed_url._replace(scheme=scheme, netloc=netloc).geturl()

        return url

    def get_public_url(self, object_key: str, bucket: str | None = None) -> str:
        """Generate direct public URL for a bucket object."""
        effective_bucket = self._ensure_configured(bucket)
        clean_key = object_key.lstrip("/")

        if self._public_url_raw:
            raw = self._public_url_raw.strip().rstrip("/")
            if not raw.startswith(("http://", "https://")):
                raw = f"{'https' if self._secure else 'http'}://{raw}"
            return f"{raw}/{effective_bucket}/{clean_key}"

        return f"{self._scheme}://{self._netloc}/{effective_bucket}/{clean_key}"

    async def cleanup_expired_objects(
        self,
        prefix: str | None = None,
        max_age_seconds: int = _DEFAULT_PRESIGNED_TTL,
        bucket: str | None = None,
    ) -> int:
        """Remove objects under prefix older than max_age_seconds (default 3600s / 1 hour)."""
        if not self.is_configured:
            return 0

        effective_bucket = self._ensure_configured(bucket)
        effective_prefix = self.default_prefix
        if prefix is not None:
            effective_prefix = prefix.strip().strip("/")

        client = self._get_minio_client()

        def _sync_cleanup() -> int:
            deleted_count = 0
            now = datetime.now(UTC)
            threshold = now - timedelta(seconds=max_age_seconds)
            try:
                search_prefix = f"{effective_prefix}/" if effective_prefix else ""
                objs = client.list_objects(
                    bucket_name=effective_bucket,
                    prefix=search_prefix,
                    recursive=True,
                )
                for obj in objs:
                    last_mod = getattr(obj, "last_modified", None)
                    if last_mod and last_mod < threshold:
                        client.remove_object(effective_bucket, obj.object_name)
                        deleted_count += 1
                        logger.info(
                            f"Removed expired storage object: {obj.object_name} (older than {max_age_seconds}s)"
                        )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Storage cleanup notice: {exc}")
            return deleted_count

        return await anyio.to_thread.run_sync(_sync_cleanup)
