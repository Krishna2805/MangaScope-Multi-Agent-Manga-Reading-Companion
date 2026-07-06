"""
MangaScope — Memory layer.

Persists lightweight user context to memory.json for personalization only.
Memory is NEVER used as a cache — live AniList calls always happen regardless.

What gets stored:
  - username
  - last_run date
  - series_history: series name, chapters_read at that time, recommendation given

What does NOT get stored:
  - Full API responses, chapter mappings, or anything that must stay fresh.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional

from schemas import UserMemory, SeriesMemoryEntry

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory.json")


def load_memory(username: str) -> Optional[UserMemory]:
    """
    Load memory for a specific user from memory.json.
    Returns None if no memory exists or the file is corrupted.
    """
    if not os.path.exists(MEMORY_FILE):
        return None

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # memory.json stores a list of user records
    if isinstance(data, list):
        for entry in data:
            if entry.get("username", "").lower() == username.lower():
                return UserMemory(**entry)
    elif isinstance(data, dict):
        # Single user record (legacy or first run)
        if data.get("username", "").lower() == username.lower():
            return UserMemory(**data)

    return None


def save_memory(
    username: str,
    series: str,
    chapters_read: int,
    recommendation_given: Optional[str] = None,
) -> None:
    """
    Save or update memory for a user+series combination.
    Merges into existing memory.json without overwriting other users/series.
    """
    # Load existing data
    all_users: list[dict] = []
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, list):
                    all_users = raw
                elif isinstance(raw, dict):
                    all_users = [raw]
        except (json.JSONDecodeError, OSError):
            all_users = []

    # Find or create user entry
    user_entry = None
    for entry in all_users:
        if entry.get("username", "").lower() == username.lower():
            user_entry = entry
            break

    if user_entry is None:
        user_entry = {
            "username": username,
            "last_run": datetime.now().strftime("%Y-%m-%d"),
            "series_history": [],
        }
        all_users.append(user_entry)

    # Update last_run
    user_entry["last_run"] = datetime.now().strftime("%Y-%m-%d")

def _clean_title(title: str) -> str:
    """Normalize a series name for comparison by removing non-alphanumeric characters."""
    return re.sub(r'[^a-z0-9]', '', title.lower())


    # Find or create series entry within user
    series_found = False
    for s in user_entry.get("series_history", []):
        if _clean_title(s.get("series", "")) == _clean_title(series):
            # Update the stored name to match the latest casing/branding (like [Oshi no Ko])
            s["series"] = series
            s["chapters_read_at_last_run"] = chapters_read
            if recommendation_given is not None:
                s["recommendation_given"] = recommendation_given
            series_found = True
            break

    if not series_found:
        user_entry.setdefault("series_history", []).append({
            "series": series,
            "chapters_read_at_last_run": chapters_read,
            "recommendation_given": recommendation_given,
        })

    # Write back
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(all_users, f, indent=2, ensure_ascii=False)


def get_previous_chapters(username: str, series: str) -> Optional[int]:
    """
    Quick helper: returns chapters_read from the last run for a series,
    or None if no memory exists.
    """
    mem = load_memory(username)
    if mem is None:
        return None
    for s in mem.series_history:
        if _clean_title(s.series) == _clean_title(series):
            return s.chapters_read_at_last_run
    return None
