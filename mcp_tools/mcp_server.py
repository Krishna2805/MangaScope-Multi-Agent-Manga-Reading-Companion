# This simulates MCP (Model Context Protocol) style tool abstraction layer

import os
import requests
import dotenv
from google import genai
from google.genai import types

# Load environment variables on startup, forcing override so changes in .env are applied
dotenv.load_dotenv(override=True)

_client = None

def _get_gemini_client() -> genai.Client:
    """Internal provider for Gemini Client."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client

def run_tool(tool_name: str, input_payload: dict) -> dict:
    """
    Unified entry point for Model Context Protocol (MCP) simulation.
    Routes queries to correct tool handler.

    Available Tools:
    - 'anilist_graphql_tool': Query AniList's GraphQL API.
    - 'gemini_search_tool': Run search-grounded text generation with Gemini.
    """
    if tool_name == "anilist_graphql_tool":
        url = "https://graphql.anilist.co"
        query = input_payload.get("query")
        variables = input_payload.get("variables")
        timeout = input_payload.get("timeout", 10)
        
        response = requests.post(
            url,
            json={"query": query, "variables": variables},
            timeout=timeout
        )
        return {
            "status_code": response.status_code,
            "data": response.json() if response.status_code in [200, 404, 500] else {}
        }
        
    elif tool_name == "gemini_search_tool":
        prompt = input_payload.get("prompt")
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        temperature = input_payload.get("temperature", 0.2)
        
        client = _get_gemini_client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=temperature
            )
        )
        
        grounding_meta = None
        if response.candidates and hasattr(response.candidates[0], "grounding_metadata"):
            grounding_meta = response.candidates[0].grounding_metadata
            
        return {
            "text": response.text,
            "grounding_metadata": grounding_meta
        }
        
    else:
        raise ValueError(f"Unknown tool name: {tool_name}")
