import asyncio
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "offline-test-key")
os.environ.setdefault("LLM_API_KEY", "offline-test-key")
os.environ.setdefault("LLM_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("LLM_MODEL", "offline-test-model")
os.environ.setdefault("SERPAPI_API_KEY", "offline-test-key")

from fastapi.testclient import TestClient

from app.core import process
import backend_app


ARTICLES = [
    {"id": "article-1", "title": "First", "source": "One", "date": "today", "url": "https://one.test", "content": "Evidence one."},
    {"id": "article-2", "title": "Second", "source": "Two", "date": "today", "url": "https://two.test", "content": "Evidence two."},
]
PREFERENCES = {"focus": "Just the Facts", "depth": 2, "tone": "Express Mode"}


class FakeLLM:
    def __init__(self, selection):
        self.selection = selection
        self.calls = []

    async def chat(self, system_prompt, user_message):
        self.calls.append((system_prompt, user_message))
        if len(self.calls) == 1:
            return "Refined topic"
        if len(self.calls) == 2:
            return json.dumps([
                {"id": article["id"], "title": article["title"], "perspective": ["test coverage"]}
                for article in ARTICLES
            ])
        if len(self.calls) == 3:
            return json.dumps(self.selection)
        if len(self.calls) == 4:
            return "Draft with citations."
        if len(self.calls) == 5:
            return "Edited report."
        raise AssertionError("Unexpected model call")


class SelectionHandoffTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(process, "search_news", return_value=ARTICLES),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def run_pipeline(self, selection):
        fake = FakeLLM(selection)
        updates = []

        async def notify(update):
            updates.append(update)

        with patch.object(process, "llm_client", fake):
            result = asyncio.run(process.process_news_backend("Topic", PREFERENCES, notify))
        return result, fake, updates

    def test_normal_report_keeps_retrieval_order_preferences_and_five_calls(self):
        result, fake, updates = self.run_pipeline(["article-2", "article-1"])
        self.assertTrue(result)
        self.assertEqual(len(fake.calls), 5)
        completed = updates[-1]["data"]["agent_details"]
        self.assertEqual([a["id"] for a in completed["selection"]], ["article-1", "article-2"])
        self.assertEqual([a["url"] for a in completed["selection"]], [a["url"] for a in ARTICLES])
        _, writer_input = fake.calls[3]
        self.assertEqual(json.loads(writer_input.split("\n", 1)[1]), ARTICLES)
        self.assertIn("Brutal efficiency", fake.calls[-1][0])
        self.assertIn("Four medium paragraphs", fake.calls[-1][0])
        self.assertEqual(updates[-1]["step"], "editing")

    def test_unknown_only_selection_fails_before_writer_call(self):
        result, fake, updates = self.run_pipeline(["missing-id"])
        self.assertFalse(result)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(updates[-1]["step"], "selection")
        self.assertEqual(updates[-1]["status"], "error")
        self.assertEqual(updates[-1]["code"], "unavailable")

    def test_partial_matches_and_duplicates_resolve_once_in_retrieval_order(self):
        self.assertEqual(
            process.resolve_selected_articles(ARTICLES, ["article-2", "missing", "article-2"]),
            [ARTICLES[1]],
        )

    def test_malformed_selector_output_is_rejected(self):
        for malformed in ("article-1", 1, None, ["article-1", 2]):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    process.resolve_selected_articles(ARTICLES, malformed)

    def test_http_job_returns_selection_failure_contract(self):
        fake = FakeLLM(["missing-id"])
        with patch.object(process, "llm_client", fake), patch.object(process, "search_news", return_value=ARTICLES):
            with TestClient(backend_app.app) as client:
                started = client.post("/process_news", json={"topic": " Topic ", "user_preferences": PREFERENCES})
                self.assertEqual(started.status_code, 200)
                job_id = started.json()["job_id"]
                response = None
                for _ in range(100):
                    response = client.get(f"/report-jobs/{job_id}")
                    if response.json()["status"] != "running":
                        break
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"status": "error", "step": "selection", "code": "unavailable"})
                self.assertEqual(len(fake.calls), 3)

    def test_http_job_returns_existing_completed_report_shape(self):
        fake = FakeLLM(["article-1"])
        with patch.object(process, "llm_client", fake), patch.object(process, "search_news", return_value=ARTICLES):
            with TestClient(backend_app.app) as client:
                started = client.post("/process_news", json={"topic": "Topic", "user_preferences": PREFERENCES})
                self.assertEqual(started.status_code, 200)
                job_id = started.json()["job_id"]
                response = None
                for _ in range(100):
                    response = client.get(f"/report-jobs/{job_id}")
                    if response.json()["status"] != "running":
                        break
                body = response.json()
                self.assertEqual(body["status"], "completed")
                self.assertEqual(body["step"], "editing")
                self.assertEqual(body["data"]["agent_details"]["editing"], "Edited report.")
                self.assertEqual(len(fake.calls), 5)


if __name__ == "__main__":
    unittest.main()
