import json
import unittest

import httpx

from app.core.utils import fetch_article_text, retrieve_news
from app.providers.serpapi_news import GOOGLE_NEWS, NEWS_TAB, NewsSearchError, discover_news
from evals.news_search import FIXTURE_PATH, compare, fixture_pages


FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
TORONTO, RATES, GRID = FIXTURES
EMPTY = {"error": "Google hasn't returned any results for this query."}


class NewsSearchTests(unittest.IsolatedAsyncioTestCase):
    async def run_retrieval(self, topic, responses, discovery_calls, article_calls, *, limit=15):
        def search_handler(request):
            params = request.url.params
            engine = params["engine"]
            discovery_calls.append((engine, dict(params)))
            payload = responses[engine]
            if isinstance(payload, int):
                return httpx.Response(payload, json={"error": "provider response"})
            if payload == "timeout":
                raise httpx.ReadTimeout("provider request timed out")
            return httpx.Response(200, json={"search_metadata": {"status": "Success"}, **payload})

        def page_handler(request):
            article_calls.append(str(request.url))
            return fixture_pages(request)

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(search_handler)) as search_client,
            httpx.AsyncClient(transport=httpx.MockTransport(page_handler)) as article_client,
        ):
            async def discover(query, engine):
                return await discover_news(search_client, "fixture-key", query, engine)

            async def extract(url):
                return await fetch_article_text(article_client, url)

            return await retrieve_news(topic, discover, extract, limit=limit)

    async def test_article_cap_is_shared_by_both_engines(self):
        calls, urls = [], []
        articles = await self.run_retrieval(TORONTO, FIXTURES[TORONTO], calls, urls, limit=2)
        self.assertEqual([article["source"] for article in articles], ["Transit Board", "Local Wire"])
        self.assertEqual(articles[0]["date"], "2026-11-19T16:00:00Z")
        self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS, NEWS_TAB])
        self.assertEqual(urls, [
            "https://transit.test/decision", "https://daily.test/analysis", "https://wire.test/announcement",
        ])

    async def test_sparse_fallback_deduplicates_and_preserves_primary_then_tab_order(self):
        calls, urls = [], []
        articles = await self.run_retrieval(TORONTO, FIXTURES[TORONTO], calls, urls)
        self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS, NEWS_TAB])
        self.assertEqual(calls[0][1]["q"], f"{TORONTO} when:30d")
        self.assertEqual(calls[1][1]["q"], TORONTO)
        self.assertEqual(calls[1][1]["tbm"], "nws")
        self.assertEqual(calls[1][1]["tbs"], "qdr:m")
        self.assertNotIn("num", calls[0][1])
        self.assertNotIn("num", calls[1][1])
        self.assertEqual([article["source"] for article in articles], ["Transit Board", "Local Radio", "Local Wire"])
        self.assertEqual(len(set(urls)), 4)
        self.assertEqual(len(urls), 4)
        self.assertTrue(all("synthetic article" in article["content"] for article in articles))

    async def test_primary_with_three_readable_skips_fallback(self):
        row = FIXTURES[TORONTO][GOOGLE_NEWS]["news_results"][0]
        third = FIXTURES[TORONTO][NEWS_TAB]["news_results"][-1]
        calls = []
        articles = await self.run_retrieval(TORONTO, {GOOGLE_NEWS: {"news_results": [row, third]}}, calls, [])
        self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS])
        self.assertEqual([article["source"] for article in articles], ["Transit Board", "Local Wire", "Local Radio"])

    async def test_successful_empty_payloads_return_no_articles(self):
        calls = []
        articles = await self.run_retrieval(GRID, {GOOGLE_NEWS: EMPTY, NEWS_TAB: EMPTY}, calls, [])
        self.assertEqual(articles, [])
        self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS, NEWS_TAB])

    async def test_empty_primary_is_recovered_by_the_tab(self):
        calls = []
        articles = await self.run_retrieval(GRID, FIXTURES[GRID], calls, [])
        self.assertEqual([article["source"] for article in articles], ["Grid Operator"])
        self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS, NEWS_TAB])

    async def test_unreadable_results_are_distinct_from_empty_search(self):
        unreadable = FIXTURES[TORONTO][NEWS_TAB]["news_results"][0]
        with self.assertRaisesRegex(NewsSearchError, "unreadable_articles"):
            await self.run_retrieval(TORONTO, {GOOGLE_NEWS: {"news_results": [unreadable]}, NEWS_TAB: EMPTY}, [], [])

    async def test_primary_errors_skip_same_provider_fallback(self):
        for response, reason in (
            (401, "credentials_rejected"),
            (429, "rate_or_quota_limit"),
            (503, "provider_error"),
            ("timeout", "timeout"),
            ({"search_metadata": {"status": "Error"}}, "provider_error"),
            ({"news_results": {}}, "invalid_response"),
        ):
            with self.subTest(response=response):
                calls = []
                with self.assertRaisesRegex(NewsSearchError, reason):
                    await self.run_retrieval(RATES, {GOOGLE_NEWS: response}, calls, [])
                self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS])

    async def test_failed_fallback_keeps_readable_primary_article(self):
        calls = []
        articles = await self.run_retrieval(
            RATES, {GOOGLE_NEWS: FIXTURES[RATES][GOOGLE_NEWS], NEWS_TAB: 503}, calls, [],
        )
        self.assertEqual([article["source"] for article in articles], ["Central Bank"])
        self.assertEqual([engine for engine, _ in calls], [GOOGLE_NEWS, NEWS_TAB])

    async def test_comparison_runs_both_engines_independently(self):
        results = await compare(FIXTURES, "fixture-key")
        self.assertEqual(
            {topic: [arm["readable"] for arm in pair.values()] for topic, pair in results.items()},
            {TORONTO: [2, 2], RATES: [1, 2], GRID: [0, 1]},
        )
        self.assertTrue(all(arm["discovery_requests"] == 1 for pair in results.values() for arm in pair.values()))
