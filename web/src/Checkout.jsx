import React, { useEffect, useState } from "react";
import { Icon, Pill, Thumb, api, money } from "./lib.jsx";

// Replace with the team's Google Form link when it exists.
const SURVEY_URL = "";

/**
 * Sends the verified local cart to the shopper's real Kroger cart through the
 * backend bridge (OAuth cart.basic:write, PUT /v1/cart/add). The bridge is
 * add-only, needs a live-data run, and only runs on a local server.
 */
export default function Checkout({ rounds, store, onOpen, onRestart }) {
  const final = rounds[rounds.length - 1]?.resp;
  const items = final?.cart?.items || [];
  const [modality, setModality] = useState("PICKUP");
  const [account, setAccount] = useState(null);
  const [preview, setPreview] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const loadAccount = () => api("/api/kroger/account").then(setAccount).catch((e) => setError(e.message));
  useEffect(() => { loadAccount(); }, []);
  useEffect(() => { setPreview(null); }, [modality]);

  const live = final?.data_source === "live";
  const canSend = account?.available && account?.authorized && live;
  const steps = rounds.map((r) => r.resp);

  async function prepare() {
    setBusy("prepare"); setError(""); setReceipt(null);
    try { setPreview(await api("/api/kroger/cart/prepare", { steps, modality })); } catch (e) { setError(e.message); } finally { setBusy(""); }
  }
  async function commit() {
    setBusy("commit"); setError("");
    try {
      const r = await api("/api/kroger/cart/commit", { plan_id: preview.plan_id, confirm: preview.plan_id });
      if (r.status === "needs_reconfirmation") { setPreview(r); setError("Prices or stock changed since the preview. Review the new preview and confirm again."); }
      else { setReceipt(r); setPreview(null); }
    } catch (e) { setError(e.message); } finally { setBusy(""); }
  }

  const flowState = (i) => {
    const at = receipt ? 4 : preview ? 2 : canSend ? 1 : 0;
    return i < at ? "done" : i === at ? "now" : "";
  };

  return (
    <>
      <div className="eyebrow">Step 5 · Checkout</div>
      <h1 style={{ fontSize: "clamp(24px,3.6vw,34px)" }}>Send it to your Kroger cart</h1>
      <p className="lede">ShopSpec never sees your card. Items are added to your own Kroger cart, and you pay on Kroger.</p>
      <div className="co-grid">
        <div className="stack">
          <div className="card stack">
            <div className="modes">
              {[["PICKUP", "Pickup", "Curbside at this store"], ["DELIVERY", "Delivery", "From this store to your door"]].map(([k, t, s]) => (
                <button key={k} type="button" className="mode" aria-pressed={modality === k} onClick={() => setModality(k)} disabled={!!receipt}>
                  <b>{t}</b><span className="muted small">{s}</span>
                </button>
              ))}
            </div>
            <ol className="flow">
              <li className={flowState(0)}><span className="n">1</span><div><b>Connect your Kroger account</b>
                <div className="muted small">You sign in on Kroger's own page and allow ShopSpec to add items (scope <code>cart.basic:write</code>). ShopSpec never sees your password.</div>
                <AccountState account={account} live={live} onRefresh={loadAccount} />
              </div></li>
              <li className={flowState(1)}><span className="n">2</span><div><b>Fresh preview</b>
                <div className="muted small">Each product is re-read from Kroger: price, stock and {modality === "PICKUP" ? "pickup" : "delivery"} availability.</div>
                {canSend && !preview && !receipt && <div style={{ marginTop: 8 }}><button className="btn small" disabled={!!busy} onClick={prepare}>{busy === "prepare" ? "Checking Kroger…" : "Preview the addition"}</button></div>}
              </div></li>
              <li className={flowState(2)}><span className="n">3</span><div><b>Confirm</b>
                <div className="muted small">Nothing is sent until you confirm this exact preview.</div>
                {preview && (
                  <div className="stack" style={{ marginTop: 8, gap: 8 }}>
                    <table className="preview-table">
                      <thead><tr><th>Item</th><th className="r">Qty</th><th className="r">Total</th></tr></thead>
                      <tbody>{preview.items.map((i) => <tr key={i.upc}><td>{i.name}<div className="muted small">{i.package_size} · UPC {i.upc}</div></td><td className="r">{i.quantity}</td><td className="r">{money(i.line_total_cents)}</td></tr>)}</tbody>
                      <tfoot><tr><th>This addition</th><th /><th className="r">{money(preview.subtotal_cents)}</th></tr></tfoot>
                    </table>
                    <div className="note">{preview.effect}</div>
                    <div><button className="btn" disabled={!!busy} onClick={commit}>{busy === "commit" ? "Sending…" : "Add to my Kroger cart"}</button></div>
                  </div>
                )}
              </div></li>
              <li className={flowState(3)}><span className="n">4</span><div><b>Pay on Kroger</b>
                <div className="muted small">Open your Kroger cart to choose a time slot, apply coupons and pay. The public API has no checkout, so ShopSpec cannot place the order.</div>
              </div></li>
            </ol>
            {error && <div className="err">{error}</div>}
            {receipt && (
              <div className="success">
                <h3>Sent to Kroger</h3>
                <div>Kroger accepted {receipt.items.length} item{receipt.items.length === 1 ? "" : "s"} ({money(receipt.addition_subtotal_cents)}). The API cannot read your cart back, so please check it on Kroger.</div>
                <div><a className="btn" href="https://www.kroger.com/cart" target="_blank" rel="noreferrer">Open Kroger cart ↗</a></div>
              </div>
            )}
          </div>
          <div className="card stack">
            <h3 style={{ fontSize: 15 }}>How did ShopSpec do?</h3>
            <div className="muted small">A 2-minute survey for our CS498 project.</div>
            <div>{SURVEY_URL ? <a className="btn ghost" href={SURVEY_URL} target="_blank" rel="noreferrer">Take the survey ↗</a> : <button className="btn ghost" disabled>Survey link coming soon</button>}</div>
          </div>
        </div>
        <div className="stack">
          <div className="card">
            <h3 style={{ fontSize: 15, marginBottom: 10, display: "flex", justifyContent: "space-between" }}>Verified cart <span className="num">{money(final?.cart?.total_cents)}</span></h3>
            <div className="mini-cart">
              {items.map((i) => (
                <div key={i.id} className="mini" onClick={() => onOpen(i.id)} role="button" tabIndex={0}>
                  <Thumb id={i.id} name={i.name} onOpen={onOpen} />
                  <span className="nm">{i.name}<div className="muted small">{i.raw_size} · ×{i.quantity}</div></span>
                  <b className="num">{money(i.line_total_cents)}</b>
                </div>
              ))}
            </div>
            <div className="fixbar">
              {final?.verification?.ok ? <Pill kind="ok">{Icon.check} Final check passed</Pill> : <Pill kind="warn">Not verified</Pill>}
              <span className="muted small">{store?.name}</span>
            </div>
          </div>
          <div className="note">Without account access you can still find each item on kroger.com:
            <div className="push-list">{items.map((i) => <a key={i.id} className="push" href={`https://www.kroger.com/search?query=${i.upc || i.id}`} target="_blank" rel="noreferrer"><span>{i.name}</span><span>×{i.quantity} ↗</span></a>)}</div>
          </div>
          <button className="btn ghost" onClick={onRestart}>Start a new list</button>
        </div>
      </div>
    </>
  );
}

function AccountState({ account, live, onRefresh }) {
  if (!account) return <div className="muted small" style={{ marginTop: 6 }}>Checking…</div>;
  if (!account.available) {
    return <div className="note" style={{ marginTop: 8 }}>This hosted demo cannot hold Kroger accounts, so sending to a real cart only works when ShopSpec runs on your own computer. Use the kroger.com links instead.</div>;
  }
  if (!live) {
    return <div className="note" style={{ marginTop: 8 }}>This cart was built from the frozen snapshot. Real Kroger cart submission needs live Kroger data: set <code>KROGER_CLIENT_ID</code> / <code>KROGER_CLIENT_SECRET</code> on the server and shop again.</div>;
  }
  if (account.authorized) {
    return <div style={{ marginTop: 6 }}><Pill kind="ok">{Icon.check} Kroger account connected</Pill></div>;
  }
  return (
    <div className="stack" style={{ marginTop: 8, gap: 6 }}>
      <div className="muted small">{account.reason || "Not connected yet."} Run this on the server machine, sign in on Kroger, then refresh:</div>
      <code className="cmd">{account.connect_command}</code>
      <div><button className="btn ghost small" onClick={onRefresh}>I connected, check again</button></div>
    </div>
  );
}
