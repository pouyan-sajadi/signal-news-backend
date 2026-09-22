from dataclasses import dataclass

from .prompts import (
    search_prompt,
    get_profiler_prompt,
    get_diversity_prompt,
    get_synthesizer_prompt,
    get_creative_editor_prompt,
)


@dataclass(frozen=True)
class AgentConfig:
    """Provider- and orchestration-independent agent configuration."""

    name: str
    instructions: str


def create_search_agent() -> AgentConfig:
    return AgentConfig(
        name="Search Query Refiner",
        instructions=search_prompt,
    )


def create_source_profiler_agent(focus: str) -> AgentConfig:
    return AgentConfig(
        name="Source Profiler",
        instructions=get_profiler_prompt(focus),
    )


def create_diversity_selector_agent(focus: str, depth: int) -> AgentConfig:
    return AgentConfig(
        name="Diversity Selector",
        instructions=get_diversity_prompt(focus, depth),
    )


def create_debate_synthesizer_agent(focus: str, depth: int) -> AgentConfig:
    return AgentConfig(
        name="Debate Synthesizer",
        instructions=get_synthesizer_prompt(focus, depth),
    )


def create_creative_editor_agent(
    focus: str, depth: int, tone: str
) -> AgentConfig:
    return AgentConfig(
        name="Creative Editor",
        instructions=get_creative_editor_prompt(focus, depth, tone),
    )
