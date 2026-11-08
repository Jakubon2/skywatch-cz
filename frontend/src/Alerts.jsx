// "Alerty" tab: alerts written in plain Czech. Claude turns the text into a rule, the user confirms it.
import { useEffect, useRef, useState } from "react";
import { useApp } from "./state.jsx";
import "./Alerts.css";

const EXAMPLES = ["Jakékoli vojenské letadlo nad ČR", "An-124 nad Vysočinou", "Něco zajímavého nade mnou", "Až poletí OK-"];

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : null;
    throw new Error(detail || (res.status >= 500 ? "Server teď neodpovídá, zkus to za chvíli." : "Zadání je moc krátké nebo neplatné."));
  }
  return data;
}

const hitsText = (n) => (n === 0 ? "Zatím bez zásahu" : n === 1 ? "1 zásah" : n < 5 ? `${n} zásahy` : `${n} zásahů`);

function Rule({ r, onToggle, onDelete }) {
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    if (!confirm) return;
    const id = setTimeout(() => setConfirm(false), 4000);
    return () => clearTimeout(id);
  }, [confirm]);

  return (
    <li className={`rule ${r.active ? "" : "rule--off"}`}>
      <div className="rule__text">
        <p className="rule__summary">{r.summary}</p>
        <p className="rule__meta">
          <span className="rule__quote">„{r.text}“</span>
          <span className={`rule__count ${r.hits ? "rule__hits" : ""}`}>{hitsText(r.hits)}</span>
        </p>
      </div>
      <div className="rule__side">
        <label className="rule-switch" title={r.active ? "Hlídá" : "Vypnuto"}>
          <input type="checkbox" role="switch" checked={r.active} onChange={() => onToggle(r)} aria-label={`Hlídat: ${r.summary}`} />
          <span className="rule-switch__track" />
        </label>
        <button
          className={`rule__del ${confirm ? "is-confirm" : ""}`}
          onClick={() => (confirm ? onDelete(r) : setConfirm(true))}
          aria-label={confirm ? "Opravdu smazat" : "Smazat alert"}
        >
          {confirm ? (
            "Smazat?"
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 7h14M10 7V5h4v2M7 7l1 12.5h8L17 7M10.5 11v5M13.5 11v5" />
            </svg>
          )}
        </button>
      </div>
    </li>
  );
}

export default function Alerts() {
  const { home, setView } = useApp();
  const [text, setText] = useState("");
  const [draft, setDraft] = useState(null); // {text, rule, summary} waiting for confirmation
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rules, setRules] = useState(null); // null = loading
  const [listError, setListError] = useState(null);
  const input = useRef(null);

  const load = () =>
    api("/api/alerts")
      .then((r) => {
        setRules(r);
        setListError(null);
      })
      .catch((e) => setListError(e.message));
  useEffect(() => {
    load();
  }, []);

  const parse = async (ev) => {
    ev?.preventDefault();
    const t = text.trim();
    if (t.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    setDraft(null);
    try {
      const body = { text: t, ...(home ? { home: { lat: home.lat, lon: home.lon, label: home.label?.slice(0, 120) } } : {}) };
      const res = await api("/api/alerts/parse", { method: "POST", body: JSON.stringify(body) });
      setDraft({ text: t, ...res });
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const saved = await api("/api/alerts", { method: "POST", body: JSON.stringify({ text: draft.text, rule: draft.rule }) });
      setRules((rs) => [{ hits: 0, ...saved }, ...(rs || [])]);
      setDraft(null);
      setText("");
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  const toggle = async (r) => {
    setRules((rs) => rs.map((x) => (x.id === r.id ? { ...x, active: !r.active } : x)));
    try {
      await api(`/api/alerts/${r.id}`, { method: "PATCH", body: JSON.stringify({ active: !r.active }) });
    } catch (e) {
      setRules((rs) => rs.map((x) => (x.id === r.id ? { ...x, active: r.active } : x)));
      setListError(e.message);
    }
  };

  const remove = async (r) => {
    try {
      await api(`/api/alerts/${r.id}`, { method: "DELETE" });
      setRules((rs) => rs.filter((x) => x.id !== r.id));
    } catch (e) {
      setListError(e.message);
    }
  };

  const pickExample = (ex) => {
    setText(ex);
    setDraft(null);
    setError(null);
    input.current?.focus();
  };

  return (
    <div className="alerts">
      <h2 className="section-title">Upozorni mě, až…</h2>
      <form className="alert-form" onSubmit={parse}>
        <textarea
          ref={input}
          rows={2}
          value={text}
          maxLength={500}
          onChange={(e) => {
            setText(e.target.value);
            setDraft(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) parse(e);
          }}
          placeholder="Napiš obyčejnou řečí, co chceš hlídat"
          aria-label="Popis alertu"
          enterKeyHint="send"
        />
        <button className="btn btn--primary" disabled={busy || text.trim().length < 3}>
          {busy && !draft ? <span className="spinner" aria-label="Zpracovávám" /> : "Pochopit"}
        </button>
      </form>

      {!draft && (
        <div className="pick-chips alert-examples" aria-label="Příklady">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="pick-chip" onClick={() => pickExample(ex)}>
              {ex.endsWith("-") ? `${ex}…` : ex}
            </button>
          ))}
        </div>
      )}

      {error && <p className="form-note form-note--error">{error}</p>}
      {error && !home && /adresu/.test(error) && (
        <button className="btn btn--ghost btn--small alerts__home" onClick={() => setView("near")}>
          Nastavit své místo
        </button>
      )}

      {draft && (
        <div className="draft" role="region" aria-label="Jak jsem zadání pochopil">
          <span className="draft__label">✦ Takhle jsem to pochopil</span>
          <p className="draft__summary">{draft.summary}</p>
          <div className="draft__actions">
            <button className="btn btn--ghost" onClick={() => setDraft(null)} disabled={busy}>
              Zrušit
            </button>
            <button className="btn btn--primary" onClick={confirm} disabled={busy}>
              Potvrdit
            </button>
          </div>
        </div>
      )}

      <h3 className="alerts__subtitle">
        Moje alerty {rules?.length ? <span className="alerts__count">{rules.length}</span> : null}
      </h3>
      {listError && <p className="form-note form-note--error">{listError}</p>}
      {rules === null && !listError && <p className="form-note">Načítám…</p>}
      {rules?.length === 0 && (
        <div className="empty empty--compact">
          <div className="empty__icon">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 9.5a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15.5 6 9.5zM10 20.5a2.2 2.2 0 0 0 4 0" />
            </svg>
          </div>
          <p>Zatím nic nehlídám. Napiš, co tě zajímá, nebo zkus některý z příkladů.</p>
        </div>
      )}
      {rules?.length > 0 && (
        <ul className="rules">
          {rules.map((r) => (
            <Rule key={r.id} r={r} onToggle={toggle} onDelete={remove} />
          ))}
        </ul>
      )}
    </div>
  );
}
