import logging

from common.logging_utils import configure_logging
from .consumer import consume_messages
from .database import init_db


logger = logging.getLogger("llm_analyzer_service.main")


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
    except Exception as exc:  
        logger.exception("llm_analyzer_service crashed: %r", exc)
        raise


if __name__ == "__main__":
    main()


