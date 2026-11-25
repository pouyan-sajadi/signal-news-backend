import asyncio
import json
import unittest

from evals.bus_fare import compare, read_fixture, replay_chat, score_picks


class BusFareEvalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = read_fixture("bus_fare.json")
        self.replies = read_fixture("bus_fare_replay.json")

    def test_each_score_component_can_change_independently(self):
        for picked, expected in (
            ([], (False, False, False)),
            (["bf1", "bf4"], (True, True, True)),
            (["bf2", "bf4"], (False, True, True)),
            (["bf1"], (True, False, True)),
            (["bf1", "bf2", "bf4"], (True, True, False)),
        ):
            with self.subTest(picked=picked):
                result = score_picks(picked, self.fixture["rubric"])
                self.assertEqual(tuple(result["checks"].values()), expected)
                self.assertEqual(result["points"], sum(expected))

    def test_comparison_replays_both_prompts_with_the_same_articles(self):
        calls = {arm: [] for arm in self.replies}

        def recording_chat(arm):
            replay = replay_chat(self.replies[arm])

            async def chat(**messages):
                calls[arm].append(messages)
                return await replay(**messages)

            return chat

        results = asyncio.run(compare(self.fixture, {arm: recording_chat(arm) for arm in calls}))
        before, after = calls["before_tags"], calls["with_tags"]
        self.assertEqual(before[0]["user_message"], after[0]["user_message"])
        self.assertEqual(json.loads(before[0]["user_message"].split("\n", 1)[1]), self.fixture["articles"])
        self.assertNotIn("evidence_types", before[0]["system_prompt"])
        self.assertNotIn("evidence_types", before[1]["system_prompt"])
        self.assertIn("evidence_types", after[0]["system_prompt"])
        self.assertIn("evidence_types", after[1]["system_prompt"])
        for arm, expected in (("before_tags", 1), ("with_tags", 3)):
            self.assertEqual(results[arm]["application_model_calls"], 2)
            self.assertEqual(results[arm]["score"]["points"], expected)

    def test_unmatched_selection_surfaces_as_a_failure(self):
        failed = {**self.replies["before_tags"], "article_ids": ["unknown"]}
        results = asyncio.run(compare(self.fixture, {
            "before_tags": replay_chat(failed),
            "with_tags": replay_chat(self.replies["with_tags"]),
        }))
        result = results["before_tags"]
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["stage"], "selection")
        self.assertEqual(result["unknown_ids"], 1)
        self.assertIsNone(result["score"])
