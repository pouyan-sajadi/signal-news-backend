from swarm import Agent
from .prompts import search_prompt, get_profiler_prompt, get_diversity_prompt, get_synthesizer_prompt, get_creative_editor_prompt
from app.config import MODEL

def create_search_agent():
    return Agent(
        name="Search Query Refiner",
        instructions=search_prompt,
        model=MODEL
    )

def create_source_profiler_agent(focus: str):
    return Agent(
        name="Source Profiler",
        instructions=get_profiler_prompt(focus),
        model=MODEL
    )

def create_diversity_selector_agent(focus: str, depth: int):
    return Agent(
        name="Diversity Selector",
        instructions=get_diversity_prompt(focus, depth),
        model=MODEL
    )

def create_debate_synthesizer_agent(focus: str, depth: int):
    return Agent(
        name="Debate Synthesizer",
        instructions=get_synthesizer_prompt(focus, depth),
        model=MODEL
    )

def create_creative_editor_agent(focus: str, depth: int, tone: str):
    return Agent(
        name="Creative Editor",
        instructions=get_creative_editor_prompt(focus, depth, tone),
        model=MODEL
    )