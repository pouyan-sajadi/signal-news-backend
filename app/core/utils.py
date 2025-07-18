import re
import uuid
import json
from datetime import datetime
from newspaper import Article
from serpapi import GoogleSearch
from app.config import SERPAPI_KEY, NUM_SOURCES
from app.core.logger import logger
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

def clean_text(text):
    if not isinstance(text, str):
        return ""
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)  # remove control chars
    text = text.replace('\\', ' ')                # remove stray backslashes
    text = text.replace('"', "'")                 # avoid breaking quotes
    text = re.sub(r'\s+', ' ', text)              # collapse whitespace
    return text.strip()

def is_json_serializable(article):
    try:
        json.dumps(article, ensure_ascii=False)
        return True
    except (TypeError, ValueError) as e:  
        logger.error(f"🚨 JSON serialization failed for article: {article.get('title', '[no title]')}")
        logger.debug(f"Full article data:\n{json.dumps(article, indent=2, ensure_ascii=False, default=str)}")  # Add default=str for debugging
        logger.error(f"❌ Error: {e}")
        return False    

def fetch_full_article(url):
    logger.debug(f"Attempting to fetch article from URL: {url}")
    try:
        article = Article(url)
        article.download()
        article.parse()
        logger.debug(f"Parsed article from {url}, length={len(article.text)} chars")
        return article.text
    except Exception as e:
        return f"[Failed to fetch full article: {e}]"

def search_news(topic):
    """
    Fetches and compiles recent news articles on a given topic.

    This function is designed to be called **once** by the search agent within the multi-agent pipeline.
    It uses SerpAPI to retrieve headlines and the Newspaper library to extract full article content.
    Returns a structured and cleaned JSON string of articles for downstream analysis.
    """
    logger.debug("Calling SerpAPI...")
    params = {
        "engine": "google",
        "q": f"{topic} news {datetime.now().strftime('%Y-%m')}",
        "tbm": "nws",  
        "num": NUM_SOURCES,
        "api_key": SERPAPI_KEY  

    }
    logger.debug(f"Search parameters: {params}")

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        news_results = results.get("news_results", [])
        logger.info(f"🔍 Found {len(news_results)} results from SerpAPI")
        for i, item in enumerate(news_results):
            logger.debug(f"{i+1}. {item.get('title', 'No title')}")


    except Exception as e:
        return f"[Error fetching search results: {e}]"

    if not news_results:
        return f"No news found for {topic}."

    compiled = []
    with ThreadPoolExecutor(max_workers=NUM_SOURCES) as executor:
        future_to_item = {executor.submit(fetch_full_article, item.get("link", "")): item for item in news_results}
        
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                full_text = future.result()
                cleaned = clean_text(full_text)
                logger.debug(f"🧼 Cleaned article:\n{cleaned[:300]}...")

                article = {
                    "id": str(uuid.uuid4()),  
                    "title": item.get("title", "").strip(),
                    "source": item.get("source", "").strip(),
                    "date": item.get("date", "").strip(),
                    "url": item.get("link", "").strip(),
                    "content": cleaned
                }
                if is_json_serializable(article):
                    compiled.append(article)
                else:
                    logger.warning(f"⚠️ Skipping article due to serialization issue: {article['url']}")
            except Exception as exc:
                logger.error(f"🚨 Article at {item.get('link')} generated an exception: {exc}")

    return json.dumps(compiled, indent=2, ensure_ascii=False)