import { useState } from "react";
import { api, type DeckInfo, type Mode, type SessionOut, type Summary } from "./api";
import { DeckList } from "./components/DeckList";
import { History } from "./components/History";
import { Quiz } from "./components/Quiz";
import { SummaryView } from "./components/SummaryView";

type Tab = "decks" | "history";

type Screen =
  | { name: Tab }
  | { name: "quiz"; session: SessionOut; deckTitle: string }
  | { name: "summary"; summary: Summary; back: Tab };

export function App() {
  const [screen, setScreen] = useState<Screen>({ name: "decks" });

  async function start(deck: DeckInfo, mode: Mode) {
    const session = await api.createSession(deck.id, mode);
    setScreen({ name: "quiz", session, deckTitle: deck.title });
  }

  async function review(sessionId: number, back: Tab) {
    setScreen({ name: "summary", summary: await api.summary(sessionId), back });
  }

  function go(tab: Tab) {
    if (screen.name === "quiz" && !window.confirm("Leave this quiz? It stays unfinished; answers so far are saved.")) {
      return;
    }
    setScreen({ name: tab });
  }

  const activeTab: Tab | null =
    screen.name === "summary" ? screen.back : screen.name === "quiz" ? null : screen.name;

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <button type="button" className="brand" onClick={() => go("decks")}>
            <span className="brand-mark">Q</span> quizzDS
          </button>
          <nav className="nav">
            {(["decks", "history"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                className={activeTab === tab ? "active" : ""}
                aria-current={activeTab === tab ? "page" : undefined}
                onClick={() => go(tab)}
              >
                {tab === "decks" ? "Decks" : "History"}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main>
        {screen.name === "decks" && <DeckList onStart={start} onReview={(id) => review(id, "decks")} />}
        {screen.name === "history" && <History onOpen={(id) => review(id, "history")} />}
        {screen.name === "quiz" && (
          <Quiz
            key={screen.session.session_id}
            session={screen.session}
            deckTitle={screen.deckTitle}
            onFinished={(summary) => setScreen({ name: "summary", summary, back: "decks" })}
          />
        )}
        {screen.name === "summary" && (
          <SummaryView
            summary={screen.summary}
            backLabel={screen.back === "history" ? "Back to history" : "Back to decks"}
            onBack={() => setScreen({ name: screen.back })}
          />
        )}
      </main>
    </>
  );
}
