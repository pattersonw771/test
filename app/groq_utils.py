import os
import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/models"
CACHED_MODEL_ID = None


def get_available_groq_model(force_refresh: bool = False):
    """
    Fetch available Groq models and return a chat-capable model.
    Caches the result to avoid a network model-list call on every request.
    """
    global CACHED_MODEL_ID

    env_model = os.getenv("GROQ_MODEL")
    if env_model and not force_refresh:
        return env_model

    if CACHED_MODEL_ID and not force_refresh:
        return CACHED_MODEL_ID

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(GROQ_API_URL, headers=headers, timeout=10)
    response.raise_for_status()

    models = response.json().get("data", [])
    if not models:
        raise RuntimeError("No Groq models available")

    preferred = [
        "llama-3.3",
        "llama-3.1",
        "mixtral",
        "gemma",
    ]

    model_ids = [m.get("id", "") for m in models]
    for keyword in preferred:
        for model_id in model_ids:
            if keyword in model_id.lower():
                CACHED_MODEL_ID = model_id
                return model_id

    CACHED_MODEL_ID = model_ids[0]
    return CACHED_MODEL_ID
