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
from swarm import Swarm
from app.core.logger import logger
from app.core.utils import search_news

client = Swarm()

def process_news(topic, user_preferences, status_callback=None):
    """Run the news processing workflow, using a callback to stream results."""

    def notify(data):
        if status_callback:
            status_callback(data)

    focus = user_preferences.get("focus", "Just the Facts")
    depth = user_preferences.get("depth", 2)
    tone = user_preferences.get("tone", "News with attitude")
    
    os.makedirs("news_output", exist_ok=True)
    final_results = {}

    # Step 1: Refine Search Query
    try:
        logger.info("🔍 Refining search query...")
        notify({"step": "search", "status": "running", "message": "🔍 Refining search query..."})
        search_agent_instance = create_search_agent()
        refine_start_time = time.time()
        search_response = client.run(
            agent=search_agent_instance,
            messages=[{"role": "user", "content": topic}]
        )
        refine_duration = time.time() - refine_start_time
        refined_topic = search_response.messages[-1]["content"].strip().strip('"')
        logger.info(f"🤖 Search query refined in {refine_duration:.2f} seconds. New query: {refined_topic}")
        logger.info(f"Checking if topics are identical: {refined_topic.lower() == topic.lower()}")

        # Step 2: Search
        logger.info(f"🔍 Calling search_news function with refined topic: {refined_topic}")
        notify({"step": "search", "status": "running", "message": f"🔍 Searching for: {refined_topic}"})
        search_start_time = time.time()
        raw_news_json = search_news(refined_topic)
        search_duration = time.time() - search_start_time
        logger.info(f"✅ search_news function execution took {search_duration:.2f} seconds.")
        
        try:
            raw_news_list = json.loads(raw_news_json)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from search_news output: {raw_news_json}")
            notify({
                "step": "search", 
                "status": "error", 
                 "message": f"We're having trouble understanding the search results. This might be a temporary issue with the news provider. Please try a different topic or try again later."
            })
            return False

        if not raw_news_list:
            logger.warning(f"No articles found for topic: {refined_topic}")
            notify({
                "step": "search", 
                "status": "error", 
                 "message": f"We couldn't find any recent articles for '{refined_topic}'. The topic might be too specific, or not currently widely covered. Try a broader term or a more current event."
            })
            return False
            
        logger.info(f"Found {len(raw_news_list)} articles.")
        final_results['raw_news_list'] = raw_news_list
        notify({"step": "search", "status": "completed", "data": raw_news_list})
    except Exception as e:
        logger.exception("Error in Search step")
        notify({"step": "error", "message": f"The news search encountered an unexpected problem. This could be a network issue or a problem with the search service. Please check your internet connection and try again."})
        return False

    # Step 3: Profile Sources
    try:
        logger.info("🧠 Running Source Profiler Agent...")
        notify({"step": "profiling", "status": "running", "message": "🧠 Profiling sources..."})
        source_profiler_agent_instance = create_source_profiler_agent(focus)
        profiler_message = f"Profile these articles:\n{json.dumps(raw_news_list, indent=2)}"
        profile_response = client.run(
            agent=source_profiler_agent_instance,
            messages=[{"role": "user", "content": profiler_message}]
        )
        profiling_output = json.loads(profile_response.messages[-1]["content"])
        final_results['profiling_output'] = profiling_output
        notify({"step": "profiling", "status": "completed", "data": profiling_output})
    except Exception as e:
        logger.exception("Error in Profiling step")
        notify({"step": "error", "message": f"Profiling failed: {e}"})
        return False

    # Step 4: Select Diverse Subset
    try:
        logger.info("🧮 Running Diversity Selector Agent...")
        notify({"step": "selection", "status": "running", "message": "🧮 Selecting diverse articles..."})
        diversity_selector_agent_instance = create_diversity_selector_agent(focus, depth)
        diversity_message = f"Select a diverse subset from these profiles: {json.dumps(profiling_output, indent=2)}"
        diversity_response = client.run(
            agent=diversity_selector_agent_instance,
            messages=[{"role": "user", "content": diversity_message}]
        )
        selected_ids = json.loads(diversity_response.messages[-1]["content"])
        selected_articles = [a for a in raw_news_list if a["id"] in selected_ids]
        logger.info(f"Selected {len(selected_articles)} articles.")
        final_results['selected_articles'] = selected_articles
        notify({"step": "selection", "status": "completed", "data": selected_articles})
    except Exception as e:
        logger.exception("Error in Selection step")
        notify({"step": "error", "message": f"Selection failed: {e}"})
        return False

    # Step 5: Synthesize Debate
    try:
        logger.info("🗣️ Running Debate Synthesizer Agent...")
        notify({"step": "synthesis", "status": "running", "message": "🗣️ Synthesizing the debate..."})
        debate_synthesizer_agent_instance = create_debate_synthesizer_agent(focus, depth)
        debate_response = client.run(
            agent=debate_synthesizer_agent_instance,
            messages=[{"role": "user", "content": f"Create a debate report:\n{json.dumps(selected_articles, indent=2)}"}]
        )
        final_report = debate_response.messages[-1]["content"]
        final_results['final_report'] = final_report
        notify({"step": "synthesis", "status": "completed", "data": final_report})
    except Exception as e:
        logger.exception("Error in Synthesis step")
        notify({"step": "error", "message": f"Synthesis failed: {e}"})
        return False

    # Step 6: Creative Editor
    try:
        logger.info("🎨 Running Creative Editor Agent...")
        notify({"step": "editing", "status": "running", "message": "🎨 Applying a creative touch..."})
        creative_editor_agent_instance = create_creative_editor_agent(focus, depth, tone)
        creative_response = client.run(
            agent=creative_editor_agent_instance,
            messages=[{"role": "user", "content": f"Rewrite this report:\n{final_report}"}]
        )
        creative_report = creative_response.messages[-1]["content"]
        final_results['creative_report'] = creative_report
        notify({"step": "editing", "status": "completed", "data": creative_report})
    except Exception as e:
        logger.exception("Error in Editing step")
        notify({"step": "error", "message": f"Editing failed: {e}"})
        return False
        
    return final_results

