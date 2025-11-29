from fastapi import FastAPI, UploadFile, File
from common.storage_client import StorageClient
import os
import uuid
import json
import pika


app = FastAPI(
    title="Psychology Session Upload Service",
    description="""
This service allows therapists to upload recorded psychology sessions.
Files are stored in MinIO and later processed by downstream services.
"""
)


storage_client = StorageClient()

MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
storage_client.create_bucket_if_not_exists(MINIO_BUCKET)


RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "user")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "pass")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "new_videos")


def publish_new_video_message(object_url: str, bucket: str, filename: str):
    """
    Send a small JSON message to RabbitMQ to notify downstream services
    that a new video has been uploaded.
    """
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
    )

    # Connect to RabbitMQ server
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    # Declare the queue (create it if it doesn't exist)
    channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

    # Create the message body
    body = json.dumps(
        {
            "bucket": bucket,
            "filename": filename,
            "object_url": object_url,
        }
    )

    # Publish the message to the queue (make it persistent)
    channel.basic_publish(
        exchange="",
        routing_key=RABBITMQ_QUEUE,
        body=body.encode("utf-8"),
        properties=pika.BasicProperties(
            delivery_mode=2  # make message persistent
        ),
    )

    # Close the connection
    connection.close()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # Save the file temporarily in the container's disk
    upload_id = uuid.uuid4()
    # Keep object names short and stable: <uuid><original_extension>
    _, ext = os.path.splitext(file.filename)
    object_name = f"{upload_id}{ext}"
    temp_filename = f"/tmp/{object_name}"

    with open(temp_filename, "wb") as f:
        f.write(await file.read())

    # Upload to MinIO – every upload gets a unique object name
    object_url = storage_client.upload_file(
        bucket=MINIO_BUCKET,
        file_path=temp_filename,
        object_name=object_name
    )

    # Notify RabbitMQ that a new video is available
    publish_new_video_message(
        object_url=object_url,
        bucket=MINIO_BUCKET,
        filename=file.filename,
    )

    # Delete the local file
    os.remove(temp_filename)

    return {
        "status": "ok",
        "filename": file.filename,
        "object_name": object_name,
        "object_url": object_url,
    }
