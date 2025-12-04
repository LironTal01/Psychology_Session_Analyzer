from fastapi import FastAPI, UploadFile, File
from common.storage_client import StorageClient
from common.config import rabbitmq
import os
import json
import pika


app = FastAPI(
    title="Psychology Session Upload Service",
    description="""
This service allows therapists to upload recorded psychology sessions.
Files are stored in MinIO and later processed by downstream services.
""",
)

# MinIO connection
storage_client = StorageClient()

MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
storage_client.create_bucket_if_not_exists(MINIO_BUCKET)


def publish_new_video_message(object_url: str, bucket: str, filename: str) -> None:
    """Publish a 'new video uploaded' event to RabbitMQ."""

    credentials = pika.PlainCredentials(rabbitmq.user, rabbitmq.password)
    parameters = pika.ConnectionParameters(
        host=rabbitmq.host,
        port=rabbitmq.port,
        credentials=credentials,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    channel.queue_declare(queue=rabbitmq.new_videos_queue, durable=True)

    body = json.dumps(
        {"bucket": bucket, "filename": filename, "object_url": object_url}
    )

    channel.basic_publish(
        exchange="",
        routing_key=rabbitmq.new_videos_queue,
        body=body.encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),
    )

    connection.close()


@app.get("/health")
async def health():
    """Simple health check endpoint used by orchestrators."""
    return {"status": "ok"}


# Upload route - with filename preservation!
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Receive an uploaded video file, store it in MinIO under a unique name,
    and emit a RabbitMQ event so the pipeline can continue.
    """
    original_name = file.filename

    # Ask storage_client for a non-conflicting object name inside the bucket.
    object_name = storage_client.get_unique_object_name(MINIO_BUCKET, original_name)
    temp_path = f"/tmp/{object_name}"

    # Save the upload temporarily to disk.
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    # Upload the file to MinIO using the unique object name.
    object_url = storage_client.upload_file(
        bucket=MINIO_BUCKET,
        file_path=temp_path,
        object_name=object_name,
    )

    # Notify downstream services that a new video is available.
    publish_new_video_message(
        object_url=object_url,
        bucket=MINIO_BUCKET,
        filename=original_name,
    )

    # Clean up the temporary file.
    os.remove(temp_path)

    return {
        "status": "ok",
        "original_filename": original_name,
        "stored_as": object_name,
        "object_url": object_url,
    }
