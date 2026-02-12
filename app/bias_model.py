import os
import json
from typing import Dict
from groq import Groq
from dotenv import load_dotenv
from app.cache import get_cached_result, save_cached_result
from app.groq_utils import get_available_groq_model

load_dotenv()
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ------------------------
# SAFE JSON PARSER
# ------------------------

def safe_json_parse(text: str) -> dict:
    try:
        return json.loads(text)
    except:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1:
            return json.loads(text[start:end])
        raise ValueError("No JSON found")

# ------------------------
# SOURCE CALIBRATION
# ------------------------

def calibrate_with_source(scores: Dict[str, float], source: str):
    adjustment = 0.15  # strong enough to matter

    if source == "right":
        scores["Right"] += adjustment
        scores["Left"] -= adjustment / 2

    elif source == "left":
        scores["Left"] += adjustment
        scores["Right"] -= adjustment / 2

    elif source == "center":
        scores["Center"] += adjustment

    # Normalize
    total = scores["Left"] + scores["Center"] + scores["Right"]
    return {
        k: round(max(v / total, 0), 3)
        for k, v in scores.items()
    }

# ------------------------
# GROQ CALL
# ------------------------

def groq_call(prompt: str) -> str:
    model_id = get_available_groq_model()

    completion = groq_client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": "You are a JSON-only political bias API."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=512
    )

    return completion.choices[0].message.content.strip()

# ------------------------
# FULL PIPELINE
# ------------------------

def full_bias_analysis(article_text: str, source: str = "unknown") -> Dict:
    # Trim to avoid token issues
    article_text = article_text[:3000]

    cached = get_cached_result(article_text)
    if cached:
        return cached

    prompt = f"""
Return ONLY valid JSON.

Schema:
{{
  "summary": "string",
  "bias_scores": {{
    "Left": float,
    "Center": float,
    "Right": float
  }},
  "top_signal": "string",
  "essay": "string"
}}

Rules:
- bias_scores must sum to 1
- summary = 4–6 sentences
- essay = 5–7 sentences

Article:
{article_text}
"""

    raw = groq_call(prompt)
    result = safe_json_parse(raw)

    # 🔥 APPLY SOURCE CALIBRATION HERE
    result["bias_scores"] = calibrate_with_source(
        result["bias_scores"],
        source
    )

    save_cached_result(article_text, result)
    return result
