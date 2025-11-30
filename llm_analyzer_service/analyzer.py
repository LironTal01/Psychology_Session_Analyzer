import json
import logging
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from common.storage_client import StorageClient

from .database import store_analysis_result, get_analysis_result
from .llm_client import analyze_transcript_with_llm
from .redis_cache import get_analysis_from_cache, store_analysis_in_cache


logger = logging.getLogger("llm_analyzer_service.analyzer")

# Reuse the shared MinIO client used by other services.
storage_client = StorageClient()


def _parse_object_url(object_url: str) -> Tuple[str, str]:
    """
    Parse a transcript object URL into (bucket, object_name).

    This helper supports both styles used in the system:
      - Internal HTTP/S URLs created by StorageClient._build_object_url:
            http(s)://minio:9000/<bucket>/<object_name>
      - Logical S3-style URLs published on RabbitMQ:
            s3://<bucket>/<object_name>

    Returning (bucket, object_name) lets us call StorageClient.download_file
    without caring which style was used upstream.
    """
    parsed = urlparse(object_url)

    # HTTP/S style: http://host:port/bucket/object
    if parsed.scheme in {"http", "https"}:
        path = parsed.path.lstrip("/")
        bucket, sep, object_name = path.partition("/")
        if not sep:
            raise ValueError(f"Invalid HTTP object_url: {object_url!r}")
    else:
        # s3://bucket/object
        bucket = parsed.netloc
        object_name = parsed.path.lstrip("/")

    if not bucket or not object_name:
        raise ValueError(
            f"Invalid object_url (could not infer bucket/name): {object_url!r}"
        )

    return bucket, object_name


def _download_transcript(transcript_object_url: str, work_dir: Path) -> Path:
    """
    Download the transcript JSON from MinIO into a local path.

    Returns the local Path to the downloaded JSON file.
    """
    bucket, object_name = _parse_object_url(transcript_object_url)
    local_path = work_dir / Path(object_name).name

    logger.info(
        "Downloading transcript from MinIO: bucket=%s, object_name=%s, dest=%s",
        bucket,
        object_name,
        local_path,
    )
    storage_client.download_file(
        bucket=bucket,
        object_name=object_name,
        destination_path=str(local_path),
    )
    return local_path


def _upload_analysis_json(
    analysis: Dict[str, Any],
    session_id: str,
    bucket: str,
    work_dir: Path,
) -> str:
    """
    Save the analysis dictionary locally and upload it as a JSON file to MinIO.

    Returns the internal object URL produced by StorageClient.
    """
    object_name = f"session_{session_id}_analysis.json"
    local_path = work_dir / object_name

    logger.info("Saving analysis JSON locally: %s", local_path)
    local_path.write_text(json.dumps(analysis, ensure_ascii=False))

    logger.info(
        "Uploading analysis to MinIO bucket=%s, object_name=%s",
        bucket,
        object_name,
    )
    object_url = storage_client.upload_file(
        bucket=bucket,
        file_path=str(local_path),
        object_name=object_name,
    )

    # Local cleanup
    try:
        if local_path.exists():
            local_path.unlink()
    except Exception:  
        logger.warning("Failed to delete local analysis file: %s", local_path)

    return object_url


def analyze_transcript_for_session(
    session_id: str,
    transcript_object_url: str,
    *,
    work_dir: Path | None = None,
    analysis_bucket_env_var: str = "ANALYSIS_BUCKET",
) -> Tuple[Dict[str, Any], str]:
    """
    High-level orchestration function for LLM analysis of a transcript.

    Steps:
      1. Check Redis cache for an existing analysis for this session_id.
      2. Check the internal database for a stored analysis.
      3. If not found, download transcript JSON from MinIO and call the LLM.
      4. Store the result in the database and cache.
      5. Upload analysis JSON to MinIO and return both the analysis dict and URL.

    Args:
        session_id: Stable identifier for the therapy session.
        transcript_object_url: Internal/s3 URL pointing to the transcript JSON.
        work_dir: Optional temporary directory for local files (defaults to /tmp).
        analysis_bucket_env_var: Name of the env var that holds the analysis bucket.

    Returns:
        (analysis_dict, analysis_object_url)
    """
    import os

    if work_dir is None:
        work_dir = Path(os.getenv("WORK_DIR", "/tmp"))

    # Create the analysis bucket if it doesn't exist
    analysis_bucket = os.getenv(analysis_bucket_env_var, "analyses")
    storage_client.create_bucket_if_not_exists(analysis_bucket)

    # Check Redis cache for an existing analysis for this session_id
    logger.info("Checking Redis cache for session_id=%s", session_id)
    cached = get_analysis_from_cache(session_id)
    if cached is not None:
        logger.info("Cache hit for session_id=%s", session_id)
        # We do not necessarily know the MinIO URL here; the caller may recompute it
        # or simply reuse previously stored metadata. For consistency with the DB,
        # we still try to fetch it from the database if present.
        db_row = get_analysis_result(session_id)
        analysis_url = db_row["analysis_object_url"] if db_row else ""
        return cached, analysis_url

    # Check internal database for a stored analysis
    logger.info("Checking database for existing analysis of session_id=%s", session_id)
    db_row = get_analysis_result(session_id)
    if db_row is not None:
        logger.info("Found existing analysis in DB for session_id=%s", session_id)
        analysis_dict = json.loads(db_row["analysis_json"])
        # Also refresh the cache for next time.
        store_analysis_in_cache(session_id, analysis_dict)
        return analysis_dict, db_row["analysis_object_url"]

    # No cached/DB result -> run a new LLM analysis.
    logger.info("No cached/DB analysis; running LLM for session_id=%s", session_id)
    transcript_path = _download_transcript(transcript_object_url, work_dir)
    transcript_text = transcript_path.read_text(encoding="utf-8")

    # Call the LLM client to perform the actual analysis.
    analysis_dict = analyze_transcript_with_llm(
        transcript_text=transcript_text,
        session_id=session_id,
    )

    # Remove internal-only metadata fields before persisting the JSON.
    # The database should contain only clinically relevant analysis data,
    # not implementation details such as which LLM provider was used.
    if isinstance(analysis_dict, dict):
        analysis_dict.pop("provider", None)

    # Upload analysis JSON to MinIO.
    analysis_object_url = _upload_analysis_json(
        analysis=analysis_dict,
        session_id=session_id,
        bucket=analysis_bucket,
        work_dir=work_dir,
    )

    # Persist the result in the DB and cache.
    store_analysis_result(
        session_id=session_id,
        transcript_object_url=transcript_object_url,
        analysis_object_url=analysis_object_url,
        analysis_json=json.dumps(analysis_dict, ensure_ascii=False),
    )
    # Store the analysis in the cache
    store_analysis_in_cache(session_id, analysis_dict)

    return analysis_dict, analysis_object_url



