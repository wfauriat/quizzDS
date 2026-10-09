import { useEffect, useState } from "react";
import { api, type SessionInfo } from "../api";
import { formatDuration } from "../labels";

interface Props {
  onOpen: (sessionId: number) => Promise<void>;
}

/** Past sessions, newest first; click one to review it in the summary view. */
export function History({ onOpen }: Props) {
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState<number | null>(null);

  useEffect(() => {
    api.listSessions().then(setSessions, (e: Error) => setError(e.message));
  }, []);

  async function remove(s: SessionInfo) {
    const what = s.finished_at
      ? `this finished ${s.mode} session (${s.n_correct}/${s.n_questions})`
      : "this unfinished session";
    const answers = s.n_answered ? ` and its ${s.n_answered} answer${s.n_answered === 1 ? "" : "s"}` : "";
    if (!window.confirm(`Delete ${what}${answers} from the history? This can't be undone.`)) return;
    setError(null);
    try {
      await api.deleteSession(s.session_id);
      setSessions((list) => list && list.filter((x) => x.session_id !== s.session_id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function open(sessionId: number) {
    setOpening(sessionId);
    setError(null);
    try {
      await onOpen(sessionId);
    } catch (e) {
      setError((e as Error).message);
      setOpening(null);
    }
  }

  if (!sessions) return error ? <p className="error">{error}</p> : <p className="muted">Loading history…</p>;

  return (
    <div className="history">
      <h1>History</h1>
      {error && <p className="error">{error}</p>}
      {sessions.length === 0 ? (
        <p className="muted">No session yet: start a deck to build your history.</p>
      ) : (
        <div className="card session-list">
          {sessions.map((s) => (
            <SessionRow
              key={s.session_id}
              session={s}
              busy={opening !== null}
              onOpen={() => open(s.session_id)}
              onDelete={() => remove(s)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  session: SessionInfo;
  busy: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

function SessionRow({ session: s, busy, onOpen, onDelete }: RowProps) {
  // An unfinished exam can't be reviewed: its answers are only revealed once it is finished.
  const locked = s.mode === "exam" && !s.finished_at;
  const pct = Math.round((100 * s.n_correct) / s.n_questions);
  const when = new Date(s.started_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const duration = s.finished_at
    ? formatDuration(Date.parse(s.finished_at) - Date.parse(s.started_at))
    : `unfinished · ${s.n_answered}/${s.n_questions} answered`;
  return (
    <div className="session-row">
      <button type="button" className="session-open" onClick={onOpen} disabled={locked || busy}>
        <span className="session-main">
          <span className="session-title">{s.deck_title}</span>
          <span className="session-meta">
            #{s.session_id} · {when} · <span className={`mode mode-${s.mode}`}>{s.mode}</span> · {duration}
          </span>
        </span>
        <span className="session-score">
          <strong>
            {s.n_correct}/{s.n_questions}
          </strong>
          <span className="muted">{pct}%</span>
        </span>
        <span className="session-go">{locked ? "locked" : "Review →"}</span>
      </button>
      <button
        type="button"
        className="session-delete"
        onClick={onDelete}
        disabled={busy}
        title="Delete this session"
        aria-label={`Delete session ${s.session_id}`}
      >
        ×
      </button>
    </div>
  );
}
