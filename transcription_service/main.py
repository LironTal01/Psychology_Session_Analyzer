import logging

from common.logging_utils import configure_logging
from .consumer import consume_messages


logger = logging.getLogger("transcription_service.main")


def main() -> None:
    configure_logging()
    # Log the start of the transcription_service
    logger.info("Starting transcription_service...")
    try:
        # Call the consume_messages function to consume the messages from the audio_ready queue
        consume_messages()
    # Log the shutdown of the transcription_service if the keyboard interrupt is caught
    except KeyboardInterrupt:
        logger.info("Shutting down transcription_service (keyboard interrupt).")
    # Log the crash of the transcription_service
    except Exception as exc:  # noqa: BLE001
        logger.exception("transcription_service crashed: %r", exc)
        # Raise the exception to the caller
        raise

if __name__ == "__main__":
    main() 
