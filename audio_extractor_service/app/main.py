import logging

from .consumer import consume_messages


logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """
    Configure root logging for the whole microservice.
    This is called once from main() when the container starts.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )


def main() -> None:
    configure_logging()
    logger.info("Starting audio_extractor_service...")
    try:
        consume_messages()
    except KeyboardInterrupt:
        logger.info("Shutting down audio_extractor_service (keyboard interrupt).")
    except Exception as exc:  # noqa: BLE001
        logger.exception("audio_extractor_service crashed: %r", exc)
        raise


if __name__ == "__main__":
    main()