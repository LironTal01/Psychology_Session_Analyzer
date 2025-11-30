import json
import logging
import os
import sys
import time
from typing import Any, Dict

import pika

from .analyzer import analyze_transcript_for_session


logger = logging.getLogger("llm_analyzer_service.consumer")


# RabbitMQ configuration (mirrors other services' style)
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "user")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "pass")
RABBITMQ_TRANSCRIPTION_READY_QUEUE = os.getenv(
    "TRANSCRIPTION_READY_QUEUE", "transcription_ready"
)
RABBITMQ_ANALYSIS_READY_QUEUE = os.getenv("ANALYSIS_READY_QUEUE", "analysis_ready")


def publish_analysis_ready_event(
    analysis_object_url: str,
    transcript_object_url: str,
    session_id: str,
) -> None:
    """
    Publish an 'analysis_ready' event to RabbitMQ so downstream
    services (e.g., results_api) can consume the analysis.

    The payload contains:
      - analysis_object_url: internal MinIO URL for the analysis JSON
      - transcript_object_url: internal/s3 URL for the transcript JSON
      - session_id: logical identifier of the therapy session
    """
    payload: Dict[str, Any] = {
        "analysis_object_url": analysis_object_url,
        "transcript_object_url": transcript_object_url,
        "session_id": session_id,
    }

    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
    )

    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    # Ensure the destination queue exists (idempotent).
    channel.queue_declare(queue=RABBITMQ_ANALYSIS_READY_QUEUE, durable=True)

    channel.basic_publish(
        exchange="",
        routing_key=RABBITMQ_ANALYSIS_READY_QUEUE,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),
    )

    connection.close()

    logger.info(
        "Published analysis_ready event to %s: %s",
        RABBITMQ_ANALYSIS_READY_QUEUE,
        payload,
    )


def handle_message(body: bytes) -> None:
    """
    Handle a single message from the 'transcription_ready' queue.

    Responsibilities:
      1. Parse the JSON message.
      2. Download the transcript JSON from MinIO (via the analyzer).
      3. Run LLM-based analysis (with caching + DB handled by analyzer).
      4. Upload the analysis JSON back to MinIO.
      5. Publish an 'analysis_ready' event with the analysis URL and session_id.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Received non-JSON message from transcription_ready: %r", body)
        return

    transcript_object_url = payload.get("transcript_object_url")
    session_id = payload.get("session_id")

    if not transcript_object_url or not session_id:
        logger.warning(
            "Discarding transcription_ready message missing required fields: %s",
            payload,
        )
        return

    logger.info(
        "Received transcription_ready event: session_id=%s, transcript_object_url=%s",
        session_id,
        transcript_object_url,
    )

    # Delegate the heavy lifting to the analyzer module.
    analysis_result, analysis_object_url = analyze_transcript_for_session(
        session_id=session_id,
        transcript_object_url=transcript_object_url,
    )

    logger.info(
        "Analysis completed for session_id=%s, stored at %s",
        session_id,
        analysis_object_url,
    )

    publish_analysis_ready_event(
        analysis_object_url=analysis_object_url,
        transcript_object_url=transcript_object_url,
        session_id=session_id,
    )


def consume_messages() -> None:
    """
    Connect to RabbitMQ and consume messages from the transcription_ready queue.

    The function runs a simple retry loop to handle transient connection errors.
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
                RABBITMQ_TRANSCRIPTION_READY_QUEUE,
            )

            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            # Ensure the source queue exists (idempotent).
            channel.queue_declare(
                queue=RABBITMQ_TRANSCRIPTION_READY_QUEUE,
                durable=True,
            )

            # Fair dispatch – one message at a time per worker.
            channel.basic_qos(prefetch_count=1)

            def _callback(ch, method, properties, body):
                try:
                    handle_message(body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Error while handling transcription_ready message, "
                        "leaving it unacked so it can be retried: %r",
                        exc,
                    )

            channel.basic_consume(
                queue=RABBITMQ_TRANSCRIPTION_READY_QUEUE,
                on_message_callback=_callback,
                auto_ack=False,
            )

            logger.info(
                "Listening on queue %s. To exit, stop the container.",
                RABBITMQ_TRANSCRIPTION_READY_QUEUE,
            )
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as exc:
            logger.warning(
                "Could not connect to RabbitMQ (%s), retrying in 5 seconds...",
                exc,
            )
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down llm_analyzer_service (keyboard interrupt).")
            try:
                connection.close()
            except Exception:
                pass
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unexpected error in consumer loop: %r, retrying in 5 seconds...",
                exc,
            )
            time.sleep(5)



