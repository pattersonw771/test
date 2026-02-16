import json
import os
import time
from typing import Dict

from dotenv import load_dotenv
from groq import Groq

from app.cache import get_cached_result, save_cached_result
from app.groq_utils import get_available_groq_model

load_dotenv()
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

DEFAULT_SCORES = {"Left": 0.333, "Center": 0.334, "Right": 0.333}


def safe_json_parse(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1:
            return json.loads(text[start:end])
        raise ValueError("No JSON found")


def _normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
    clamped = {k: max(float(v), 0.0) for k, v in scores.items()}
    total = sum(clamped.values())
    if total <= 0:
        return dict(DEFAULT_SCORES)
    return {k: round(v / total, 3) for k, v in clamped.items()}


def _coerce_bias_scores(raw_scores) -> Dict[str, float]:
    if not isinstance(raw_scores, dict):
        return dict(DEFAULT_SCORES)

    lookup = {str(k).strip().lower(): v for k, v in raw_scores.items()}

    def pick(*keys, default=0.0):
        for key in keys:
            if key in lookup:
                try:
                    return float(lookup[key])
                except (TypeError, ValueError):
                    return default
        return default

    parsed = {
        "Left": pick("left", "liberal", "progressive"),
        "Center": pick("center", "centrist", "neutral"),
        "Right": pick("right", "conservative"),
    }
    return _normalize_scores(parsed)


def calibrate_with_source(scores: Dict[str, float], source: str):
    adjusted = dict(scores)
    adjustment = 0.15

    if source == "right":
        adjusted["Right"] += adjustment
        adjusted["Left"] -= adjustment / 2
    elif source == "left":
        adjusted["Left"] += adjustment
        adjusted["Right"] -= adjustment / 2
    elif source == "center":
        adjusted["Center"] += adjustment

    return _normalize_scores(adjusted)


def groq_call(prompt: str) -> str:
    last_error = None
    for attempt in range(3):
        try:
            model_id = get_available_groq_model()
            completion = groq_client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are a JSON-only political bias API."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=900,
            )
            content = (completion.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("Empty model response")
            return content
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(0.7 * (attempt + 1))
                continue
            break

    raise RuntimeError(f"Groq call failed after retries: {last_error}")


def full_bias_analysis(article_text: str, source: str = "unknown") -> Dict:
    article_text = article_text[:6500]

    cache_key = f"{source}|{article_text}"
    cached = get_cached_result(cache_key)
    if cached:
        if "global_perspective" not in cached:
            cached["global_perspective"] = "Global perspective unavailable for this cached result."
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
  "essay": "string",
  "global_perspective": "string"
}}

Rules:
- bias_scores must sum to 1
- summary = 4-6 sentences
- essay = 5-7 sentences
- global_perspective = 4-6 sentences, describing how different regions and political cultures might interpret this story.
- Keep global_perspective balanced; avoid claiming a single world consensus.

Article:
{article_text}
"""

    raw = groq_call(prompt)

    try:
        result = safe_json_parse(raw)
    except Exception:
        repair_prompt = (
            "Convert this to valid JSON using the exact schema and no markdown:\n\n" + raw
        )
        result = safe_json_parse(groq_call(repair_prompt))

    summary = str(result.get("summary", "No summary available.")).strip()
    essay = str(result.get("essay", "No detailed reasoning available.")).strip()
    top_signal = str(result.get("top_signal", "No dominant signal detected.")).strip()
    global_perspective = str(
        result.get(
            "global_perspective",
            "Global perspective was not generated for this article.",
        )
    ).strip()

    scores = _coerce_bias_scores(result.get("bias_scores", {}))
    scores = calibrate_with_source(scores, source)

    normalized_result = {
        "summary": summary,
        "essay": essay,
        "top_signal": top_signal,
        "global_perspective": global_perspective,
        "bias_scores": scores,
    }

    save_cached_result(cache_key, normalized_result)
    return normalized_result
