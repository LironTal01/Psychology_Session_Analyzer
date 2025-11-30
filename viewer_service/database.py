import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


logger = logging.getLogger("viewer_service.database")


def _get_connection_params() -> Dict[str, str]:
    """
    Return PostgreSQL connection parameters for the viewer_service.

    By default these align with the existing `postgres` service used
    by llm_analyzer_service:
      - host: postgres
      - port: 5432
      - dbname: sessions_db
      - user: admin
      - password: admin123

    You can override any of these via:
      - ANALYSIS_DB_HOST
      - ANALYSIS_DB_PORT
      - ANALYSIS_DB_NAME
      - ANALYSIS_DB_USER
      - ANALYSIS_DB_PASSWORD
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

    All database access for this microservice flows through this helper.
    """
    params = _get_connection_params()
    conn = psycopg2.connect(**params)
    try:
        yield conn
    finally:
        conn.close()


def get_all_sessions() -> List[Dict[str, Any]]:
    """
    Return a list of all analyzed sessions from the session_analyses table.

    Each item is a dict with:
      - session_id
      - created_at
    """
    query = """
        SELECT
            TRIM(session_id) AS session_id,
            created_at
        FROM session_analyses
        ORDER BY created_at DESC NULLS LAST, session_id ASC
    """

    with _get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

    # Convert Row objects to plain dicts.
    return [dict(row) for row in rows]


def get_analysis(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Return the full analysis row for a specific session_id, or None if not found.

    The returned dict has the columns:
      - session_id
      - transcript_object_url
      - analysis_object_url
      - analysis_json
      - created_at
    """
    query = """
        SELECT
            TRIM(session_id) AS session_id,
            transcript_object_url,
            analysis_object_url,
            analysis_json,
            created_at
        FROM session_analyses
        WHERE TRIM(session_id) = %s
    """

    with _get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (session_id,))
            row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)



