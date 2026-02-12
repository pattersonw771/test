import hashlib
import json
import os

CACHE_DIR = "cache"

os.makedirs(CACHE_DIR, exist_ok=True)

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def get_cached_result(text: str):
    key = _hash(text)
    path = os.path.join(CACHE_DIR, key + ".json")

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None

def save_cached_result(text: str, result: dict):
    key = _hash(text)
    path = os.path.join(CACHE_DIR, key + ".json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
