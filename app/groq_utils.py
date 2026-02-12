import os
import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/models"

def get_available_groq_model():
    """
    Fetches available Groq models and returns a chat-capable one.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    response = requests.get(GROQ_API_URL, headers=headers, timeout=10)
    response.raise_for_status()

    models = response.json().get("data", [])

    # Prefer large chat models, fallback to anything chat-capable
    preferred_keywords = ["llama", "mixtral", "chat"]

    for model in models:
        model_id = model.get("id", "")
        if any(k in model_id.lower() for k in preferred_keywords):
            return model_id

    if models:
        return models[0]["id"]

    raise RuntimeError("No Groq models available")
