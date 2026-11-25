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
from app.core.citations import citation_urls
from app.core.utils import retrieve_news
from app.providers.serpapi_news import NewsCandidate, NewsSearchError, GOOGLE_NEWS, NEWS_TAB
import backend_app


ARTICLES = [
    {"id": "article-1", "title": "First", "source": "One", "date": "today", "url": "https://one.test", "content": "Evidence one."},
    {"id": "article-2", "title": "Second", "source": "Two", "date": "today", "url": "https://two.test", "content": "Evidence two."},
]
PREFERENCES = {"focus": "Just the Facts", "depth": 2, "tone": "Express Mode"}
PROFILES = [
    {
        "id": "article-1",
        "perspective": ["test coverage"],
        "source_type": "news report",
        "coverage_roles": ["main development", "impact"],
        "evidence_types": ["primary document", "firsthand account"],
        "represented_voices": ["bus riders"],
    },
    {"id": "article-2", "perspective": []},
]


class FakeLLM:
    def __init__(self, selection_text, profiling_text=json.dumps(PROFILES), *, draft=None, edited=None, refined_topic="Refined topic"):
        self.selection_text = selection_text
        self.profiling_text = profiling_text
        self.draft = draft
        self.edited = edited
        self.refined_topic = refined_topic
        self.calls = []

    async def chat(self, system_prompt, user_message):
        self.calls.append((system_prompt, user_message))
        if len(self.calls) == 1:
            return self.refined_topic
        if len(self.calls) == 2:
            return self.profiling_text
        if len(self.calls) == 3:
            return self.selection_text
        if len(self.calls) == 4:
            if self.draft is not None:
                return self.draft
            articles = json.loads(user_message.split("\n", 1)[1])
            links = " and ".join(f'[{article["source"]}]({article["url"]})' for article in articles)
            return f"The report draws on {links}."
        if len(self.calls) == 5:
            return self.edited if self.edited is not None else "Edited report.\n\n" + user_message.split("\n", 1)[1]
        raise AssertionError("Unexpected model call")


class SelectionHandoffTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(process, "search_news", return_value=ARTICLES),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def run_pipeline(self, selection_text, **fake_options):
        fake = FakeLLM(selection_text, **fake_options)
        updates = []

        async def notify(update):
            updates.append(update)

        with patch.object(process, "llm_client", fake):
            result = asyncio.run(process.process_news_backend("Topic", PREFERENCES, notify))
        return result, fake, updates

    def test_normal_report_keeps_retrieval_order_preferences_and_five_calls(self):
        result, fake, updates = self.run_pipeline('{"article_ids": ["article-2", "article-1"]}')
        self.assertTrue(result)
        self.assertEqual(len(fake.calls), 5)
        completed = updates[-1]["data"]["agent_details"]
        self.assertEqual([a["id"] for a in completed["selection"]], ["article-1", "article-2"])
        self.assertEqual([a["url"] for a in completed["selection"]], [a["url"] for a in ARTICLES])
        profiler_prompt, _ = fake.calls[1]
        profiler_schema = json.loads(profiler_prompt.strip().splitlines()[-1])
        profile_schema = profiler_schema["$defs"]["SourceProfile"]
        self.assertEqual(profile_schema["required"], ["id", "perspective"])
        self.assertIn("factual density", profiler_prompt)
        selector_prompt, selector_input = fake.calls[2]
        for field in ("coverage_roles", "evidence_types", "represented_voices"):
            self.assertIn(field, profile_schema["properties"])
            self.assertIn(field, selector_prompt)
        expected_profiles = [
            {**profile, "title": article["title"], "source": article["source"]}
            for profile, article in zip(PROFILES, ARTICLES, strict=True)
        ]
        self.assertEqual(json.loads(selector_input.split(": ", 1)[1]), expected_profiles)
        self.assertEqual(completed["profiling"], expected_profiles)
        self.assertIn('"article_ids"', selector_prompt)
        self.assertIn("Aim for 4-5 articles", selector_prompt)
        self.assertIn("Select fewer articles", selector_prompt)
        _, writer_input = fake.calls[3]
        self.assertEqual(json.loads(writer_input.split("\n", 1)[1]), ARTICLES)
        self.assertIn("Brutal efficiency", fake.calls[-1][0])
        self.assertIn("Four medium paragraphs", fake.calls[-1][0])
        self.assertIn("Preserve every distinct citation URL", fake.calls[-1][0])
        self.assertEqual(citation_urls(completed["editing"]), {"https://one.test", "https://two.test"})
        self.assertEqual(updates[-1]["step"], "editing")

    def test_writer_rejects_missing_unselected_and_invented_links(self):
        for draft in (
            "Report without citations.",
            "The story came from [a retrieved but unselected article](https://two.test).",
            "[Selected article](https://one.test) and a bare invented URL https://invented.test/news.",
        ):
            with self.subTest(draft=draft), self.assertLogs(process.logger, level="ERROR"):
                result, fake, updates = self.run_pipeline('{"article_ids": ["article-1"]}', draft=draft)
                self.assertFalse(result)
                self.assertEqual(len(fake.calls), 4)
                self.assertEqual(updates[-1], process.report_error("synthesis"))

    def test_editor_rejects_removed_or_added_links(self):
        scenarios = (
            ("[First](https://one.test) and [Second](https://two.test).", "[First](https://one.test)."),
            ("[First](https://one.test).", "[First](https://one.test) plus [Second](https://two.test)."),
            ("[First](https://one.test).", "[First](https://one.test) plus <https://invented.test>."),
        )
        for draft, edited in scenarios:
            with self.subTest(edited=edited), self.assertLogs(process.logger, level="ERROR"):
                result, fake, updates = self.run_pipeline(
                    '{"article_ids": ["article-1", "article-2"]}', draft=draft, edited=edited,
                )
                self.assertFalse(result)
                self.assertEqual(len(fake.calls), 5)
                self.assertEqual(updates[-1], process.report_error("editing"))

    def test_unknown_only_selection_fails_before_writer_call(self):
        result, fake, updates = self.run_pipeline('{"article_ids": ["missing-id"]}')
        self.assertFalse(result)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(updates[-1]["step"], "selection")
        self.assertEqual(updates[-1]["status"], "error")
        self.assertEqual(updates[-1]["code"], "unavailable")

    def test_partial_matches_and_duplicates_resolve_once_in_retrieval_order(self):
        result, fake, updates = self.run_pipeline(
            '{"article_ids": ["article-2", "missing", "article-1", "article-2"]}'
        )
        self.assertTrue(result)
        self.assertEqual(len(fake.calls), 5)
        self.assertEqual(updates[-1]["data"]["agent_details"]["selection"], ARTICLES)

    def test_partial_profiling_and_selection_can_finish_with_one_article(self):
        result, fake, updates = self.run_pipeline(
            '{"article_ids": ["unknown-id", "article-1"]}',
            profiling_text=json.dumps([
                {"id": "unknown-id", "perspective": ["unknown article"]},
                {"id": "article-1", "perspective": [], "tone": None, "focus_notes": ["A specific detail."]},
                {"id": "article-1", "perspective": ["duplicate"]},
            ]),
        )
        self.assertTrue(result)
        self.assertEqual(len(fake.calls), 5)
        _, selector_input = fake.calls[2]
        self.assertEqual(json.loads(selector_input.split(": ", 1)[1]), [
            {"id": "article-1", "title": "First", "source": "One", "perspective": [], "tone": None,
             "focus_notes": ["A specific detail."]},
        ])
        self.assertEqual(updates[-1]["data"]["agent_details"]["selection"], [ARTICLES[0]])

    def test_invalid_profiling_stops_before_selection(self):
        valid_profile = {"id": "article-1", "perspective": ["valid"]}
        for profiling_text in (
            '[]',
            '{"profiles": []}',
            '[{"id": "article-1", "perspective": []}',
            '[{"id": "unknown-id", "perspective": []}]',
            json.dumps([valid_profile, {"perspective": []}]),
            json.dumps([valid_profile, {"id": "article-2"}]),
            json.dumps([valid_profile, {"id": "article-2", "perspective": [2]}]),
            json.dumps([valid_profile, {"id": "article-2", "perspective": [" "]}]),
            json.dumps([valid_profile, {"id": "article-2", "perspective": [], "tone": "made up"}]),
            json.dumps([{**valid_profile, "coverage_roles": ["credible"]}]),
            json.dumps([{**valid_profile, "evidence_types": ["certain"]}]),
            json.dumps([{**valid_profile, "represented_voices": "bus riders"}]),
        ):
            with self.subTest(profiling_text=profiling_text):
                with self.assertLogs(process.logger, level="ERROR"):
                    result, fake, updates = self.run_pipeline(
                        '{"article_ids": ["article-1"]}',
                        profiling_text=profiling_text,
                    )
                self.assertFalse(result)
                self.assertEqual(len(fake.calls), 2)
                self.assertEqual(updates[-1], process.report_error("profiling"))

    def test_http_job_returns_profiling_failure_contract(self):
        fake = FakeLLM('{"article_ids": ["article-1"]}', profiling_text='[{"id": "article-1"}]')
        with patch.object(process, "llm_client", fake), TestClient(backend_app.app) as client:
            started = client.post("/process_news", json={"topic": "Topic", "user_preferences": PREFERENCES})
            self.assertEqual(started.status_code, 200)
            job_id = started.json()["job_id"]
            for _ in range(100):
                response = client.get(f"/report-jobs/{job_id}")
                if response.json()["status"] != "running":
                    break
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "error", "step": "profiling", "code": "unavailable"})
            self.assertEqual(len(fake.calls), 2)

    def test_http_job_rejects_unsearchable_topic_before_retrieval(self):
        topic = "zqvqxjkl nfrtpswz drkxvqp 994037"
        fake = FakeLLM('{"article_ids": ["article-1"]}', refined_topic=' "NO_SEARCHABLE_TOPIC"\n')
        with (
            patch.object(process, "llm_client", fake),
            patch.object(process, "search_news", side_effect=NewsSearchError("timeout")) as search,
            TestClient(backend_app.app) as client,
        ):
            started = client.post("/process_news", json={"topic": topic, "user_preferences": PREFERENCES})
            self.assertEqual(started.status_code, 200)
            job_id = started.json()["job_id"]
            for _ in range(100):
                response = client.get(f"/report-jobs/{job_id}")
                if response.json()["status"] != "running":
                    break
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "error", "step": "search", "code": "invalid_topic"})
        search.assert_not_awaited()
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1], topic)

    def test_http_job_distinguishes_search_failure_outcomes(self):
        candidate = NewsCandidate("Title", "Source", "", "https://example.test/news", "https://example.test/news")
        for scenario, code, expected_engines in (
            ("empty", "no_articles", [GOOGLE_NEWS, NEWS_TAB]),
            ("unreadable", "unavailable", [GOOGLE_NEWS, NEWS_TAB]),
            ("timeout", "timed_out", [GOOGLE_NEWS]),
        ):
            with self.subTest(scenario=scenario):
                engines = []

                async def discover(topic, engine):
                    engines.append(engine)
                    if scenario == "timeout":
                        raise NewsSearchError("timeout")
                    return [candidate] if scenario == "unreadable" else []

                async def extract(url):
                    return ""

                async def search(topic):
                    return await retrieve_news(topic, discover, extract)

                fake = FakeLLM('{"article_ids": ["article-1"]}')
                with patch.object(process, "llm_client", fake), patch.object(process, "search_news", new=search):
                    with TestClient(backend_app.app) as client:
                        started = client.post("/process_news", json={"topic": "Topic", "user_preferences": PREFERENCES})
                        self.assertEqual(started.status_code, 200)
                        job_id = started.json()["job_id"]
                        for _ in range(100):
                            response = client.get(f"/report-jobs/{job_id}")
                            if response.json()["status"] != "running":
                                break
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), {"status": "error", "step": "search", "code": code})
                self.assertEqual(engines, expected_engines)
                self.assertEqual(len(fake.calls), 1)

    def test_malformed_selector_output_fails_before_writer_call(self):
        for malformed in (
            '["article-1"]',
            '{"article_ids": "article-1"}',
            '{"article_ids": ["article-1", 2]}',
            '{"article_ids": ["article-1"], "response-text-marker": "extra field"}',
            '{"article_ids": []}',
            '{}',
            '{"article_ids": ["article-1"',
            '```json\n{"article_ids": ["article-1"]}\n```',
        ):
            with self.subTest(malformed=malformed):
                with self.assertLogs(process.logger, level="ERROR") as logs:
                    result, fake, updates = self.run_pipeline(malformed)
                self.assertIn("Invalid selector response", logs.output[-1])
                self.assertNotIn("response-text-marker", logs.output[-1])
                self.assertFalse(result)
                self.assertEqual(len(fake.calls), 3)
                self.assertEqual(updates[-1]["step"], "selection")
                self.assertEqual(updates[-1]["status"], "error")
                self.assertEqual(updates[-1]["code"], "unavailable")

    def test_http_job_returns_selection_failure_contract(self):
        fake = FakeLLM('{"article_ids": ["missing-id"]}')
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
        edited = "Edited report citing [the original article][source].\n\n[source]: https://one.test"
        fake = FakeLLM('{"article_ids": ["article-1"]}', edited=edited)
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
                self.assertEqual(body["data"]["agent_details"]["editing"], edited)
                self.assertEqual(citation_urls(body["data"]["agent_details"]["editing"]), {"https://one.test"})
                self.assertEqual(len(fake.calls), 5)

    def test_http_job_reports_citation_failure_at_the_stage_that_caused_it(self):
        for stage, options, calls in (
            ("synthesis", {"draft": "[Unknown](https://invented.test)."}, 4),
            ("editing", {"edited": "Edited report with the link removed."}, 5),
        ):
            with self.subTest(stage=stage):
                fake = FakeLLM('{"article_ids": ["article-1"]}', **options)
                with patch.object(process, "llm_client", fake), TestClient(backend_app.app) as client:
                    started = client.post("/process_news", json={"topic": "Topic", "user_preferences": PREFERENCES})
                    self.assertEqual(started.status_code, 200)
                    job_id = started.json()["job_id"]
                    for _ in range(100):
                        response = client.get(f"/report-jobs/{job_id}")
                        if response.json()["status"] != "running":
                            break
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"status": "error", "step": stage, "code": "unavailable"})
                    self.assertEqual(len(fake.calls), calls)


if __name__ == "__main__":
    unittest.main()
