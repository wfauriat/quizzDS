Here are some instructions on what I want you to help me with.

I want you to quiz me on topics related to data science, data engineering,
computer science, software engineering, modern stacks and possibly a bit of
infra (such as cloud deployement)

I want to be able to track progress, and you or any further session / interaction
to be able to adjust the level of depth and difficult (from junior to senior, from surface to technical,
maybe along a breadth and depth axis also) as you see my current level of answer.
That means, taking care of a "permanance layer" and history across sessions and across quiz, possibly on different
topic or different depth. That means also, doing so posterior analysis on answer, or the
ability for you to do so, to adjust from one session to the next. Maybe, it would be good, if
(maybe not as a first feature to design, but to plan or leave the option open, to display "processed"
metrics or graphs to track progress, in different domain (e.g. a chart with scores))

It is probably good to work a bit on the UI for the quiz. Not something too complex,
but slick enough, say a React-style panel with clickable cards for multiple-choice question / answers

Let us work step by step. You propose, you code feature by feature (or layer by layer), and I validate along the way.
Let us work in close, short interactives phases and progress sequentially.

Maybe let us set the first targer on a the UI, a simple 20 question deck to try it out, a permanance layer (let us discuss
on the form, maybe a simple SQLite file, or a json on disk file, let us talk about it)

---

## Project guide for Claude (maintained by Claude)

### Layout and commands
Run from the repo root with the venv `/opt/venvs/pyDS` (`PY=/opt/venvs/pyDS/bin/python`).

- `decks/*.yaml`: question content (schema in `quizz/models.py`, exported to `decks/deck.schema.json`).
- `data/quizz.sqlite`: answer history (gitignored). Analysis view `v_attempt`; see `quizz/schema.sql`.
- `notes/learner.md`: the learner profile, interpreted by Claude, with a dated analysis log.
- `quizz/`: backend (FastAPI + SQLite). `web/`: React UI (`npm run build` after UI changes).
- `$PY -m quizz serve` runs the app at http://localhost:8000 and imports the decks at startup.
- `$PY -m quizz validate | import | render [deck] | report [--session N] [--deck ID] [--since DATE]`
- `$PY -m quizz sessions` lists past sessions; `review [SESSION]` renders one (default: the latest finished)
  as an HTML page like the UI summary. The UI's History tab shows the same thing.
- `$PY -m pytest -q`

### Session loop
1. Read `notes/learner.md`, then run `$PY -m quizz report`. Accuracy counts first attempts only;
   repeats measure retention.
2. Comment on the new results for the user: confidence calibration, misses and which wrong option
   was picked, patterns by kind and level.
3. Update `notes/learner.md`: refresh the current estimate and add a dated entry to the analysis log.
4. Propose the next deck (levels, topics, breadth vs depth) based on the gaps and on the coverage
   table. Write it once the user agrees.
5. Commit only when the user says so.

### Deck authoring rules
- Question ids follow `<domain>-<topic>-NNN`. They are globally unique and never reused for different
  content. Typos can be fixed in place (revisions are kept by hash), but a changed meaning needs a
  new id.
- Every question needs an `explanation` and a `why` on every choice, usually 4 choices. Multi-select
  prompts say "Select all that apply".
- `validate` lints whether the correct choice is the longest one; aim for 10–40%
  (`tests/test_decks.py` enforces it).
- Never show a deck's questions or answers in chat before the user has taken it.
- After writing a deck, run `validate`, then `import` (a running server picks it up on page reload).
