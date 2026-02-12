import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

def clean_text(text):
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def extract_article_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Try <article>
    article = soup.find("article")
    if article:
        text = " ".join(p.get_text() for p in article.find_all("p"))
        text = clean_text(text)
        if len(text) > 300:
            return text

    # Try <main>
    main = soup.find("main")
    if main:
        text = " ".join(p.get_text() for p in main.find_all("p"))
        text = clean_text(text)
        if len(text) > 300:
            return text

    # Fallback: all paragraphs
    paragraphs = soup.find_all("p")
    text = clean_text(" ".join(p.get_text() for p in paragraphs))

    if len(text) < 200:
        raise ValueError("Could not extract meaningful article text")

    return text


# -------- SOURCE DETECTION --------

def detect_source(url: str) -> str:
    domain = urlparse(url).netloc.lower()

    RIGHT = [
        "foxnews", "dailywire", "breitbart",
        "newsmax", "washingtontimes", "theblaze"
    ]

    LEFT = [
        "msnbc", "huffpost", "vox",
        "motherjones", "slate", "salon"
    ]

    CENTER = [
        "reuters", "apnews", "bbc",
        "npr", "axios", "usatoday"
    ]

    for s in RIGHT:
        if s in domain:
            return "right"

    for s in LEFT:
        if s in domain:
            return "left"

    for s in CENTER:
        if s in domain:
            return "center"

    return "unknown"
