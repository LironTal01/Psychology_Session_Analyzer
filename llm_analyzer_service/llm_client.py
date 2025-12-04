import json
import logging
import re
from typing import Any, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from common.config import openai as openai_config

logger = logging.getLogger("llm_analyzer_service.llm_client")


def _build_system_prompt() -> str:
    """
    Build the system-level instructions for the LLM.

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
    max_chars_per_chunk = 120000
    text_len = len(transcript_text)
    if text_len <= max_chars_per_chunk:
        return [transcript_text]

    chunks: list[str] = []
    start = 0
    while start < text_len:
        end = min(start + max_chars_per_chunk, text_len)
        chunks.append(transcript_text[start:end])
        start = end

    # Log the number of chunks and the max characters per chunk
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

    # If there is only one chunk, return the analysis for that chunk
    if len(analyses) == 1:
        return analyses[0]

    merged: Dict[str, Any] = {}
    # if the same speaker is mentioned in multiple chunks, only include it once
    seen_speakers = set()
    speakers_result = []
    # loop through each chunk and add the speakers to the result if they are not already in the result
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

    # Clean and deduplicate mood triggers to avoid empty/duplicate entries
    def _clean_triggers(triggers: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in triggers:
            if not isinstance(item, dict):
                continue
            trig = str(item.get("trigger") or "").strip()
            evidence = str(item.get("evidence_quote") or "").strip()
            if not trig and not evidence:
                continue
            key = (trig, evidence)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                {
                    "trigger": trig,
                    "evidence_quote": evidence,
                }
            )
        return cleaned

    positive_triggers_clean = _clean_triggers(positive_triggers)
    negative_triggers_clean = _clean_triggers(negative_triggers)

    if positive_triggers_clean or negative_triggers_clean:
        merged["mood_triggers"] = {
            "positive_triggers": positive_triggers_clean,
            "negative_triggers": negative_triggers_clean,
        }

    # Filter out empty homework items (both fields empty or whitespace)
    homework = []
    for analysis in analyses:
        homework.extend(analysis.get("homework_assignments") or [])

    if homework:
        cleaned_homework: list[Dict[str, Any]] = []
        seen_hw: set[tuple[str, str]] = set()
        for item in homework:
            if not isinstance(item, dict):
                continue
            task = str(item.get("task") or "").strip()
            evidence = str(item.get("evidence_quote") or "").strip()
            if not task and not evidence:
                continue
            key = (task, evidence)
            if key in seen_hw:
                continue
            seen_hw.add(key)
            cleaned_homework.append(
                {
                    "task": task,
                    "evidence_quote": evidence,
                }
            )

        if cleaned_homework:
            merged["homework_assignments"] = cleaned_homework

    # next_session_followup
    followup = []
    for analysis in analyses:
        followup.extend(analysis.get("next_session_followup") or [])

    # Remove empty strings and deduplicate while preserving order
    if followup:
        cleaned_followup: list[str] = []
        seen_followup: set[str] = set()
        for item in followup:
            text = str(item or "").strip()
            if not text:
                continue
            if text in seen_followup:
                continue
            seen_followup.add(text)
            cleaned_followup.append(text)

        if cleaned_followup:
            merged["next_session_followup"] = cleaned_followup

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


def _refine_summary_and_followup_with_llm(
    session_summary: str | None,
    next_session_followup: list[str] | None,
    session_id: str,
    model_name: str,
    client: OpenAI,
) -> tuple[str | None, list[str] | None]:
    """
    Refine session_summary and next_session_followup using the LLM.
    """
    has_summary = bool(session_summary)
    has_followup = bool(next_session_followup)
    if not (has_summary or has_followup):
        return session_summary, next_session_followup
    
    system_prompt = (
        "You are a clinical psychology assistant that compresses an existing summary.\n"
        "You will receive:\n"
        "  - `session_summary`: a long clinical narrative.\n"
        "  - `next_session_followup`: a list of bullet-style follow-up items.\n\n"
        "Your tasks:\n"
        "  1) Rewrite `session_summary` as a concise 3–6 sentence clinical summary,\n"
        "     removing repetitions but preserving the main themes.\n"
        "  2) Rewrite `next_session_followup` as a list of at most 10 bullet-style\n"
        "     strings, merging or dropping overlapping items while keeping key ideas.\n\n"
        "Return ONLY a single JSON object of the form:\n"
        "{\n"
        "  \"session_summary\": \"...\",\n"
        "  \"next_session_followup\": [\"...\", \"...\"]\n"
        "}\n"
        "If one of the inputs is missing, simply copy the other without changes."
    )

    payload: Dict[str, Any] = {}
    if has_summary:
        payload["session_summary"] = session_summary
    if has_followup:
        payload["next_session_followup"] = next_session_followup

    user_content = (
        "Here is the current summary/follow-up for session_id="
        f"{session_id}.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
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
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "LLM refinement of summary/followup failed for session_id=%s: %r",
            session_id,
            exc,
        )
        return session_summary, next_session_followup

    content = completion.choices[0].message.content or "{}"

    try:
        refined = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(
            "LLM refinement returned non-JSON content for session_id=%s; "
            "falling back to original summary/followup",
            session_id,
        )
        return session_summary, next_session_followup

    if not isinstance(refined, dict):
        return session_summary, next_session_followup

    new_summary = refined.get("session_summary", session_summary)
    new_followup = refined.get("next_session_followup", next_session_followup)

    # Type safety: only accept if of expected types.
    if not isinstance(new_summary, str):
        new_summary = session_summary
    if not (isinstance(new_followup, list) and all(isinstance(x, str) for x in new_followup or [])):
        new_followup = next_session_followup

    return new_summary, new_followup


def analyze_transcript_with_llm(transcript_text: str, session_id: str) -> Dict[str, Any]:
    """Analyze a transcript using OpenAI, with chunking and merging.
    """
    api_key = openai_config.api_key
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Please set the OPENAI_API_KEY environment variable."
        )

    model_name = openai_config.model
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
    
    # Refine the summary and followup with the LLM to avoid overly long/duplicated content.
    summary_before = merged.get("session_summary")
    followup_before = merged.get("next_session_followup")

    new_summary, new_followup = _refine_summary_and_followup_with_llm(
        session_summary=summary_before,
        next_session_followup=followup_before,
        session_id=session_id,
        model_name=model_name,
        client=client,
    )

    if new_summary is not None:
        merged["session_summary"] = new_summary
    if new_followup is not None:
        merged["next_session_followup"] = new_followup

    # Return the merged analysis json object 
    return merged




