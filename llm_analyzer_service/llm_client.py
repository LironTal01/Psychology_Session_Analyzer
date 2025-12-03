import json
import logging
import os
from typing import Any, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

logger = logging.getLogger("llm_analyzer_service.llm_client")


def _build_system_prompt() -> str:
    """
    Build the system-level instructions for the LLM.

    This text explains to the model what kind of analysis we expect
    (e.g., who is speaking, topics, emotions, risk factors).
    """
    return (
        """You are an expert clinical psychology assistant analyzing a therapy session transcript.
Your goals:
- Infer which speakers are the therapist and the patient.
- Tag each sentence the patient or therapist says with a TOPIC and an EMOTION/FEELING.
- Provide clear, structured JSON output with evidence quotes for every claim.

You MUST return ONLY a single valid JSON object with the following schema (no extra text, no markdown):

{
  "speakers": [
    {
      "id": "P",
      "role": "patient",              // either "patient" or "therapist"
      "description": "short description of how this person speaks or behaves"
    },
    {
      "id": "T",
      "role": "therapist",
      "description": "short description of how this person speaks or behaves"
    }
  ],
  "utterances": [
    {
      "speaker_id": "P",              // references one of the speaker ids above
      "text": "exact sentence as it appears in the transcript",
      "topic": "short topic label (e.g. 'mother', 'work stress', 'sleep', 'medication')",
      "emotion": "one of: [\"happy\", \"sad\", \"anxious\", \"angry\", \"ashamed\", \"guilty\", \"relieved\", \"hopeful\", \"neutral\"]",
      "evidence_quote": "repeat the exact part of the sentence that shows this emotion/topic"
    }
    // one object per spoken sentence; if no clear emotion/topic, use \"neutral\" and a generic topic like \"other\"
  ],
  "session_summary": "2-4 sentence clinical summary of the main issues discussed",
  "mood_triggers": {
    "positive_triggers": [
      {
        "trigger": "short phrase for something that makes the patient feel good",
        "evidence_quote": "exact quote showing it"
      }
    ],
    "negative_triggers": [
      {
        "trigger": "short phrase for something that makes the patient feel bad",
        "evidence_quote": "exact quote showing it"
      }
    ]
  },
  "homework_assignments": [
    {
      "task": "concrete task the therapist assigned or implied",
      "evidence_quote": "exact therapist wording (or empty string if unclear)"
    }
  ],
  "next_session_followup": [
    "bullet-style recommendation for the therapist to check next time",
    "..."
  ],
  "addiction_history": {
    "has_history": true or false,
    "substances": ["Alcohol", "Cocaine"],  // [] if none mentioned
    "evidence_quote": "exact patient quote mentioning substances or 'none'"
  }
}

Input transcript (verbatim):
{TRANSCRIPT_TEXT}
"""
    )



def _split_transcript_into_chunks(transcript_text: str) -> list[str]:
    """
    Split a long transcript into character-based chunks so that each chunk
    safely fits into the LLM context window.
    """
    max_chars_per_chunk = 75000
    text_len = len(transcript_text)
    if text_len <= max_chars_per_chunk:
        return [transcript_text]

    chunks: list[str] = []
    start = 0
    while start < text_len:
        end = min(start + max_chars_per_chunk, text_len)
        chunks.append(transcript_text[start:end])
        start = end

    logger.info(
        "Transcript split into %d chunks using max_chars_per_chunk=%d",
        len(chunks),
        max_chars_per_chunk,
    )
    return chunks


def _call_openai_for_text(
    transcript_text: str,
    session_id: str,
    model_name: str,
    client: OpenAI,
) -> Dict[str, Any] | None:
    """
    Call OpenAI Chat Completions API for a single text chunk and parse JSON.
 
    Returns a dict on success, or None if the response is not valid JSON.
    """
    system_prompt = _build_system_prompt()
    user_content = (
        "Here is the full transcript of a therapy session (or a part of it). "
        "Please analyze it according to the instructions and return ONLY valid JSON.\n\n"
        "TRANSCRIPT:\n"
        f"{transcript_text}"
    )
 
    try:
        completion = client.chat.completions.create(
            model=model_name,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as exc:  
        logger.exception("OpenAI call failed for session_id=%s: %r", session_id, exc)
        raise
 
    content = completion.choices[0].message.content or "{}"
 
    try:
        analysis = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(
            "OpenAI returned non-JSON content for session_id=%s, returning empty analysis",
            session_id,
        )
        return None
 
    return analysis


def _merge_analyses(analyses: list[Dict[str, Any]], session_id: str) -> Dict[str, Any]:
    """
    Merge multiple chunk-level analyses into a single session-level analysis.
    """
    if not analyses:
        raise ValueError(f"No analyses to merge for session_id={session_id}")

    if len(analyses) == 1:
        return analyses[0]

    merged: Dict[str, Any] = {}

    # speakers: union, deduplicated
    seen_speakers = set()
    speakers_result = []
    for analysis in analyses:
        for sp in (analysis.get("speakers") or []):
            key = (sp.get("id"), sp.get("role"), sp.get("description"))
            if key not in seen_speakers:
                seen_speakers.add(key)
                speakers_result.append(sp)
    if speakers_result:
        merged["speakers"] = speakers_result

    # utterances: concatenate in order
    merged_utterances = []
    for analysis in analyses:
        merged_utterances.extend(analysis.get("utterances") or [])
    merged["utterances"] = merged_utterances

    # session_summary: concatenate simple summaries
    summaries = [
        analysis.get("session_summary", "")
        for analysis in analyses
        if analysis.get("session_summary")
    ]
    if summaries:
        merged["session_summary"] = " ".join(summaries)

    # mood_triggers: merge positive/negative
    positive_triggers = []
    negative_triggers = []
    for analysis in analyses:
        mood = analysis.get("mood_triggers") or {}
        positive_triggers.extend(mood.get("positive_triggers") or [])
        negative_triggers.extend(mood.get("negative_triggers") or [])
    if positive_triggers or negative_triggers:
        merged["mood_triggers"] = {
            "positive_triggers": positive_triggers,
            "negative_triggers": negative_triggers,
        }

    # homework_assignments
    homework = []
    for analysis in analyses:
        homework.extend(analysis.get("homework_assignments") or [])
    if homework:
        merged["homework_assignments"] = homework

    # next_session_followup
    followup = []
    for analysis in analyses:
        followup.extend(analysis.get("next_session_followup") or [])
    if followup:
        merged["next_session_followup"] = followup

    # addiction_history: OR over has_history, union of substances, first evidence_quote
    has_history = False
    substances_set: set[str] = set()
    evidence_quote = "none"
    for analysis in analyses:
        addiction = analysis.get("addiction_history") or {}
        if addiction.get("has_history"):
            has_history = True
            for substance in (addiction.get("substances") or []):
                substances_set.add(str(substance))
            if evidence_quote == "none" and addiction.get("evidence_quote"):
                evidence_quote = addiction["evidence_quote"]

    merged["addiction_history"] = {
        "has_history": has_history,
        "substances": sorted(substances_set) if substances_set else [],
        "evidence_quote": evidence_quote,
    }

    return merged


def analyze_transcript_with_llm(transcript_text: str, session_id: str) -> Dict[str, Any]:
    """Analyze a transcript using OpenAI, with chunking and merging.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Please set the OPENAI_API_KEY environment variable."
        )

    model_name = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    client = OpenAI(api_key=api_key)

    chunks = _split_transcript_into_chunks(transcript_text)
    logger.info(
        "Analyzing transcript for session_id=%s using %d chunk(s)",
        session_id,
        len(chunks),
    )

    partial_analyses: list[Dict[str, Any]] = []

    # Optional parallelism over chunks to speed up long analyses.
    max_parallel = 3
    if max_parallel <= 1 or len(chunks) == 1:
        for idx, chunk in enumerate(chunks, start=1):
            chunk_label = f"{session_id} (chunk {idx}/{len(chunks)})"
            logger.info(
                "Calling OpenAI for %s, chunk length=%d characters",
                chunk_label,
                len(chunk),
            )
            analysis = _call_openai_for_text(
                transcript_text=chunk,
                session_id=chunk_label,
                model_name=model_name,
                client=client,
            )
            if analysis is None:
                logger.warning(
                    "Skipping empty/invalid analysis for %s (chunk %d)",
                    session_id,
                    idx,
                )
                continue
            partial_analyses.append(analysis)
    else:
        logger.info(
            "Running LLM calls in parallel with max_workers=%d for session_id=%s",
            max_parallel,
            session_id,
        )
        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            future_to_idx = {}
            for idx, chunk in enumerate(chunks, start=1):
                chunk_label = f"{session_id} (chunk {idx}/{len(chunks)})"
                future = executor.submit(
                    _call_openai_for_text,
                    transcript_text=chunk,
                    session_id=chunk_label,
                    model_name=model_name,
                    client=client,
                )
                future_to_idx[future] = idx

            # Collect results as they complete (order doesn't matter for merging).
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    analysis = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "OpenAI call failed for %s (chunk %d): %r",
                        session_id,
                        idx,
                        exc,
                    )
                    continue

                if analysis is None:
                    logger.warning(
                        "Skipping empty/invalid analysis for %s (chunk %d)",
                        session_id,
                        idx,
                    )
                    continue
                partial_analyses.append(analysis)

    if not partial_analyses:
        raise RuntimeError(
            f"LLM did not return any valid JSON analyses for session_id={session_id}"
        )

    if len(partial_analyses) == 1:
        return partial_analyses[0]

    merged = _merge_analyses(partial_analyses, session_id=session_id)
    logger.info(
        "Merged %d chunk analyses into a single result for session_id=%s",
        len(partial_analyses),
        session_id,
    )
    return merged




