"""Static HTML pages: a deck, for reading it (answers collapsed to avoid spoilers), and a past
session's results, for reviewing it offline (the same content as the UI summary).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from html import escape

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from quizz.decks import ROOT
from quizz.models import DOMAIN_LABELS, Deck, Question, level_label
from quizz.service import Bucket, ReviewItem, Summary

RENDER_DIR = ROOT / "data" / "render"


def _highlight(code: str, lang: str, _attrs: str) -> str:
    if lang == "sql" and ("{{" in code or "{%" in code):
        lang = "sql+jinja"  # dbt models
    try:
        lexer = get_lexer_by_name(lang)
    except ClassNotFound:
        return ""  # markdown-it then falls back to plain escaped text
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


_md = MarkdownIt("commonmark", {"html": False, "highlight": _highlight}).enable("table")


def _pygments_css() -> str:
    light = HtmlFormatter(style="default").get_style_defs(".md pre")
    dark = HtmlFormatter(style="github-dark").get_style_defs(".md pre")
    return f"{light}\n@media (prefers-color-scheme: dark) {{\n{dark}\n}}\n"


CSS = """
:root {
  color-scheme: light dark;
  --bg: #f6f7f9; --card: #ffffff; --text: #1d2330; --muted: #5f6b7a; --border: #dde1e7;
  --accent: #3b5bdb; --chip: #eef1f6; --code-bg: #f3f4f6;
  --ok: #2f9e44; --ok-bg: #ebfbee; --ko: #c92a2a; --ko-bg: #fff5f5; --on-status: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111418; --card: #1a1e24; --text: #e3e6ea; --muted: #9aa4b1; --border: #2c323b;
    --accent: #8ea2ff; --chip: #262b33; --code-bg: #0d1117;
    --ok: #51cf66; --ok-bg: #16281b; --ko: #ff8787; --ko-bg: #2f1719; --on-status: #111418;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 820px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
.meta { color: var(--muted); margin: 0 0 12px; }
.dist { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0; }
.dist b { width: 64px; font-size: 12px; color: var(--muted); font-weight: 600; }
.toolbar { display: flex; gap: 8px; margin: 16px 0 8px; }
button {
  font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--card); color: var(--text);
}
button:hover { border-color: var(--accent); }
.q {
  background: var(--card); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px 20px; margin: 16px 0;
}
.q header { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
.num { font-weight: 700; margin-right: 4px; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--chip); color: var(--muted); }
.chip.multi { color: var(--accent); font-weight: 600; }
.qid { margin-left: auto; font: 12px ui-monospace, monospace; color: var(--muted); text-decoration: none; }
.md p { margin: 0.5em 0; }
.md pre {
  background: var(--code-bg); padding: 10px 12px; border-radius: 8px; overflow-x: auto;
  font-size: 13px; line-height: 1.45;
}
.md pre .err { border: none; background: none; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; }
:not(pre) > code { background: var(--chip); padding: 1px 5px; border-radius: 4px; }
.choices, .whys { list-style: none; padding: 0; display: grid; }
.choices { margin: 12px 0; gap: 8px; }
.choice {
  display: flex; gap: 10px; align-items: baseline;
  border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px;
}
.letter {
  flex: none; display: inline-grid; place-items: center; width: 22px; height: 22px;
  border-radius: 6px; font-size: 12px; font-weight: 700; background: var(--chip);
}
.q:has(details[open]) .choice.correct { border-color: var(--ok); background: var(--ok-bg); }
.q:has(details[open]) .choice.correct .letter, .whys .ok .letter { background: var(--ok); color: var(--on-status); }
.whys .ko .letter { background: var(--ko); color: var(--on-status); }
details { border-top: 1px dashed var(--border); padding-top: 10px; }
summary { cursor: pointer; color: var(--accent); font-weight: 600; }
.whys { margin: 10px 0; gap: 6px; }
.whys li { display: flex; gap: 10px; align-items: baseline; color: var(--muted); }
.explanation { border-left: 3px solid var(--accent); padding-left: 12px; margin-top: 10px; }
"""

SCRIPT = """
function setAll(open) { document.querySelectorAll('details').forEach(d => d.open = open); }
"""


def _choices(q: Question) -> str:
    items = []
    for c in q.choices:
        cls = "choice correct" if c.id in q.answer else "choice"
        items.append(
            f'<li class="{cls}"><span class="letter">{c.id.upper()}</span>'
            f"<span>{_md.renderInline(c.text)}</span></li>"
        )
    return f'<ol class="choices">{"".join(items)}</ol>'


def _reveal(q: Question, reveal: bool) -> str:
    whys = "".join(
        f'<li class="{"ok" if c.id in q.answer else "ko"}"><span class="letter">{c.id.upper()}</span>'
        f"<span>{_md.renderInline(c.why) if c.why else '—'}</span></li>"
        for c in q.choices
    )
    answer = ", ".join(a.upper() for a in q.answer)
    return (
        f"<details{' open' if reveal else ''}><summary>Answer &amp; explanation</summary>"
        f"<p><strong>Answer: {answer}</strong></p>"
        f'<ul class="whys">{whys}</ul>'
        f'<div class="md explanation">{_md.render(q.explanation)}</div></details>'
    )


def _chips(q: Question) -> str:
    chips = "".join(f'<span class="chip">{escape(c)}</span>' for c in (q.domain, q.topic, f"L{q.level}", q.kind))
    if q.type == "multi":
        chips += '<span class="chip multi">select all that apply</span>'
    return chips


def _question(n: int, q: Question, reveal: bool) -> str:
    return (
        f'<article class="q" id="{q.id}">'
        f'<header><span class="num">{n}.</span>{_chips(q)}<a class="qid" href="#{q.id}">{q.id}</a></header>'
        f'<div class="md">{_md.render(q.prompt)}</div>'
        f"{_choices(q)}{_reveal(q, reveal)}</article>"
    )


def _distribution(deck: Deck) -> str:
    rows = []
    for axis in ("domain", "level", "kind", "type"):
        counts = sorted(Counter(getattr(q, axis) for q in deck.questions).items())
        chips = "".join(f'<span class="chip">{escape(str(k))} · {n}</span>' for k, n in counts)
        rows.append(f'<div class="dist"><b>{axis}</b>{chips}</div>')
    return "".join(rows)


def _page(title: str, body: str, css: str = CSS) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{_pygments_css()}{css}</style>
<script>{SCRIPT}</script>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def render_deck(deck: Deck, reveal: bool = False) -> str:
    """Return a self-contained HTML page for ``deck``."""
    meta = " · ".join(escape(x) for x in (deck.id, f"{len(deck.questions)} questions", deck.author) if x)
    questions = "".join(_question(i, q, reveal) for i, q in enumerate(deck.questions, start=1))
    body = f"""<h1>{escape(deck.title)}</h1>
<p class="meta">{meta}</p>
<div class="md">{_md.render(deck.description)}</div>
{_distribution(deck)}
<div class="toolbar">
  <button type="button" onclick="setAll(true)">Reveal all</button>
  <button type="button" onclick="setAll(false)">Hide all</button>
</div>
{questions}"""
    return _page(deck.title, body)


# ---------------------------------------------------------------- past session (same content as the UI summary)

CONFIDENCE_LABELS = {1: "Guess", 2: "Unsure", 3: "Sure"}
_STATE_TAGS = {"correct": "✓ your answer", "wrong": "✗ your answer", "missed": "correct answer"}

SESSION_CSS = """
.muted { color: var(--muted); }
.score {
  display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 20px;
  background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin: 16px 0;
}
.score-value { font-size: 2.6rem; font-weight: 800; line-height: 1.1; }
.stats { display: flex; gap: 28px; }
.stat { display: grid; text-align: center; }
.stat b { font-size: 1.4rem; }
.stat span { font-size: 12px; color: var(--muted); }
.stat.ko b { color: var(--ko); }
.breakdowns { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; }
.panel h3 { margin: 0 0 10px; font-size: 0.95rem; }
.bar-row {
  display: grid; grid-template-columns: 130px minmax(0, 1fr) 36px; gap: 10px; align-items: center;
  font-size: 13px; margin: 6px 0;
}
.bar-track { height: 8px; border-radius: 999px; background: var(--chip); overflow: hidden; }
.bar-fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
.bar-value { text-align: right; color: var(--muted); }
.toolbar { align-items: center; margin-top: 28px; }
.toolbar h2 { margin: 0 auto 0 0; font-size: 1.15rem; }
details.q > summary {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px; list-style: none;
  color: var(--text); font-weight: normal;
}
details.q > summary::-webkit-details-marker { display: none; }
details.q[open] > summary { margin-bottom: 10px; }
.status {
  display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 50%;
  font-size: 12px; font-weight: 700; color: var(--on-status); background: var(--muted);
}
.status.ok { background: var(--ok); }
.status.ko { background: var(--ko); }
.extra { margin-left: auto; font-size: 13px; color: var(--muted); }
.choice .body { flex: 1; min-width: 0; display: grid; gap: 2px; }
.why { font-size: 13px; color: var(--muted); }
.tag { flex: none; align-self: center; font-size: 11px; font-weight: 700; text-transform: uppercase; }
.state-correct, .state-missed { border-color: var(--ok); background: var(--ok-bg); }
.state-missed { border-style: dashed; }
.state-wrong { border-color: var(--ko); background: var(--ko-bg); }
.state-neutral { opacity: 0.7; }
.state-correct .letter { background: var(--ok); color: var(--on-status); }
.state-wrong .letter { background: var(--ko); color: var(--on-status); }
.state-missed .letter { box-shadow: inset 0 0 0 1.5px var(--ok); color: var(--ok); }
.state-correct .tag, .state-missed .tag { color: var(--ok); }
.state-wrong .tag { color: var(--ko); }
"""


def _local_time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")


def _seconds(ms: int | None) -> str:
    s = round((ms or 0) / 1000)
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def _stat(value: object, label: str, tone: str = "") -> str:
    return f'<div class="stat {tone}"><b>{value}</b><span>{label}</span></div>'


def _bars(title: str, buckets: list[Bucket], label: Callable[[str], str]) -> str:
    rows = "".join(
        f'<div class="bar-row"><span>{escape(label(b.key))}</span><span class="bar-track">'
        f'<span class="bar-fill" style="width: {100 * b.correct / b.n:.0f}%"></span></span>'
        f'<span class="bar-value">{b.correct}/{b.n}</span></div>'
        for b in buckets
    )
    return f'<section class="panel"><h3>{title}</h3>{rows}</section>'


def _review_choice(choice_id: str, text: str, why: str | None, selected: list[str], answer: list[str]) -> str:
    picked, right = choice_id in selected, choice_id in answer
    state = ("correct" if picked else "missed") if right else ("wrong" if picked else "neutral")
    why_html = f'<span class="why">{_md.renderInline(why)}</span>' if why else ""
    tag = f'<span class="tag">{_STATE_TAGS[state]}</span>' if state in _STATE_TAGS else ""
    return (
        f'<li class="choice state-{state}"><span class="letter">{choice_id.upper()}</span>'
        f'<span class="body"><span>{_md.renderInline(text)}</span>{why_html}</span>{tag}</li>'
    )


def _review_item(n: int, item: ReviewItem) -> str:
    q = item.question
    status = "skipped" if item.is_correct is None else "ok" if item.is_correct else "ko"
    icon = {"ok": "✓", "ko": "✗", "skipped": "–"}[status]
    extra = (
        "skipped"
        if item.is_correct is None
        else f"{CONFIDENCE_LABELS.get(item.confidence or 0, '—')} · {_seconds(item.time_ms)}"
    )
    choices = "".join(_review_choice(c.id, c.text, c.why, item.selected or [], q.answer) for c in q.choices)
    return (
        f'<details class="q review-{status}" id="{q.id}"{" open" if status == "ko" else ""}>'
        f'<summary><span class="status {status}">{icon}</span><span class="num">{n}.</span>{_chips(q)}'
        f'<span class="extra">{extra}</span></summary>'
        f'<div class="md">{_md.render(q.prompt)}</div>'
        f'<ol class="choices">{choices}</ol>'
        f'<div class="md explanation">{_md.render(q.explanation)}</div></details>'
    )


def render_session(summary: Summary) -> str:
    """Return a self-contained HTML page with a session's results, like the UI summary screen."""
    s = summary
    answered = [i for i in s.items if i.is_correct is not None]
    sure_wrong = sum(i.confidence == 3 and not i.is_correct for i in answered)
    guessed_right = sum(i.confidence == 1 and bool(i.is_correct) for i in answered)
    meta = [f"session {s.session_id}", s.mode, _local_time(s.started_at)]
    if s.finished_at:
        elapsed = datetime.fromisoformat(s.finished_at) - datetime.fromisoformat(s.started_at)
        meta.append(_seconds(int(elapsed.total_seconds() * 1000)))
    else:
        meta.append("unfinished")
    body = f"""<h1>{escape(s.deck_title)}</h1>
<p class="meta">{" · ".join(meta)}</p>
<section class="score">
  <div>
    <div class="score-value">{100 * s.n_correct / s.n_questions:.0f}%</div>
    <div class="muted">{s.n_correct} / {s.n_questions} correct</div>
  </div>
  <div class="stats">
    {_stat(f"{s.n_answered}/{s.n_questions}", "answered")}
    {_stat(sure_wrong, "sure but wrong", "ko" if sure_wrong else "")}
    {_stat(guessed_right, "guessed right")}
  </div>
</section>
<div class="breakdowns">
  {_bars("By domain", s.by_domain, lambda k: DOMAIN_LABELS.get(k, k))}
  {_bars("By level", s.by_level, level_label)}
</div>
<div class="toolbar">
  <h2>Review</h2>
  <button type="button" onclick="setAll(true)">Expand all</button>
  <button type="button" onclick="setAll(false)">Collapse all</button>
</div>
{"".join(_review_item(n, item) for n, item in enumerate(s.items, start=1))}"""
    return _page(f"{s.deck_title} — session {s.session_id}", body, CSS + SESSION_CSS)
