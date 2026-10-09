import { useEffect, useState } from "react";
import { api, type DeckInfo, type Mode } from "../api";
import { domainLabel } from "../labels";

interface Props {
  onStart: (deck: DeckInfo, mode: Mode) => Promise<void>;
  onReview: (sessionId: number) => Promise<void>;
}

export function DeckList({ onStart, onReview }: Props) {
  const [decks, setDecks] = useState<DeckInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => {
    api.listDecks().then(setDecks, (e: Error) => setError(e.message));
  }, []);

  async function review(sessionId: number) {
    setError(null);
    try {
      await onReview(sessionId);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function start(deck: DeckInfo, mode: Mode) {
    setStarting(`${deck.id}:${mode}`);
    setError(null);
    try {
      await onStart(deck, mode);
    } catch (e) {
      setError((e as Error).message);
      setStarting(null);
    }
  }

  if (!decks) return error ? <p className="error">{error}</p> : <p className="muted">Loading decks…</p>;
  if (decks.length === 0) return <p className="muted">No deck yet: add a YAML file in decks/ and restart the server.</p>;

  return (
    <div className="deck-list">
      <h1>Decks</h1>
      {error && <p className="error">{error}</p>}
      {decks.map((deck) => (
        <article key={deck.id} className="card deck">
          <header className="deck-head">
            <h2>{deck.title}</h2>
            <span className="muted">{deck.n_questions} questions</span>
          </header>
          {deck.description && <p className="deck-desc">{deck.description}</p>}
          <div className="chips">
            {Object.entries(deck.domains).map(([d, n]) => (
              <span key={d} className="chip chip-domain">
                {domainLabel(d)} · {n}
              </span>
            ))}
          </div>
          <div className="chips">
            {Object.entries(deck.levels).map(([level, n]) => (
              <span key={level} className="chip">
                L{level} · {n}
              </span>
            ))}
          </div>
          <LastScore deck={deck} onReview={review} />
          <div className="deck-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={starting !== null}
              onClick={() => start(deck, "learn")}
            >
              Start · Learn mode
            </button>
            <button type="button" className="btn" disabled={starting !== null} onClick={() => start(deck, "exam")}>
              Start · Exam mode
            </button>
          </div>
          <p className="hint">
            Learn: answer and explanation after each question. Exam: no feedback until the end.
          </p>
        </article>
      ))}
    </div>
  );
}

function LastScore({ deck, onReview }: { deck: DeckInfo; onReview: (sessionId: number) => void }) {
  const last = deck.last_finished;
  if (!last) return <p className="deck-last muted">Not taken yet</p>;
  const pct = Math.round((100 * last.n_correct) / last.n_questions);
  const date = new Date(last.finished_at ?? last.started_at).toLocaleDateString();
  return (
    <p className="deck-last">
      Last score: <strong>
        {last.n_correct}/{last.n_questions}
      </strong>{" "}
      ({pct}%) · {last.mode} · {date} ·{" "}
      <button type="button" className="link" onClick={() => onReview(last.session_id)}>
        Review
      </button>
    </p>
  );
}
