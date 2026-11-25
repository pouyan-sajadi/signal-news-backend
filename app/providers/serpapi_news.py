import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx


GOOGLE_NEWS = "google_news"
NEWS_TAB = "google"
SERPAPI_URL = "https://serpapi.com/search"
DISCOVERY_TIMEOUT_SECONDS = 8


class NewsSearchError(RuntimeError):
    """A search failure safe to log without a query, URL, or provider response."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class NewsCandidate:
    title: str
    source: str
    date: str
    url: str
    url_key: str


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _url_key(url: str) -> str:
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
            return ""
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")
        ]
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", urlencode(query), ""))
    except ValueError:
        return ""


def _article_rows(rows):
    nested = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        yield row
        highlight = row.get("highlight")
        if isinstance(highlight, dict):
            yield highlight
        stories = row.get("stories")
        if isinstance(stories, list):
            nested.extend(story for story in stories if isinstance(story, dict))
    yield from nested


def _parse_candidates(payload: dict) -> list[NewsCandidate]:
    if not isinstance(payload, dict):
        raise NewsSearchError("invalid_response")
    metadata = payload.get("search_metadata")
    status = metadata.get("status") if isinstance(metadata, dict) else None
    if status != "Success":
        raise NewsSearchError("provider_error" if status == "Error" else "invalid_response")

    # SerpApi may set a top-level error string on a successful empty search.
    rows = payload.get("news_results", [])
    if not isinstance(rows, list):
        raise NewsSearchError("invalid_response")
    candidates = []
    for row in _article_rows(rows):
        title = _text(row.get("title"))
        url = _text(row.get("link"))
        key = _url_key(url)
        if not title or not key or row.get("video") is True:
            continue
        source = row.get("source")
        if isinstance(source, dict):
            source = _text(source.get("name")) or _text(source.get("title"))
        candidates.append(NewsCandidate(
            title=title,
            source=_text(source) or urlsplit(url).hostname,
            date=_text(row.get("iso_date")) or _text(row.get("date")),
            url=url,
            url_key=key,
        ))
    return candidates


async def discover_news(client: httpx.AsyncClient, api_key: str, topic: str, engine: str) -> list[NewsCandidate]:
    if not api_key:
        raise NewsSearchError("missing_credentials")
    params = {"api_key": api_key, "engine": engine, "hl": "en", "gl": "us"}
    if engine == GOOGLE_NEWS:
        params["q"] = f"{topic} when:30d"
    elif engine == NEWS_TAB:
        params.update(q=topic, tbm="nws", tbs="qdr:m")
    else:
        raise ValueError(f"Unsupported news engine: {engine}")

    try:
        async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
            response = await client.get(SERPAPI_URL, params=params, timeout=DISCOVERY_TIMEOUT_SECONDS)
    except (TimeoutError, httpx.TimeoutException):
        raise NewsSearchError("timeout") from None
    except httpx.RequestError:
        raise NewsSearchError("provider_error") from None

    if not response.is_success:
        reason = {401: "credentials_rejected", 403: "credentials_rejected", 429: "rate_or_quota_limit"}
        raise NewsSearchError(reason.get(response.status_code, "provider_error"))
    try:
        payload = response.json()
    except ValueError:
        raise NewsSearchError("invalid_response") from None
    return _parse_candidates(payload)
