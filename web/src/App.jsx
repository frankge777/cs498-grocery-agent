import React, { useCallback, useEffect, useRef, useState } from "react";
import { Icon, Pill, api, streamApi } from "./lib.jsx";
import Shopping, { foldLive } from "./Shopping.jsx";
import Receipt from "./Receipt.jsx";
import Checkout from "./Checkout.jsx";
import ProductModal from "./ProductModal.jsx";

const STEPS = ["Store", "Request", "Shopping", "Receipt", "Checkout"];
const EXAMPLES = [
  "Spaghetti dinner for 4: one box of spaghetti, one jar of marinara sauce and a bag of baby spinach",
  "A dozen large eggs and a gallon of whole milk",
  "Breakfast for one week: rolled oats, bananas and a carton of almond milk",
];
const DIETS = ["Vegan", "Gluten-free", "Organic", "Dairy-free"];

function storeView(loc, live) {
  if (!loc) return null;
  const a = loc.address || {};
  return { ...loc, live, addressText: [a.addressLine1, a.city, [a.state, a.zipCode].filter(Boolean).join(" ")].filter(Boolean).join(", ") };
}

function composeInstruction({ text, people, budget, diets }) {
  let first = text.trim().replace(/\s+/g, " ");
  if (first && !/[.!?]$/.test(first)) first += ".";
  const parts = [first];
  if (people) parts.push(`It is for ${people} ${people === 1 ? "person" : "people"}.`);
  if (diets.length) parts.push(`Every item must be ${diets.join(" and ").toLowerCase()}.`);
  if (budget) parts.push(`Keep the total under $${budget}.`);
  return parts.join(" ");
}

export default function App() {
  const [step, setStep] = useState(0);
  const [maxStep, setMaxStep] = useState(0);
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [zip, setZip] = useState("61820");
  const [locs, setLocs] = useState(null);
  const [locSource, setLocSource] = useState(null);
  const [loc, setLoc] = useState(null);
  const [locBusy, setLocBusy] = useState(false);
  const [locError, setLocError] = useState("");
  const [req, setReq] = useState({ text: EXAMPLES[0], people: 4, budget: "15", diets: [] });
  const [rounds, setRounds] = useState([]);
  const [live, setLive] = useState([]);
  const [busy, setBusy] = useState(null);
  const [runError, setRunError] = useState("");
  const [products, setProducts] = useState({});
  const [pd, setPd] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const tokenRef = useRef(null);
  const elapsedBase = useRef(0);

  useEffect(() => {
    api("/api/health").then(setHealth).catch((e) => setHealthError(e.message));
  }, []);
  useEffect(() => {
    if (!busy) return undefined;
    const t0 = Date.now();
    const t = setInterval(() => setElapsed(elapsedBase.current + (Date.now() - t0) / 1000), 250);
    return () => { clearInterval(t); elapsedBase.current += (Date.now() - t0) / 1000; };
  }, [busy]);

  const go = useCallback((i) => {
    setStep(i);
    setMaxStep((m) => Math.max(m, i));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const store = storeView(loc, locSource === "live");

  async function findStores(e) {
    e.preventDefault();
    setLocBusy(true); setLocError("");
    try {
      const r = await api(`/api/locations?zip_code=${encodeURIComponent(zip)}`);
      setLocs(r.locations); setLocSource(r.data_source);
      setLoc(r.locations[0] || null);
      if (!r.locations.length) setLocError("No Kroger stores near that ZIP code.");
    } catch (err) { setLocError(err.message); } finally { setLocBusy(false); }
  }

  async function runStep(path, body, action, actionNote) {
    setBusy({ action }); setLive([]); setRunError("");
    let collected = [];
    try {
      const resp = await streamApi(path, body, (ev) => { collected = foldLive(collected, ev); setLive(collected); });
      tokenRef.current = resp.session_token || null;
      setProducts((p) => ({ ...p, ...(resp.products || {}) }));
      setRounds((rs) => [...rs, { resp, live: collected, action, actionNote }]);
      if (resp.status === "complete") go(4);
      else if (resp.status === "awaiting_basket_confirmation" && step === 3) go(3);
      else if (resp.status !== "awaiting_basket_confirmation") go(2);
    } catch (err) {
      setRunError(err.message);
      if (step !== 2) go(2);
    } finally {
      setBusy(null); setLive([]);
    }
  }

  function start() {
    setRounds([]); setProducts({}); tokenRef.current = null; elapsedBase.current = 0; setElapsed(0);
    go(2);
    runStep("/api/agent/interactive/stream/start", {
      instruction: composeInstruction(req), source: "auto",
      zip_code: zip, location_id: loc?.location_id || null,
      context: { household_size: req.people, dietary_needs: req.diets },
    }, null);
  }

  const answer = (payload, action, note) => runStep("/api/agent/interactive/stream/resume", { session_token: tokenRef.current, ...payload }, action, note);

  const last = rounds[rounds.length - 1]?.resp;
  const draftResp = last?.status === "awaiting_basket_confirmation" ? last : null;
  const prevDraft = rounds.slice(0, -1).map((r) => r.resp).filter((r) => r.status === "awaiting_basket_confirmation").pop()?.recommendation;
  const complete = last?.status === "complete";
  const can = (i) => !busy || i === step || (i === 2);
  const reachable = [true, !!loc, rounds.length > 0 || !!busy, !!draftResp, complete];

  const ready = health && health.deepseek_configured && health.session_configured;
  const sourceLive = health?.kroger_configured;

  return (
    <>
      <div className={`banner ${sourceLive ? "live" : ""}`}>
        {healthError ? `Backend unreachable: ${healthError}` : !health ? "Connecting…"
          : sourceLive ? "Live Kroger Products & Locations API · a real AI agent builds your cart"
            : "Kroger keys are not set on this server, so ShopSpec uses the frozen Nov 16 2026 snapshot of a real store (722 products). The AI agent is real."}
      </div>
      <header className="top">
        <div className="wrap">
          <div className="brand">
            <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" fill="var(--leaf)" /><path d="M8 12h16l-2 10.5a2 2 0 0 1-2 1.5h-8a2 2 0 0 1-2-1.5z" fill="var(--leaf-ink)" /><path d="M16 12c0-4 2.5-6 6-6-0.3 3.6-2.6 6-6 6z" fill="var(--citrus)" /></svg>
            ShopSpec
          </div>
          <nav className="steps" aria-label="Progress">
            {STEPS.map((s, i) => {
              const done = i < step && reachable[i];
              return (
                <button key={s} className={`step ${i === step ? "on" : done ? "done" : ""}`} disabled={!reachable[i] || !can(i)}
                  aria-current={i === step ? "step" : undefined} onClick={() => go(i)}>
                  <b>{done ? <span style={{ width: 12, height: 12, display: "grid" }}>{Icon.check}</span> : i + 1}</b><span>{s}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="wrap">
        <section className="panel enter" key={step}>
          {step === 0 && (
            <>
              <div className="eyebrow">Step 1 · Pick your store</div>
              <h1 className="hero-title">Real shelves, real prices.<br />Shopped for you.</h1>
              <p className="lede">ShopSpec reads product, price and stock data from the Kroger store you pick, then an AI agent builds a cart that fits your plan, and you check it before anything is bought.</p>
              <div className="store-grid">
                <form className="card stack" onSubmit={findStores}>
                  <label className="field" htmlFor="zip">Your ZIP code
                    <div className="zip-row">
                      <input className="input" id="zip" inputMode="numeric" maxLength={5} pattern="\d{5}" value={zip} onChange={(e) => setZip(e.target.value)} required />
                      <button className="btn" disabled={locBusy}>{locBusy ? "Finding…" : "Find stores"}</button>
                    </div>
                  </label>
                  <div className="source"><span className="dot" />Kroger Locations API · <code>GET /v1/locations?filter.zipCode.near={zip}</code></div>
                  {health && !sourceLive && <div className="note">Snapshot mode: the store list is the one store captured in the snapshot.</div>}
                </form>
                <div className="stack">
                  {locError && <div className="err">{locError}</div>}
                  {!locs && !locError && <div className="empty" style={{ padding: "40px 16px" }}>Enter a ZIP code to see nearby Kroger stores.</div>}
                  {locs && locs.length > 1 && (
                    <div className="locs">
                      {locs.map((l) => (
                        <button key={l.location_id} type="button" className="loc" aria-pressed={loc?.location_id === l.location_id} onClick={() => setLoc(l)}>
                          <b>{l.name}</b><span className="muted small">{storeView(l).addressText}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {store && (
                    <article className="card store-card">
                      <div className="store-head">
                        <div><div className="eyebrow">{locSource === "live" ? "Selected store" : "Snapshot store"}</div><h3>{store.name}</h3>
                          <div className="muted small">Location ID <span className="num">{store.location_id}</span>{store.chain ? ` · ${store.chain}` : ""}</div></div>
                        <Pill kind={locSource === "live" ? "ok" : "warn"}>{locSource === "live" ? "Live data" : "Snapshot · Nov 16"}</Pill>
                      </div>
                      <dl className="kv"><dt>Address</dt><dd>{store.addressText}</dd>{store.address?.county && <><dt>County</dt><dd>{store.address.county}</dd></>}</dl>
                      <div><button className="btn" onClick={() => go(1)}>Shop at this store →</button></div>
                    </article>
                  )}
                </div>
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div className="eyebrow">Step 2 · Tell the agent what you need</div>
              <h1 className="hero-title" style={{ fontSize: "clamp(26px,4vw,38px)" }}>What are we shopping for?</h1>
              <div className="req-grid">
                <div className="card stack">
                  <label className="field" htmlFor="reqText">Your request
                    <textarea className="input" id="reqText" maxLength={1500} value={req.text} onChange={(e) => setReq({ ...req, text: e.target.value })} />
                  </label>
                  <div className="chips">{EXAMPLES.map((ex) => <button key={ex} type="button" className="chip example" onClick={() => setReq({ ...req, text: ex })}>{ex}</button>)}</div>
                  <p className="muted small" style={{ margin: 0 }}>Write it the way you'd text a friend. The agent asks if something important is missing.</p>
                </div>
                <div className="card stack">
                  <div className="row2">
                    <div className="field">People
                      <div className="stepper">
                        <button type="button" aria-label="Fewer people" onClick={() => setReq({ ...req, people: Math.max(1, req.people - 1) })}>−</button>
                        <output className="num">{req.people}</output>
                        <button type="button" aria-label="More people" onClick={() => setReq({ ...req, people: Math.min(20, req.people + 1) })}>+</button>
                      </div>
                    </div>
                    <label className="field" htmlFor="budget">Budget ($)
                      <input className="input num" id="budget" type="number" min="1" step="1" placeholder="none" value={req.budget} onChange={(e) => setReq({ ...req, budget: e.target.value })} />
                    </label>
                  </div>
                  <div className="field">Dietary needs
                    <div className="chips">{DIETS.map((d) => (
                      <button key={d} type="button" className="chip" aria-pressed={req.diets.includes(d)}
                        onClick={() => setReq({ ...req, diets: req.diets.includes(d) ? req.diets.filter((x) => x !== d) : [...req.diets, d] })}>{d}</button>
                    ))}</div>
                    <span className="muted small" style={{ fontWeight: 400 }}>Only products whose maker declares it count.</span>
                  </div>
                  <div className="note"><b>Sent to the agent:</b> {composeInstruction(req)}</div>
                  {health && !ready && <div className="err">{!health.deepseek_configured ? "DEEPSEEK_API_KEY is not set on the server." : "GROCERY_SESSION_SECRET is not set on the server."}</div>}
                  <button className="btn" disabled={!req.text.trim() || !ready || !!busy} onClick={start}>Start shopping</button>
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <Shopping store={store} rounds={rounds} live={live} busy={busy} error={runError} products={products} elapsed={elapsed}
              onAnswer={answer} onGo={go} onRestart={() => go(1)} onOpen={setPd} />
          )}
          {step === 3 && draftResp && (
            <Receipt resp={draftResp} prevDraft={prevDraft} store={store} busy={!!busy} products={products} onAnswer={answer} onOpen={setPd} />
          )}
          {step === 3 && !draftResp && (
            <div className="empty">{busy ? "The agent is updating your basket…" : "No basket to review right now."} <button className="btn ghost small" onClick={() => go(2)}>Back to shopping</button></div>
          )}
          {step === 4 && complete && <Checkout rounds={rounds} store={store} onOpen={setPd} onRestart={() => go(1)} />}
        </section>
      </main>

      <footer>
        <div className="wrap">ShopSpec is a CS498 course project. It is not affiliated with or endorsed by Kroger. Store, product and price data come from the Kroger Public API.</div>
      </footer>
      {pd && <ProductModal id={pd} source={last?.data_source || (sourceLive ? "live" : "snapshot")} locationId={loc?.location_id} onClose={() => setPd(null)} />}
    </>
  );
}
