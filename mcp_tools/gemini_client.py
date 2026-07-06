import os
import dotenv
from google import genai
from google.genai import types

# Load environment variables on module load
dotenv.load_dotenv()

_client = None

def get_client() -> genai.Client:
    """Unified provider for the GenAI Client using GEMINI_API_KEY from environment."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client

def generate_with_search(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Unified wrapper to perform search-grounded text generation with Gemini."""
    client = get_client()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )
    return response.text
