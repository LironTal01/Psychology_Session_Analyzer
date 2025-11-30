import json
import logging
import os
from typing import Any, Dict

from openai import OpenAI


logger = logging.getLogger("llm_analyzer_service.llm_client")


def _build_system_prompt() -> str:
    """
    Build the system-level instructions for the LLM.

    This text explains to the model what kind of analysis we expect
    (e.g., key themes, emotions, risk factors). You can freely adjust
    this prompt to match your course requirements.
    """
    return (
        "You are a clinical psychology assistant analyzing therapy session transcripts. "
        "Given the full conversation, you must return a concise JSON object with:\n"
        "  - main_issues: list of key problems discussed by the client\n"
        "  - emotions: list of prominent emotions with short evidence quotes\n"
        "  - interventions: list of therapist techniques you recognize\n"
        "  - risk_assessment: object with { level: 'low'|'medium'|'high', notes: string }\n"
        "  - summary: short paragraph summarizing the session in plain language.\n"
        "Return ONLY valid JSON, no markdown and no additional commentary."
    )


def _fallback_rule_based_analysis(transcript_text: str, session_id: str) -> Dict[str, Any]:
    """
    Simple local heuristic analysis used when no real LLM provider is
    configured or available.

    This keeps the microservice functional in local/dev environments,
    and can also be used for unit tests without external API calls.
    """
    word_count = len(transcript_text.split())

    return {
        "session_id": session_id,
        "provider": "dummy_local",
        "word_count": word_count,
        "main_issues": [],
        "emotions": [],
        "interventions": [],
        "risk_assessment": {
            "level": "low",
            "notes": "Dummy analysis – configure a real LLM to get meaningful output.",
        },
        "summary": (
            "This is a placeholder analysis generated without contacting an external LLM. "
            "Configure LLM_PROVIDER and relevant API keys to enable real analysis."
        ),
    }


def analyze_transcript_with_llm(transcript_text: str, session_id: str) -> Dict[str, Any]:
    """
    Analyze a transcript using OpenAI (Chat Completions API).

    Environment variables:
        OPENAI_API_KEY   - required
        OPENAI_MODEL     - optional, defaults to 'gpt-4o-mini'

    Returns:
        A Python dict parsed from the JSON produced by the model.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Please set the OPENAI_API_KEY environment variable."
        )

    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")

    # Initialize the OpenAI client
    client = OpenAI(api_key=api_key)

    system_prompt = _build_system_prompt()
    user_content = (
        "Here is the full transcript of a therapy session. "
        "Please analyze it according to the instructions.\n\n"
        "TRANSCRIPT:\n"
        f"{transcript_text}"
    )

    try:
        completion = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenAI call failed for session_id=%s: %r", session_id, exc)
        raise

    content = completion.choices[0].message.content or "{}"

    try:
        analysis = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(
            "OpenAI returned non-JSON content for session_id=%s, falling back to dummy",
            session_id,
        )
        return _fallback_rule_based_analysis(transcript_text, session_id)

    # Attach some metadata for traceability.
    analysis.setdefault("session_id", session_id)
    analysis.setdefault("provider", "openai")

    return analysis



