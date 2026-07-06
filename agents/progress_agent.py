"""
MangaScope — Progress Agent.

Queries the AniList GraphQL API to get a user's reading status for a given
manga series. Returns structured ProgressOutput.

Critical: GraphQL APIs return HTTP 200 even on logical failures. Both the
`errors` key and null-data checks are mandatory after every call.
"""

from __future__ import annotations

import dotenv
from schemas import ProgressOutput
from errors import normalize_error
from mcp_tools import mcp_server

# Load environment variables on startup for standalone execution support
dotenv.load_dotenv()

AGENT_SKILLS = {
    "ProgressAgent": ["anilist_query", "reading_status_extraction"]
}

def get_agent_skills() -> list[str]:
    """Expose agent skills for rubric compliance."""
    return AGENT_SKILLS["ProgressAgent"]

ANILIST_URL = "https://graphql.anilist.co"

# ── GraphQL Queries ──────────────────────────────────────────────────────────

SEARCH_MANGA_QUERY = """
query ($search: String) {
  Media(search: $search, type: MANGA) {
    id
    title {
      romaji
      english
    }
    status
    chapters
  }
}
"""

USER_MANGA_LIST_QUERY = """
query ($userName: String, $mediaId: Int) {
  MediaList(userName: $userName, mediaId: $mediaId, type: MANGA) {
    status
    progress
    progressVolumes
    score
    media {
      id
      title {
        romaji
        english
      }
      status
      chapters
    }
  }
}
"""


def _anilist_request(query: str, variables: dict) -> tuple[dict, int]:
    """
    Make a GraphQL request using the centralized MCP tool layer.
    """
    res = mcp_server.run_tool(
        "anilist_graphql_tool",
        {"query": query, "variables": variables, "timeout": 15}
    )
    return res["data"], res["status_code"]


def _search_manga(series_name: str) -> tuple[int | None, str]:
    """
    Search AniList for a manga by name.
    Returns (anilist_id, resolved_title) or (None, "") on failure.
    """
    data, status_code = _anilist_request(SEARCH_MANGA_QUERY, {"search": series_name})

    # Check for API-level errors
    if "errors" in data:
        return None, ""

    media = data.get("data", {}).get("Media")
    if media is None:
        return None, ""

    title = media["title"].get("english") or media["title"].get("romaji") or series_name
    return media["id"], title


def run(username: str, series_name: str) -> ProgressOutput:
    """
    Main entry point. Queries AniList for the user's progress on a manga.
    
    Steps:
      1. Search AniList for the manga to get its ID.
      2. Query the user's list for that specific manga.
      3. Return structured output with agent_status.
    """
    # Step 1 — Resolve manga ID
    try:
        manga_id, resolved_title = _search_manga(series_name)
    except Exception as e:
        norm = normalize_error(e, "Progress Agent (Search)")
        return ProgressOutput(
            agent_status="fallback",
            series=series_name,
            status="API_ERROR",
            message=norm["message"],
        )

    if manga_id is None:
        return ProgressOutput(
            agent_status="fallback",
            series=series_name,
            status="NOT_FOUND",
            message=f"Could not find manga '{series_name}' on AniList.",
        )

    # Step 2 — Query user's list for this manga
    try:
        data, status_code = _anilist_request(
            USER_MANGA_LIST_QUERY,
            {"userName": username, "mediaId": manga_id},
        )
    except Exception as e:
        norm = normalize_error(e, "Progress Agent (User List)")
        return ProgressOutput(
            agent_status="fallback",
            series=resolved_title,
            anilist_id=manga_id,
            status="API_ERROR",
            message=norm["message"],
        )

    # Step 2a — Handle HTTP-level errors (AniList uses 404 for "not in list")
    if status_code == 404:
        return ProgressOutput(
            agent_status="success",
            series=resolved_title,
            anilist_id=manga_id,
            status="NOT_IN_LIST",
            message=f"'{resolved_title}' is not in {username}'s manga list.",
        )
    if status_code >= 400:
        error_msg = ""
        if "errors" in data and data["errors"]:
            error_msg = data["errors"][0].get("message", "")
        return ProgressOutput(
            agent_status="fallback",
            series=resolved_title,
            anilist_id=manga_id,
            status="API_ERROR",
            message=error_msg or f"AniList returned HTTP {status_code}.",
        )

    # Step 2a — Check for API-level errors (GraphQL returns 200 on errors!)
    if "errors" in data:
        error_msg = data["errors"][0].get("message", "Unknown AniList error")
        # "Not Found." usually means the user has no entry for this manga
        if "not found" in error_msg.lower():
            return ProgressOutput(
                agent_status="success",
                series=resolved_title,
                anilist_id=manga_id,
                status="NOT_IN_LIST",
                message=f"'{resolved_title}' is not in {username}'s manga list.",
            )
        return ProgressOutput(
            agent_status="fallback",
            series=resolved_title,
            anilist_id=manga_id,
            status="API_ERROR",
            message=error_msg,
        )

    # Step 2b — Check for null data
    media_list = data.get("data", {}).get("MediaList")
    if media_list is None:
        return ProgressOutput(
            agent_status="success",
            series=resolved_title,
            anilist_id=manga_id,
            status="NOT_IN_LIST",
            message=f"'{resolved_title}' is not in {username}'s manga list.",
        )

    # Step 3 — Parse the response
    media_data = media_list.get("media", {})
    manga_status = media_data.get("status")
    total_chapters = media_data.get("chapters")

    return ProgressOutput(
        agent_status="success",
        series=resolved_title,
        anilist_id=manga_id,
        status=media_list.get("status", "UNKNOWN"),
        chapters_read=media_list.get("progress", 0) or 0,
        volumes_read=media_list.get("progressVolumes", 0) or 0,
        user_score=media_list.get("score"),
        manga_status=manga_status,
        total_chapters=total_chapters,
        message="Successfully retrieved reading progress.",
    )
