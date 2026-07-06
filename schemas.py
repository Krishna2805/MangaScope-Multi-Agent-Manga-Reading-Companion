"""
MangaScope — Output schemas for all agents and the final synthesized report.

Every agent sub-output includes an `agent_status` field ("success" or "fallback").
The Coordinator ensures this field is always present before passing to the UI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Agent Sub-Outputs ────────────────────────────────────────────────────────

class ProgressOutput(BaseModel):
    """Output from the Progress Agent (AniList reading status)."""
    agent_status: str = Field(default="success", description="'success' or 'fallback'")
    series: str = ""
    status: str = ""  # CURRENT, COMPLETED, PAUSED, DROPPED, PLANNING, NOT_IN_LIST
    chapters_read: int = 0
    volumes_read: int = 0
    user_score: Optional[int] = None
    anilist_id: Optional[int] = None
    manga_status: Optional[str] = None  # AniList manga status e.g. FINISHED, RELEASING
    total_chapters: Optional[int] = None  # Total chapters if finished/tracked
    message: str = ""  # Human-readable status/error message


class AdaptationOutput(BaseModel):
    """Output from the Adaptation Tracker Agent."""
    agent_status: str = Field(default="success", description="'success' or 'fallback'")
    series: str = ""
    anime_status: str = ""  # ONGOING, FINISHED, NO_ADAPTATION
    anime_episodes_aired: Optional[int] = None
    manga_chapter_equivalent: Optional[int] = None
    safe_resume_chapter: Optional[int] = None
    confidence: str = "unknown"  # high, low, unknown
    note: str = ""
    message: str = ""  # Standardised status/error message


class RecommendationOutput(BaseModel):
    """Output from the Recommendation Agent."""
    agent_status: str = Field(default="success", description="'success' or 'fallback'")
    next_arc: Optional[str] = None
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    description: str = ""
    estimated_chapters_remaining: Optional[int] = None
    reading_priority: str = ""  # high, medium, low, up_to_date
    message: str = ""  # Standardised status/error message


class CommunityOutput(BaseModel):
    """Output from the Community Context Agent."""
    agent_status: str = Field(default="success", description="'success' or 'fallback'")
    series: str = ""
    top_discussion_summary: str = ""
    source: str = "web_search"
    message: str = ""  # Standardised status/error message



# ── Final Synthesized Report ─────────────────────────────────────────────────

class MangaScopeReport(BaseModel):
    """
    The complete output the Coordinator produces after running all agents.
    The UI renders exclusively from this structure.
    """
    username: str
    series: str
    progress: ProgressOutput
    adaptation: AdaptationOutput
    recommendation: RecommendationOutput
    community_context: CommunityOutput
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ── Memory Schema ────────────────────────────────────────────────────────────

class SeriesMemoryEntry(BaseModel):
    """A single series entry stored in memory."""
    series: str
    chapters_read_at_last_run: int = 0
    recommendation_given: Optional[str] = None


class UserMemory(BaseModel):
    """Top-level memory structure persisted to memory.json."""
    username: str
    last_run: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    series_history: list[SeriesMemoryEntry] = Field(default_factory=list)
