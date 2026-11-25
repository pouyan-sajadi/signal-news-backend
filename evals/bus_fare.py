"""Compare the profiler and selector prompts on a frozen synthetic article set."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter

from app.agents.prompts import get_diversity_prompt, get_profiler_prompt
from app.core.source_selection import profile_sources, request_selected_ids, resolve_selected_articles


FIXTURE_DIR = Path(__file__).with_name("fixtures")


def read_fixture(filename):
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


def score_picks(picked_ids, rubric):
    """Score article IDs after they have been resolved against the fixture."""
    picked = set(picked_ids)
    extra_announcement_picks = max(0, len(picked.intersection(rubric["same_announcement"])) - 1)
    checks = {
        "original_decision": rubric["original_decision"] in picked,
        "firsthand_rider_experience": rubric["firsthand_rider_experience"] in picked,
        "no_redundant_announcement": bool(picked) and extra_announcement_picks == 0,
    }
    return {
        "points": sum(checks.values()),
        "out_of": len(checks),
        "checks": checks,
        "extra_announcement_picks": extra_announcement_picks,
    }


def replay_chat(replies):
    responses = iter((json.dumps(replies["profiles"]), json.dumps({"article_ids": replies["article_ids"]})))

    async def chat(**_messages):
        return next(responses)

    return chat


async def run_arm(fixture, prompts, chat, *, live=False):
    articles = fixture["articles"]
    result = {"application_model_calls": 0}
    start = perf_counter()

    async def counted_chat(**messages):
        result["application_model_calls"] += 1
        return await asyncio.wait_for(chat(**messages), timeout=30)

    stage = "profiling"
    try:
        profiles = await profile_sources(articles, prompts["profiler"], counted_chat)
        result["profiles_kept"] = len(profiles)
        stage = "selection"
        proposed_ids = await request_selected_ids(profiles, prompts["selector"], counted_chat)
        known_ids = {article["id"] for article in articles}
        result["unknown_ids"] = len(set(proposed_ids) - known_ids)
        picked_ids = [article["id"] for article in resolve_selected_articles(articles, proposed_ids)]
        result.update(status="completed", picked_ids=picked_ids, score=score_picks(picked_ids, fixture["rubric"]))
    except Exception as error:
        result.update(status="error", stage=stage, error_type=type(error).__name__, score=None)
    if live:
        result["elapsed_seconds"] = round(perf_counter() - start, 3)
    return result


async def compare(fixture, chats, *, live=False):
    prompts = {
        "before_tags": read_fixture("bus_fare_before_tags.json"),
        "with_tags": {
            "profiler": get_profiler_prompt(fixture["focus"]),
            "selector": get_diversity_prompt(fixture["focus"], fixture["depth"]),
        },
    }
    return {
        arm: await run_arm(fixture, pair, chats[arm], live=live)
        for arm, pair in prompts.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use the configured model gateway for up to four calls.")
    args = parser.parse_args()
    fixture = read_fixture("bus_fare.json")
    if args.live:
        from dotenv import load_dotenv

        load_dotenv()
        missing = [name for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL") if not os.getenv(name)]
        if missing:
            parser.error(f"Live comparison requires {', '.join(missing)}.")
        from app.providers.llm_client import llm_client

        chats = dict.fromkeys(("before_tags", "with_tags"), llm_client.chat)
        mode = "live model comparison"
    else:
        replies = read_fixture("bus_fare_replay.json")
        chats = {arm: replay_chat(replies[arm]) for arm in replies}
        mode = "offline replay of scripted outputs"
    results = asyncio.run(compare(fixture, chats, live=args.live))
    print(json.dumps({"mode": mode, "fixture": fixture["name"], "arms": results}, indent=2))
    return int(any(arm["status"] == "error" for arm in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
