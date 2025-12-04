import logging


def configure_logging() -> None:
    """
    Configure root logging for all microservices.

    This helper centralizes the logging format/level so that any change
    only needs to be made in one place.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )


