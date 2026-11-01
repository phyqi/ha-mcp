"""Base classes and helpers for tools that interact with object storage."""

from __future__ import annotations

from typing import Any

from ha_mcp.client.s3_client import S3Client


class StorageConsumerMixin:
    """Mixin providing shared client and s3_client attributes for storage-enabled tools."""

    _client: Any
    _s3_client: S3Client

    def __init__(self, client: Any, s3_client: S3Client | None = None) -> None:
        self._client = client
        self._s3_client = s3_client or S3Client()
