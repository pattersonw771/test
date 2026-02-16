import html
import json
import re
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


class ScrapeError(ValueError):
    pass


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = _build_session()


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        raise ScrapeError("Please paste a URL.")

    if not re.match(r"^https?://", candidate, flags=re.IGNORECASE):
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ScrapeError("Please use a valid URL (http/https).")
    return candidate


def _extract_json_ld_text(soup: BeautifulSoup) -> str:
    chunks = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            for key in ("articleBody", "headline", "description", "text"):
                value = node.get(key)
                if isinstance(value, str):
                    chunks.append(value)
    return clean_text(" ".join(chunks))


def _has_article_signals(soup: BeautifulSoup) -> bool:
    if soup.find("article"):
        return True

    og_type = soup.find("meta", attrs={"property": "og:type"})
    if og_type and "article" in og_type.get("content", "").lower():
        return True

    if soup.find("meta", attrs={"property": "article:published_time"}):
        return True

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if re.search(r'"@type"\s*:\s*"(NewsArticle|Article|ReportageNewsArticle)"', raw, flags=re.IGNORECASE):
            return True

    return False


def _extract_embedded_script_text(soup: BeautifulSoup) -> str:
    fragments = []
    patterns = [
        r'"articleBody"\s*:\s*"([^"]{80,})"',
        r'"description"\s*:\s*"([^"]{80,})"',
        r'"headline"\s*:\s*"([^"]{40,})"',
        r'"title"\s*:\s*"([^"]{40,})"',
    ]

    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not raw:
            continue
        for pattern in patterns:
            for match in re.findall(pattern, raw):
                text = (
                    match.replace("\\n", " ")
                    .replace("\\t", " ")
                    .replace('\\"', '"')
                    .replace("\\/", "/")
                    .replace("&quot;", '"')
                )
                fragments.append(clean_text(text))
    return clean_text(" ".join(fragments))


def _extract_msn_detail_text(url: str) -> str:
    match = re.search(r"/ar-([A-Za-z0-9]+)", url)
    if not match:
        return ""

    article_id = match.group(1)
    detail_url = f"https://assets.msn.com/content/view/v2/Detail/en-us/{article_id}"
    try:
        response = SESSION.get(detail_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        raise ScrapeError(f"Could not fetch article data from MSN ({e}).")

    title = clean_text(str(payload.get("title", "")))
    abstract = clean_text(str(payload.get("abstract", "")))
    body_html = payload.get("body", "")
    body_text = ""

    if isinstance(body_html, str) and body_html.strip():
        body_soup = BeautifulSoup(body_html, "html.parser")
        body_text = clean_text(" ".join(p.get_text(" ", strip=True) for p in body_soup.find_all("p")))

    return clean_text(" ".join(part for part in [title, abstract, body_text] if part))


def _is_youtube_domain(domain: str) -> bool:
    return any(host in domain for host in ["youtube.com", "youtu.be"])


def _extract_youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "youtu.be" in host:
        return parsed.path.strip("/").split("/")[0]

    if "youtube.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]

        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
            return parts[1]

    return ""


def _decode_escaped_json_string(raw: str) -> str:
    try:
        return json.loads('"' + raw.replace('"', '\\"') + '"')
    except Exception:
        return raw


def _extract_youtube_content(url: str) -> str:
    video_id = _extract_youtube_video_id(url)
    if not video_id:
        raise ScrapeError("Could not parse YouTube video ID from this URL.")

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    parts = []

    try:
        oembed_url = f"https://www.youtube.com/oembed?url={quote_plus(canonical_url)}&format=json"
        oembed_res = SESSION.get(oembed_url, headers=HEADERS, timeout=20)
        if oembed_res.ok:
            meta = oembed_res.json()
            title = clean_text(str(meta.get("title", "")))
            author = clean_text(str(meta.get("author_name", "")))
            if title:
                parts.append(f"Video title: {title}.")
            if author:
                parts.append(f"Channel: {author}.")
    except Exception:
        pass

    try:
        watch_res = SESSION.get(canonical_url, headers=HEADERS, timeout=20)
        watch_res.raise_for_status()
        html_text = watch_res.text

        short_desc_match = re.search(r'"shortDescription":"(.*?)"', html_text, flags=re.DOTALL)
        if short_desc_match:
            short_desc = _decode_escaped_json_string(short_desc_match.group(1))
            short_desc = clean_text(short_desc)
            if short_desc:
                parts.append(f"Description: {short_desc}")

        captions_match = re.search(r'"captionTracks":(\[.*?\])', html_text, flags=re.DOTALL)
        if captions_match:
            caption_tracks = json.loads(captions_match.group(1))
            if caption_tracks and isinstance(caption_tracks, list):
                base_url = caption_tracks[0].get("baseUrl", "")
                if base_url:
                    captions_res = SESSION.get(base_url, headers=HEADERS, timeout=20)
                    if captions_res.ok:
                        captions_soup = BeautifulSoup(captions_res.text, "xml")
                        lines = [clean_text(html.unescape(node.get_text(" "))) for node in captions_soup.find_all("text")]
                        transcript = clean_text(" ".join(line for line in lines if line))
                        if transcript:
                            parts.append(f"Transcript excerpt: {transcript[:6000]}")
    except Exception:
        pass

    joined = clean_text(" ".join(parts))
    if len(joined) < 100:
        raise ScrapeError(
            "Could not extract enough text from this YouTube video. If captions are disabled, try a related article URL."
        )
    return joined


def _is_twitter_domain(domain: str) -> bool:
    return any(host in domain for host in ["twitter.com", "x.com"])


def _extract_twitter_content(url: str) -> str:
    try:
        oembed = SESSION.get(
            f"https://publish.twitter.com/oembed?omit_script=true&url={quote_plus(url)}",
            headers=HEADERS,
            timeout=20,
        )
        oembed.raise_for_status()
        payload = oembed.json()
    except requests.RequestException as e:
        raise ScrapeError(f"Could not fetch tweet details ({e}).")

    html_block = payload.get("html", "")
    text = clean_text(BeautifulSoup(html_block, "html.parser").get_text(" ", strip=True))

    author = clean_text(str(payload.get("author_name", "")))
    provider = clean_text(str(payload.get("provider_name", "")))

    combined = clean_text(" ".join(part for part in [f"Source: {provider}." if provider else "", f"Author: {author}." if author else "", text] if part))

    if len(combined) < 60:
        raise ScrapeError("Could not extract enough text from this social post.")
    return combined


def _looks_like_article_path(path: str) -> bool:
    lowered = (path or "").lower()
    if "/ar-" in lowered:
        return True
    if any(marker in lowered for marker in ["/article/", "/story/"]):
        return True
    if re.search(r"/\d{4}/\d{2}/\d{2}/", lowered):
        return True
    segments = [seg for seg in lowered.split("/") if seg]
    if not segments:
        return False
    last = segments[-1]
    return bool(re.search(r"[a-z0-9-]{20,}", last) and "-" in last)


def _is_home_or_section_path(path: str) -> bool:
    segments = [seg for seg in (path or "").lower().split("/") if seg]
    if not segments:
        return True

    section_names = {
        "news",
        "world",
        "us",
        "politics",
        "business",
        "sport",
        "sports",
        "entertainment",
        "video",
        "live",
    }

    if len(segments) == 1 and segments[0] in section_names:
        return True
    if len(segments) == 1 and re.fullmatch(r"[a-z-]{2,12}", segments[0]):
        return True
    return False


def extract_article_text(url: str) -> str:
    return extract_content(url)["text"]


def extract_content(url: str) -> dict:
    normalized_url = _normalize_url(url)
    parsed = urlparse(normalized_url)
    domain = parsed.netloc.lower()

    if _is_youtube_domain(domain):
        return {
            "text": _extract_youtube_content(normalized_url),
            "normalized_url": normalized_url,
            "content_kind": "youtube-video",
        }

    if _is_twitter_domain(domain):
        return {
            "text": _extract_twitter_content(normalized_url),
            "normalized_url": normalized_url,
            "content_kind": "social-post",
        }

    if "msn.com" in domain:
        msn_text = _extract_msn_detail_text(normalized_url)
        if len(msn_text) >= 120:
            return {
                "text": msn_text,
                "normalized_url": normalized_url,
                "content_kind": "msn-detail",
            }

    try:
        response = SESSION.get(normalized_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        raise ScrapeError(
            f"Website blocked access (HTTP {status}). Try a direct publisher link or a different source."
        )
    except requests.RequestException as e:
        raise ScrapeError(f"Could not load this page ({e}).")

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []
    likely_article = _looks_like_article_path(parsed.path) or (
        _has_article_signals(soup) and not _is_home_or_section_path(parsed.path)
    )

    article = soup.find("article")
    if article:
        candidates.append(clean_text(" ".join(p.get_text(" ", strip=True) for p in article.find_all("p"))))

    main = soup.find("main")
    if main:
        candidates.append(clean_text(" ".join(p.get_text(" ", strip=True) for p in main.find_all("p"))))

    for block in soup.select("[class*='article'], [class*='content'], [class*='story'], [id*='article']")[:10]:
        candidates.append(clean_text(" ".join(p.get_text(" ", strip=True) for p in block.find_all("p"))))

    fallback_paragraphs = clean_text(" ".join(p.get_text(" ", strip=True) for p in soup.find_all("p")))
    if fallback_paragraphs:
        candidates.append(fallback_paragraphs)

    json_ld_text = _extract_json_ld_text(soup)
    if json_ld_text:
        candidates.append(json_ld_text)

    embedded_text = _extract_embedded_script_text(soup)
    if embedded_text:
        candidates.append(embedded_text)

    title = clean_text(soup.title.string if soup.title and soup.title.string else "")
    description_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    description = clean_text(description_tag.get("content", "")) if description_tag else ""

    combined_meta = clean_text(" ".join(part for part in [title, description] if part))
    if combined_meta:
        candidates.append(combined_meta)

    best = max((c for c in candidates if c), key=len, default="")
    sentence_count = len(re.findall(r"[.!?]", best))
    word_count = len(best.split())
    unique_words = len(set(w.lower() for w in re.findall(r"[A-Za-z]+", best)))

    if likely_article and len(best) >= 350 and word_count >= 60 and sentence_count >= 3 and unique_words >= 40:
        return {
            "text": best,
            "normalized_url": normalized_url,
            "content_kind": "web-article",
        }

    if likely_article and len(best) >= 180 and word_count >= 40:
        return {
            "text": best,
            "normalized_url": normalized_url,
            "content_kind": "web-article-light",
        }

    if not likely_article:
        raise ScrapeError(
            "This link does not look like a direct article page. Open the article itself and paste that URL."
        )

    raise ScrapeError(
        "Could not extract enough article text from this page. Try the publisher's direct article link."
    )


def detect_source(url: str) -> str:
    candidate = (url or "").strip()
    if candidate and not re.match(r"^https?://", candidate, flags=re.IGNORECASE):
        candidate = "https://" + candidate
    domain = urlparse(candidate).netloc.lower()

    RIGHT = [
        "foxnews",
        "dailywire",
        "breitbart",
        "newsmax",
        "washingtontimes",
        "theblaze",
    ]

    LEFT = [
        "msnbc",
        "huffpost",
        "vox",
        "motherjones",
        "slate",
        "salon",
    ]

    CENTER = [
        "reuters",
        "apnews",
        "bbc",
        "npr",
        "axios",
        "usatoday",
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
