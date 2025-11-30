from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class VideoListItem(BaseModel):
    """
    Represents a single analyzed video/session in the list endpoint.

    We expose:
      - session_id: logical identifier of the session
      - created_at:'2025-11-30 17:00:17'
    """

    session_id: str
    created_at: Optional[str] = None


class AnalysisResult(BaseModel):
    """
    Full analysis for a given session, as returned to the end user.

    We intentionally expose only:
      - session_id: logical session identifier
      - analysis: parsed JSON with all insights from the LLM

    Internal storage details such as transcript/analysis URLs in MinIO
    are omitted because they are not useful for the viewer client.
    """

    session_id: str
    analysis: Dict[str, Any]


class Summary(BaseModel):
    """
    Short textual summary extracted from the full analysis.
    """

    session_id: str
    summary: str


class VideoListResponse(BaseModel):
    """
    Wrapper model for the /videos endpoint.
    """

    items: List[VideoListItem]



