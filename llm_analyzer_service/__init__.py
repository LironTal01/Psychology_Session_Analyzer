"""
llm_analyzer_service package.

This package implements the microservice responsible for taking completed
transcripts, running an LLM-based psychological analysis, caching results
in Redis, and persisting them to a small internal database.

The main entrypoint used by Docker is `llm_analyzer_service.main`.
"""


