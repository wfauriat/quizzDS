"""Static HTML rendering of a deck, for reading and reviewing it (not the quiz UI).

Answers, per-choice notes and explanations are collapsed by default to avoid spoilers.
"""

from __future__ import annotations

from collections import Counter
from html import escape

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from quizz.decks import ROOT
from quizz.models import Deck, Question

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
  --ok: #2f9e44; --ok-bg: #ebfbee; --ko: #c92a2a; --on-status: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111418; --card: #1a1e24; --text: #e3e6ea; --muted: #9aa4b1; --border: #2c323b;
    --accent: #8ea2ff; --chip: #262b33; --code-bg: #0d1117;
    --ok: #51cf66; --ok-bg: #16281b; --ko: #ff8787; --on-status: #111418;
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


def _question(n: int, q: Question, reveal: bool) -> str:
    chips = "".join(f'<span class="chip">{escape(c)}</span>' for c in (q.domain, q.topic, f"L{q.level}", q.kind))
    if q.type == "multi":
        chips += '<span class="chip multi">select all that apply</span>'
    return (
        f'<article class="q" id="{q.id}">'
        f'<header><span class="num">{n}.</span>{chips}<a class="qid" href="#{q.id}">{q.id}</a></header>'
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


def render_deck(deck: Deck, reveal: bool = False) -> str:
    """Return a self-contained HTML page for ``deck``."""
    meta = " · ".join(escape(x) for x in (deck.id, f"{len(deck.questions)} questions", deck.author) if x)
    questions = "".join(_question(i, q, reveal) for i, q in enumerate(deck.questions, start=1))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(deck.title)}</title>
<style>{_pygments_css()}{CSS}</style>
<script>{SCRIPT}</script>
</head>
<body>
<main>
<h1>{escape(deck.title)}</h1>
<p class="meta">{meta}</p>
<div class="md">{_md.render(deck.description)}</div>
{_distribution(deck)}
<div class="toolbar">
  <button type="button" onclick="setAll(true)">Reveal all</button>
  <button type="button" onclick="setAll(false)">Hide all</button>
</div>
{questions}
</main>
</body>
</html>
"""
