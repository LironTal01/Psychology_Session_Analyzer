import json
import logging
import os
from typing import Any, Dict

import google.generativeai as genai


logger = logging.getLogger("llm_analyzer_service.llm_client")


def _build_system_prompt() -> str:
    """
    Build the system-level instructions for the LLM.

    This text explains to the model what kind of analysis we expect
    (e.g., key themes, emotions, risk factors). You can freely adjust
    this prompt to match your course requirements.
    """
    return (
        """You are an expert clinical AI assistant analyzing a therapy session transcript.
    Your goal is to extract structured clinical insights and provide **verbatim quotes** from the text as evidence for every claim.

    Analyze the transcript and output a valid JSON object based strictly on the schema below.
    Ensure every insight is backed by a direct quote from the patient or therapist.

    JSON Schema Requirements:

    1. "session_summary": (String) A concise professional summary of the session.
    2. "emotional_analysis": (List of Objects)
    - "emotion": (String) The emotion identified (e.g., Shame, Euphoria).
    - "trigger": (String) What caused this feeling.
    - "evidence_quote": (String) The exact sentence where the patient expresses this.
    3. "mood_triggers": (Object)
    - "positive_triggers": (List of Objects) Things that make the patient feel "good" (even if manic).
        - "trigger": (String) e.g., "Ritalin use"
        - "evidence_quote": (String) Quote supporting this.
    - "negative_triggers": (List of Objects) Things that make the patient feel "bad".
        - "trigger": (String) e.g., "Failing exams"
        - "evidence_quote": (String) Quote supporting this.
    4. "homework_assignments": (List of Objects)
    - "task": (String) Description of the task assigned by the therapist.
    - "evidence_quote": (String) The therapist's exact instruction. (If none, return empty list).
    5. "next_session_followup": (List of Strings) Recommendations for the therapist to check next time based on the analysis.
    6. "addiction_history": (Object)
    - "has_history": (Boolean) true/false
    - "substances": (List of Strings) e.g. ["Alcohol", "Cocaine"]
    - "evidence_quote": (String) The exact text where the patient mentions specific substances.

    Input Transcript:
    {TRANSCRIPT_TEXT}
        """
    )



def analyze_transcript_with_llm(transcript_text: str, session_id: str) -> Dict[str, Any]:
    """
    Analyze a transcript using Gemini 2.5 Pro.

    Returns:
        A Python dict parsed from the JSON produced by the model.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set the GEMINI_API_KEY environment variable."
        )

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

    # Configure the Gemini client
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config={
            # Ask Gemini to respond with JSON so we can parse it reliably.
            "response_mime_type": "application/json",
        },
    )

    system_prompt = _build_system_prompt()
    # Combine instructions and transcript into a single prompt string.
    full_prompt = (
        system_prompt.replace("{TRANSCRIPT_TEXT}", transcript_text)
        if "{TRANSCRIPT_TEXT}" in system_prompt
        else system_prompt + "\n\nTRANSCRIPT:\n" + transcript_text
    )

    try:
        # Gemini's generate_content can take a single string; with
        # response_mime_type='application/json' we expect JSON text back.
        response = model.generate_content(full_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Gemini call failed for session_id=%s: %r", session_id, exc)
        raise

    # Return the response as a JSON object
    content = response.text or "{}"

    try:
        analysis = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(
            "Gemini returned non-JSON content for session_id=%s, returning None",
            session_id,
        )
        return None

    return analysis



