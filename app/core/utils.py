import asyncio
import uuid
from dataclasses import dataclass

import httpx
import trafilatura

from app.core.logger import logger
from app.providers.serpapi_news import GOOGLE_NEWS, NEWS_TAB, NewsSearchError, discover_news


MIN_READABLE_ARTICLES = 3
MAX_ARTICLES = 15
MAX_CONCURRENT_EXTRACTIONS = 6
ARTICLE_TIMEOUT_SECONDS = 6
SEARCH_TIMEOUT_SECONDS = 55
MAX_ARTICLE_BYTES = 2_000_000


@dataclass(frozen=True)
class SearchBatch:
    articles: list[dict]
    candidates: int
    duplicates: int
    attempted: int

    @property
    def unreadable(self) -> int:
        return self.attempted - len(self.articles)


async def fetch_article_text(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a bounded response and extract its article text."""
    try:
        async with asyncio.timeout(ARTICLE_TIMEOUT_SECONDS):
            async with client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > MAX_ARTICLE_BYTES:
                        return ""
            text = await asyncio.to_thread(
                trafilatura.extract, bytes(data), include_comments=False, include_tables=False,
            )
    except (TimeoutError, httpx.HTTPError, httpx.InvalidURL, ValueError):
        return ""
    return " ".join(text.split()) if text else ""


async def collect_engine_articles(topic, engine, discover, extract, *, limit=MAX_ARTICLES, seen=None) -> SearchBatch:
    """Run one discovery request and the common extraction path in discovery order."""
    candidates = await discover(topic, engine)
    seen = seen if seen is not None else set()
    unique = {}
    for candidate in candidates:
        if candidate.url_key not in seen:
            unique.setdefault(candidate.url_key, candidate)
    selected = list(unique.values())[:limit]
    seen.update(candidate.url_key for candidate in selected)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)

    async def extract_one(candidate):
        async with semaphore:
            content = await extract(candidate.url)
        if not content:
            return None
        return {
            "id": str(uuid.uuid4()),
            "title": candidate.title,
            "source": candidate.source,
            "date": candidate.date,
            "url": candidate.url,
            "content": content,
        }

    results = await asyncio.gather(*(extract_one(candidate) for candidate in selected))
    batch = SearchBatch(
        articles=[article for article in results if article is not None],
        candidates=len(candidates),
        duplicates=len(candidates) - len(unique),
        attempted=len(selected),
    )
    logger.info(
        "News discovery engine=%s candidates=%d duplicates=%d attempted=%d readable=%d",
        engine, batch.candidates, batch.duplicates, batch.attempted, len(batch.articles),
    )
    return batch


async def retrieve_news(topic, discover, extract, *, limit=MAX_ARTICLES) -> list[dict]:
    """Try the News tab once after a successful but sparse Google News search."""
    seen = set()
    articles = []
    try:
        async with asyncio.timeout(SEARCH_TIMEOUT_SECONDS):
            primary = await collect_engine_articles(topic, GOOGLE_NEWS, discover, extract, limit=limit, seen=seen)
            articles = primary.articles
            if len(articles) >= min(MIN_READABLE_ARTICLES, limit):
                return articles

            fallback = await collect_engine_articles(
                topic, NEWS_TAB, discover, extract, limit=limit - len(articles), seen=seen,
            )
            articles.extend(fallback.articles)
            if not articles and (primary.unreadable or fallback.unreadable):
                raise NewsSearchError("unreadable_articles")
            return articles
    except TimeoutError:
        error = NewsSearchError("timeout")
    except NewsSearchError as failure:
        error = failure

    if articles:
        logger.warning("News tab fallback did not complete: %s", error.reason)
        return articles
    raise error from None


async def search_news(topic: str) -> list[dict]:
    from app.config import SERPAPI_KEY

    async with httpx.AsyncClient() as search_client, httpx.AsyncClient(max_redirects=3) as article_client:
        async def discover(query, engine):
            return await discover_news(search_client, SERPAPI_KEY, query, engine)

        async def extract(url):
            return await fetch_article_text(article_client, url)

        return await retrieve_news(topic, discover, extract)
