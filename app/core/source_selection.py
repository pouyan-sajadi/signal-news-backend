import json

from app.agents.schemas import ProfilingResponse, SelectionResponse, SourceProfile


async def profile_sources(articles, system_prompt, chat):
    response = await chat(
        system_prompt=system_prompt,
        user_message=f"Profile these articles:\n{json.dumps(articles, indent=2)}",
    )
    profiles = ProfilingResponse.model_validate_json(response).root
    return resolve_source_profiles(articles, profiles)


async def request_selected_ids(profiles, system_prompt, chat) -> list[str]:
    response = await chat(
        system_prompt=system_prompt,
        user_message=f"Select a diverse subset from these profiles: {json.dumps(profiles, indent=2)}",
    )
    return SelectionResponse.model_validate_json(response).article_ids


def resolve_source_profiles(articles, profiles: list[SourceProfile]) -> list[dict]:
    """Keep one profile per known article and attach retrieved metadata."""
    articles_by_id = {article["id"]: article for article in articles}
    profiles_by_id = {}
    for profile in profiles:
        if profile.id in articles_by_id and profile.id not in profiles_by_id:
            article = articles_by_id[profile.id]
            profiles_by_id[profile.id] = {
                **profile.model_dump(exclude_unset=True),
                "title": article["title"],
                "source": article["source"],
            }
    if not profiles_by_id:
        raise ValueError("Profiler output did not identify any retrieved articles.")
    return list(profiles_by_id.values())


def resolve_selected_articles(articles, selected_ids: list[str]):
    """Keep known articles in retrieval order and reject an empty match."""
    requested_ids = set(selected_ids)
    selected_articles = [article for article in articles if article.get("id") in requested_ids]
    if not selected_articles:
        raise ValueError("Selector output did not identify any retrieved articles.")
    return selected_articles
