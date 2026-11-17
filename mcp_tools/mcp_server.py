# Model Context Protocol (MCP) tool abstraction layer with Groq + Live Web Search

import os
import re
import logging
import requests
import dotenv
from groq import Groq
from duckduckgo_search import DDGS

# Load environment variables on startup, forcing override so changes in .env are applied
dotenv.load_dotenv(override=True)
logger = logging.getLogger(__name__)

_groq_client = None


def _get_groq_client() -> Groq:
    """Internal provider for Groq Client."""
    global _groq_client
    if _groq_client is None:
        api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def _extract_search_keywords(prompt: str) -> str:
    """Extract precise query keywords from agent instructions."""
    # Look for series name in quotes, e.g. for 'One Piece'
    series_match = re.search(r"for\s+['\"]([^'\"]+)['\"]", prompt, re.IGNORECASE)
    if series_match:
        series = series_match.group(1)
        if "anime" in prompt.lower() or "adaptation" in prompt.lower() or "episode" in prompt.lower():
            return f"{series} anime latest episode crunchyroll"
        elif "arc" in prompt.lower() or "chapter" in prompt.lower():
            return f"{series} manga arcs chapters wiki"
        elif "discussion" in prompt.lower() or "community" in prompt.lower():
            return f"{series} manga reddit discussion"
        return f"{series} manga latest chapters"
    
    # Fallback to cleaning prompt words
    words = [w for w in prompt.split() if len(w) > 3 and not w.lower().startswith(("you", "current", "ensure", "specifically", "please", "return"))]
    return " ".join(words[:6])


def _live_web_search(query: str, max_results: int = 4) -> list[dict]:
    """Execute live web search for real-time anime/manga grounding."""
    try:
        ddgs = DDGS(timeout=8)
        results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception as exc:
        logger.warning(f"Live web search failed for query '{query}': {exc}")
        return []


def run_tool(tool_name: str, input_payload: dict) -> dict:
    """
    Unified entry point for Model Context Protocol (MCP) simulation.
    Routes queries to correct tool handler.

    Available Tools:
    - 'anilist_graphql_tool': Query AniList's GraphQL API.
    - 'gemini_search_tool' / 'groq_search_tool': Run search-grounded text generation with Groq LLM.
    """
    if tool_name == "anilist_graphql_tool":
        url = "https://graphql.anilist.co"
        query = input_payload.get("query")
        variables = input_payload.get("variables")
        timeout = input_payload.get("timeout", 10)

        try:
            response = requests.post(
                url,
                json={"query": query, "variables": variables},
                timeout=timeout
            )
            data = {}
            if response.status_code in [200, 404, 500]:
                try:
                    data = response.json()
                except ValueError:
                    data = {"error": f"Invalid JSON response: {response.text[:200]}"}
            return {
                "status_code": response.status_code,
                "data": data
            }
        except Exception as exc:
            return {
                "status_code": 500,
                "data": {"error": str(exc)}
            }

    elif tool_name in ["gemini_search_tool", "groq_search_tool", "llm_search_tool"]:
        prompt = input_payload.get("prompt", "")
        model = os.environ.get("GROQ_MODEL", os.environ.get("GEMINI_MODEL", "openai/gpt-oss-120b"))
        temperature = input_payload.get("temperature", 0.2)

        # Extract focused search keywords from prompt
        search_query = _extract_search_keywords(prompt)
        # Perform live web search for fresh grounding
        search_results = _live_web_search(search_query, max_results=4) if search_query else []

        search_context = ""
        if search_results:
            snippets = [
                f"- Title: {r.get('title')}\n  Snippet: {r.get('body')}\n  URL: {r.get('href')}"
                for r in search_results
            ]
            search_context = "\n\n[Live Web Search Context]:\n" + "\n".join(snippets)

        system_instruction = (
            "You are an expert manga reading companion and adaptation tracker. "
            "Use the provided live web search context along with your reasoning to output accurate, up-to-date answers. "
            "Strictly follow the user's requested output format. When JSON is requested in a ```json code block, "
            "output strictly valid JSON inside ```json and ``` code fences."
        )

        user_content = prompt + search_context

        client = _get_groq_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ],
            temperature=temperature,
            max_tokens=1500
        )

        response_text = response.choices[0].message.content or ""
        grounding_meta = {
            "search_queries": [search_query] if search_query else [],
            "sources": [r.get("href") for r in search_results if r.get("href")]
        }

        return {
            "text": response_text,
            "grounding_metadata": grounding_meta
        }

    else:
        raise ValueError(f"Unknown tool name: {tool_name}")
