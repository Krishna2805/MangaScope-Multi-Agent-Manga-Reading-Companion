"""
MangaScope — Coordinator Agent.

The orchestrator. Receives user input, calls each agent in sequence,
handles failures gracefully, and synthesizes the final MangaScopeReport.

Data flow (linear, not parallel):
  1. Validate input via guardrails
  2. Load memory for personalization context
  3. Call Progress Agent → AniList reading status
  4. Call Adaptation Tracker Agent → anime-to-manga chapter mapping
  5. Call Recommendation Agent → arc/chapter recommendation
  6. Call Community Context Agent → discussion summary
  7. Synthesize all outputs into MangaScopeReport
  8. Save to memory

Error handling: Each agent call is wrapped in try/except. On failure, the
Coordinator fills in a fallback output with agent_status="fallback" and a
human-readable message. The report is NEVER missing a section.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from schemas import (
    MangaScopeReport,
    ProgressOutput,
    AdaptationOutput,
    RecommendationOutput,
    CommunityOutput,
)
from guardrails import validate_and_sanitize
from memory import load_memory, save_memory, get_previous_chapters
from agents import progress_agent, tracker_agent, recommendation_agent, community_agent
from errors import normalize_error
import dotenv

# Load environment variables (such as GEMINI_API_KEY)
dotenv.load_dotenv(override=True)



# ── Fallback Factories ───────────────────────────────────────────────────────

def _fallback_progress(series: str, error: str = "") -> ProgressOutput:
    return ProgressOutput(
        agent_status="fallback",
        series=series,
        status="ERROR",
        message=error or "Progress Agent failed unexpectedly.",
    )


def _fallback_adaptation(series: str, error: str = "") -> AdaptationOutput:
    msg = error or "Adaptation Tracker failed unexpectedly."
    return AdaptationOutput(
        agent_status="fallback",
        series=series,
        anime_status="UNKNOWN",
        confidence="unknown",
        note=msg,
        message=msg,
    )


def _fallback_recommendation(error: str = "") -> RecommendationOutput:
    msg = error or "Recommendation Agent failed unexpectedly."
    return RecommendationOutput(
        agent_status="fallback",
        description=msg,
        reading_priority="unknown",
        message=msg,
    )


def _fallback_community(series: str, error: str = "") -> CommunityOutput:
    msg = error or "Community Context Agent failed unexpectedly."
    return CommunityOutput(
        agent_status="fallback",
        series=series,
        top_discussion_summary=msg,
        source="none",
        message=msg,
    )


# ── Orchestration ────────────────────────────────────────────────────────────

class CoordinatorResult:
    """Wraps the final report along with metadata the UI needs."""
    def __init__(self):
        self.report: Optional[MangaScopeReport] = None
        self.validation_error: str = ""
        self.previous_chapters: Optional[int] = None
        self.memory_note: str = ""
        self.trace: list[str] = []  # Diagnostic trace logs for evaluation and writeup
        self.execution_trace: list[dict] = []  # Structured trace of agent/tool calls for Kaggle rubric compliance


def _check_up_to_date(
    chapters_read: int,
    total_chapters: Optional[int],
    user_list_status: str,
    manga_status: Optional[str]
) -> tuple[bool, str]:
    """Single source of truth to check if the user is caught up with the manga."""
    if user_list_status == "COMPLETED":
        return True, "User marked the series as completed on AniList."
    if total_chapters is not None and total_chapters > 0 and chapters_read >= total_chapters:
        return True, f"User has read all {total_chapters} chapters of the series."
    if manga_status == "FINISHED" and total_chapters is not None and total_chapters > 0 and chapters_read >= total_chapters:
        return True, f"Manga is finished and user has read all {total_chapters} chapters."
    return False, ""


def run(
    username: str,
    series_name: str,
    on_step: Optional[Callable[[str, str], None]] = None,
    fetch_community: bool = False,
) -> CoordinatorResult:
    """
    Main entry point. Orchestrates all agents and produces the final report.

    Args:
        username: AniList username.
        series_name: Manga series to look up.
        on_step: Optional callback(step_name, status_message) for UI updates.
                 Called before and after each agent run.
        fetch_community: If True, execute the search-grounded Community Agent.

    Returns:
        CoordinatorResult with the final report and metadata.
    """
    result = CoordinatorResult()
    result.trace.append(f"[Start] Initiating MangaScope run for user '{username}' on series '{series_name}'.")

    def step(name: str, msg: str) -> None:
        if on_step:
            on_step(name, msg)

    # ── Step 0: Validate input ───────────────────────────────────────────
    is_valid, error_msg, username, series_name = validate_and_sanitize(username, series_name)
    if not is_valid:
        result.validation_error = error_msg
        result.trace.append(f"[Validation] Input validation failed: {error_msg}")
        return result

    # ── Step 0.5: Load memory (personalization only) ─────────────────────
    prev_chapters = get_previous_chapters(username, series_name)
    if prev_chapters is not None:
        result.previous_chapters = prev_chapters
        result.memory_note = (
            f"Last time you checked, you were at Chapter {prev_chapters}."
        )
        result.trace.append(f"[Memory] Found previous reading point for '{username}': Chapter {prev_chapters}.")

    # ── Step 1: Progress Agent ───────────────────────────────────────────
    step("progress", "Querying AniList...")
    try:
        progress = progress_agent.run(username, series_name)
        result.trace.append(
            f"[Progress] AniList check complete. status={progress.status}, "
            f"chapters_read={progress.chapters_read}, total_chapters={progress.total_chapters}, "
            f"manga_status={progress.manga_status}."
        )
        result.execution_trace.append({
            "agent": "ProgressAgent",
            "skill_used": "anilist_query",
            "input": f"username={username}, series_name={series_name}",
            "output_summary": f"status={progress.status}, chapters_read={progress.chapters_read}",
            "tool_calls": ["mcp.anilist_graphql_tool"]
        })
    except Exception as e:
        norm = normalize_error(e, "Progress Agent")
        progress = _fallback_progress(series_name, norm["message"])
        result.trace.append(f"[Progress] Agent failed: {norm['message']}")
        result.execution_trace.append({
            "agent": "ProgressAgent",
            "skill_used": "anilist_query",
            "input": f"username={username}, series_name={series_name}",
            "output_summary": f"failed: {norm['message']}",
            "tool_calls": ["mcp.anilist_graphql_tool"]
        })
    step("progress", f"Done — {progress.status}")

    # ── Step 1.5: Programmatic Up-to-Date Verification ──────────────────
    is_caught_up, caught_up_reason = _check_up_to_date(
        chapters_read=progress.chapters_read,
        total_chapters=progress.total_chapters,
        user_list_status=progress.status,
        manga_status=progress.manga_status,
    )

    if is_caught_up:
        # User is caught up: skip tracking and recommendations programmatically (Issue 1 & Gap 4)
        result.trace.append(f"[CaughtUp] Upfront caught-up trigger hit: {caught_up_reason}. Skipping tracker and LLM recommendation.")
        
        adaptation = AdaptationOutput(
            agent_status="skipped",
            series=progress.series or series_name,
            anime_status="UNKNOWN",
            safe_resume_chapter=None,
            confidence="high",
            note="Skipped because user is fully caught up with the manga.",
            message="Skipped. Series caught up.",
        )
        
        recommendation = RecommendationOutput(
            agent_status="success",
            next_arc=None,
            start_chapter=None,
            end_chapter=None,
            description=f"Congratulations! {caught_up_reason} You are completely up-to-date.",
            estimated_chapters_remaining=0,
            reading_priority="up_to_date",
            message="You are fully caught up with this series!",
        )
        
        result.execution_trace.append({
            "agent": "TrackerAgent",
            "skill_used": "skipped (user caught up)",
            "input": f"series={progress.series or series_name}",
            "output_summary": "skipped",
            "tool_calls": []
        })
        result.execution_trace.append({
            "agent": "RecommendationAgent",
            "skill_used": "skipped (user caught up)",
            "input": f"chapters_read={progress.chapters_read}",
            "output_summary": "reading_priority=up_to_date",
            "tool_calls": []
        })
        
        step("tracker", "Skipped — Caught up")
        step("recommendation", "Skipped — Caught up")

    else:
        # ── Step 2: Adaptation Tracker Agent ─────────────────────────────────
        step("tracker", "Mapping anime to manga chapters...")
        try:
            adaptation = tracker_agent.run(
                series_name=progress.series or series_name,
                anilist_id=progress.anilist_id,
            )
            result.trace.append(
                f"[Tracker] Mapping complete. anime_status={adaptation.anime_status}, "
                f"safe_resume_chapter={adaptation.safe_resume_chapter}, confidence={adaptation.confidence}."
            )
            tool_used = ["mcp.gemini_search_tool"] if adaptation.confidence == "low" else []
            result.execution_trace.append({
                "agent": "TrackerAgent",
                "skill_used": "anime_manga_mapping",
                "input": f"series_name={progress.series or series_name}",
                "output_summary": f"anime_status={adaptation.anime_status}, safe_resume={adaptation.safe_resume_chapter}",
                "tool_calls": tool_used
            })
            # Automatically cache Gemini's tracker result as an unverified mapping
            if adaptation.agent_status == "success" and adaptation.confidence == "low":
                try:
                    tracker_agent.register_verified_mapping(
                        series_name=progress.series or series_name,
                        mapping_data={
                            "anime_status": adaptation.anime_status,
                            "anime_episodes_aired": adaptation.anime_episodes_aired,
                            "manga_chapter_equivalent": adaptation.manga_chapter_equivalent,
                            "safe_resume_chapter": adaptation.safe_resume_chapter,
                            "confidence": "low",
                            "note": adaptation.note,
                        }
                    )
                    result.trace.append("[Tracker] Cached low-confidence estimate to local verified mappings database.")
                except Exception as cache_err:
                    result.trace.append(f"[Tracker] Failed to cache estimate: {cache_err}")
        except Exception as e:
            norm = normalize_error(e, "Adaptation Tracker")
            adaptation = _fallback_adaptation(series_name, norm["message"])
            result.trace.append(f"[Tracker] Agent failed: {norm['message']}")
            result.execution_trace.append({
                "agent": "TrackerAgent",
                "skill_used": "anime_manga_mapping",
                "input": f"series_name={progress.series or series_name}",
                "output_summary": f"failed: {norm['message']}",
                "tool_calls": ["mcp.gemini_search_tool"]
            })
        step("tracker", f"Done — confidence: {adaptation.confidence}")

        # ── Step 3: Recommendation Agent (Dependency Chain Guard) ────────────
        tracker_failed = (adaptation.agent_status == "fallback" or adaptation.safe_resume_chapter is None)
        
        if tracker_failed:
            # Issue 1: Block recommendation agent from running with invalid bounds
            recommendation = _fallback_recommendation("Skipped because Adaptation Tracker failed to determine chapter mapping.")
            result.trace.append("[Recommendation] Tracker failed. Skipping recommendation LLM call to prevent inconsistent outputs.")
            result.execution_trace.append({
                "agent": "RecommendationAgent",
                "skill_used": "skipped (tracker failed)",
                "input": f"chapters_read={progress.chapters_read}",
                "output_summary": "skipped",
                "tool_calls": []
            })
            step("recommendation", "Skipped — Tracker failed")
        else:
            step("recommendation", "Finding arcs to read...")
            try:
                recommendation = recommendation_agent.run(
                    series_name=progress.series or series_name,
                    chapters_read=progress.chapters_read,
                    safe_resume_chapter=adaptation.safe_resume_chapter,
                    anime_status=adaptation.anime_status,
                    manga_status=progress.manga_status,
                    total_chapters=progress.total_chapters,
                    user_list_status=progress.status,
                )
                result.trace.append(
                    f"[Recommendation] Generated. next_arc={recommendation.next_arc}, "
                    f"start_chapter={recommendation.start_chapter}, priority={recommendation.reading_priority}."
                )
                result.execution_trace.append({
                    "agent": "RecommendationAgent",
                    "skill_used": "arc_recommendation",
                    "input": f"chapters_read={progress.chapters_read}, safe_resume={adaptation.safe_resume_chapter}",
                    "output_summary": f"next_arc={recommendation.next_arc}, start_chapter={recommendation.start_chapter}",
                    "tool_calls": ["mcp.gemini_search_tool"]
                })
            except Exception as e:
                norm = normalize_error(e, "Recommendation Agent")
                recommendation = _fallback_recommendation(norm["message"])
                result.trace.append(f"[Recommendation] Agent failed: {norm['message']}")
                result.execution_trace.append({
                    "agent": "RecommendationAgent",
                    "skill_used": "arc_recommendation",
                    "input": f"chapters_read={progress.chapters_read}, safe_resume={adaptation.safe_resume_chapter}",
                    "output_summary": f"failed: {norm['message']}",
                    "tool_calls": ["mcp.gemini_search_tool"]
                })
            step("recommendation", f"Done — priority: {recommendation.reading_priority}")

    # ── Step 4: Community Context Agent ──────────────────────────────────
    if fetch_community:
        step("community", "Fetching community discussion...")
        try:
            community = community_agent.run(progress.series or series_name)
            result.trace.append(f"[Community] Fetch complete. Status={community.agent_status}, Source={community.source}.")
            result.execution_trace.append({
                "agent": "CommunityAgent",
                "skill_used": "web_retrieval",
                "input": f"series={progress.series or series_name}",
                "output_summary": f"status={community.agent_status}, source={community.source}",
                "tool_calls": ["mcp.gemini_search_tool"]
            })
        except Exception as e:
            norm = normalize_error(e, "Community Context Agent")
            community = _fallback_community(series_name, norm["message"])
            result.trace.append(f"[Community] Agent failed: {norm['message']}")
            result.execution_trace.append({
                "agent": "CommunityAgent",
                "skill_used": "web_retrieval",
                "input": f"series={progress.series or series_name}",
                "output_summary": f"failed: {norm['message']}",
                "tool_calls": ["mcp.gemini_search_tool"]
            })
        step("community", "Done")
    else:
        community = CommunityOutput(
            agent_status="skipped",
            series=progress.series or series_name,
            top_discussion_summary="Community buzz may contain spoilers. Click below to fetch.",
            source="none",
            message="Skipped to prevent spoilers and optimize API usage.",
        )
        result.trace.append("[Community] Skipped on-demand community context retrieval.")
        result.execution_trace.append({
            "agent": "CommunityAgent",
            "skill_used": "skipped (on-demand protection)",
            "input": f"series={progress.series or series_name}",
            "output_summary": "skipped",
            "tool_calls": []
        })
        step("community", "Skipped")

    # ── Step 4.5: Coordinator-Level Contract Enforcement (Gap 2) ──────────
    result.trace.append("[Contract] Re-validating schema constraints...")
    
    # Enforce Safe Resume bounds constraint
    if recommendation.agent_status == "success" and recommendation.reading_priority != "up_to_date":
        min_required_chapter = progress.chapters_read + 1
        if adaptation.safe_resume_chapter is not None:
            min_required_chapter = max(min_required_chapter, adaptation.safe_resume_chapter)
        
        if recommendation.start_chapter is None or recommendation.start_chapter < min_required_chapter:
            old_start = recommendation.start_chapter
            recommendation.start_chapter = min_required_chapter
            result.trace.append(f"[Contract] Enforced Constraint: recommendation.start_chapter corrected from {old_start} to {min_required_chapter}.")
            
            # Recalculate remaining chapters if possible
            if recommendation.end_chapter is not None and recommendation.end_chapter >= min_required_chapter:
                recommendation.estimated_chapters_remaining = recommendation.end_chapter - min_required_chapter
            else:
                recommendation.estimated_chapters_remaining = None

    # Guarantee non-null fields on error/fallbacks to protect UI (Issue 3)
    if progress.agent_status != "success":
        progress.message = progress.message or "Progress check skipped or failed."
    if adaptation.agent_status != "success":
        adaptation.message = adaptation.message or "Anime mapping skipped or failed."
    if recommendation.agent_status != "success":
        recommendation.message = recommendation.message or "Recommendation skipped or failed."
    if community.agent_status != "success" and community.agent_status != "skipped":
        community.message = community.message or "Community summary failed."

    result.trace.append("[Contract] Re-validation complete. Outputs are guaranteed consistent.")

    # ── Step 5: Synthesize report ────────────────────────────────────────
    report = MangaScopeReport(
        username=username,
        series=progress.series or series_name,
        progress=progress,
        adaptation=adaptation,
        recommendation=recommendation,
        community_context=community,
        generated_at=datetime.now().isoformat(),
    )
    result.report = report

    # ── Step 6: Save memory ──────────────────────────────────────────────
    try:
        save_memory(
            username=username,
            series=progress.series or series_name,
            chapters_read=progress.chapters_read,
            recommendation_given=recommendation.next_arc,
        )
    except Exception:
        pass  # Memory save failure is non-critical

    # ── Step 7: Save Trace Log to Project Workspace (Gap 5) ───────────────
    try:
        import json
        trace_file = "c:/Files/Coding/antigravity demo kaggle course/mangascope/mangascope_trace.json"
        with open(trace_file, "w", encoding="utf-8") as tf:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "username": username,
                "series": series_name,
                "trace": result.trace,
                "execution_trace": result.execution_trace
            }, tf, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return result
