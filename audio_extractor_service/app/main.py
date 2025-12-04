import logging

from common.logging_utils import configure_logging
from .consumer import consume_messages


logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    logger.info("Starting audio_extractor_service...")
    try:
        consume_messages()
    except KeyboardInterrupt:
        logger.info("Shutting down audio_extractor_service (keyboard interrupt).")
    except Exception as exc:  
        logger.exception("audio_extractor_service crashed: %r", exc)
        raise


if __name__ == "__main__":
    main()