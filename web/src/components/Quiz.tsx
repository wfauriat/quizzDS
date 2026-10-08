import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Confidence, type Feedback, type SessionOut, type Summary } from "../api";
import { CONFIDENCE_OPTIONS, letter } from "../labels";
import { ChoiceCard, revealState } from "./ChoiceCard";
import { Markdown } from "./Markdown";
import { QuestionMeta } from "./QuestionMeta";

type Phase = "answering" | "submitting" | "revealed" | "finishing";

interface Props {
  session: SessionOut;
  deckTitle: string;
  onFinished: (summary: Summary) => void;
}

function shuffled<T>(items: T[]): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function Quiz({ session, deckTitle, onFinished }: Props) {
  const { questions, mode, session_id } = session;
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [confidence, setConfidence] = useState<Confidence | null>(null);
  const [phase, setPhase] = useState<Phase>("answering");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shownAt = useRef(performance.now());

  // Choice order is shuffled once per session; answers are stored by choice id.
  const choiceOrder = useMemo(() => new Map(questions.map((q) => [q.id, shuffled(q.choices)])), [questions]);

  const question = questions[index];
  const choices = choiceOrder.get(question.id)!;
  const isLast = index === questions.length - 1;
  const canSubmit = phase === "answering" && selected.length > 0 && confidence !== null;

  useEffect(() => {
    shownAt.current = performance.now();
    window.scrollTo({ top: 0 });
  }, [index]);

  function toggle(choiceId: string) {
    if (phase !== "answering") return;
    setSelected((prev) => {
      if (question.type === "single") return [choiceId];
      return prev.includes(choiceId) ? prev.filter((id) => id !== choiceId) : [...prev, choiceId];
    });
  }

  async function finish() {
    const previous = phase;
    setPhase("finishing");
    setError(null);
    try {
      onFinished(await api.finish(session_id));
    } catch (e) {
      setError((e as Error).message);
      setPhase(previous);
    }
  }

  function next() {
    if (isLast) return void finish();
    setIndex((i) => i + 1);
    setSelected([]);
    setConfidence(null);
    setFeedback(null);
    setPhase("answering");
  }

  async function submit() {
    if (!canSubmit || confidence === null) return;
    setPhase("submitting");
    setError(null);
    try {
      const fb = await api.answer(session_id, {
        question_id: question.id,
        selected,
        confidence,
        time_ms: Math.round(performance.now() - shownAt.current),
      });
      if (mode === "learn") {
        setFeedback(fb);
        setPhase("revealed");
      } else {
        next();
      }
    } catch (e) {
      setError((e as Error).message);
      setPhase("answering");
    }
  }

  function quit() {
    const answered = phase === "revealed" ? index + 1 : index;
    const left = questions.length - answered;
    if (window.confirm(`End the session now? ${left} unanswered question(s) will count as skipped.`)) {
      void finish();
    }
  }

  // Keyboard: 1-6 or A-F pick a choice, G/U/S set confidence, Enter submits / goes on.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "Enter") {
        e.preventDefault(); // don't also "click" a focused button
        if (phase === "answering") void submit();
        else if (phase === "revealed") next();
        return;
      }
      const key = e.key.toLowerCase();
      if (key.length !== 1) return;
      const pos = "123456".includes(key) ? "123456".indexOf(key) : "abcdef".indexOf(key);
      if (pos >= 0 && pos < choices.length) return toggle(choices[pos].id);
      const conf = CONFIDENCE_OPTIONS.find((o) => o.key.toLowerCase() === key);
      if (conf && phase === "answering") setConfidence(conf.value);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const revealed = phase === "revealed" || (phase === "finishing" && feedback !== null);
  const progress = ((revealed || phase === "finishing" ? index + 1 : index) / questions.length) * 100;

  return (
    <div className="quiz">
      <div className="quiz-top">
        <span className="muted">
          {deckTitle} · <span className={`mode mode-${mode}`}>{mode}</span>
        </span>
        <button type="button" className="link" onClick={quit} disabled={phase === "finishing"}>
          End session
        </button>
      </div>
      <div className="progress" aria-label={`Question ${index + 1} of ${questions.length}`}>
        <div className="progress-bar" style={{ width: `${progress}%` }} />
      </div>

      <article className="card question">
        <header className="question-head">
          <span className="question-num">
            {index + 1} <span className="muted">/ {questions.length}</span>
          </span>
          <QuestionMeta question={question} />
        </header>

        <Markdown>{question.prompt}</Markdown>

        <div className="choices">
          {choices.map((c, i) => (
            <ChoiceCard
              key={c.id}
              letter={letter(i)}
              text={c.text}
              multi={question.type === "multi"}
              state={
                revealed && feedback?.answer
                  ? revealState(c.id, selected, feedback.answer)
                  : selected.includes(c.id)
                    ? "selected"
                    : "idle"
              }
              why={revealed ? feedback?.why?.[c.id] : undefined}
              onClick={phase === "answering" ? () => toggle(c.id) : undefined}
            />
          ))}
        </div>

        {revealed && feedback ? (
          <div className={`verdict ${feedback.is_correct ? "verdict-ok" : "verdict-ko"}`}>
            <strong>{feedback.is_correct ? "Correct" : "Not quite"}</strong>
            {feedback.explanation && <Markdown>{feedback.explanation}</Markdown>}
          </div>
        ) : (
          <div className="confidence">
            <span className="muted">How sure are you?</span>
            <div className="segmented" role="radiogroup" aria-label="Confidence">
              {CONFIDENCE_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  role="radio"
                  aria-checked={confidence === o.value}
                  className={confidence === o.value ? "active" : ""}
                  disabled={phase !== "answering"}
                  onClick={() => setConfidence(o.value)}
                >
                  {o.label} <kbd>{o.key}</kbd>
                </button>
              ))}
            </div>
          </div>
        )}

        {error && <p className="error">{error}</p>}

        <footer className="question-foot">
          <span className="hint">
            {phase === "answering" ? (
              <>
                <kbd>1</kbd>–<kbd>{choices.length}</kbd> choose · <kbd>G</kbd> <kbd>U</kbd> <kbd>S</kbd> confidence ·{" "}
                <kbd>Enter</kbd> submit
              </>
            ) : (
              <>
                <kbd>Enter</kbd> {isLast ? "finish" : "next"}
              </>
            )}
          </span>
          {revealed ? (
            <button type="button" className="btn btn-primary" onClick={next} disabled={phase === "finishing"}>
              {isLast ? "See results" : "Next question →"}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => void submit()} disabled={!canSubmit}>
              {phase === "submitting" || phase === "finishing" ? "Saving…" : isLast && mode === "exam" ? "Submit & finish" : "Submit"}
            </button>
          )}
        </footer>
      </article>
    </div>
  );
}
