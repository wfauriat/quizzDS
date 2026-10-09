"""On-demand deck design.

The Design tab turns a per-domain request (target level, number of questions, optional focus) into
a self-contained prompt for an LLM. The deck the LLM writes is then pasted back and imported here,
with the same checks as a hand-written deck plus the answer-length lint; question ids that clash
with other decks are renumbered.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from quizz.decks import DeckError, length_bias_warning, load_decks
from quizz.models import (
    DOMAIN_GUIDE,
    DOMAIN_LABELS,
    KIND_GUIDE,
    LEVEL_GUIDE,
    Deck,
    Domain,
    Kind,
    Question,
    deck_json_schema,
    level_label,
)
from quizz.service import Conflict, Invalid

DOMAIN_ORDER = list(DOMAIN_LABELS)


class DomainSpec(BaseModel):
    domain: Domain
    level: int = Field(3, ge=1, le=5)
    count: int = Field(0, ge=0, le=50)
    focus: str = Field("", max_length=300, description="Optional topics to cover, e.g. 'Kafka, Spark'.")


class DesignRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    domains: list[DomainSpec]
    spread: bool = Field(False, description="Allow questions one level above or below each target.")
    multi_share: int = Field(15, ge=0, le=100, description="Percentage of 'select all that apply' questions.")
    kinds: dict[Kind, Annotated[int, Field(ge=0)]] | None = Field(
        None, description="Relative weights of the question kinds; null lets the LLM mix them."
    )
    avoid_existing: bool = Field(
        True, description="List the existing questions in the prompt so the new deck doesn't repeat them."
    )

    @model_validator(mode="after")
    def _check(self) -> DesignRequest:
        if len({d.domain for d in self.domains}) != len(self.domains):
            raise ValueError("each domain can appear only once")
        if self.total == 0:
            raise ValueError("ask for at least one question")
        if self.kinds is not None and sum(self.kinds.values()) == 0:
            raise ValueError("at least one kind needs a non-zero weight")
        return self

    @property
    def total(self) -> int:
        return sum(d.count for d in self.domains)


class DesignPrompt(BaseModel):
    deck_id: str
    n_questions: int
    prompt: str


def suggest_deck_id(title: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "custom"
    deck_id, n = base, 2
    while deck_id in taken:
        deck_id, n = f"{base}-{n}", n + 1
    return deck_id


def apportion(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Split ``total`` proportionally to ``weights`` into integers (largest remainder method)."""
    weight_sum = sum(weights.values())
    exact = {k: total * w / weight_sum for k, w in weights.items()}
    counts = {k: int(v) for k, v in exact.items()}
    for k in sorted(exact, key=lambda k: exact[k] - counts[k], reverse=True)[: total - sum(counts.values())]:
        counts[k] += 1
    return counts


EXAMPLE_DECK = """\
id: example-deck
title: "Example deck"
description: >-
  One or two sentences describing what the deck covers.
author: "model-name 2026-01-31"
questions:
  - id: stack-example-001          # <domain>-<topic>-NNN, globally unique
    domain: stack                  # ds | de | mlops | cs | swe | stack | infra
    topic: example                 # lowercase slug
    tags: [lists, sorting]         # lowercase slugs
    level: 2                       # 1-5
    kind: practical                # concept | practical | internals | design
    type: single                   # single | multi
    prompt: |
      What does `x` contain after this line?

      ```python
      x = [3, 1, 2].sort()
      ```
    choices:
      - id: a
        text: "`[1, 2, 3]`"
        why: "That's what `sorted([3, 1, 2])` returns. `list.sort()` sorts in place and returns `None`."
      - id: b
        text: "`None`"
        why: "Correct: `list.sort()` sorts the list in place and returns `None`, which is what `x` receives."
      - id: c
        text: "`[3, 1, 2]`, since the sort happens on a temporary copy"
        why: "No copy is made: the list is sorted in place, but `x` receives the return value, not the list."
      - id: d
        text: "A `TypeError`, because a list literal can't be sorted"
        why: "Any list can be sorted in place; a literal is a normal list object."
    answer: [b]
    explanation: |
      Python methods that mutate an object in place (`sort`, `append`, `reverse`...) return `None`,
      a deliberate convention that separates them from functions returning a new object.
      Use `sorted(iterable)` when you need the sorted result as a value.
"""


def build_prompt(req: DesignRequest, existing: list[Deck], deck_id: str, today: date) -> str:
    """The full prompt asking an LLM to write the requested deck."""
    rows = sorted((d for d in req.domains if d.count), key=lambda d: DOMAIN_ORDER.index(d.domain))
    n = req.total
    table = "\n".join(
        f"| `{d.domain}` | {DOMAIN_LABELS[d.domain]} | {level_label(d.level)} | {d.count} | "
        f"{d.focus.strip() or '—'} |"
        for d in rows
    )
    level_rule = (
        "Each question may be one level above or below its domain's target level, with most of them at the target."
        if req.spread
        else "Every question must be exactly at its domain's target level."
    )
    n_multi = round(n * req.multi_share / 100)
    type_rule = (
        f"{n_multi} `multi` question(s) (\"select all that apply\"), the other {n - n_multi} `single`."
        if n_multi
        else "Only `single` questions (one correct choice each)."
    )
    if req.kinds is None:
        kind_rule = "mix the four kinds as suits each topic."
    else:
        counts = apportion(n, {k: w for k, w in req.kinds.items() if w})
        kind_rule = "about " + ", ".join(f"{c} {k}" for k, c in counts.items() if c) + "."
    domains = "\n".join(f"- `{d}` ({DOMAIN_LABELS[d]}): {text}" for d, text in DOMAIN_GUIDE.items())
    levels = "\n".join(f"- {level_label(lv)}: {text}" for lv, (_, text) in LEVEL_GUIDE.items())
    kinds = "\n".join(f"- `{k}`: {text}" for k, text in KIND_GUIDE.items())
    schema = json.dumps(deck_json_schema(), indent=1, ensure_ascii=False)
    if req.avoid_existing:
        id_rule = (
            'be unique: never reuse an id listed under "Existing questions"; for a topic that already exists,\n'
            "   continue its numbering."
        )
        existing_section = (
            "## Existing questions\n\nDon't reuse these ids, and avoid testing the same facts again:\n\n"
            f"{_existing_questions(existing)}\n\n"
        )
    else:
        id_rule = (
            "be unique within the deck: number each topic's questions from 001 (the app renumbers\n"
            "   ids that other decks already use)."
        )
        existing_section = ""

    return f"""# Write a quiz deck for quizzDS

quizzDS is a personal quiz app for a learner in data science, data engineering, MLOps, computer
science, software engineering, modern tooling, and cloud infrastructure and operations. Decks are
YAML files. The app shuffles the choices, grades the answers, shows each choice's `why` and the
question's `explanation` after answering, and keeps a history used to track progress by domain,
topic and level. Questions must therefore be accurate, unambiguous and pitched at the requested
level.

## The deck to write

- `id`: `{deck_id}` · `title`: "{req.title}" · **{n} questions** in total.
- `author`: your model name and today's date, e.g. "claude-opus-5-5 {today.isoformat()}".
- Order the questions by increasing level.

| domain | meaning | target level | questions | focus |
|---|---|---|---|---|
{table}

- {level_rule}
- When a focus is given, draw that domain's questions from it; otherwise choose varied, relevant
  topics. Within a domain, cover different topics or facets: no two questions should test the same fact.
- Question types: {type_rule}
- Kinds: {kind_rule}

## Domains, levels and kinds

Domains (`domain`): put each question in the domain whose scope it fits. Topics marked
"occasionally" should be a minority of a domain's questions, unless its focus asks for them.
{domains}

Levels (`level`):
{levels}

Kinds (`kind`):
{kinds}

## Writing rules

1. `single` questions have exactly one correct choice. `multi` questions have 2 to 4 correct choices
   among 4 or 5, and their prompt ends with "**Select all that apply.**"
2. Usually 4 choices (2 to 6 allowed), with ids `a`, `b`, `c`... Distractors must be plausible:
   typical misconceptions, half-truths, confusions between neighbouring concepts. No joke options,
   no "all of the above".
3. Don't give the answer away by its form: keep the choices similar in length and style. The
   correct choice must **not** usually be the longest one: across the deck, it should be the longest
   in only about 10-40% of the single-answer questions. The importer rejects decks outside that range.
4. Every choice has a `why`: one or two sentences on why it is right or wrong. Every question has an
   `explanation` (markdown, 2 to 5 sentences) that teaches the underlying concept and, when useful,
   names the relevant tool, paper or documentation.
5. Prefer concrete scenarios (a code snippet, a query, numbers, a production symptom) to asking for
   definitions. Prompts and choices are markdown; use fenced code blocks with a language tag.
6. Facts must be correct and current. State versions when the behaviour depends on them. If you are
   not sure of a fact, write a different question.
7. Question ids follow `<domain>-<topic>-NNN` (lowercase, hyphens), e.g. `de-streaming-002`. They must
   {id_rule} `topic` and `tags` are lowercase slugs too.
8. Ids, topics and tags must not reveal the answer.

## Format

One YAML document following this JSON Schema:

```json
{schema}
```

An annotated example with one question:

```yaml
{EXAMPLE_DECK}```

{existing_section}## How to deliver

- If you can write files in the quizzDS repository (e.g. Claude Code): write `decks/{deck_id}.yaml`,
  run `/opt/venvs/pyDS/bin/python -m quizz validate` and fix any problem it reports, then run
  `/opt/venvs/pyDS/bin/python -m quizz import`. Reply with the deck's shape only (domains, levels,
  counts): the learner hasn't taken it yet, so don't show questions or answers.
- Otherwise, reply with the YAML document only, in a single ```yaml code block, without any other
  text. The learner pastes it into the app without reading it.
"""


def _existing_questions(decks: list[Deck]) -> str:
    by_topic: dict[tuple[str, str], dict[str, Question]] = {}
    for deck in decks:
        for q in deck.questions:
            by_topic.setdefault((q.domain, q.topic), {})[q.id] = q
    if not by_topic:
        return "(none yet)"
    lines = []
    for domain, topic in sorted(by_topic, key=lambda key: (DOMAIN_ORDER.index(key[0]), key[1])):
        questions = sorted(by_topic[domain, topic].values(), key=lambda q: q.id)
        items = "; ".join(f"`{q.id}` L{q.level} [{', '.join(q.tags)}]" for q in questions)
        lines.append(f"- {domain}/{topic}: {items}")
    return "\n".join(lines)


# ---------------------------------------------------------------- import of a generated deck


def _strip_fences(text: str) -> str:
    """Accept a whole LLM reply: keep only the content of its ```yaml block if there is one."""
    match = re.search(r"```(?:ya?ml)?[ \t]*\n(.*?)\n```", text, flags=re.S)
    return match.group(1) if match else text


def _validation_errors(e: ValidationError, data: object) -> list[str]:
    errors = []
    for err in e.errors():
        loc = err["loc"]
        where = ".".join(str(part) for part in loc) or "deck"
        if len(loc) >= 2 and loc[0] == "questions" and isinstance(loc[1], int) and isinstance(data, dict):
            try:
                where += f" (id {data['questions'][loc[1]]['id']})"
            except (KeyError, IndexError, TypeError):
                pass
        errors.append(f"{where}: {err['msg']}")
    return errors


_NUMBERED_ID = re.compile(r"^(?P<stem>.+)-(?P<n>\d+)$")


def _renumber_clashes(deck: Deck, body: str, known: dict[str, Question]) -> tuple[Deck, str, dict[str, str]]:
    """Give a new number to each question whose id another deck uses for different content.

    The YAML text is edited in place (``id:`` lines only) to keep the LLM's formatting. If that edit
    can't be done safely, nothing is renamed and the clash is reported as an error by the caller.
    """
    clashes = [q.id for q in deck.questions if q.id in known and known[q.id] != q]
    if not clashes:
        return deck, body, {}
    taken = set(known) | {q.id for q in deck.questions}
    renamed: dict[str, str] = {}
    for old in clashes:
        match = _NUMBERED_ID.match(old)
        stem, width = (match["stem"], len(match["n"])) if match else (old, 3)
        numbers = [int(m["n"]) for i in taken if (m := _NUMBERED_ID.match(i)) and m["stem"] == stem]
        new = f"{stem}-{max(numbers, default=0) + 1:0{width}d}"
        taken.add(new)
        renamed[old] = new

    id_line = re.compile(
        r"^(?P<key>[ \t]*(?:-[ \t]+)?id:[ \t]*)(?P<q>[\"']?)(?P<id>" + "|".join(map(re.escape, renamed)) + r")(?P=q)"
        r"(?P<rest>[ \t]*(?:#.*)?)$",
        flags=re.M,
    )
    new_body = id_line.sub(lambda m: f"{m['key']}{m['q']}{renamed[m['id']]}{m['q']}{m['rest']}", body)
    expected = deck.model_copy(
        update={"questions": [q.model_copy(update={"id": renamed.get(q.id, q.id)}) for q in deck.questions]}
    )
    try:
        new_deck = Deck.model_validate(yaml.safe_load(new_body))
    except (yaml.YAMLError, ValidationError):
        return deck, body, {}
    if new_deck != expected:  # e.g. flow-style YAML, or an id line inside a prompt
        return deck, body, {}
    return new_deck, new_body, renamed


def save_generated_deck(text: str, decks_dir: Path, today: date) -> tuple[Deck, Path, dict[str, str]]:
    """Validate a generated deck and save it as ``decks/<id>.yaml``.

    Question ids already used by other decks for different content are renumbered; the third
    value maps each old id to its new one. Raises ``Invalid`` with one problem per line (phrased
    so it can be sent back to the LLM), or ``Conflict`` if the file already exists.
    """
    body = _strip_fences(text).strip()
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as e:
        raise Invalid(f"not valid YAML: {e}") from e
    try:
        deck = Deck.model_validate(data)
    except ValidationError as e:
        raise Invalid("\n".join(_validation_errors(e, data))) from e

    try:
        existing = load_decks(decks_dir)
    except DeckError as e:
        raise Invalid("fix the existing decks first:\n" + "\n".join(e.errors)) from e
    known = {q.id: q for _, d in existing for q in d.questions}
    deck, body, renamed = _renumber_clashes(deck, body, known)
    errors = []
    if deck.id in {d.id for _, d in existing}:
        errors.append(f"deck id {deck.id!r} is already used: choose another `id`")
    errors += [
        f"question id {q.id!r} is already used by a different question: choose a new id"
        for q in deck.questions
        if q.id in known and known[q.id] != q
    ]
    if warning := length_bias_warning(deck):
        errors.append(warning + " (rewrite some choices)")
    if errors:
        raise Invalid("\n".join(errors))

    path = decks_dir / f"{deck.id}.yaml"
    if path.exists():
        raise Conflict(f"{path.name} already exists")
    header = (
        "# yaml-language-server: $schema=./deck.schema.json\n"
        f"# Generated by an LLM from a Design-tab prompt, imported on {today.isoformat()}.\n"
    )
    path.write_text(header + body + "\n", encoding="utf-8")
    return deck, path, renamed
