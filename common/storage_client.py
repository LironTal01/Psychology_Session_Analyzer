import os
from datetime import timedelta
from typing import Final

from minio import Minio
from minio.error import S3Error

from .config import minio as minio_config


class StorageClient:
    """
    Thin wrapper around the MinIO client used by multiple microservices.

    Responsibilities:
    - create buckets on first use
    - generate non-conflicting object names
    - upload and download objects
    - return a stable object URL that other services can pass around
    """

    def __init__(self) -> None:
        self._endpoint: Final[str] = minio_config.endpoint
        self._secure: Final[bool] = minio_config.secure

        self.client = Minio(
            endpoint=minio_config.endpoint,
            access_key=minio_config.access_key,
            secret_key=minio_config.secret_key,
            secure=minio_config.secure,
        )

    def create_bucket_if_not_exists(self, bucket_name: str) -> None:
        """
        Ensure that a bucket exists in MinIO.

        This is safe to call repeatedly; the bucket is created only on first use.
        """
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def _object_exists(self, bucket: str, object_name: str) -> bool:
        """
        Return True if the given object exists in the bucket, False if not.

        Any other storage-related error (e.g. missing bucket, permissions)
        is re-raised so callers can handle it.
        """
        try:
            self.client.stat_object(bucket, object_name)
            return True
        except S3Error as exc:
            # NoSuchKey / NoSuchObject means the object is not there – this is OK.
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            # Propagate all other errors (e.g. NoSuchBucket, auth issues).
            raise

    def get_unique_object_name(self, bucket: str, filename: str) -> str:
        """
        Generate a non-conflicting object name for a given original filename.

        Examples:
            CBT.mp4       -> CBT.mp4
            (exists)         CBT(1).mp4
            (exists)         CBT(2).mp4
        """
        base, ext = os.path.splitext(filename)
        # Normalise empty base just in case (very defensive).
        if not base:
            base = "file"

        candidate = f"{base}{ext}"
        counter = 1

        # Loop until we find a name that does not exist in MinIO.
        while self._object_exists(bucket, candidate):
            candidate = f"{base}({counter}){ext}"
            counter += 1

        return candidate

    def _build_object_url(self, bucket: str, object_name: str) -> str:
        """
        Construct an internal HTTP(S) object URL.

        Other services treat this as an opaque reference and may parse it later
        to recover (bucket, object_name).

        Format (backwards compatible):
            http://minio:9000/<bucket>/<object_name>
        """
        scheme = "https" if self._secure else "http"
        # object_name is assumed not to start with a slash, so no double slashes.
        return f"{scheme}://{self._endpoint}/{bucket}/{object_name}"

    def upload_file(self, bucket: str, file_path: str, object_name: str) -> str:
        """
        Upload a local file to the given bucket and return its object URL.

        The caller is responsible for providing a non-conflicting object_name,
        typically by calling `get_unique_object_name(bucket, filename)` first.
        """
        self.create_bucket_if_not_exists(bucket)
        self.client.fput_object(
            bucket_name=bucket,
            object_name=object_name,
            file_path=file_path,
        )
        return self._build_object_url(bucket=bucket, object_name=object_name)

    def download_file(self, bucket: str, object_name: str, destination_path: str) -> None:
        """
        Download an object into a local path.
        """
        self.client.fget_object(bucket, object_name, destination_path)

    def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires_seconds: int = 3600,
    ) -> str:
        """
        Generate a presigned GET URL for an object so that external services
        (like AssemblyAI) can access it without direct MinIO credentials.
        """
        expires = timedelta(seconds=expires_seconds)
        return self.client.presigned_get_object(bucket, object_name, expires=expires)

