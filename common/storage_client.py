import os
from typing import Final

from minio import Minio


class StorageClient:
    """
    Thin wrapper around the MinIO client used by multiple microservices.

    Responsibilities:
    - create buckets on first use
    - upload and download objects
    - return a stable object URL that other services can pass around
    """

    _DEFAULT_ENDPOINT: Final[str] = "minio:9000"
    _DEFAULT_ACCESS_KEY: Final[str] = "admin"
    _DEFAULT_SECRET_KEY: Final[str] = "password123"

    def __init__(self) -> None:
        endpoint = os.getenv("MINIO_ENDPOINT", self._DEFAULT_ENDPOINT)
        access_key = os.getenv("MINIO_ACCESS_KEY", self._DEFAULT_ACCESS_KEY)
        secret_key = os.getenv("MINIO_SECRET_KEY", self._DEFAULT_SECRET_KEY)

        # Represent security as a boolean, driven by env but defaulting to HTTP.
        secure_env = os.getenv("MINIO_SECURE", "false").lower()
        secure = secure_env in {"1", "true", "yes", "on"}

        self._endpoint = endpoint
        self._secure = secure

        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def create_bucket_if_not_exists(self, bucket_name: str) -> None:
        """
        Ensure that a bucket exists in MinIO.

        This is safe to call repeatedly; the bucket is created only on first use.
        """
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def _build_object_url(self, bucket: str, object_name: str) -> str:
        """
        Construct an internal HTTP(S) object URL.

        Other services treat this as an opaque reference and may parse it later
        to recover (bucket, object_name).
        """
        scheme = "https" if self._secure else "http"
        return f"{scheme}://{self._endpoint}/{bucket}/{object_name}"

    def upload_file(self, bucket: str, file_path: str, object_name: str) -> str:
        """
        Upload a local file to the given bucket and return its object URL.
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

