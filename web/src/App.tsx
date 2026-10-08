import { useState } from "react";
import { api, type DeckInfo, type Mode, type SessionOut, type Summary } from "./api";
import { DeckList } from "./components/DeckList";
import { Quiz } from "./components/Quiz";
import { SummaryView } from "./components/SummaryView";

type Screen =
  | { name: "decks" }
  | { name: "quiz"; session: SessionOut; deckTitle: string }
  | { name: "summary"; summary: Summary; deckTitle: string };

export function App() {
  const [screen, setScreen] = useState<Screen>({ name: "decks" });

  async function start(deck: DeckInfo, mode: Mode) {
    const session = await api.createSession(deck.id, mode);
    setScreen({ name: "quiz", session, deckTitle: deck.title });
  }

  function home() {
    if (screen.name === "quiz" && !window.confirm("Leave this quiz? It stays unfinished; answers so far are saved.")) {
      return;
    }
    setScreen({ name: "decks" });
  }

  return (
    <>
      <header className="topbar">
        <button type="button" className="brand" onClick={home}>
          <span className="brand-mark">Q</span> quizzDS
        </button>
      </header>
      <main>
        {screen.name === "decks" && <DeckList onStart={start} />}
        {screen.name === "quiz" && (
          <Quiz
            key={screen.session.session_id}
            session={screen.session}
            deckTitle={screen.deckTitle}
            onFinished={(summary) => setScreen({ name: "summary", summary, deckTitle: screen.deckTitle })}
          />
        )}
        {screen.name === "summary" && (
          <SummaryView summary={screen.summary} deckTitle={screen.deckTitle} onBack={() => setScreen({ name: "decks" })} />
        )}
      </main>
    </>
  );
}
