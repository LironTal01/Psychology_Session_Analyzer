import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from common.storage_client import StorageClient


logger = logging.getLogger(__name__)

# Environment variables
AUDIO_BUCKET = os.getenv("AUDIO_BUCKET", "audio")
WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp"))

# Initialize the storage client
storage_client = StorageClient()

# Create the audio bucket if it doesn't exist
storage_client.create_bucket_if_not_exists(AUDIO_BUCKET)


def _parse_object_url(object_url: str, fallback_bucket: Optional[str]) -> Tuple[str, str]:
    """
    Parse an object URL into (bucket, object_name).

    Supports both:
    - http(s)://minio:9000/<bucket>/<object_name>
    - s3://<bucket>/<object_name>
    """
    parsed = urlparse(object_url)

    # HTTP/S style: http://host:port/bucket/object
    if parsed.scheme in {"http", "https"}:
        path = parsed.path.lstrip("/")
        bucket, _, object_name = path.partition("/")
    else:
        # s3://bucket/object or bucket/object
        bucket = parsed.netloc or (fallback_bucket or "")
        object_name = parsed.path.lstrip("/")

    if not bucket or not object_name:
        raise ValueError(f"Invalid object_url (could not infer bucket/name): {object_url!r}")

    return bucket, object_name


def extract_and_upload_audio(
    object_url: str,
    fallback_bucket: Optional[str],
    filename: Optional[str],
) -> str:
    """
    Download a video object from MinIO, extract its audio as MP3 using ffmpeg,
    upload the MP3 to the audio bucket, and return the resulting object URL.
    """
    if not object_url:
        raise ValueError("Message missing object_url field")

    source_bucket, object_name = _parse_object_url(object_url, fallback_bucket)

    video_path = WORK_DIR / object_name
    audio_filename = f"{Path(object_name).stem}.mp3"
    audio_path = WORK_DIR / audio_filename

    # Download video from MinIO
    logger.info(
        "Downloading video from MinIO: bucket=%s, object_name=%s, dest=%s",
        source_bucket,
        object_name,
        video_path,
    )
    storage_client.download_file(
        bucket=source_bucket,
        object_name=object_name,
        destination_path=str(video_path),
    )

    # Extract audio track as MP3 using ffmpeg
    logger.info("Extracting audio to MP3 with ffmpeg: %s -> %s", video_path, audio_path)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "libmp3lame",
                str(audio_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                "ffmpeg failed with code %s. stderr=%s",
                result.returncode,
                result.stderr.strip(),
            )
            raise RuntimeError("ffmpeg failed to extract audio")
    except Exception:
        logger.exception("Unexpected error while running ffmpeg")
        raise

    # Upload the MP3 back to MinIO (audio bucket)
    logger.info(
        "Uploading extracted audio to MinIO: bucket=%s, object_name=%s",
        AUDIO_BUCKET,
        audio_filename,
    )
    audio_object_url = storage_client.upload_file(
        bucket=AUDIO_BUCKET,
        file_path=str(audio_path),
        object_name=audio_filename,
    )

    logger.info("Audio extraction completed successfully: %s", audio_object_url)

    # Cleanup local files
    for path in (video_path, audio_path):
        try:
            if path.exists():
                path.unlink()
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete temp file: %s", path)

    return audio_object_url

