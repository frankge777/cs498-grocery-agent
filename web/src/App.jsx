import React, { useEffect, useState } from "react";

const EXAMPLES = [
  "Buy one gallon of whole milk and a dozen eggs under $10",
  "Ingredients for spaghetti dinner for 4 people, vegetarian, under $20",
  "Healthy breakfast for a week for one person, no peanuts",
];

const money = (cents) => `$${(cents / 100).toFixed(2)}`;

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${res.status}`);
  return body;
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [instruction, setInstruction] = useState(EXAMPLES[0]);
  const [zip, setZip] = useState("61820");
  const [source, setSource] = useState("auto");
  const [notes, setNotes] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    api("/api/health").then(setHealth).catch((e) => setError(`Backend unreachable: ${e.message}`));
  }, []);

  async function run(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const body = await api("/api/agent/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction,
          source,
          zip_code: zip || null,
          context: notes.trim() ? { notes: notes.trim() } : {},
          clarification_answer: answer || null,
        }),
      });
      setResult(body);
      if (body.error) setError(`Agent stopped early: ${body.error}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header>
        <h1>Grocery Agent</h1>
        <p className="muted">Describe what you need; the agent searches Kroger and builds a cart.</p>
        {health && (
          <div className="badges">
            <span className={health.kroger_configured ? "badge ok" : "badge warn"}>
              Kroger live {health.kroger_configured ? "on" : "off (snapshot only)"}
            </span>
            <span className={health.deepseek_configured ? "badge ok" : "badge warn"}>
              LLM {health.deepseek_configured ? "ready" : "not configured"}
            </span>
          </div>
        )}
      </header>

      <form className="card" onSubmit={run}>
        <label>
          Shopping request
          <textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} required />
        </label>
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button type="button" key={ex} className="chip" onClick={() => setInstruction(ex)}>
              {ex}
            </button>
          ))}
        </div>
        <div className="row">
          <label>
            ZIP code
            <input value={zip} onChange={(e) => setZip(e.target.value)} pattern="\d{5}" maxLength={5} />
          </label>
          <label>
            Data source
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="auto">Auto</option>
              <option value="live" disabled={health && !health.kroger_configured}>Live Kroger API</option>
              <option value="snapshot">Frozen snapshot (Mt Zion)</option>
            </select>
          </label>
        </div>
        <label>
          Household notes (optional)
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. 2 adults, lactose intolerant" />
        </label>
        <label>
          Answer to give if the agent asks a question (optional)
          <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Default: use your best judgment" />
        </label>
        <button className="primary" disabled={loading}>
          {loading ? "Shopping… (can take up to a minute)" : "Build my cart"}
        </button>
      </form>

      {error && <div className="card error">{error}</div>}
      {result && <Result result={result} />}
    </div>
  );
}

function Result({ result }) {
  const { cart, location, stats, clarifications, intent, trajectory } = result;
  return (
    <>
      <section className="card">
        <div className="cart-head">
          <h2>Cart</h2>
          <span className="muted">
            {location?.name} · {result.data_source} · {result.cart_mode}
          </span>
        </div>
        {cart.items.length === 0 ? (
          <p className="muted">The cart is empty.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Product</th><th>Size</th><th>Price</th><th>Qty</th><th>Total</th></tr>
              </thead>
              <tbody>
                {cart.items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}<div className="muted small">{item.brand} · UPC {item.upc || item.id}</div></td>
                    <td>{item.raw_size || `${item.size} ${item.unit}`}</td>
                    <td>{money(item.price_cents)}</td>
                    <td>{item.quantity}</td>
                    <td>{money(item.line_total_cents)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr><td colSpan={4}>Total</td><td>{money(cart.total_cents)}</td></tr>
              </tfoot>
            </table>
          </div>
        )}
        <p className="muted small">
          {stats.tool_calls} tool calls · {stats.model_calls} model calls · {stats.elapsed_seconds}s ·{" "}
          {stats.termination_reason}
        </p>
      </section>

      {clarifications.length > 0 && (
        <section className="card">
          <h2>Agent questions</h2>
          {clarifications.map((c, i) => (
            <p key={i}><b>Q:</b> {c.question}<br /><b>A:</b> {c.answer}</p>
          ))}
        </section>
      )}

      <details className="card">
        <summary>Parsed intent</summary>
        <pre>{JSON.stringify(intent, null, 2)}</pre>
      </details>
      <details className="card">
        <summary>Tool trajectory ({trajectory.length} steps)</summary>
        <ol className="trajectory">
          {trajectory.map((step) => (
            <li key={step.step} className={step.ok === false ? "failed" : ""}>
              <code>{step.tool || step.event}</code> {step.args && <code className="muted">{JSON.stringify(step.args)}</code>}
              <div className="small">{step.message || step.reason}</div>
            </li>
          ))}
        </ol>
      </details>
    </>
  );
}
