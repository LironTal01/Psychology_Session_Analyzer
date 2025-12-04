import logging
from contextlib import contextmanager
from typing import Dict, Generator, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from common.config import database


logger = logging.getLogger("llm_analyzer_service.database")


def _get_connection_params() -> Dict[str, str]:
    """Return PostgreSQL connection parameters from shared config."""
    return {
        "host": database.host,
        "port": database.port,
        "dbname": database.name,
        "user": database.user,
        "password": database.password,
    }


@contextmanager
def _get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Yield a PostgreSQL connection and ensure it is closed."""
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
    """Create the session_analyses table if it does not exist."""
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
    """Return a stored analysis record for the session_id, or None if missing."""
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
    """Insert or update an analysis record for the given session_id."""
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


