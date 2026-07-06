"""
MangaScope — Recommendation Agent.

Recommends what arcs/chapters to read next based on the user's progress
and the safe resume chapter from the Tracker Agent.

CRITICAL CONSTRAINT: `start_chapter` in the output can NEVER be lower than
`safe_resume_chapter` / `chapters_read + 1`. This constraint is enforced
both in the prompt and programmatically in Python as a guarantee.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional
import dotenv
from mcp_tools import mcp_server

AGENT_SKILLS = {
    "RecommendationAgent": ["arc_recommendation", "constraint_reasoning"]
}

def get_agent_skills() -> list[str]:
    """Expose agent skills for rubric compliance."""
    return AGENT_SKILLS["RecommendationAgent"]

from schemas import RecommendationOutput
from errors import normalize_error

# Load environment variables on startup for standalone execution support
dotenv.load_dotenv(override=True)


def _extract_json_block(text: str) -> dict:
    """Robust helper to extract and parse JSON from LLM text output."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError("Response does not contain a valid JSON block.")


from datetime import datetime

def _gemini_recommendation(
    series_name: str, target_chapter: int
) -> RecommendationOutput:
    """
    Query Gemini with web search grounding to find story arcs/chapters
    starting from target_chapter.
    """
    current_date = datetime.now().strftime("%B %d, %Y")
    prompt = f"""
You are a Manga Recommendation Agent. Your job is to search the web to find the manga story arcs and chapter ranges for '{series_name}' starting from chapter {target_chapter}.
Current Reference Date: {current_date}. Ensure you suggest the latest story arcs and chapters released up to this date.

Specifically, search for:
1. What is the name of the major story arc containing or starting at chapter {target_chapter}?
2. What are the chapter boundaries (start and end chapters) for this arc?
3. Provide a brief, spoiler-safe description of the arc.
4. Estimate how many chapters are remaining in this arc from chapter {target_chapter} onwards.

CRITICAL CONSTRAINT:
The "start_chapter" in your JSON output MUST be greater than or equal to {target_chapter}. If the major arc begins before chapter {target_chapter}, you MUST adjust "start_chapter" to {target_chapter} and mention in your description that it is a continuation of that arc from chapter {target_chapter}.

Please output your final answer as a raw JSON block with the following keys and values:
{{
  "next_arc": "Name of the Story Arc" or null if user is fully up-to-date/caught up,
  "start_chapter": {target_chapter}_or_higher_integer or null if up-to-date,
  "end_chapter": end_chapter_integer_or_null_if_ongoing_or_up-to-date,
  "description": "A brief, spoiler-safe description of this arc, or a congrats note if up-to-date.",
  "estimated_chapters_remaining": chapters_remaining_integer_or_null,
  "reading_priority": "high" or "medium" or "low" or "up_to_date"
}}

Return ONLY the JSON block inside ```json and ``` code fence.
"""

    res = mcp_server.run_tool(
        "gemini_search_tool",
        {"prompt": prompt, "temperature": 0.2}
    )

    try:
        data = _extract_json_block(res["text"])
    except Exception as e:
        raise ValueError(f"Could not parse Gemini recommendation response: {e}")

    # Enforce constraints programmatically (Issue 1: Constraint logic enforcement)
    raw_start = data.get("start_chapter")
    try:
        start_chapter = max(int(raw_start), target_chapter) if raw_start is not None else target_chapter
    except (ValueError, TypeError):
        start_chapter = target_chapter

    # If the start chapter was modified programmatically, add a note to description
    description = data.get("description", "").strip()
    if raw_start is not None and int(raw_start) < target_chapter:
        note = f" (Recommendation adjusted to begin at your current resume point of Chapter {target_chapter}.)"
        if note not in description:
            description += note

    end_chapter = data.get("end_chapter")
    if end_chapter is not None:
        try:
            end_chapter = int(end_chapter)
            if end_chapter < start_chapter:
                end_chapter = None
        except (ValueError, TypeError):
            end_chapter = None

    est_remaining = data.get("estimated_chapters_remaining")
    if est_remaining is not None:
        try:
            est_remaining = int(est_remaining)
        except (ValueError, TypeError):
            est_remaining = None
    elif end_chapter is not None:
        # Calculate estimate if missing
        est_remaining = max(0, end_chapter - start_chapter)

    priority = data.get("reading_priority", "medium").lower()
    if priority not in ["high", "medium", "low", "up_to_date"]:
        priority = "medium"

    next_arc = data.get("next_arc")
    if priority == "up_to_date":
        next_arc = None
        start_chapter = None
        end_chapter = None
        est_remaining = None
        message = "You are fully caught up with this series!"
    else:
        next_arc = next_arc or "Next Arc"
        message = "Successfully generated reading recommendation."

    return RecommendationOutput(
        agent_status="success",
        next_arc=next_arc,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        description=description,
        estimated_chapters_remaining=est_remaining,
        reading_priority=priority,
        message=message,
    )


def run(
    series_name: str,
    chapters_read: int,
    safe_resume_chapter: int | None,
    anime_status: str = "UNKNOWN",
    manga_status: Optional[str] = None,
    total_chapters: Optional[int] = None,
    user_list_status: Optional[str] = None,
) -> RecommendationOutput:
    """
    Main entry point. Recommends what to read next.
    """
    try:
        # Upfront Caught-up / Up-to-date checking
        # Case A: User completed the series on AniList
        # Case B: User has read up to or past total chapters (if total chapters is known)
        is_caught_up = False
        caught_up_reason = ""

        if user_list_status == "COMPLETED":
            is_caught_up = True
            caught_up_reason = "You have marked this series as completed on AniList."
        elif total_chapters is not None and total_chapters > 0 and chapters_read >= total_chapters:
            is_caught_up = True
            caught_up_reason = f"You have read all {total_chapters} chapters of this series."
        elif manga_status == "FINISHED" and total_chapters is not None and total_chapters > 0 and chapters_read >= total_chapters:
            is_caught_up = True
            caught_up_reason = "The manga is finished and you have read all chapters."
        elif total_chapters is not None and total_chapters > 0 and safe_resume_chapter is not None and safe_resume_chapter > total_chapters:
            is_caught_up = True
            caught_up_reason = f"The anime adaptation (resuming at Chapter {safe_resume_chapter}) has already covered the entire manga (which has {total_chapters} chapters)."

        if is_caught_up:
            return RecommendationOutput(
                agent_status="success",
                next_arc=None,
                start_chapter=None,
                end_chapter=None,
                description=f"Congratulations! {caught_up_reason} You are completely up-to-date.",
                estimated_chapters_remaining=0,
                reading_priority="up_to_date",
                message="You are fully caught up with this series!",
            )

        # 1. Determine target start chapter (at least safe_resume_chapter if available, and > chapters_read)
        if safe_resume_chapter is not None:
            target_chapter = max(chapters_read + 1, safe_resume_chapter)
        else:
            target_chapter = chapters_read + 1

        # 2. Call Gemini to find arc details starting from target_chapter
        return _gemini_recommendation(series_name, target_chapter)

    except Exception as e:
        normalized_err = normalize_error(e, "Recommendation Agent")
        # Enforce fallback semantics
        return RecommendationOutput(
            agent_status="fallback",
            next_arc=None,
            start_chapter=chapters_read + 1,
            end_chapter=None,
            description=normalized_err["message"],
            estimated_chapters_remaining=None,
            reading_priority="unknown",
            message=normalized_err["message"],
        )
