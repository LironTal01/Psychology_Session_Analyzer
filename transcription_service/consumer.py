import json
import logging
import sys
import time
from typing import Any, Dict

import pika
from common.config import rabbitmq

from .transcription_worker import process_audio_ready_message

logger = logging.getLogger("transcription_service.consumer")

def publish_transcription_ready_event(
    transcript_object_url: str,
    audio_object_url: str,
    video_object_url: str | None,
    session_id: str,
) -> None:
    """
    Publish a 'transcription_ready' event to RabbitMQ.
    """
    # Create the payload for the transcription_ready event
    payload: Dict[str, Any] = {
        "transcript_object_url": transcript_object_url,
        "audio_object_url": audio_object_url,
        "video_object_url": video_object_url,
        "session_id": session_id,
    }

    # Create the credentials for the RabbitMQ connection
    credentials = pika.PlainCredentials(rabbitmq.user, rabbitmq.password)
    parameters = pika.ConnectionParameters(
        host=rabbitmq.host,
        port=rabbitmq.port,
        credentials=credentials,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    channel.queue_declare(
        queue=rabbitmq.transcription_ready_queue, durable=True
    )

    # Publish the transcription_ready event to the RabbitMQ server
    channel.basic_publish(
        exchange="",
        routing_key=rabbitmq.transcription_ready_queue,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),
    )

    # Close the connection to the RabbitMQ server
    connection.close()

    logger.info(
        "Published transcription_ready event to %s: %s",
        rabbitmq.transcription_ready_queue,
        payload,
    )


def handle_message(body: bytes) -> None:
    """
    Handle a single message from the audio_ready queue.

    Responsible for orchestrating the transcription step.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Received non-JSON message from audio_ready: %r", body)
        return
    # Get the audio_object_url and video_object_url from the payload for the transcription_ready event
    audio_object_url = payload.get("audio_object_url")
    video_object_url = payload.get("video_object_url")

    # Check if the audio_object_url is present in the payload
    if not audio_object_url:
        logger.warning("Discarding audio_ready message without audio_object_url: %s", payload)
        return

    # Log the received audio_ready event
    logger.info("Received audio_ready event: %s", payload)

    transcript_s3_url, session_id = process_audio_ready_message(payload)

    publish_transcription_ready_event(
        transcript_object_url=transcript_s3_url,
        audio_object_url=audio_object_url,
        video_object_url=video_object_url,
        session_id=session_id,
    )


def consume_messages() -> None:
    """
    Connect to RabbitMQ and consume messages from the audio_ready queue forever.

    Includes a retry loop in case RabbitMQ is not available.
    """
    while True:
        try:
            credentials = pika.PlainCredentials(rabbitmq.user, rabbitmq.password)
            parameters = pika.ConnectionParameters(
                host=rabbitmq.host,
                port=rabbitmq.port,
                credentials=credentials,
                heartbeat=30,
            )

            logger.info(
                "Connecting to RabbitMQ at %s:%s, queue=%s",
                rabbitmq.host,
                rabbitmq.port,
                rabbitmq.audio_ready_queue,
            )

            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            channel.queue_declare(
                queue=rabbitmq.audio_ready_queue, durable=True
            )

            # Fair dispatch - one message at a time per worker
            channel.basic_qos(prefetch_count=1)

            # Callback function to handle the audio_ready message
            def _callback(ch, method, properties, body):
                try:
                    handle_message(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:  # noqa: BLE001
                    # Do not ack the message to allow it to be retried
                    logger.exception(
                        "Error while handling audio_ready message, "
                        "leaving it unacked so it can be retried: %r",
                        exc,
                    )

            channel.basic_consume(
                queue=rabbitmq.audio_ready_queue,
                on_message_callback=_callback,
                auto_ack=False,
            )

            # Log the listening on the audio_ready queue
            logger.info(
                "Listening on queue %s. To exit, stop the container.",
                rabbitmq.audio_ready_queue,
            )
            # Start consuming the messages from the audio_ready queue
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as exc:
            # Log the connection error and retry in 5 seconds
            logger.warning(
                "Could not connect to RabbitMQ (%s), retrying in 5 seconds...", exc
            )
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down transcription_service (keyboard interrupt).")
            try:
                connection.close()
            except Exception:
                pass
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unexpected error in consumer loop: %r, retrying in 5 seconds...", exc
            )
            time.sleep(5)


