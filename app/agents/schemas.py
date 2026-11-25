from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


ProfileText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CoverageRole = Literal["main development", "background", "stakeholder response", "impact", "verification", "outlook"]
EvidenceType = Literal[
    "direct observation",
    "firsthand account",
    "data or study",
    "primary document",
    "on-record statement",
    "expert interpretation",
    "secondary reporting",
]


class SourceProfile(BaseModel):
    """Model judgments about a retrieved article."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    id: str = Field(min_length=1, description="Original article ID copied exactly.")
    perspective: list[ProfileText] = Field(
        description="Short tags about the article's perspective and the requested focus. Use [] if unclear.",
    )
    tone: Literal["neutral", "supportive", "critical", "speculative", "alarmist"] | None = None
    source_type: Literal["news report", "opinion/editorial", "analysis", "press release", "blog/post"] | None = None
    region: ProfileText | None = Field(default=None, description="Geographic focus of the coverage.")
    focus_notes: list[ProfileText] | None = Field(
        default=None,
        description="Brief observations supported by the article and useful for the requested focus.",
    )
    coverage_roles: list[CoverageRole] | None = Field(
        default=None,
        description="The main contributions this article makes to understanding the story.",
    )
    evidence_types: list[EvidenceType] | None = Field(
        default=None,
        description="Kinds of evidence the article actually provides or attributes for its main points.",
    )
    represented_voices: list[ProfileText] | None = Field(
        default=None,
        description="People or groups whose views or experiences the article quotes or attributes.",
    )


class ProfilingResponse(RootModel[list[SourceProfile]]):
    """The profiler's JSON array of article profiles."""

    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    root: list[SourceProfile] = Field(min_length=1)


class SelectionResponse(BaseModel):
    """The selector's response before its IDs are checked against retrieval."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    article_ids: list[str] = Field(
        min_length=1,
        description="Original article IDs copied from the supplied profiles.",
    )
