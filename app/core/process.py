import json
import os
import time
from app.agents.agent_factory import (
    create_search_agent,
    create_source_profiler_agent,
    create_diversity_selector_agent,
    create_debate_synthesizer_agent,
    create_creative_editor_agent
)
from app.core.citations import validate_draft_citations, validate_edited_citations
from app.core.source_selection import profile_sources, request_selected_ids, resolve_selected_articles
from app.providers.llm_client import llm_client
from app.core.logger import logger
from app.core.utils import search_news
from app.providers.serpapi_news import NewsSearchError
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, List
from datetime import datetime

DEFAULT_EDITOR_TONE = "News with attitude"
EDITOR_TONES = {
    "Grandma Mode": "Grandma Mode",
    "Gen Z Mode": "Gen Z Mode",
    "Express Mode": "Sharp & Snappy",
    "Commentary Mode": DEFAULT_EDITOR_TONE,
    # Older clients send the editor prompt names directly.
    "Sharp & Snappy": "Sharp & Snappy",
    "News with attitude": DEFAULT_EDITOR_TONE,
}

class ReportPreferences(BaseModel):
    focus: str
    depth: int
    tone: str

class AgentDetails(BaseModel):
    search: List[dict] = []
    profiling: List[dict] = []
    selection: List[dict] = []
    synthesis: str = ""
    editing: str = ""

class Report(BaseModel):
    job_id: str = Field(...)
    topic: str = Field(...)
    refined_topic: Optional[str] = None
    user_preferences: ReportPreferences
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    final_report_data: AgentDetails

def report_error(step, code="unavailable"):
    messages = {
        "no_articles": "We couldn't find recent coverage for that topic. Try a broader search.",
        "timed_out": "This report took too long to finish. Try a narrower topic or try again.",
        "unavailable": "We couldn't finish your report. Please try again in a moment.",
    }
    return {"step": step, "status": "error", "code": code, "message": messages[code]}


async def process_news_backend(topic, user_preferences, notify):
    """Run the news pipeline and publish progress and results."""
    focus = user_preferences.get("focus", "Just the Facts")
    depth = user_preferences.get("depth", 2)
    requested_tone = user_preferences.get("tone")
    tone = DEFAULT_EDITOR_TONE
    if isinstance(requested_tone, str):
        tone = EDITOR_TONES.get(requested_tone, DEFAULT_EDITOR_TONE)
    
    os.makedirs("news_output", exist_ok=True)

    # Step 1: Refine Search Query
    try:
        logger.info("🔍 Refining search query...")
        await notify({"step": "search", "status": "running", "message": "🔍 Refining search query..."})
        search_agent_instance = create_search_agent()
        refine_start_time = time.time()
        refined_topic = (await llm_client.chat(
            system_prompt=search_agent_instance.instructions,
            user_message=topic,
        )).strip().strip('"')
        refine_duration = time.time() - refine_start_time
        logger.debug("Search query refined in %.2f seconds", refine_duration)
        logger.debug(f"Checking if topics are identical: {refined_topic.lower() == topic.lower()}")

        # Step 2: Search
        await notify({"step": "search", "status": "running", "message": f"🔍 Searching for: {refined_topic}", "refined_topic": refined_topic})
        search_start_time = time.time()
        raw_news_list = await search_news(refined_topic)
        search_duration = time.time() - search_start_time
        logger.debug(f"✅ search_news function execution took {search_duration:.2f} seconds.")
        
        if not raw_news_list:
            logger.warning("No articles found")
            await notify(report_error("search", "no_articles"))
            return False
            
        logger.info(f"Found {len(raw_news_list)} articles.")
        await notify({"step": "search", "status": "completed", "data": raw_news_list, "refined_topic": refined_topic})
    except NewsSearchError as error:
        logger.warning("Report search failed: %s", error.reason)
        code = "timed_out" if error.reason == "timeout" else "unavailable"
        await notify(report_error("search", code))
        return False
    except Exception:
        logger.exception("Error in Search step")
        await notify(report_error("search"))
        return False

    # Step 3: Profile Sources
    try:
        logger.info("🧠 Running Source Profiler Agent...")
        await notify({"step": "profiling", "status": "running", "message": "🧠 Profiling sources..."})
        source_profiler_agent_instance = create_source_profiler_agent(focus)
        profiling_output = await profile_sources(
            raw_news_list, source_profiler_agent_instance.instructions, llm_client.chat,
        )
        logger.info("Kept %d profiles for %d retrieved articles.", len(profiling_output), len(raw_news_list))
        await notify({"step": "profiling", "status": "completed", "data": profiling_output})
    except ValidationError as error:
        error_types = sorted({issue["type"] for issue in error.errors(include_input=False)})
        logger.error("Invalid profiler response: %s", ", ".join(error_types))
        await notify(report_error("profiling"))
        return False
    except Exception:
        logger.exception("Error in Profiling step")
        await notify(report_error("profiling"))
        return False

    # Step 4: Select Diverse Subset
    try:
        logger.info("🧮 Running Diversity Selector Agent...")
        await notify({"step": "selection", "status": "running", "message": "🧮 Selecting diverse articles..."})
        diversity_selector_agent_instance = create_diversity_selector_agent(focus, depth)
        selected_ids = await request_selected_ids(
            profiling_output, diversity_selector_agent_instance.instructions, llm_client.chat,
        )
        selected_articles = resolve_selected_articles(raw_news_list, selected_ids)
        logger.info(f"Selected {len(selected_articles)} articles.")
        await notify({"step": "selection", "status": "completed", "data": selected_articles})
    except ValidationError as error:
        error_types = sorted({issue["type"] for issue in error.errors(include_input=False)})
        logger.error("Invalid selector response: %s", ", ".join(error_types))
        await notify(report_error("selection"))
        return False
    except Exception:
        logger.exception("Error in Selection step")
        await notify(report_error("selection"))
        return False

    # Step 5: Synthesize Debate
    try:
        logger.info("🗣️ Running Debate Synthesizer Agent...")
        await notify({"step": "synthesis", "status": "running", "message": "🗣️ Synthesizing the debate..."})
        debate_synthesizer_agent_instance = create_debate_synthesizer_agent(focus, depth)
        final_report = await llm_client.chat(
            system_prompt=debate_synthesizer_agent_instance.instructions,
            user_message=f"Create a debate report:\n{json.dumps(selected_articles, indent=2)}",
        )
        draft_citations = validate_draft_citations(final_report, selected_articles)
        await notify({"step": "synthesis", "status": "completed", "data": final_report})
    except Exception:
        logger.exception("Error in Synthesis step")
        await notify(report_error("synthesis"))
        return False

    # Step 6: Creative Editor
    try:
        logger.info("🎨 Running Creative Editor Agent...")
        await notify({"step": "editing", "status": "running", "message": "🎨 Applying a creative touch..."})
        creative_editor_agent_instance = create_creative_editor_agent(focus, depth, tone)
        creative_report = await llm_client.chat(
            system_prompt=creative_editor_agent_instance.instructions,
            user_message=f"Rewrite this report:\n{final_report}",
        )
        validate_edited_citations(creative_report, draft_citations)
        
        final_report_data = {
            "topic": topic,
            "refined_topic": refined_topic,
            "agent_details": {
                "search": raw_news_list,
                "profiling": profiling_output,
                "selection": selected_articles,
                "synthesis": final_report,
                "editing": creative_report # Store the final creative report here too
            }
        }
        await notify({"step": "editing", "status": "completed", "data": final_report_data})

        

    except Exception:
        logger.exception("Error in Editing step")
        await notify(report_error("editing"))
        return False
        
    return True

