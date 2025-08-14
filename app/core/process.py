import json
import os
import time
import asyncio
from app.agents.agent_factory import (
    create_search_agent,
    create_source_profiler_agent,
    create_diversity_selector_agent,
    create_debate_synthesizer_agent,
    create_creative_editor_agent
)
from swarm import Swarm
from app.core.logger import logger
from app.core.utils import search_news
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

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

client = Swarm()

async def process_news_backend(job_id, topic, user_preferences, websocket_sender, supabase_client):
    """Run the news processing workflow, using a websocket to stream results."""

    async def notify(data):
        await websocket_sender(data)

    focus = user_preferences.get("focus", "Just the Facts")
    depth = user_preferences.get("depth", 2)
    tone = user_preferences.get("tone", "News with attitude")
    if tone not in ["Grandma Mode", "News with attitude", "Gen Z Mode", "Sharp & Snappy"]:
        tone = "News with attitude"
    
    os.makedirs("news_output", exist_ok=True)

    # Step 1: Refine Search Query
    try:
        logger.info("🔍 Refining search query...")
        await notify({"step": "search", "status": "running", "message": "🔍 Refining search query..."})
        search_agent_instance = create_search_agent()
        refine_start_time = time.time()
        search_response = await asyncio.to_thread(
            client.run,
            agent=search_agent_instance,
            messages=[{"role": "user", "content": topic}]
        )
        refine_duration = time.time() - refine_start_time
        refined_topic = search_response.messages[-1]["content"].strip().strip('"')
        logger.info(f"🤖 Search query refined in {refine_duration:.2f} seconds. New query: {refined_topic}")
        logger.info(f"Checking if topics are identical: {refined_topic.lower() == topic.lower()}")

        # Step 2: Search
        logger.info(f"🔍 Calling search_news function with refined topic: {refined_topic}")
        await notify({"step": "search", "status": "running", "message": f"🔍 Searching for: {refined_topic}", "refined_topic": refined_topic})
        search_start_time = time.time()
        raw_news_json = await asyncio.to_thread(search_news, refined_topic)
        search_duration = time.time() - search_start_time
        logger.info(f"✅ search_news function execution took {search_duration:.2f} seconds.")
        
        try:
            raw_news_list = json.loads(raw_news_json)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from search_news output: {raw_news_json}")
            await notify({
                "step": "search", 
                "status": "error", 
                 "message": f"We're having trouble understanding the search results. This might be a temporary issue with the news provider. Please try a different topic or try again later."
            })
            return False

        if not raw_news_list:
            logger.warning(f"No articles found for topic: {refined_topic}")
            await notify({
                "step": "search", 
                "status": "error", 
                 "message": f"We couldn't find any recent articles for '{refined_topic}'. The topic might be too specific, or not currently widely covered. Try a broader term or a more current event."
            })
            return False
            
        logger.info(f"Found {len(raw_news_list)} articles.")
        await notify({"step": "search", "status": "completed", "data": raw_news_list, "refined_topic": refined_topic})
    except Exception as e:
        logger.exception("Error in Search step")
        await notify({"step": "error", "message": f"The news search encountered an unexpected problem. This could be a network issue or a problem with the search service. Please check your internet connection and try again."
})
        return False

    # Step 3: Profile Sources
    try:
        logger.info("🧠 Running Source Profiler Agent...")
        await notify({"step": "profiling", "status": "running", "message": "🧠 Profiling sources..."})
        source_profiler_agent_instance = create_source_profiler_agent(focus)
        profiler_message = f"Profile these articles:\n{json.dumps(raw_news_list, indent=2)}"
        profile_response = await asyncio.to_thread(
            client.run,
            agent=source_profiler_agent_instance,
            messages=[{"role": "user", "content": profiler_message}]
        )
        profiling_output = json.loads(profile_response.messages[-1]["content"])
        await notify({"step": "profiling", "status": "completed", "data": profiling_output})
    except Exception as e:
        logger.exception("Error in Profiling step")
        await notify({"step": "error", "message": f"Profiling failed: {e}"})
        return False

    # Step 4: Select Diverse Subset
    try:
        logger.info("🧮 Running Diversity Selector Agent...")
        await notify({"step": "selection", "status": "running", "message": "🧮 Selecting diverse articles..."})
        diversity_selector_agent_instance = create_diversity_selector_agent(focus, depth)
        diversity_message = f"Select a diverse subset from these profiles: {json.dumps(profiling_output, indent=2)}"
        diversity_response = await asyncio.to_thread(
            client.run,
            agent=diversity_selector_agent_instance,
            messages=[{"role": "user", "content": diversity_message}]
        )
        selected_ids = json.loads(diversity_response.messages[-1]["content"])
        selected_articles = [a for a in raw_news_list if a["id"] in selected_ids]
        logger.info(f"Selected {len(selected_articles)} articles.")
        await notify({"step": "selection", "status": "completed", "data": selected_articles})
    except Exception as e:
        logger.exception("Error in Selection step")
        await notify({"step": "error", "message": f"Selection failed: {e}"})
        return False

    # Step 5: Synthesize Debate
    try:
        logger.info("🗣️ Running Debate Synthesizer Agent...")
        await notify({"step": "synthesis", "status": "running", "message": "🗣️ Synthesizing the debate..."})
        debate_synthesizer_agent_instance = create_debate_synthesizer_agent(focus, depth)
        debate_response = await asyncio.to_thread(
            client.run,
            agent=debate_synthesizer_agent_instance,
            messages=[{"role": "user", "content": f"Create a debate report:\n{json.dumps(selected_articles, indent=2)}"}]
        )
        final_report = debate_response.messages[-1]["content"]
        await notify({"step": "synthesis", "status": "completed", "data": final_report})
    except Exception as e:
        logger.exception("Error in Synthesis step")
        await notify({"step": "error", "message": f"Synthesis failed: {e}"})
        return False

    # Step 6: Creative Editor
    try:
        logger.info("🎨 Running Creative Editor Agent...")
        await notify({"step": "editing", "status": "running", "message": "🎨 Applying a creative touch..."})
        creative_editor_agent_instance = create_creative_editor_agent(focus, depth, tone)
        creative_response = await asyncio.to_thread(
            client.run,
            agent=creative_editor_agent_instance,
            messages=[{"role": "user", "content": f"Rewrite this report:\n{final_report}"}]
        )
        creative_report = creative_response.messages[-1]["content"]
        
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

        # Save report to database
        try:
            logger.info(f"user_preferences before Report: {user_preferences}")
            logger.info(f"final_report_data['agent_details'] before Report: {final_report_data['agent_details']}")
            report_entry = Report(
                job_id=job_id,
                topic=final_report_data["topic"],
                refined_topic=final_report_data.get("refined_topic"),
                user_preferences=user_preferences,
                final_report_data=final_report_data["agent_details"]
            )
            # Convert Pydantic model to dictionary for Supabase insertion
            report_data_to_insert = report_entry.model_dump(by_alias=True)
            
            # Manually convert datetime to ISO 8601 string format
            if 'timestamp' in report_data_to_insert and isinstance(report_data_to_insert['timestamp'], datetime):
                report_data_to_insert['timestamp'] = report_data_to_insert['timestamp'].isoformat()

            # Insert into 'user_report_history' table in Supabase
            insert_response = await supabase_client.table("user_report_history").insert(report_data_to_insert).execute()

            if insert_response.data:
                logger.info(f'Report {job_id} saved to Supabase.')
            else:
                logger.error(f"Failed to save report {job_id} to Supabase. Response: {insert_response.data}")
                raise Exception(f"Supabase insert failed: {insert_response.data}")

        except Exception as db_e:
            logger.exception(f"Error saving report to Supabase: {db_e}")
            await notify({"step": "error", "message": f"Failed to save report to Supabase: {db_e}"})
            return False

    except Exception as e:
        logger.exception("Error in Editing step")
        await notify({"step": "error", "message": f"Editing failed: {e}"})
        return False
        
    await asyncio.sleep(1) # Add a small delay to ensure the last message is sent
    return True

