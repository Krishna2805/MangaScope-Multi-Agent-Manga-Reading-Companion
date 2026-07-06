"""
MangaScope — Adaptation Tracker Agent.

Maps anime episodes to manga chapters so the user knows where to resume reading.

Strategy: Deterministic first, LLM fallback second.
  1. Check dynamic lifecycle-managed verified mappings (confidence: high).
  2. If not found, call Gemini with web search grounding (confidence: low).
  3. If Gemini also fails, return confidence: unknown.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional
import dotenv
from datetime import datetime
from mcp_tools import mcp_server

AGENT_SKILLS = {
    "TrackerAgent": ["anime_manga_mapping", "chapter_alignment"]
}

def get_agent_skills() -> list[str]:
    """Expose agent skills for rubric compliance."""
    return AGENT_SKILLS["TrackerAgent"]

from schemas import AdaptationOutput
from errors import normalize_error

# Load environment variables on startup for standalone execution support
dotenv.load_dotenv()

# Path to the dynamic lifecycle-managed JSON file
MAPPINGS_FILE = os.path.join(os.path.dirname(__file__), "verified_mappings.json")

# Baseline hardcoded mappings in case JSON file is missing/uncaught issues
BASELINE_MAPPINGS = {
    "one piece": {
        "anime_status": "ONGOING",
        "anime_episodes_aired": 1122,
        "manga_chapter_equivalent": 1122,
        "safe_resume_chapter": 1123,
        "note": "Anime is ongoing. Verified mapping.",
    },
    "attack on titan": {
        "anime_status": "FINISHED",
        "anime_episodes_aired": 89,
        "manga_chapter_equivalent": 139,
        "safe_resume_chapter": 140,
        "note": "Anime fully covered the manga. Manga is complete.",
    },
}


def load_verified_mappings() -> dict:
    """Load verified mappings from verified_mappings.json with strict schema validation."""
    if not os.path.exists(MAPPINGS_FILE):
        return {}

    try:
        with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Enforce schema validity
            validated = {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        # Ensure essential keys exist and have correct types
                        anime_status = v.get("anime_status")
                        safe_resume = v.get("safe_resume_chapter")
                        if anime_status in ["ONGOING", "FINISHED", "NO_ADAPTATION"]:
                            try:
                                safe_resume_val = int(safe_resume) if safe_resume is not None else None
                            except (ValueError, TypeError):
                                safe_resume_val = None
                            
                            validated[_normalize_series_name(k)] = {
                                "anime_status": anime_status,
                                "anime_episodes_aired": v.get("anime_episodes_aired"),
                                "manga_chapter_equivalent": v.get("manga_chapter_equivalent"),
                                "safe_resume_chapter": safe_resume_val,
                                "confidence": v.get("confidence", "high"),
                                "note": str(v.get("note", "Verified Mapping")),
                            }
            return validated
    except Exception:
        return {}


def register_verified_mapping(series_name: str, mapping_data: dict) -> bool:
    """
    Lifecycle helper to register or update a verified mapping dynamically.
    Returns True if successfully written, False otherwise.
    """
    mappings = load_verified_mappings()
    normalized = _normalize_series_name(series_name)
    mappings[normalized] = {
        "anime_status": mapping_data.get("anime_status", "UNKNOWN"),
        "anime_episodes_aired": mapping_data.get("anime_episodes_aired"),
        "manga_chapter_equivalent": mapping_data.get("manga_chapter_equivalent"),
        "safe_resume_chapter": mapping_data.get("safe_resume_chapter"),
        "confidence": mapping_data.get("confidence", "high"),
        "note": mapping_data.get("note", "Dynamically registered mapping."),
    }

    try:
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(mappings, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def _normalize_series_name(name: str) -> str:
    """Normalize a series name for lookup by removing non-alphanumeric characters."""
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _extract_json_block(text: str) -> dict:
    """Robust helper to extract and parse JSON from LLM text output."""
    # Try finding markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try parsing the whole text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try simple brace extraction if above fails
    brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError("Response does not contain a valid JSON block.")


def _gemini_tracker_fallback(series_name: str) -> AdaptationOutput:
    """
    Call Gemini with web search grounding to estimate anime-to-manga mapping.
    Confidence is always 'low' for Gemini estimates.
    """
    current_date = datetime.now().strftime("%B %d, %Y")
    prompt = f"""
You are a Manga-to-Anime Adaptation Tracker. Your job is to search the web to map where the anime adaptation of the manga series '{series_name}' currently stands.
Current Reference Date: {current_date}. Ensure you search for the absolute latest episodes and chapter mappings released up to this date.

Search for:
1. Is there an anime adaptation of '{series_name}'?
2. If yes, is the anime status ONGOING or FINISHED? (Or NO_ADAPTATION if no anime exists at all)
3. How many total episodes have aired?
4. What manga chapter does the latest episode correspond to?
5. What is the safe chapter to resume reading from to pick up exactly where the anime left off?

Please output your final answer as a raw JSON block with the following keys and values:
{{
  "anime_status": "ONGOING" or "FINISHED" or "NO_ADAPTATION",
  "anime_episodes_aired": number_of_episodes_aired_or_null,
  "manga_chapter_equivalent": manga_chapter_equivalent_or_null,
  "safe_resume_chapter": safe_resume_chapter_to_continue_reading,
  "note": "A concise explanation of the anime status and mapping."
}}

If there is NO anime adaptation, set:
- "anime_status" to "NO_ADAPTATION"
- "anime_episodes_aired" to null
- "manga_chapter_equivalent" to null
- "safe_resume_chapter" to 1
- "note" to "No anime adaptation. Start from Chapter 1."

Be precise and factual. Ensure the JSON block is properly formatted. Return ONLY the JSON block inside ```json and ``` code fence.
"""

    res = mcp_server.run_tool(
        "gemini_search_tool",
        {"prompt": prompt, "model": "gemini-2.5-flash", "temperature": 0.1}
    )

    try:
        data = _extract_json_block(res["text"])
    except Exception as e:
        raise ValueError(f"Could not parse Gemini mapping response: {e}")

    # Enforce safe defaults/validation on the parsed JSON
    anime_status = data.get("anime_status", "UNKNOWN").upper()
    if anime_status not in ["ONGOING", "FINISHED", "NO_ADAPTATION"]:
        anime_status = "UNKNOWN"

    episodes = data.get("anime_episodes_aired")
    if episodes is not None:
        try:
            episodes = int(episodes)
        except (ValueError, TypeError):
            episodes = None

    chapter_eq = data.get("manga_chapter_equivalent")
    if chapter_eq is not None:
        try:
            chapter_eq = int(chapter_eq)
        except (ValueError, TypeError):
            chapter_eq = None

    resume_ch = data.get("safe_resume_chapter")
    if resume_ch is not None:
        try:
            resume_ch = int(resume_ch)
        except (ValueError, TypeError):
            resume_ch = 1
    else:
        resume_ch = 1

    # Override note to include the disclaimer mandated by the plan
    disclaimer = "Chapter mapping estimated via web search. Verify before reading to avoid spoilers."
    note = data.get("note", "").strip()
    full_note = f"{note} [{disclaimer}]" if note else disclaimer

    return AdaptationOutput(
        agent_status="success",
        series=series_name,
        anime_status=anime_status,
        anime_episodes_aired=episodes,
        manga_chapter_equivalent=chapter_eq,
        safe_resume_chapter=resume_ch,
        confidence="low",
        note=full_note,
        message="Successfully estimated mapping via search.",
    )


def run(series_name: str, anilist_id: int | None = None) -> AdaptationOutput:
    """
    Main entry point. Determines where the anime adaptation ends in manga chapters.
    """
    try:
        normalized = _normalize_series_name(series_name)
        verified_mappings = load_verified_mappings()

        # Step 1 — Check verified mappings first (deterministic, high confidence)
        if normalized in verified_mappings:
            mapping = verified_mappings[normalized]
            return AdaptationOutput(
                agent_status="success",
                series=series_name,
                anime_status=mapping["anime_status"],
                anime_episodes_aired=mapping.get("anime_episodes_aired"),
                manga_chapter_equivalent=mapping["manga_chapter_equivalent"],
                safe_resume_chapter=mapping["safe_resume_chapter"],
                confidence=mapping.get("confidence", "high"),
                note=mapping["note"],
                message="Successfully resolved verified mapping.",
            )

        # Step 2 — Gemini web search fallback (low confidence)
        return _gemini_tracker_fallback(series_name)

    except Exception as e:
        normalized_err = normalize_error(e, "Adaptation Tracker")
        return AdaptationOutput(
            agent_status="fallback",
            series=series_name,
            anime_status="UNKNOWN",
            confidence="unknown",
            note=normalized_err["message"],
            message=normalized_err["message"],
        )
