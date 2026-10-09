"""Content layer: the schema of a question deck.

Decks are authored as YAML files in ``decks/`` and validated against these models.
``python -m quizz schema`` exports the JSON Schema to ``decks/deck.schema.json``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
Slug = Annotated[str, Field(pattern=SLUG_PATTERN)]

Domain = Literal["ds", "de", "cs", "swe", "stack", "infra"]
Kind = Literal["concept", "practical", "internals", "design"]
QuestionType = Literal["single", "multi"]

# What the taxonomy means, shared by the HTML pages and the deck-design prompt.
DOMAIN_LABELS: dict[str, str] = {
    "ds": "Data science",
    "de": "Data engineering",
    "cs": "Computer science",
    "swe": "Software engineering",
    "stack": "Modern stack",
    "infra": "Cloud & infra",
}
LEVEL_GUIDE: dict[int, tuple[str, str]] = {
    1: ("junior", "foundations: core definitions and basic usage that anyone in the field should know"),
    2: ("junior+", "common practical situations: standard tools used correctly, classic beginner mistakes"),
    3: ("mid", "applied: realistic scenarios, typical pitfalls, choosing between standard approaches"),
    4: ("senior", "trade-offs and non-obvious behaviour: design decisions, production debugging, performance"),
    5: ("staff", "deep internals and edge cases: subtle semantics, failure modes, guarantees and their limits"),
}
KIND_GUIDE: dict[str, str] = {
    "concept": "understanding an idea, a definition or a principle",
    "practical": "hands-on usage: code, queries, commands, configuration, debugging",
    "internals": "how a tool, system or algorithm works underneath",
    "design": "architecture and trade-off decisions",
}


def level_label(level: int | str) -> str:
    """E.g. "L3 · mid"."""
    name = LEVEL_GUIDE.get(int(level), ("?", ""))[0]
    return f"L{level} · {name}"


class _Strict(BaseModel):
    # A misspelled field name is an error instead of being silently dropped.
    model_config = ConfigDict(extra="forbid")


class Choice(_Strict):
    id: str = Field(pattern=r"^[a-z]$", description="Stable choice id (a, b, c...); `answer` refers to it.")
    text: str = Field(min_length=1, description="Markdown.")
    why: str | None = Field(None, description="Why this choice is right or wrong, shown after answering.")


class Question(_Strict):
    id: Slug = Field(
        description="Globally unique and stable, e.g. `de-sql-001`. Never reuse an id for different content."
    )
    domain: Domain = Field(
        description="Breadth axis, top level: ds = data science/ML, de = data engineering, cs = computer "
        "science, swe = software engineering, stack = modern tooling, infra = cloud/infrastructure."
    )
    topic: Slug = Field(description="Breadth axis, second level, e.g. `sql`, `ml-eval`.")
    tags: list[Slug] = Field(default_factory=list)
    level: int = Field(
        ge=1,
        le=5,
        description="Depth axis: 1 junior/foundations, 2 junior+, 3 mid/applied, 4 senior/trade-offs, "
        "5 staff/edge cases.",
    )
    kind: Kind = Field(
        description="concept = understanding, practical = hands-on usage, internals = how it works "
        "underneath, design = trade-offs/architecture."
    )
    type: QuestionType = Field("single", description="single: one correct choice; multi: select all that apply.")
    prompt: str = Field(min_length=1, description="Markdown; code blocks allowed.")
    choices: list[Choice] = Field(min_length=2, max_length=6)
    answer: list[str] = Field(min_length=1, description="Ids of the correct choices.")
    explanation: str = Field(min_length=1, description="Markdown, shown after answering.")

    @model_validator(mode="after")
    def _check_answer(self) -> Question:
        ids = [c.id for c in self.choices]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate choice ids: {ids}")
        if len(set(self.answer)) != len(self.answer):
            raise ValueError(f"duplicate ids in answer: {self.answer}")
        if unknown := set(self.answer) - set(ids):
            raise ValueError(f"answer refers to unknown choices: {sorted(unknown)}")
        if self.type == "single" and len(self.answer) != 1:
            raise ValueError("a 'single' question needs exactly one answer")
        return self


class Deck(_Strict):
    id: Slug
    title: str = Field(min_length=1)
    description: str = ""
    author: str = ""
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_question_ids(self) -> Deck:
        ids = [q.id for q in self.questions]
        if dupes := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"duplicate question ids: {dupes}")
        return self


def deck_json_schema() -> dict[str, Any]:
    """JSON Schema of a deck file, for editor validation/completion of the YAML."""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **Deck.model_json_schema()}
