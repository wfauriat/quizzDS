import { useEffect, useState } from "react";
import {
  api,
  type DesignPrompt,
  type DesignRequest,
  type Domain,
  type DomainSpec,
  type ImportedDeck,
  type Kind,
} from "../api";
import { DOMAIN_LABELS, LEVEL_LABELS } from "../labels";

const DOMAINS = Object.keys(DOMAIN_LABELS) as Domain[];
const KINDS: Kind[] = ["concept", "practical", "internals", "design"];
const STORAGE_KEY = "quizz.design";

interface Form {
  title: string;
  domains: DomainSpec[];
  spread: boolean;
  multiShare: number;
  customKinds: boolean;
  kinds: Record<Kind, number>;
}

const DEFAULT_FORM: Form = {
  title: "",
  domains: DOMAINS.map((domain) => ({ domain, level: 3, count: 2, focus: "" })),
  spread: false,
  multiShare: 15,
  customKinds: false,
  kinds: { concept: 25, practical: 25, internals: 25, design: 25 },
};

// The last design is remembered in this browser only (a convenience, not data).
function loadForm(): Form {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? { ...DEFAULT_FORM, ...JSON.parse(saved) } : DEFAULT_FORM;
  } catch {
    return DEFAULT_FORM;
  }
}

const clamp = (value: number, min: number, max: number) =>
  Number.isFinite(value) ? Math.min(max, Math.max(min, Math.round(value))) : min;

interface Props {
  onImported: () => void;
}

/** Shape a deck, get a prompt for an LLM, and import the deck it writes. */
export function Design({ onImported }: Props) {
  const [form, setForm] = useState<Form>(loadForm);
  const [prompt, setPrompt] = useState<DesignPrompt | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deckText, setDeckText] = useState("");
  const [showText, setShowText] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [imported, setImported] = useState<ImportedDeck | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(form));
    } catch {
      // storage unavailable (private window...): the form just isn't remembered
    }
  }, [form]);

  const total = form.domains.reduce((n, d) => n + d.count, 0);

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setPrompt(null); // the prompt no longer matches the form
  }

  function updateDomain(domain: Domain, patch: Partial<DomainSpec>) {
    update(
      "domains",
      form.domains.map((d) => (d.domain === domain ? { ...d, ...patch } : d)),
    );
  }

  async function generate() {
    setPromptError(null);
    setCopied(false);
    const body: DesignRequest = {
      title: form.title.trim() || "Custom deck",
      domains: form.domains.filter((d) => d.count > 0).map((d) => ({ ...d, focus: d.focus.trim() })),
      spread: form.spread,
      multi_share: form.multiShare,
      kinds: form.customKinds ? form.kinds : null,
    };
    try {
      setPrompt(await api.designPrompt(body));
    } catch (e) {
      setPromptError((e as Error).message);
    }
  }

  async function copy() {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt.prompt);
      setCopied(true);
    } catch {
      setPromptError("Copying failed: select the text of the prompt and copy it manually.");
    }
  }

  async function importDeck() {
    setImporting(true);
    setImportError(null);
    setImported(null);
    try {
      setImported(await api.importDeck(deckText));
      setDeckText("");
    } catch (e) {
      setImportError((e as Error).message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="design">
      <h1>Design a deck</h1>
      <p className="muted">
        Choose a level and a number of questions per domain. The app writes a prompt for an LLM (e.g. Claude)
        to generate the deck; paste its reply in step 3 to add the deck.
      </p>

      <section className="card design-step">
        <h2>
          <span className="step">1</span> Shape
        </h2>
        <label className="field">
          <span>Title</span>
          <input
            type="text"
            value={form.title}
            placeholder="e.g. Streaming & concurrency"
            onChange={(e) => update("title", e.target.value)}
          />
        </label>

        <div className="domain-grid">
          <div className="domain-head">
            <span>Domain</span>
            <span>Level</span>
            <span>Questions</span>
            <span>Focus (optional)</span>
          </div>
          {form.domains.map((d) => (
            <div key={d.domain} className={`domain-row${d.count ? "" : " domain-off"}`}>
              <span className="domain-name">{DOMAIN_LABELS[d.domain]}</span>
              <span className="level-cell">
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={d.level}
                  aria-label={`${DOMAIN_LABELS[d.domain]} level`}
                  onChange={(e) => updateDomain(d.domain, { level: Number(e.target.value) })}
                />
                <span className="level-value">{LEVEL_LABELS[String(d.level)]}</span>
              </span>
              <input
                className="domain-count"
                type="number"
                min={0}
                max={50}
                value={d.count || ""}
                placeholder="0"
                aria-label={`${DOMAIN_LABELS[d.domain]} questions`}
                onChange={(e) => updateDomain(d.domain, { count: clamp(Number(e.target.value), 0, 50) })}
              />
              <input
                className="domain-focus"
                type="text"
                value={d.focus}
                placeholder="e.g. Kafka, Spark"
                aria-label={`${DOMAIN_LABELS[d.domain]} focus`}
                onChange={(e) => updateDomain(d.domain, { focus: e.target.value })}
              />
            </div>
          ))}
        </div>

        <div className="design-options">
          <label className="field inline">
            <span>Select-all questions</span>
            <input
              type="number"
              min={0}
              max={100}
              value={form.multiShare || ""}
              placeholder="0"
              onChange={(e) => update("multiShare", clamp(Number(e.target.value), 0, 100))}
            />
            <span>%</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={form.spread} onChange={(e) => update("spread", e.target.checked)} />
            Allow ±1 level variety
          </label>
        </div>

        <div className="design-options">
          <span>Kinds</span>
          <label className="check">
            <input type="radio" name="kinds" checked={!form.customKinds} onChange={() => update("customKinds", false)} />
            Let the LLM mix
          </label>
          <label className="check">
            <input type="radio" name="kinds" checked={form.customKinds} onChange={() => update("customKinds", true)} />
            Custom weights
          </label>
          {form.customKinds &&
            KINDS.map((k) => (
              <label key={k} className="field inline">
                <span>{k}</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={form.kinds[k] || ""}
                  placeholder="0"
                  onChange={(e) => update("kinds", { ...form.kinds, [k]: clamp(Number(e.target.value), 0, 100) })}
                />
              </label>
            ))}
        </div>

        <footer className="design-foot">
          <span className="muted">
            {total} question{total === 1 ? "" : "s"}
          </span>
          <button type="button" className="btn btn-primary" disabled={total === 0} onClick={generate}>
            Generate prompt
          </button>
        </footer>
        {promptError && <p className="error">{promptError}</p>}
      </section>

      {prompt && (
        <section className="card design-step">
          <h2>
            <span className="step">2</span> Prompt
          </h2>
          <p className="muted">
            Deck <code>{prompt.deck_id}</code> · {prompt.n_questions} questions. Paste it into Claude: a Claude Code
            session in this repo writes and imports the deck directly, without showing you the answers. In a chat,
            copy its reply into step 3 without reading it.
          </p>
          <textarea
            className="prompt-text"
            readOnly
            rows={14}
            wrap="off"
            value={prompt.prompt}
            onFocus={(e) => e.target.select()}
          />
          <footer className="design-foot">
            <span className="muted">{prompt.prompt.length.toLocaleString()} characters</span>
            <button type="button" className="btn btn-primary" onClick={copy}>
              {copied ? "Copied ✓" : "Copy prompt"}
            </button>
          </footer>
        </section>
      )}

      <section className="card design-step">
        <h2>
          <span className="step">3</span> Import the generated deck
        </h2>
        <p className="muted">
          Paste the LLM's reply (the YAML, or the whole message). It is validated, saved to <code>decks/</code> and
          ready to play. The text stays blurred so you don't see the answers.
        </p>
        <textarea
          className={`deck-input${showText ? "" : " masked"}`}
          rows={8}
          value={deckText}
          spellCheck={false}
          placeholder="Paste the generated deck here"
          onChange={(e) => setDeckText(e.target.value)}
        />
        {importError && (
          <div className="error">
            <strong>Not imported:</strong>
            <ul>
              {importError.split("\n").map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
            <span className="hint">You can send these lines back to the LLM so it fixes the deck.</span>
          </div>
        )}
        {imported && (
          <p className="success">
            Imported <strong>{imported.title}</strong> ({imported.n_questions} question
            {imported.n_questions === 1 ? "" : "s"}, decks/{imported.file}).{" "}
            <button type="button" className="link" onClick={onImported}>
              Go to decks →
            </button>
          </p>
        )}
        <footer className="design-foot">
          <label className="check muted">
            <input type="checkbox" checked={showText} onChange={(e) => setShowText(e.target.checked)} />
            Show text
          </label>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!deckText.trim() || importing}
            onClick={importDeck}
          >
            {importing ? "Importing…" : "Validate & import"}
          </button>
        </footer>
      </section>
    </div>
  );
}
