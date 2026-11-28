import React, { useEffect, useMemo, useState } from "react";
import { Icon, Thumb, money, tagLabel } from "./lib.jsx";
import { primaryLabel, reqLabel } from "./Shopping.jsx";

/**
 * The agent's proposed basket as an editable receipt. Edits are sent back to
 * the agent as structured revisions (the backend accepts one kind per call):
 *   quantities -> set_package_counts, budget -> set_budget,
 *   "Choose myself" -> choose_candidates, "Agent picks another" -> replace.
 */
export default function Receipt({ resp, prevDraft, store, busy, products, onAnswer, onOpen }) {
  const draft = resp.recommendation;
  const [qty, setQty] = useState({});
  const [budget, setBudget] = useState("");
  useEffect(() => { setQty({}); setBudget(""); }, [draft.recommendation_id]);

  const byProduct = useMemo(() => {
    const map = {};
    for (const a of draft.assignments || []) (map[a.product_id] = map[a.product_id] || []).push(a);
    return map;
  }, [draft]);
  const prevItems = useMemo(() => Object.fromEntries((prevDraft?.items || []).map((i) => [i.product_id, i.quantity])), [prevDraft]);

  const lines = draft.items.map((item) => {
    const assigns = byProduct[item.product_id] || [];
    const rid = assigns.length === 1 ? assigns[0].requirement_id : null;
    const q = rid && qty[rid] != null ? qty[rid] : item.quantity;
    return { item, assigns, rid, q, total: item.price_cents * q, changed: prevDraft && prevItems[item.product_id] !== item.quantity };
  });
  const edits = lines.filter((l) => l.rid && qty[l.rid] != null && qty[l.rid] !== l.item.quantity);
  const total = lines.reduce((s, l) => s + l.total, 0);
  const budgetCents = draft.budget_cents;
  const newBudget = budget.trim() === "" ? null : Math.round(parseFloat(budget) * 100);
  const dirty = edits.length > 0;

  const states = Object.fromEntries((resp.requirement_states || []).map((s) => [s.requirement_id, s]));
  const checks = [];
  if (budgetCents != null) {
    checks.push(total <= budgetCents
      ? { k: "ok", t: `Within budget · ${money(total)} of ${money(budgetCents)}`, s: `${money(budgetCents - total)} left` }
      : { k: "bad", t: `Over budget by ${money(total - budgetCents)}`, s: "Lower a quantity, swap an item, or raise the budget" });
  }
  for (const a of draft.assignments || []) {
    const st = states[a.requirement_id] || {};
    const tags = (st.active_requirement?.constraints || []).filter((c) => c.kind === "tag").map((c) => tagLabel(c.value));
    checks.push({ k: "ok", t: `${reqLabel(resp, a.requirement_id)} · ${a.quantity} × ${products[a.product_id]?.raw_size || ""}`.trim(),
      s: [a.quantity_interpretation?.explanation, tags.length ? `Maker declares: ${tags.join(", ")}` : null].filter(Boolean).join(" · ") });
  }
  const outOfStock = draft.items.filter((i) => products[i.product_id] && products[i.product_id].in_stock === false);
  for (const i of outOfStock) checks.push({ k: "bad", t: `${i.name} is out of stock`, s: "Swap it before accepting" });
  if (dirty) checks.push({ k: "warn", t: "You changed quantities", s: "Apply them so the agent re-checks size, quantity and budget" });

  const swap = (rid, action) => onAnswer({ recommendation_answer: { recommendation_id: draft.recommendation_id, action, requirement_ids: [rid] } },
    action === "replace" ? `Asked the agent for a different “${reqLabel(resp, rid)}”` : `Chose “${reqLabel(resp, rid)}” myself`);

  return (
    <>
      <div className="eyebrow">Step 4 · Review</div>
      <h1 style={{ fontSize: "clamp(24px,3.6vw,34px)" }}>Your receipt, before anything is bought</h1>
      <p className="lede">Change any line. Every change goes back to the agent, which re-checks it against your request before you accept.</p>
      <div className="rcpt-grid">
        <div className="receipt" aria-busy={!!busy}>
          <div className="c">
            <h2>ShopSpec</h2>
            <div>{store?.name}</div>
            <div style={{ fontSize: 11 }}>{store?.addressText}</div>
            <div style={{ fontSize: 11 }}>Draft {draft.recommendation_id} · {resp.data_source === "live" ? "live prices" : "snapshot prices (Nov 16)"}</div>
          </div>
          <div className="rule" />
          {lines.map(({ item, assigns, rid, q, total: lt, changed }) => (
            <div key={item.product_id} className={`rline ${changed || (rid && qty[rid] != null && qty[rid] !== item.quantity) ? "changed" : ""}`}>
              <div className="rl-main">
                <Thumb id={item.product_id} name={item.name} onOpen={onOpen} />
                <div style={{ minWidth: 0 }}>
                  <div className="nm">{item.name}</div>
                  <div className="meta">{item.package_size} · {money(item.price_cents)} ea · UPC {item.product_id}</div>
                </div>
              </div>
              <div className="amt num">{money(lt)}</div>
              {assigns.map((a) => a.phase === "fallback" && <div key={`fb-${a.requirement_id}`} className="reason"><b>Backup choice:</b> this store has no product matching your first choice “{primaryLabel(resp, a.requirement_id)}”, so this uses the backup your request allowed: “{reqLabel(resp, a.requirement_id)}”.</div>)}
              {assigns.map((a) => a.reason && <div key={a.requirement_id} className="reason">Why: {a.reason}</div>)}
              <div className="ctrls">
                {rid ? (
                  <span className="qty">
                    <button type="button" aria-label="Fewer" disabled={busy || q <= 1} onClick={() => setQty((o) => ({ ...o, [rid]: q - 1 }))}>−</button>
                    <span className="num">{q}</span>
                    <button type="button" aria-label="More" disabled={busy || q >= 99} onClick={() => setQty((o) => ({ ...o, [rid]: q + 1 }))}>+</button>
                  </span>
                ) : <span className="meta">×{item.quantity}</span>}
                {assigns.map((a) => (
                  <React.Fragment key={a.requirement_id}>
                    <button type="button" className="rbtn" disabled={busy || dirty} onClick={() => swap(a.requirement_id, "choose_candidates")}>Choose myself</button>
                    <button type="button" className="rbtn" disabled={busy || dirty} onClick={() => swap(a.requirement_id, "replace")}>Agent picks another</button>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ))}
          <div className="rule" />
          <div className="tot">
            <span>Items</span><span className="num">{lines.reduce((s, l) => s + l.q, 0)}</span>
            {budgetCents != null && <><span>Budget</span><span className="num">{money(budgetCents)}</span></>}
            <span className="big">Subtotal</span><span className="big num">{money(total)}</span>
          </div>
          <div className="barcode" aria-hidden="true" />
          <div className="c" style={{ fontSize: 11 }}>Tax, fees and coupons are set by Kroger at checkout.</div>
        </div>

        <div className="stack">
          <div className="card">
            <h3 style={{ fontSize: 15, marginBottom: 10 }}>Checks</h3>
            <ul className="checks">
              {checks.map((c, i) => (
                <li key={i} className={`check ${c.k}`}>
                  <span className="mk">{c.k === "ok" ? Icon.check : c.k === "bad" ? Icon.x : Icon.warn}</span>
                  <span>{c.t}{c.s && <small>{c.s}</small>}</span>
                </li>
              ))}
            </ul>
            <div className="fixbar">
              {dirty ? (
                <>
                  <button className="btn" disabled={busy} onClick={() => onAnswer({ recommendation_answer: { recommendation_id: draft.recommendation_id, action: "set_package_counts",
                    updates: edits.map((l) => ({ requirement_id: l.rid, amount: qty[l.rid] })) } }, "Changed quantities", edits.map((l) => `${l.item.name} → ${qty[l.rid]}`).join(", "))}>Apply changes</button>
                  <button className="btn ghost" disabled={busy} onClick={() => setQty({})}>Undo</button>
                </>
              ) : (
                <button className="btn" disabled={busy || outOfStock.length > 0} onClick={() => onAnswer({ recommendation_answer: { recommendation_id: draft.recommendation_id, action: "accept" } }, "Accepted this basket")}>
                  {busy ? "Working…" : "Accept & build cart →"}
                </button>
              )}
              <span className="muted small">{busy ? "The agent is re-checking…" : dirty ? "Apply first, then accept." : "Prices and stock are re-read before the cart is built."}</span>
            </div>
          </div>
          <form className="card stack" onSubmit={(e) => {
            e.preventDefault();
            if (newBudget != null && newBudget >= 0) onAnswer({ recommendation_answer: { recommendation_id: draft.recommendation_id, action: "set_budget", budget_cents: newBudget } }, `Changed the budget to ${money(newBudget)}`);
          }}>
            <label className="field">Change budget
              <div className="zip-row"><input className="input num" type="number" min="0" step="0.01" placeholder={budgetCents != null ? (budgetCents / 100).toFixed(2) : "No budget"} value={budget} onChange={(e) => setBudget(e.target.value)} />
                <button className="btn ghost small" disabled={busy || dirty || newBudget == null || Number.isNaN(newBudget)}>Update</button></div>
            </label>
          </form>
        </div>
      </div>
    </>
  );
}
