"""Compare SerpApi discovery engines on identical news topics."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv

from app.core.utils import collect_engine_articles, fetch_article_text
from app.providers.serpapi_news import GOOGLE_NEWS, NEWS_TAB, NewsSearchError, discover_news


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "news_search.json"


def fixture_search(responses):
    def handler(request):
        params = request.url.params
        engine = params["engine"]
        payload = responses[engine]
        return httpx.Response(200, json={"search_metadata": {"status": "Success"}, **payload})

    return httpx.MockTransport(handler)


def fixture_pages(request):
    if request.url.host in {"daily.test", "finance.test", "metro.test"}:
        return httpx.Response(403)
    headline = request.url.path.strip("/")
    html = f"""<html><body><article><h1>Fixture article about {headline}</h1>
    <p>This synthetic article has paragraphs so the evaluation can exercise the same extraction code as a report.
    It records what the reporter learned from the original material and names the people who were interviewed.
    The report describes when the decision was made and how the change is expected to affect the community.</p>
    <p>The story also includes context about a previous decision and the reasons cited at the public meeting.
    Readers can compare what each source contributed. These text fixtures are generated for testing only.</p>
    </article></body></html>"""
    return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})


async def compare_topic(topic, responses, api_key, *, live=False):
    search_transport = None if live else fixture_search(responses)
    article_transport = None if live else httpx.MockTransport(fixture_pages)
    async with (
        httpx.AsyncClient(transport=search_transport) as search_client,
        httpx.AsyncClient(transport=article_transport, max_redirects=3) as article_client,
    ):
        async def discover(query, engine):
            return await discover_news(search_client, api_key, query, engine)

        async def extract(url):
            return await fetch_article_text(article_client, url)

        results = {}
        for engine, label in ((GOOGLE_NEWS, "google_news"), (NEWS_TAB, "news_tab")):
            start = perf_counter()
            try:
                batch = await collect_engine_articles(topic, engine, discover, extract)
                outcome = {
                    "status": "readable" if batch.articles else ("unreadable" if batch.unreadable else "empty"),
                    "candidates": batch.candidates,
                    "duplicate_links": batch.duplicates,
                    "attempted_extractions": batch.attempted,
                    "unreadable": batch.unreadable,
                    "readable": len(batch.articles),
                    "publishers": len({article["source"].casefold() for article in batch.articles}),
                    "articles": [
                        {name: article[name] for name in ("title", "source", "date", "url")}
                        for article in batch.articles
                    ],
                }
            except NewsSearchError as error:
                outcome = {"status": "error", "reason": error.reason}
            outcome["discovery_requests"] = 1
            if live:
                outcome["elapsed_seconds"] = round(perf_counter() - start, 3)
            results[label] = outcome
        return results


async def compare(fixtures, api_key, *, live=False):
    return {
        topic: await compare_topic(topic, responses, api_key, live=live)
        for topic, responses in fixtures.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make two live discovery requests per topic.")
    args = parser.parse_args()
    api_key = "fixture-key"
    if args.live:
        load_dotenv()
        api_key = os.getenv("SERPAPI_API_KEY")
        if not api_key:
            parser.error("Live comparison requires SERPAPI_API_KEY.")
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    results = asyncio.run(compare(fixtures, api_key, live=args.live))
    print(json.dumps({
        "mode": "live endpoint comparison" if args.live else "synthetic response replay",
        "topics": results,
    }, indent=2))
    return int(any(arm["status"] == "error" for pair in results.values() for arm in pair.values()))


if __name__ == "__main__":
    raise SystemExit(main())
