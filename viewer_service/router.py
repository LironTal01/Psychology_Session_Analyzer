import json
from typing import List

from fastapi import APIRouter, HTTPException

from . import cache
from . import database
from .models import AnalysisResult, Summary, VideoListItem, VideoListResponse


router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("", response_model=VideoListResponse)
def list_videos() -> VideoListResponse:
    """
    Return a list of all analyzed sessions (videos).

    This endpoint only exposes session_id and created_at so that
    a client UI can render a list or table of sessions.
    """
    rows = database.get_all_sessions()
    items: List[VideoListItem] = []

    for row in rows:
        created_at_raw = row.get("created_at")
        created_at_str: str | None = None

        # 'YYYY-MM-DD HH:MM:SS' (no microseconds, no timezone).
        if created_at_raw is not None:
            try:
                created_at_str = (
                    created_at_raw.replace(microsecond=0)
                    .isoformat(sep=" ")
                )
            except Exception: 
                created_at_str = None

        items.append(
            VideoListItem(
                session_id=row["session_id"],
                created_at=created_at_str,
            )
        )
    return VideoListResponse(items=items)


@router.get("/{session_id}", response_model=AnalysisResult)
def get_video_analysis(session_id: str) -> AnalysisResult:
    """
    Return the full analysis JSON for a specific session.

    This endpoint:
      - checks Redis cache first
      - falls back to PostgreSQL if not cached
      - parses the stored analysis_json into a Python dict
    """
    # Try cache first
    cached = cache.get_cached_analysis(session_id)
    if cached is not None:
        return AnalysisResult(**cached)

    row = database.get_analysis(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        analysis_dict = json.loads(row["analysis_json"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Stored analysis_json is missing or invalid for session_id={session_id}",
        ) from exc

    result = AnalysisResult(session_id=row["session_id"], analysis=analysis_dict)

    # Store in cache for next time
    cache.set_cached_analysis(session_id, result.dict())

    return result


@router.get("/{session_id}/summary", response_model=Summary)
def get_video_summary(session_id: str) -> Summary:
    """
    Return a short summary string for a specific session.

    The summary is extracted from the 'summary' field inside the
    analysis JSON produced by the llm_analyzer_service.
    """
    # Reuse the main analysis endpoint to benefit from caching logic.
    analysis_result = get_video_analysis(session_id)

    analysis_json = analysis_result.analysis

    summary_text = ""

    # We first look for a generic 'summary' field.
    # For compatibility with the llm_analyzer_service prompt schema,
    # we also support 'session_summary' as an alternative key.
    # If neither is present, we fall back to something safe and generic.
    if isinstance(analysis_json, dict):
        raw_summary = analysis_json.get("summary") or analysis_json.get("session_summary")
        if isinstance(raw_summary, str):
            summary_text = raw_summary.strip()

    if not summary_text:
        summary_text = "No simple textual summary was found in the stored analysis."

    return Summary(session_id=session_id, summary=summary_text)



