import re
import uuid
import json
from datetime import datetime
import trafilatura
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
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            extracted_text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if extracted_text:
                logger.debug(f"Parsed article from {url}, length={len(extracted_text)} chars")
                return extracted_text
            else:
                logger.warning(f"Trafilatura extracted no content from {url}")
                return "Failed to extract article content: No content found"
        else:
            logger.warning(f"Trafilatura failed to download content from {url}")
            return "Failed to fetch article content: Download failed"
    except Exception as e:
        logger.error(f"Error fetching full article from {url}: {e}")
        return f"Failed to fetch article content: {type(e).__name__}"

def search_news(topic):
    """
    Fetches and compiles recent news articles on a given topic.

    This function is designed to be called **once** by the search agent within the multi-agent pipeline.
    It uses SerpAPI to retrieve headlines and the Newspaper library to extract full article content.
    Returns cleaned articles for downstream analysis.
    """
    logger.debug("Calling SerpAPI...")
    params = {
        "engine": "google",
        "q": f"{topic} news {datetime.now().strftime('%Y-%m')}",
        "tbm": "nws",  
        "num": NUM_SOURCES,
        "api_key": SERPAPI_KEY  

    }
    results = GoogleSearch(params).get_dict()
    if results.get("error"):
        raise RuntimeError("News provider returned an error.")
    news_results = results.get("news_results", [])
    logger.info("Found %d results from SerpAPI", len(news_results))

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

    return compiled
