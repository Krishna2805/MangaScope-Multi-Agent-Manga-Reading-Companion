"""
MangaScope — Global Orchestration-Level Error Normalizer.

Translates diverse exceptions (network, API, parsing, etc.) from various agents
into standard, user-friendly error messages and clean fallback states.
"""

from __future__ import annotations

import logging
import requests

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MangaScope")


class NormalizedError(Exception):
    """A standardized error carrying user-friendly information."""
    def __init__(self, message: str, raw_error: Exception, is_transient: bool = False):
        super().__init__(message)
        self.message = message
        self.raw_error = raw_error
        self.is_transient = is_transient


def normalize_error(error: Exception, agent_name: str) -> dict:
    """
    Normalize an exception into a standard dictionary format for agent fallbacks.

    Args:
        error: The caught exception.
        agent_name: Name of the agent that encountered the error.

    Returns:
        dict: Containing standard keys:
            - "agent_status": "fallback"
            - "message": A clean, user-friendly error message
            - "raw_error_type": Type name of the original exception
    """
    error_type = type(error).__name__
    logger.error(f"Error in {agent_name}: {error_type} - {error}", exc_info=True)

    # 1. HTTP/Network Errors
    if isinstance(error, requests.exceptions.Timeout):
        return {
            "agent_status": "fallback",
            "message": f"Connection timed out while fetching data for {agent_name}. Please try again later.",
            "raw_error_type": error_type,
        }
    elif isinstance(error, requests.exceptions.ConnectionError):
        return {
            "agent_status": "fallback",
            "message": f"Could not connect to the server for {agent_name}. Check your internet connection.",
            "raw_error_type": error_type,
        }
    elif isinstance(error, requests.exceptions.HTTPError):
        status_code = error.response.status_code if error.response else "unknown"
        if status_code == 404:
            return {
                "agent_status": "fallback",
                "message": f"Requested resource for {agent_name} was not found (404).",
                "raw_error_type": error_type,
            }
        elif status_code == 429:
            return {
                "agent_status": "fallback",
                "message": f"Rate limit exceeded (429) for {agent_name}. Please wait a moment before retrying.",
                "raw_error_type": error_type,
            }
        return {
            "agent_status": "fallback",
            "message": f"External service error (HTTP {status_code}) encountered by {agent_name}.",
            "raw_error_type": error_type,
        }

    # 2. Google GenAI / Gemini API Errors
    if "genai" in error_type.lower() or "google" in error_type.lower() or "apierror" in error_type.lower():
        err_msg = str(error).lower()
        if "api_key" in err_msg or "apikey" in err_msg or "credential" in err_msg:
            return {
                "agent_status": "fallback",
                "message": "Invalid Gemini API key. Please check your configuration.",
                "raw_error_type": error_type,
            }
        elif "quota" in err_msg or "limit" in err_msg or "resource_exhausted" in err_msg:
            return {
                "agent_status": "fallback",
                "message": "Gemini API quota exceeded or rate limited. Please try again in a minute.",
                "raw_error_type": error_type,
            }
        return {
            "agent_status": "fallback",
            "message": "Gemini API encountered an error processing the request.",
            "raw_error_type": error_type,
        }

    # 3. JSON Parsing / Schema Validation Errors
    if isinstance(error, (ValueError, KeyError, TypeError)):
        return {
            "agent_status": "fallback",
            "message": f"Failed to parse or validate data structure in {agent_name}.",
            "raw_error_type": error_type,
        }

    # 4. Fallback for all other exceptions
    return {
        "agent_status": "fallback",
        "message": f"An unexpected error occurred in {agent_name}.",
        "raw_error_type": error_type,
    }
