"""AWS S3 file storage connector provider."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...models import ConnectorCostInfo
from ._base import BaseFileStorageProvider, FileStorageProviderError

logger = logging.getLogger(__name__)


class S3FileStorageProvider(BaseFileStorageProvider):
    """AWS S3 file storage connector provider.

    Uses boto3 (optional dependency) with static access key credentials.

    Example::

        provider = S3FileStorageProvider(
            region="us-east-1",
            bucket="my-bucket",
            aws_access_key_id="AKIA...",
            aws_secret_access_key="...",
        )

    Environment variables::

        AWS_REGION or AWS_DEFAULT_REGION, S3_DEFAULT_BUCKET,
        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN
    """

    def __init__(
        self,
        region: str,
        bucket: str,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        aws_session_token: str = "",
    ) -> None:
        self._region = region
        self._default_bucket = bucket
        self._access_key = aws_access_key_id
        self._secret_key = aws_secret_access_key
        self._session_token = aws_session_token
        self._api_key = bucket  # satisfies is_available()

    @classmethod
    def from_env(cls) -> "S3FileStorageProvider | None":
        """Create an instance from environment variables.

        Required env vars: ``AWS_REGION`` or ``AWS_DEFAULT_REGION``,
        ``S3_DEFAULT_BUCKET``

        Optional env vars: ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
        ``AWS_SESSION_TOKEN``

        Returns None if region or bucket are missing. Warns if boto3 is not
        importable.
        """
        import os
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "")
        bucket = os.environ.get("S3_DEFAULT_BUCKET", "")
        if not region or not bucket:
            return None
        try:
            import boto3  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            logger.warning(
                "boto3 is not installed; S3FileStorageProvider will not be functional. "
                "Install it with: pip install boto3"
            )
        return cls(
            region=region,
            bucket=bucket,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN", ""),
        )

    @property
    def provider_id(self) -> str:
        """Unique provider identifier used for registry lookups."""
        return "file_storage.s3"

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the registry descriptor."""
        return "AWS S3 File Storage"

    def _get_client(self) -> Any:
        """Create a boto3 S3 client. Import is deferred to avoid hard dependency."""
        import boto3  # type: ignore[import-untyped]
        kwargs: dict = {"region_name": self._region}
        if self._access_key:
            kwargs["aws_access_key_id"] = self._access_key
        if self._secret_key:
            kwargs["aws_secret_access_key"] = self._secret_key
        if self._session_token:
            kwargs["aws_session_token"] = self._session_token
        return boto3.client("s3", **kwargs)

    async def _upload_file(
        self,
        name: str,
        content: str | bytes,
        path: str | None,
        content_type: str | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Upload a file to S3.

        Args:
            name: Object name (filename).
            content: File content as str or bytes.
            path: Optional prefix/directory path within the bucket.
            content_type: MIME type of the file.
            bucket: Target bucket; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the S3 API call fails.
        """
        target_bucket = bucket or self._default_bucket
        key = f"{path}/{name}" if path else name
        content_bytes = content.encode() if isinstance(content, str) else content

        def _call() -> None:
            try:
                client = self._get_client()
                client.put_object(
                    Bucket=target_bucket,
                    Key=key,
                    Body=content_bytes,
                    ContentType=content_type or "application/octet-stream",
                )
            except Exception as exc:
                raise FileStorageProviderError(
                    f"S3 upload_file error for key={key!r}: {exc}"
                ) from exc

        await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=key,
            name=name,
            path=path,
            size_bytes=len(content_bytes),
            content_type=content_type,
            url=None,
            content=None,
            raw_payload={"bucket": target_bucket, "key": key},
            resource_type="file",
            provenance={"provider": "s3", "bucket": target_bucket},
        )
        logger.info("S3 upload_file: bucket=%r key=%r", target_bucket, key)
        return artifact.model_dump(mode="json"), None

    async def _download_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Download a file from S3.

        Args:
            file_id: S3 object key.
            bucket: Source bucket; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict with content, None).

        Raises:
            FileStorageProviderError: When the S3 API call fails.
        """
        target_bucket = bucket or self._default_bucket

        def _call() -> dict:
            try:
                client = self._get_client()
                return client.get_object(Bucket=target_bucket, Key=file_id)
            except Exception as exc:
                raise FileStorageProviderError(
                    f"S3 download_file error for key={file_id!r}: {exc}"
                ) from exc

        response = await asyncio.get_running_loop().run_in_executor(None, _call)
        content = response["Body"].read().decode("utf-8", errors="replace")
        name = file_id.split("/")[-1]

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=name,
            path=None,
            size_bytes=response.get("ContentLength"),
            content_type=response.get("ContentType"),
            url=None,
            content=content,
            raw_payload={"bucket": target_bucket, "key": file_id},
            resource_type="file",
            provenance={"provider": "s3", "bucket": target_bucket},
        )
        logger.info("S3 download_file: bucket=%r key=%r", target_bucket, file_id)
        return artifact.model_dump(mode="json"), None

    async def _list_files(
        self,
        path: str | None,
        query: str | None,
        limit: int | None,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """List files in an S3 bucket.

        Args:
            path: Optional key prefix to restrict listing.
            query: Optional substring filter applied to object keys.
            limit: Maximum number of objects to return (default 100).
            bucket: Target bucket; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict with file_list, None).

        Raises:
            FileStorageProviderError: When the S3 API call fails.
        """
        target_bucket = bucket or self._default_bucket
        max_keys = limit or 100

        def _call() -> dict:
            try:
                client = self._get_client()
                kwargs: dict = {"Bucket": target_bucket, "MaxKeys": max_keys}
                if path:
                    kwargs["Prefix"] = path
                return client.list_objects_v2(**kwargs)
            except Exception as exc:
                raise FileStorageProviderError(
                    f"S3 list_files error: {exc}"
                ) from exc

        response = await asyncio.get_running_loop().run_in_executor(None, _call)
        items = [
            {
                "file_id": o["Key"],
                "name": o["Key"].split("/")[-1],
                "size_bytes": o["Size"],
            }
            for o in response.get("Contents", [])
        ]

        artifact = self._make_file_list_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            path=path,
            items=items,
            total=len(items),
            provenance={"provider": "s3", "bucket": target_bucket},
        )
        logger.info(
            "S3 list_files: bucket=%r path=%r items=%d",
            target_bucket, path, len(items),
        )
        return artifact.model_dump(mode="json"), None

    async def _delete_file(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Delete a file from S3.

        Args:
            file_id: S3 object key.
            bucket: Target bucket; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict, None).

        Raises:
            FileStorageProviderError: When the S3 API call fails.
        """
        target_bucket = bucket or self._default_bucket

        def _call() -> None:
            try:
                client = self._get_client()
                client.delete_object(Bucket=target_bucket, Key=file_id)
            except Exception as exc:
                raise FileStorageProviderError(
                    f"S3 delete_file error for key={file_id!r}: {exc}"
                ) from exc

        await asyncio.get_running_loop().run_in_executor(None, _call)

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=file_id,
            path=None,
            size_bytes=None,
            content_type=None,
            url=None,
            content=None,
            raw_payload={"bucket": target_bucket, "key": file_id},
            resource_type="file",
            provenance={"provider": "s3", "bucket": target_bucket},
        )
        logger.info("S3 delete_file: bucket=%r key=%r", target_bucket, file_id)
        return artifact.model_dump(mode="json"), None

    async def _get_metadata(
        self,
        file_id: str,
        bucket: str | None,
    ) -> tuple[dict, ConnectorCostInfo | None]:
        """Get S3 object metadata without downloading content.

        Args:
            file_id: S3 object key.
            bucket: Target bucket; falls back to the configured default.

        Returns:
            Tuple of (ExternalArtifact dict with size/content_type, None).

        Raises:
            FileStorageProviderError: When the S3 API call fails.
        """
        target_bucket = bucket or self._default_bucket

        def _call() -> dict:
            try:
                client = self._get_client()
                return client.head_object(Bucket=target_bucket, Key=file_id)
            except Exception as exc:
                raise FileStorageProviderError(
                    f"S3 get_metadata error for key={file_id!r}: {exc}"
                ) from exc

        response = await asyncio.get_running_loop().run_in_executor(None, _call)
        name = file_id.split("/")[-1]

        artifact = self._make_file_artifact(
            provider=self.provider_id,
            connector_id=self.provider_id,
            file_id=file_id,
            name=name,
            path=None,
            size_bytes=response.get("ContentLength"),
            content_type=response.get("ContentType"),
            url=None,
            content=None,
            raw_payload={"bucket": target_bucket, "key": file_id},
            resource_type="file",
            provenance={"provider": "s3", "bucket": target_bucket},
        )
        logger.info("S3 get_metadata: bucket=%r key=%r", target_bucket, file_id)
        return artifact.model_dump(mode="json"), None
