from minio import Minio
import os


class StorageClient:
    def __init__(self):
        self.client = Minio(
            endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
            secure=False,
        )

    def create_bucket_if_not_exists(self, bucket_name: str):
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def upload_file(self, bucket: str, file_path: str, object_name: str):
        self.create_bucket_if_not_exists(bucket)
        self.client.fput_object(
            bucket_name=bucket,
            object_name=object_name,
            file_path=file_path,
        )
        return f"s3://{bucket}/{object_name}"

    def download_file(self, bucket: str, object_name: str, destination_path: str):
        self.client.fget_object(bucket, object_name, destination_path)


