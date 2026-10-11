"""Remote backup storage: a provider-neutral interface and its S3-compatible implementation."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from mbp.logging import register_secret

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
MAX_DETAIL = 500
PROBE_KEY = ".mbp-connection-test"

# Multipart uploads stream from the file in bounded parts (Principle VII): memory use is at
# most part size x concurrency, whatever the backup size. 64 MiB parts allow ~640 GB files.
_TRANSFER = TransferConfig(
    multipart_threshold=64 * 1024 * 1024,
    multipart_chunksize=64 * 1024 * 1024,
    max_concurrency=4,
    use_threads=True,
)


class RemoteError(Exception):
    """A remote storage operation failed; `code` is stable, `message` is sanitized."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class RemoteStorage(Protocol):
    """What backup and retention logic need from any remote backend (Principle XI)."""

    def check(self) -> None:
        """Verify the target is reachable and writable; raise RemoteError otherwise."""

    def upload(self, local_path: Path, key: str, sha256: str) -> None:
        """Stream a local file to `key`; raise RemoteError if it is not stored completely."""

    def delete(self, key: str) -> None:
        """Remove `key`; deleting a missing object is not an error."""

    def open_stream(self, key: str) -> Iterator[bytes]:
        """Stream the object's bytes in chunks."""

    def size(self, key: str) -> int:
        """Size of the stored object in bytes."""


@dataclass(frozen=True)
class S3Config:
    bucket: str
    access_key_id: str
    secret_access_key: str = field(repr=False)
    endpoint_url: str = ""
    region: str = ""
    prefix: str = ""
    force_path_style: bool = True


def join_key(prefix: str, relative: str) -> str:
    prefix = prefix.strip("/")
    relative = relative.lstrip("/")
    return f"{prefix}/{relative}" if prefix else relative


def _sanitize(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "***")
    return text[:MAX_DETAIL]


class S3RemoteStorage:
    """Any S3-compatible service: AWS S3, MinIO, Ceph RGW, Wasabi, Arvan, ..."""

    def __init__(self, config: S3Config, timeout: int = 30) -> None:
        self.config = config
        register_secret(config.secret_access_key)
        self._client = boto3.session.Session().client(
            "s3",
            endpoint_url=config.endpoint_url or None,
            region_name=config.region or "us-east-1",
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(
                connect_timeout=timeout,
                read_timeout=timeout * 2,
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path" if config.force_path_style else "auto"},
                # Many S3-compatible services reject the newer default CRC checksums.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def _error(self, exc: Exception) -> RemoteError:
        secret = self.config.secret_access_key
        if isinstance(exc, EndpointConnectionError):
            return RemoteError("endpoint_unreachable", _sanitize(str(exc), secret))
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            code = str(error.get("Code", ""))
            message = _sanitize(f"{code}: {error.get('Message', '')}".strip(": "), secret)
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("NoSuchBucket",) or (code == "404" and "Bucket" in str(exc)):
                return RemoteError("bucket_not_found", message)
            if code in (
                "InvalidAccessKeyId",
                "SignatureDoesNotMatch",
                "AuthorizationHeaderMalformed",
            ):
                return RemoteError("auth_rejected", message)
            if code in ("AccessDenied", "AllAccessDisabled") or status == 403:
                return RemoteError("access_denied", message)
            return RemoteError("remote_error", message)
        if isinstance(exc, BotoCoreError):
            return RemoteError("remote_error", _sanitize(str(exc), secret))
        if isinstance(exc, OSError):
            return RemoteError("remote_error", _sanitize(str(exc), secret))
        return RemoteError("remote_error", _sanitize(repr(exc), secret))

    def check(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.config.bucket)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise RemoteError("bucket_not_found", None) from exc
            raise self._error(exc) from exc
        except (BotoCoreError, OSError) as exc:
            raise self._error(exc) from exc
        # Listing may be allowed while writing is not: prove write and delete access.
        key = join_key(self.config.prefix, PROBE_KEY)
        try:
            self._client.put_object(Bucket=self.config.bucket, Key=key, Body=b"ok")
            self._client.delete_object(Bucket=self.config.bucket, Key=key)
        except (ClientError, BotoCoreError, OSError) as exc:
            raise self._error(exc) from exc

    def upload(self, local_path: Path, key: str, sha256: str) -> None:
        expected = local_path.stat().st_size
        try:
            self._client.upload_file(
                str(local_path),
                self.config.bucket,
                key,
                ExtraArgs={"Metadata": {"sha256": sha256}},
                Config=_TRANSFER,
            )
            stored = self.size(key)
        except RemoteError:
            raise
        except (ClientError, BotoCoreError, OSError) as exc:
            raise self._error(exc) from exc
        except Exception as exc:  # boto3's S3UploadFailedError wraps the ClientError
            cause = exc.__cause__ or exc.__context__
            raise self._error(cause if isinstance(cause, Exception) else exc) from exc
        if stored != expected:
            raise RemoteError(
                "upload_incomplete", f"Stored object has {stored} bytes, expected {expected}."
            )

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.config.bucket, Key=key)
        except (ClientError, BotoCoreError, OSError) as exc:
            raise self._error(exc) from exc

    def size(self, key: str) -> int:
        try:
            head = self._client.head_object(Bucket=self.config.bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise RemoteError("object_not_found", None) from exc
            raise self._error(exc) from exc
        except (BotoCoreError, OSError) as exc:
            raise self._error(exc) from exc
        return int(head["ContentLength"])

    def open_stream(self, key: str) -> Iterator[bytes]:
        try:
            body = self._client.get_object(Bucket=self.config.bucket, Key=key)["Body"]
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise RemoteError("object_not_found", None) from exc
            raise self._error(exc) from exc
        except (BotoCoreError, OSError) as exc:
            raise self._error(exc) from exc

        def chunks() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(CHUNK_SIZE)
            finally:
                body.close()

        return chunks()
