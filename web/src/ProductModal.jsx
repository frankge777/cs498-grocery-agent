import React, { useEffect, useState } from "react";
import { Icon, Pill, api, money, tagLabel } from "./lib.jsx";

const NUTRIENTS = [
  ["calories", "Calories", true], ["total_fat", "Total Fat"], ["saturated_fat", "Saturated Fat", false, true],
  ["sodium", "Sodium"], ["total_carbohydrate", "Total Carbohydrate"], ["dietary_fiber", "Dietary Fiber", false, true],
  ["sugar", "Total Sugars", false, true], ["protein", "Protein"],
];

export default function ProductModal({ id, source, locationId, onClose }) {
  const [p, setP] = useState(null);
  const [error, setError] = useState("");
  const [view, setView] = useState(0);
  const [broken, setBroken] = useState({});

  useEffect(() => {
    setP(null); setError(""); setView(0); setBroken({});
    const q = new URLSearchParams({ source: source || "auto" });
    if (locationId) q.set("location_id", locationId);
    api(`/api/products/${id}?${q}`).then(setP).catch((e) => setError(e.message));
  }, [id, source, locationId]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const images = (p?.images || []).filter((im) => !broken[im.url]);
  const img = images[Math.min(view, images.length - 1)];
  const n = p?.nutrition_per_serving || {};
  const fmt = (v) => (v ? `${v.quantity}${v.unit && !/kilocalorie/.test(v.unit) ? ` ${v.unit}` : ""}` : null);
  const perOz = p && p.unit === "g" && p.size ? `${money(Math.round(p.price_cents / (p.size / 28.3495)))}/oz` : null;

  return (
    <div className="pd-wrap" onClick={onClose}>
      <div className="pd" role="dialog" aria-modal="true" aria-label={p?.name || "Product"} onClick={(e) => e.stopPropagation()}>
        <button className="pd-x" onClick={onClose} aria-label="Close">{Icon.close}</button>
        {!p ? <div className="pd-info">{error ? <div className="err">{error}</div> : <div className="muted">Loading product from {source === "live" ? "Kroger" : "the store data"}…</div>}</div> : (
          <>
            <div className="pd-top">
              <div className="pd-img">
                {img ? <img src={img.url} alt={`${p.name}, ${img.perspective}`} onError={() => setBroken((b) => ({ ...b, [img.url]: true }))} /> : <span className="ph">{Icon.leaf}</span>}
                {images.length > 1 && (
                  <div className="pd-tabs">
                    {images.map((im, i) => <button key={im.url} aria-pressed={i === view} onClick={() => setView(i)}>{im.perspective}</button>)}
                  </div>
                )}
                {img && <div className="pd-cap">{img.url.replace(/^https?:\/\/(www\.)?/, "")}</div>}
              </div>
              <div className="pd-info">
                <div className="eyebrow">{p.brand}</div>
                <h2>{p.name}</h2>
                <div className="pd-price"><b className="num">{money(p.price_cents)}</b><span className="muted">{p.raw_size}{perOz ? ` · ${perOz}` : ""}</span></div>
                <div className="pd-tags">
                  <Pill kind={p.in_stock ? "ok" : "bad"}>{p.in_stock ? `In stock${p.stock_level ? ` · ${p.stock_level.toLowerCase().replace(/_/g, " ")}` : ""}` : "Out of stock"}</Pill>
                  {(p.manufacturer_declarations || []).map((d) => <Pill key={d}>{d}</Pill>)}
                </div>
                <dl className="kv">
                  <dt>Size</dt><dd>{p.raw_size || `${p.size} ${p.unit}`}</dd>
                  {p.sold_by && <><dt>Sold by</dt><dd>{p.sold_by.toLowerCase()}</dd></>}
                  {p.servings_per_package && <><dt>Servings</dt><dd>{p.servings_per_package} per package</dd></>}
                  {p.availability && <><dt>Available</dt><dd>{Object.entries(p.availability).filter(([, v]) => v).map(([k]) => k.replace(/([A-Z])/g, " $1").toLowerCase()).join(", ")}</dd></>}
                  {p.aisles?.length > 0 && <><dt>Aisle</dt><dd>{p.aisles.join(", ")}</dd></>}
                  {p.country_origin && <><dt>Origin</dt><dd>{p.country_origin}</dd></>}
                  <dt>UPC</dt><dd className="num">{p.upc || p.id}</dd>
                </dl>
              </div>
            </div>
            <div className="pd-body">
              <div className="stack" style={{ gap: 14 }}>
                {(p.allergens?.contains?.length > 0 || p.allergens?.may_contain?.length > 0) && (
                  <div className="pd-sec"><h4>Allergens</h4>
                    {p.allergens.contains.length > 0 && <p>Contains: {p.allergens.contains.map(tagLabel).join(", ")}</p>}
                    {p.allergens.may_contain.length > 0 && <p className="muted">May contain: {p.allergens.may_contain.map(tagLabel).join(", ")}</p>}
                  </div>
                )}
                {p.ingredient_statement && <div className="pd-sec"><h4>Ingredients</h4><p>{p.ingredient_statement}</p></div>}
                <div className="live-only">{p.data_source === "live" ? "Read live from the Kroger Products API just now." : "From the frozen Nov 16 Kroger snapshot of this store. Live mode also shows aisle and origin."}</div>
              </div>
              {Object.keys(n).length > 0 && (
                <div className="nf">
                  <h4>Nutrition Facts</h4>
                  {p.serving_size?.quantity && <div className="r"><span>Serving size</span><b>{p.serving_size.quantity} {p.serving_size.unit}</b></div>}
                  {NUTRIENTS.filter(([k]) => n[k]).map(([k, label, big, ind], i) => (
                    <div key={k} className={`r ${i === 0 ? "thick" : ""} ${big ? "mid" : ""} ${ind ? "ind" : ""}`}><span>{big ? <b>{label}</b> : label}</span><b>{fmt(n[k])}</b></div>
                  ))}
                </div>
              )}
            </div>
            <div className="pd-actions">
              <span className="muted small">{p.location?.name}</span>
              <span className="spacer" />
              <a className="btn ghost small" href={p.product_page_url || p.search_url} target="_blank" rel="noreferrer">View on kroger.com ↗</a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
