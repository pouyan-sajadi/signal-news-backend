import json
from datetime import date, datetime, timedelta, timezone
from unicodedata import normalize


def _rank_keywords(pulse_data: object) -> list[dict]:
    if isinstance(pulse_data, str):
        try:
            pulse_data = json.loads(pulse_data)
        except json.JSONDecodeError:
            return []
    if not isinstance(pulse_data, dict):
        return []

    word_cloud = pulse_data.get("news_word_cloud")
    keywords = word_cloud.get("keywords") if isinstance(word_cloud, dict) else None
    if not isinstance(keywords, list):
        return []

    by_key = {}
    for keyword in keywords:
        if not isinstance(keyword, dict):
            continue
        label = keyword.get("text")
        score = keyword.get("value")
        if not isinstance(label, str) or type(score) not in (int, float) or not 1 <= score <= 100:
            continue
        label = " ".join(label.split())
        if not label:
            continue
        key = normalize("NFKC", label).casefold()
        if key not in by_key or score > by_key[key][1]:
            by_key[key] = (label, score)

    # Scores are relative to each brief. Compare their ranks across briefs.
    ordered = sorted(by_key.items(), key=lambda item: (-item[1][1], item[0]))
    return [
        {"key": key, "label": label, "rank": rank}
        for rank, (key, (label, _score)) in enumerate(ordered[:10], start=1)
    ]


def build_topic_history(snapshots: list[dict], first_day: date, last_day: date) -> list[dict]:
    """Use the latest usable keyword list per UTC day from newest-first snapshots."""
    topics_by_day = {}
    for snapshot in snapshots:
        timestamp = snapshot.get("created_at")
        if not isinstance(timestamp, str):
            continue
        try:
            created_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        day = created_at.astimezone(timezone.utc).date()
        if day < first_day or day > last_day or day in topics_by_day:
            continue

        topics = _rank_keywords(snapshot.get("pulse_data"))
        if topics:
            topics_by_day[day] = topics

    days = (first_day + timedelta(days=offset) for offset in range((last_day - first_day).days + 1))
    return [{"date": day.isoformat(), "topics": topics_by_day.get(day)} for day in days]
