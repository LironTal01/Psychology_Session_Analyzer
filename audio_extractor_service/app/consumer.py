import json
import logging
import os
import sys
import time

import pika

from .audio_extractor import extract_and_upload_audio


logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "user")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "pass")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "new_videos")
AUDIO_READY_QUEUE = os.getenv("AUDIO_READY_QUEUE", "audio_ready")


def handle_message(body: bytes) -> None:
    """
    Handle a single message from the new_videos queue.
    Responsible for orchestrating the audio extraction step.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Received non-JSON message: %r", body)
        return

    bucket = payload.get("bucket")
    filename = payload.get("filename")
    object_url = payload.get("object_url")

    logger.info(
        "Received new video event: bucket=%s, filename=%s, object_url=%s",
        bucket,
        filename,
        object_url,
    )

    audio_object_url = extract_and_upload_audio(
        object_url=object_url,
        fallback_bucket=bucket,
        filename=filename,
    )

    logger.info("Audio object is ready at: %s", audio_object_url)

    publish_audio_ready_event(
        audio_object_url=audio_object_url,
        video_bucket=bucket,
        video_filename=filename,
        video_object_url=object_url,
    )


def publish_audio_ready_event(
    audio_object_url: str,
    video_bucket: str | None,
    video_filename: str | None,
    video_object_url: str | None,
) -> None:
    """
    Publish an 'audio_ready' event to RabbitMQ so downstream services
    (e.g. transcription) know that an audio file is available.
    """
    payload = {
        "audio_object_url": audio_object_url,
        "video_bucket": video_bucket,
        "video_filename": video_filename,
        "video_object_url": video_object_url,
    }

    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    # Ensure the queue exists (idempotent)
    channel.queue_declare(queue=AUDIO_READY_QUEUE, durable=True)

    channel.basic_publish(
        exchange="",
        routing_key=AUDIO_READY_QUEUE,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),
    )

    connection.close()

    logger.info(
        "Published audio_ready event to %s: %s",
        AUDIO_READY_QUEUE,
        payload,
    )


def consume_messages() -> None:
    """
    Connect to RabbitMQ and consume messages from the new_videos queue forever.
    Includes a simple retry loop in case RabbitMQ is not available.
    """
    while True:
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=30,
            )

            logger.info(
                "Connecting to RabbitMQ at %s:%s, queue=%s",
                RABBITMQ_HOST,
                RABBITMQ_PORT,
                RABBITMQ_QUEUE,
            )

            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            # Ensure the queue exists (idempotent)
            channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

            # Fair dispatch – one message at a time per worker
            channel.basic_qos(prefetch_count=1)

            def _callback(ch, method, properties, body):
                try:
                    handle_message(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Error while handling message, leaving it unacked so it can be retried: %r",
                        exc,
                    )

            channel.basic_consume(
                queue=RABBITMQ_QUEUE,
                on_message_callback=_callback,
                auto_ack=False,
            )

            logger.info("Waiting for messages. To exit, stop the container.")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as exc:
            logger.warning(
                "Could not connect to RabbitMQ (%s), retrying in 5 seconds...", exc
            )
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down consumer (keyboard interrupt).")
            try:
                connection.close()
            except Exception:
                pass
            sys.exit(0)
        except Exception as exc:  
            logger.exception(
                "Unexpected error in consumer loop: %r, retrying in 5 seconds...", exc
            )
            time.sleep(5)


