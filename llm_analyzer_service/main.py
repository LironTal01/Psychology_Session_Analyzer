import logging

from .consumer import consume_messages
from .database import init_db


logger = logging.getLogger("llm_analyzer_service.main")


def configure_logging() -> None:
    """
    Configure root logging for the llm_analyzer_service.

    This function is called once when the container starts so that
    all modules in this microservice share the same logging setup.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )


def main() -> None:
    """
    Entrypoint for the llm_analyzer_service container.

    - Configure logging.
    - Initialize the internal analysis database (e.g., create tables).
    - Start consuming messages from the 'transcription_ready' queue.
    """
    configure_logging()
    logger.info("Starting llm_analyzer_service...")

    # Initialize the analysis database before we process any messages
    init_db()

    try:
        consume_messages()
    except KeyboardInterrupt:
        logger.info("Shutting down llm_analyzer_service (keyboard interrupt).")
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm_analyzer_service crashed: %r", exc)
        raise


if __name__ == "__main__":
    main()


