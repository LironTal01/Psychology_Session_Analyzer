import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from common.storage_client import StorageClient

# Logger for the transcription_service.worker module
logger = logging.getLogger("transcription_service.worker")

# Environment variables
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
# Default base URL for AssemblyAI; endpoints are under /transcript
ASSEMBLYAI_BASE_URL = os.getenv("ASSEMBLYAI_BASE_URL", "https://api.assemblyai.com/v2")
TRANSCRIPTS_BUCKET = os.getenv("TRANSCRIPTS_BUCKET", "transcripts")
WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp"))
_DEFAULT_POLL_INTERVAL_SECONDS = int(os.getenv("ASSEMBLYAI_POLL_INTERVAL", "5"))
_DEFAULT_POLL_TIMEOUT_SECONDS = int(os.getenv("ASSEMBLYAI_POLL_TIMEOUT", "600"))
# Initialize the storage client
storage_client = StorageClient()
# Create the transcripts bucket if it doesn't exist
storage_client.create_bucket_if_not_exists(TRANSCRIPTS_BUCKET)

def _parse_object_url(object_url: str) -> Tuple[str, str]:
    """Parse an internal MinIO object URL into (bucket, object_name)."""
    parsed = urlparse(object_url)
    path = parsed.path.lstrip("/")
    bucket, sep, object_name = path.partition("/")
    # Check if the bucket and object name are valid
    if not sep or not bucket or not object_name:
        raise ValueError(f"Invalid object_url: {object_url!r}")
    return bucket, object_name


def _download_audio(audio_object_url: str) -> Path:
    """Download the MP3 audio from MinIO into WORK_DIR and return the local path."""
    bucket, object_name = _parse_object_url(audio_object_url)
    local_path = WORK_DIR / object_name

    logger.info(
        "Downloading audio from MinIO: bucket=%s, object_name=%s, dest=%s",
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

# Upload audio to AssemblyAI
def _upload_audio_to_assemblyai(local_path: Path) -> str:
    """Upload the MP3 file to AssemblyAI and return its public URL."""
    upload_url = f"{ASSEMBLYAI_BASE_URL}/upload"
    headers = {"Authorization": ASSEMBLYAI_API_KEY}

    logger.info("Uploading audio file to AssemblyAI: %s", local_path)
    with open(local_path, "rb") as f:
        resp = requests.post(upload_url, headers=headers, data=f, timeout=60)

    if resp.status_code != 200:
        logger.error("Failed to upload audio: %s | %s", resp.status_code, resp.text)
        raise RuntimeError("AssemblyAI audio upload failed")

    upload_result = resp.json()
    uploaded_url = upload_result.get("upload_url")

    logger.info("Audio uploaded to AssemblyAI successfully: %s", uploaded_url)
    return uploaded_url



def _assemblyai_headers() -> Dict[str, str]:
    if not ASSEMBLYAI_API_KEY:
        raise RuntimeError("ASSEMBLYAI_API_KEY environment variable is not set")

    return {
        "Authorization": ASSEMBLYAI_API_KEY,
        "Content-Type": "application/json",
    }


def start_transcription_job(audio_url: str) -> str:
    """Start a transcription job at AssemblyAI and return the job id."""
    url = f"{ASSEMBLYAI_BASE_URL}/transcript"
    payload = {"audio_url": audio_url, "speaker_labels": True}

    logger.info("Starting AssemblyAI transcription job for audio_url=%s", audio_url)
    response = requests.post(url, headers=_assemblyai_headers(), json=payload, timeout=30)
    if response.status_code != 200:
        logger.error(
            "Failed to start transcription job. status=%s, body=%s",
            response.status_code,
            response.text,
        )
        raise RuntimeError("Failed to start transcription job")

    job_id = response.json().get("id")
    if not job_id:
        raise RuntimeError(f"AssemblyAI response missing job id: {response.json()!r}")
    logger.info("AssemblyAI transcription job started: id=%s", job_id)
    return job_id


# Poll the transcription result from AssemblyAI
def poll_transcription_result(
    job_id: str,
    timeout_seconds: int = _DEFAULT_POLL_TIMEOUT_SECONDS,
    interval_seconds: int = _DEFAULT_POLL_INTERVAL_SECONDS,
) -> Dict[str, Any]:
    """Poll AssemblyAI until the job completes or fails and return the final JSON."""
    url = f"{ASSEMBLYAI_BASE_URL}/transcript/{job_id}"
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            logger.error(
                "Transcription job %s timed out after %s seconds", job_id, timeout_seconds
            )
            raise TimeoutError(f"Transcription job {job_id} timed out")
        response = requests.get(url, headers=_assemblyai_headers(), timeout=30)
        if response.status_code != 200:
            logger.warning(
                "Polling job %s failed with status=%s, body=%s",
                job_id,
                response.status_code,
                response.text,
            )
            time.sleep(interval_seconds)
            continue

        data = response.json()
        status = data.get("status")

        if status == "completed":
            logger.info("Transcription job %s completed successfully", job_id)
            return data
        if status == "error":
            logger.error("Transcription job %s failed: %s", job_id, data)
            raise RuntimeError(f"Transcription job {job_id} failed")

        logger.info(
            "Transcription job %s status=%s, waiting %s seconds...",
            job_id,
            status,
            interval_seconds,
        )
        time.sleep(interval_seconds)

# Get the session id from the audio URL
def _get_session_id_from_audio_url(audio_object_url: str) -> str:
    """
    Derive a stable session_id from the audio object URL.

    We use the object name without extension for this.
    """
    parsed = urlparse(audio_object_url)
    object_name = Path(parsed.path.lstrip("/")).name
    return Path(object_name).stem


def process_audio_ready_message(payload: Dict[str, Any]) -> Tuple[str, str]:
    """
    Orchestrate the full transcription pipeline for an 'audio_ready' event.

    Returns:
        transcript_s3_url, session_id
    """
    audio_object_url = payload.get("audio_object_url")
    if not audio_object_url:
        raise ValueError("audio_ready message missing 'audio_object_url'")

    # Parse bucket/object from the internal MinIO URL
    bucket, object_name = _parse_object_url(audio_object_url)

    # Download audio locally
    local_audio_path = _download_audio(audio_object_url)
    # Upload audio to AssemblyAI
    uploaded_audio_url = _upload_audio_to_assemblyai(local_audio_path)

    # Prepare file names
    session_id = _get_session_id_from_audio_url(audio_object_url)
    transcript_object_name = f"session_{session_id}.json"
    local_transcript_path = WORK_DIR / transcript_object_name

    # 3. Start transcription job
    job_id = start_transcription_job(uploaded_audio_url)

    # 4. Poll until job is done
    transcript_data = poll_transcription_result(job_id)

    # 5. Save transcription locally
    logger.info("Saving transcript locally: %s", local_transcript_path)
    local_transcript_path.write_text(json.dumps(transcript_data, ensure_ascii=False))

    # 6. Upload transcript JSON back to MinIO
    logger.info("Uploading transcript to MinIO bucket=%s", TRANSCRIPTS_BUCKET)
    transcript_url = storage_client.upload_file(
        bucket=TRANSCRIPTS_BUCKET,
        file_path=str(local_transcript_path),
        object_name=transcript_object_name,
    )

    # 7. Cleanup
    try:
        if local_transcript_path.exists():
            local_transcript_path.unlink()
    except Exception:
        logger.warning("Could not delete local transcript file")

    # return s3:// URL
    transcript_s3_url = f"s3://{TRANSCRIPTS_BUCKET}/{transcript_object_name}"
    return transcript_s3_url, session_id


