import React, { useState } from "react";

export const money = (cents) => (cents == null ? "—" : `$${(cents / 100).toFixed(2)}`);

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function detailText(body, status) {
  const d = body && body.detail;
  if (!d) return `HTTP ${status}`;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => e.msg || JSON.stringify(e)).join("; ");
  return JSON.stringify(d);
}

export async function api(path, body) {
  const res = await fetch(path, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(detailText(data, res.status), res.status);
  return data;
}

/** POST to an NDJSON endpoint; calls onEvent for each progress line, resolves with the result. */
export async function streamApi(path, body, onEvent) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(detailText(data, res.status), res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let outcome = null;
  const handle = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "result") outcome = { data: event.data };
    else if (event.type === "error") outcome = { error: new ApiError(event.detail, event.status) };
    else onEvent(event);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      handle(buffer.slice(0, nl));
      buffer = buffer.slice(nl + 1);
    }
  }
  handle(buffer);
  if (!outcome) throw new ApiError("The server closed the stream without a result", 502);
  if (outcome.error) throw outcome.error;
  return outcome.data;
}

// Same CDN pattern the Kroger Products API returns in images[].sizes[].url.
export const imageUrl = (upc, size = "medium", view = "front") =>
  `https://www.kroger.com/product/images/${size}/${view}/${upc}`;

export const tagLabel = (t) =>
  String(t).replace(/_and_(their|its)_derivat\w*/g, "").replace(/_/g, " ").replace(/\bnon gmo\b/i, "non-GMO");

export const Icon = {
  leaf: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 19C5 10 11 4 20 4c0 9-6 15-15 15z" /><path d="M5 19 14 10" /></svg>
  ),
  check: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
  ),
  x: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><path d="M7 7l10 10M17 7 7 17" /></svg>
  ),
  warn: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round"><path d="M12 7v6M12 17v.5" /></svg>
  ),
  think: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3a6 6 0 0 0-3.5 10.9V17h7v-3.1A6 6 0 0 0 12 3zM9.5 21h5" /></svg>
  ),
  search: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5" /></svg>
  ),
  cart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg>
  ),
  shield: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6z" /><path d="m9 12 2 2 4-4" strokeLinecap="round" /></svg>
  ),
  wrench: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 1-2-2z" /></svg>
  ),
  user: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></svg>
  ),
  ask: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.5" /></svg>
  ),
  close: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
  ),
};

export function Thumb({ id, name, onOpen, large }) {
  const [failed, setFailed] = useState(false);
  return (
    <button type="button" className={`thumb${large ? " lg" : ""}`} onClick={(e) => { e.stopPropagation(); onOpen && onOpen(id); }}
      aria-label={`Details for ${name || id}`}>
      {failed || !id ? <span className="ph">{Icon.leaf}</span> : (
        <img src={imageUrl(id, "thumbnail")} alt="" loading="lazy" onError={() => setFailed(true)} />
      )}
    </button>
  );
}

export function Pill({ kind, children }) {
  return <span className={`pill${kind ? " " + kind : ""}`}>{children}</span>;
}
