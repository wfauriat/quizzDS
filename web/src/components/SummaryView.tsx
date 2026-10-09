import type { Bucket, ReviewItem, Summary } from "../api";
import { confidenceLabel, domainLabel, formatDuration, LEVEL_LABELS, letter } from "../labels";
import { ChoiceCard, revealState } from "./ChoiceCard";
import { Markdown } from "./Markdown";
import { QuestionMeta } from "./QuestionMeta";

interface Props {
  summary: Summary;
  backLabel: string;
  onBack: () => void;
}

export function SummaryView({ summary, backLabel, onBack }: Props) {
  const pct = Math.round((100 * summary.n_correct) / summary.n_questions);
  const answered = summary.items.filter((i) => i.is_correct !== null);
  const sureWrong = answered.filter((i) => i.confidence === 3 && !i.is_correct).length;
  const guessedRight = answered.filter((i) => i.confidence === 1 && i.is_correct).length;
  const duration =
    summary.finished_at && Date.parse(summary.finished_at) - Date.parse(summary.started_at);
  const when = new Date(summary.started_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  return (
    <div className="summary">
      <p className="muted">
        {summary.deck_title} · <span className={`mode mode-${summary.mode}`}>{summary.mode}</span> · {when}
        {duration ? ` · ${formatDuration(duration)}` : " · unfinished"}
      </p>

      <section className="card score">
        <div className="score-main">
          <span className="score-value">{pct}%</span>
          <span className="muted">
            {summary.n_correct} / {summary.n_questions} correct
          </span>
        </div>
        <div className="stats">
          <Stat value={`${summary.n_answered}/${summary.n_questions}`} label="answered" />
          <Stat value={sureWrong} label="sure but wrong" tone={sureWrong ? "ko" : undefined} />
          <Stat value={guessedRight} label="guessed right" />
        </div>
      </section>

      <div className="breakdowns">
        <section className="card">
          <h3>By domain</h3>
          <Bars buckets={summary.by_domain} label={domainLabel} />
        </section>
        <section className="card">
          <h3>By level</h3>
          <Bars buckets={summary.by_level} label={(k) => LEVEL_LABELS[k] ?? `L${k}`} />
        </section>
      </div>

      <h2>Review</h2>
      <div className="review">
        {summary.items.map((item, i) => (
          <ReviewCard key={item.question.id} item={item} number={i + 1} />
        ))}
      </div>

      <button type="button" className="btn btn-primary" onClick={onBack}>
        ← {backLabel}
      </button>
    </div>
  );
}

function Stat({ value, label, tone }: { value: string | number; label: string; tone?: "ko" }) {
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ""}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

function Bars({ buckets, label }: { buckets: Bucket[]; label: (key: string) => string }) {
  return (
    <div className="bars">
      {buckets.map((b) => (
        <div key={b.key} className="bar-row">
          <span className="bar-label">{label(b.key)}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(100 * b.correct) / b.n}%` }} />
          </span>
          <span className="bar-value">
            {b.correct}/{b.n}
          </span>
        </div>
      ))}
    </div>
  );
}

function ReviewCard({ item, number }: { item: ReviewItem; number: number }) {
  const { question: q, selected, is_correct } = item;
  const status = is_correct === null ? "skipped" : is_correct ? "ok" : "ko";
  const icon = { ok: "✓", ko: "✗", skipped: "–" }[status];
  return (
    <details className={`card review-item review-${status}`} open={status === "ko"}>
      <summary>
        <span className="review-icon">{icon}</span>
        <span className="question-num">{number}</span>
        <QuestionMeta question={q} />
        <span className="review-extra muted">
          {status === "skipped"
            ? "skipped"
            : `${confidenceLabel(item.confidence)} · ${formatDuration(item.time_ms ?? 0)}`}
        </span>
      </summary>
      <Markdown>{q.prompt}</Markdown>
      <div className="choices">
        {q.choices.map((c, i) => (
          <ChoiceCard
            key={c.id}
            letter={letter(i)}
            text={c.text}
            multi={q.type === "multi"}
            state={revealState(c.id, selected ?? [], q.answer)}
            why={c.why}
          />
        ))}
      </div>
      <div className="explanation">
        <Markdown>{q.explanation}</Markdown>
      </div>
    </details>
  );
}
