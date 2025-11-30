import logging
import os
from contextlib import contextmanager
from typing import Dict, Generator, Optional

# Database client
import psycopg2
from psycopg2.extras import RealDictCursor


# Logger
logger = logging.getLogger("llm_analyzer_service.database")


def _get_connection_params() -> Dict[str, str]:
    """
    Return PostgreSQL connection parameters from environment variables.
    Defaults are aligned with the existing `postgres` service in docker-compose:
      - host: postgres
      - port: 5432
      - dbname: sessions_db
      - user: admin
      - password: admin123
    """
    return {
        "host": os.getenv("ANALYSIS_DB_HOST", "postgres"),
        "port": os.getenv("ANALYSIS_DB_PORT", "5432"),
        "dbname": os.getenv("ANALYSIS_DB_NAME", "sessions_db"),
        "user": os.getenv("ANALYSIS_DB_USER", "admin"),
        "password": os.getenv("ANALYSIS_DB_PASSWORD", "admin123"),
    }


@contextmanager
def _get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager that yields a PostgreSQL connection and ensures it is closed.

    All database access for this microservice goes through this helper, so if
    you ever need to switch connection details or tune parameters, you only
    need to change it here.
    """
    # Get the connection parameters
    params = _get_connection_params()
    # Connect to the database
    conn = psycopg2.connect(**params)
    # Yield the connection
    try:
        yield conn
    finally:
        # Close the connection
        conn.close()


def init_db() -> None:
    """
    Initialize the PostgreSQL database by creating tables if needed.

    This function creates the `session_analysis` table if it does not exist.
    It is safe to call multiple times (idempotent) and is invoked from the
    microservice entrypoint before consuming any messages.
    """
    with _get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS session_analyses (
                    session_id TEXT PRIMARY KEY,
                    transcript_object_url TEXT NOT NULL,
                    analysis_object_url TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        conn.commit()

    params = _get_connection_params()
    logger.info(
        "Database initialized in PostgreSQL (host=%s, db=%s)",
        params["host"],
        params["dbname"],
    )


def get_analysis_result(session_id: str) -> Optional[Dict[str, str]]:
    """
    Retrieve a stored analysis record for the given session_id, if any.

    Returns a dict with keys:
      - session_id
      - transcript_object_url
      - analysis_object_url
      - analysis_json
    or None if the record does not exist.
    """
    with _get_connection() as conn:
        # Create a cursor to execute the query
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Execute the query
            cursor.execute(
                """
                SELECT
                    session_id,
                    transcript_object_url,
                    analysis_object_url,
                    analysis_json
                FROM session_analyses
                WHERE session_id = %s
                """,
                (session_id,),
            )
            # Fetch the result
            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "session_id": row["session_id"],
        "transcript_object_url": row["transcript_object_url"],
        "analysis_object_url": row["analysis_object_url"],
        "analysis_json": row["analysis_json"],
    }


def store_analysis_result(
    session_id: str,
    transcript_object_url: str,
    analysis_object_url: str,
    analysis_json: str,
) -> None:
    """
    Insert or update an analysis record for the given session_id.

    Uses PostgreSQL's `ON CONFLICT` to implement an upsert on `session_id`:
      - if the row does not exist, it is inserted
      - if it exists, it is updated with the new data.
    """
    with _get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO session_analyses (
                    session_id,
                    transcript_object_url,
                    analysis_object_url,
                    analysis_json
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    transcript_object_url = EXCLUDED.transcript_object_url,
                    analysis_object_url = EXCLUDED.analysis_object_url,
                    analysis_json = EXCLUDED.analysis_json
                """,
                (session_id, transcript_object_url, analysis_object_url, analysis_json),
            )
        conn.commit()

    logger.info("Stored analysis result in DB for session_id=%s", session_id)


