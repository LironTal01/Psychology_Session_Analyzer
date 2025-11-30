"""
viewer_service package.

This microservice exposes a FastAPI HTTP API that lets clients:
  - list all analyzed therapy sessions
  - fetch the full analysis of a specific session
  - fetch only a short summary extracted from the stored analysis JSON

It does NOT perform any LLM calls or upload videos. It only reads
from the PostgreSQL database populated by llm_analyzer_service.
"""


