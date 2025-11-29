import logging

from .consumer import consume_messages


logger = logging.getLogger("transcription_service.main")


def configure_logging() -> None:
    """
    Configure root logging for the transcription_service.
    """
    # Configure the logging for the transcription_service.main module
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )


def main() -> None:
    # Call the configure_logging function to configure the logging for the transcription_service.main module
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
