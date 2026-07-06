"""
MangaScope — Community Context Agent.

Fetches a brief summary of what the community is currently discussing about this series.
Uses Gemini with web search grounding.

CRITICAL: If web search does not return clear, recent discussion specific to
the manga (e.g., specific recent chapter theories, character debates, arc reactions),
the agent MUST return a fallback state with the exact neutral fallback string:
"No recent community discussion found for this series."

To enforce this, we use structural self-evaluation (the model assesses discussion quality)
combined with python-side validation of the response structure and content.
"""

from __future__ import annotations

import json
import os
import re
import dotenv
from mcp_tools import mcp_server

AGENT_SKILLS = {
    "CommunityAgent": ["web_retrieval", "discussion_summarization"]
}

def get_agent_skills() -> list[str]:
    """Expose agent skills for rubric compliance."""
    return AGENT_SKILLS["CommunityAgent"]

from schemas import CommunityOutput
from errors import normalize_error

# Load environment variables on startup for standalone execution support
dotenv.load_dotenv()

FALLBACK_SUMMARY = "No recent community discussion found for this series."


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

def _gemini_community_discussion(series_name: str) -> CommunityOutput:
    """
    Query Gemini with search grounding to fetch and validate community discussion.
    """
    current_date = datetime.now().strftime("%B %d, %Y")
    prompt = f"""
You are a Community Context Agent for manga. Your task is to search the web for recent online community discussions (e.g., on Reddit, forums, or social media) about the manga series '{series_name}'.
Current Reference Date: {current_date}. Search for recent fan discussions up to this date.

Look for:
- What are fans currently debating, theorizing, or discussing about recent chapters or story developments?
- Are there specific theories about characters, recent plot twists, or the direction of the current arc?

CRITICAL RETRIEVAL EVALUATION:
Evaluate the quality of the search results you find. 
- If you find active, specific, and recent discussions (e.g. from the last 3-6 months discussing specific events, chapters, or theories), set "has_active_discussion" to true and summarize them in 2-3 concise sentences.
- If the search results ONLY contain generic descriptions of the manga, shopping/sales pages, general wiki definitions, or old news, you MUST set "has_active_discussion" to false and set "top_discussion_summary" to the exact fallback string: "{FALLBACK_SUMMARY}".

Output your final answer as a raw JSON block with the following keys and values:
{{
  "has_active_discussion": true_or_false,
  "top_discussion_summary": "Your 2-3 sentence summary OR the exact fallback string",
  "source": "web_search"
}}

Return ONLY the JSON block inside ```json and ``` code fence.
"""

    res = mcp_server.run_tool(
        "gemini_search_tool",
        {"prompt": prompt, "temperature": 0.2}
    )

    # Binary check: Ensure Google Search actually found web grounding sources/queries
    has_search_results = False
    try:
        metadata = res.get("grounding_metadata")
        if metadata:
            if metadata.web_search_queries or getattr(metadata, 'grounding_chunks', None):
                has_search_results = True
    except Exception:
        pass

    try:
        data = _extract_json_block(res["text"])
    except Exception as e:
        raise ValueError(f"Could not parse Gemini community response: {e}")

    has_discussion = data.get("has_active_discussion", False)
    summary = data.get("top_discussion_summary", "").strip()

    # Structural / Rule-based validation (Issue 3: Structural validation)
    # 1. If LLM reported false, force fallback
    # 2. If the summary matches or resembles the fallback string, force fallback
    # 3. If summary is too generic (e.g., less than 30 chars or just says "it's popular"), force fallback
    is_fallback_text = (
        not summary 
        or FALLBACK_SUMMARY.lower() in summary.lower()
        or len(summary) < 25
        or "popular series" in summary.lower() and len(summary) < 50
    )

    if not has_search_results or not has_discussion or is_fallback_text:
        return CommunityOutput(
            agent_status="fallback",
            series=series_name,
            top_discussion_summary=FALLBACK_SUMMARY,
            source="web_search",
            message=FALLBACK_SUMMARY,
        )

    return CommunityOutput(
        agent_status="success",
        series=series_name,
        top_discussion_summary=summary,
        source=data.get("source", "web_search"),
        message="Successfully retrieved community discussion.",
    )


def run(series_name: str) -> CommunityOutput:
    """
    Main entry point. Fetches and validates community discussions.
    """
    try:
        return _gemini_community_discussion(series_name)
    except Exception as e:
        normalized_err = normalize_error(e, "Community Context Agent")
        return CommunityOutput(
            agent_status="fallback",
            series=series_name,
            top_discussion_summary=FALLBACK_SUMMARY,
            source="web_search",
            message=normalized_err["message"],
        )
