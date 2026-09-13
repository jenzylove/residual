"use strict";
// Landing body: signal room (with event strip and autoplay), how it works, results.
(() => {
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x, d = 2) => x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const pp = (x, d = 1) => x == null ? "n/a" : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
const usd = (x, d = 0) => x == null ? "n/a" : (x < 0 ? "−" : x > 0 ? "+" : "") + "$" + Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const bn = m => m == null ? "n/a" : m >= 1000 ? "$" + (m / 1000).toFixed(1) + "B" : "$" + Math.round(m) + "M";
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
const day = iso => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const GATE = {
  event_data: "Filing verified", market_data: "Market data", hedge: "Hedge fits", liquidity: "Liquidity",
  robust: "Robust betas", reaction_open: "Move still open", residual_vs_cost: "Clears cost", ai_interpretation: "AI read"
};
const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
const QS = new URLSearchParams(location.search);

let D, EV = {}, ROW = {}, current = null, IO = null, auto = null;

fetch("data.json", { cache: "no-store" }).then(r => r.json()).then(d => {
  D = d; d.events.forEach(e => EV[e.event_id] = e); d.rows.forEach(r => ROW[r.event_id] = r);
  strip();
  const trades = d.rows.filter(r => r.decision.decision === "TRADE");
  show((trades[trades.length - 1] || d.rows[d.rows.length - 1]).event_id);
  results("primary");
  reveal();
  startAuto();
}).catch(e => { $("#stage").innerHTML = `<div class="card"><p>Could not load data.json: ${esc(e.message)}</p></div>`; });

/* ---------- event strip ---------- */
function strip() {
  const rows = [...D.rows].sort((a, b) => EV[a.event_id].release_ms - EV[b.event_id].release_ms);
  const t0 = EV[rows[0].event_id].release_ms, t1 = EV[rows[rows.length - 1].event_id].release_ms;
  const W = 1000, H = 96, pad = 16;
  const x = ms => pad + (ms - t0) / (t1 - t0) * (W - pad * 2);
  const maxR = Math.max(...rows.map(r => Math.abs(r.analysis.residual || 0)));
  // stagger dots that share a date region
  const placed = [];
  let g = `<line x1="${pad}" x2="${W - pad}" y1="48" y2="48" stroke="#141418" stroke-opacity=".12"/>`;
  const months = new Set();
  rows.forEach(r => {
    const e = EV[r.event_id], cx = x(e.release_ms);
    const res = r.analysis.residual, rad = res == null ? 4 : 4 + Math.abs(res) / maxR * 11;
    let cy = 48;
    for (const p of placed) if (Math.abs(p.x - cx) < p.r + rad + 2 && Math.abs(p.y - cy) < p.r + rad + 2) cy = cy <= 48 ? 48 + (48 - cy) + p.r + rad + 2 : 48 - (cy - 48);
    placed.push({ x: cx, y: cy, r: rad });
    const trade = r.decision.decision === "TRADE";
    g += `<g class="dotg" data-id="${esc(r.event_id)}" tabindex="0"><circle class="ring" cx="${cx}" cy="${cy}" r="${rad + 5}"/>
      <circle class="d" cx="${cx}" cy="${cy}" r="${rad}" fill="${trade ? "#6c4ee6" : "#c9c5d8"}" fill-opacity="${res == null ? .5 : .92}"/></g>`;
    const m = e.release_utc.slice(0, 7);
    if (!months.has(m) && ["01", "04", "07", "10"].includes(m.slice(5))) {
      months.add(m);
      g += `<text x="${cx}" y="${H - 2}" text-anchor="middle">${new Date(e.release_ms).toLocaleDateString(undefined, { month: "short", year: "2-digit", timeZone: "UTC" })}</text>`;
    }
  });
  $("#strip").innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}</svg><div class="tip" id="tip"></div>`;
  const tip = $("#tip");
  $("#strip").querySelectorAll(".dotg").forEach(el => {
    const id = el.dataset.id;
    el.onclick = () => { stopAuto(); show(id); };
    el.onkeydown = ev => { if (ev.key === "Enter") { stopAuto(); show(id); } };
    el.onmouseenter = () => {
      const c = el.querySelector("circle.d"), box = $("#strip").getBoundingClientRect(), svg = $("#strip svg").getBoundingClientRect();
      const px = +c.getAttribute("cx") / W * svg.width, py = +c.getAttribute("cy") / H * svg.height;
      const r = ROW[id];
      tip.innerHTML = `<b>${esc(EV[id].ticker)}</b> ${day(EV[id].release_utc)} · ${r.decision.decision === "TRADE" ? "trade" : "no trade"} · residual ${pct(r.analysis.residual)}`;
      tip.style.left = px + "px"; tip.style.top = py + "px"; tip.style.opacity = 1;
    };
    el.onmouseleave = () => tip.style.opacity = 0;
  });
}

/* ---------- stage ---------- */
function waterfall(d) {
  const steps = [["Market", d.market, "#9a93b5"], ["Sector", d.sector, "#b99a55"], ["Liquidity", d.liquidity, "#c5c2d0"], ["Company", d.residual, "#6c4ee6"]];
  let cum = 0; const pts = [0];
  steps.forEach(s => { cum += s[1]; pts.push(cum); });
  const lo = Math.min(0, ...pts, d.observed), hi = Math.max(0, ...pts, d.observed);
  const W = 640, L = 92, R = 76, rowH = 42;
  const H = 10 + (steps.length + 1) * rowH + 12;
  const x = v => L + (v - lo) / ((hi - lo) || 1) * (W - L - R);
  let g = `<line x1="${x(0)}" x2="${x(0)}" y1="2" y2="${H - 4}" stroke="#141418" stroke-opacity=".16"/>`;
  let c = 0;
  steps.forEach(([n, v, col], i) => {
    const y = 10 + i * rowH, a = x(c), b = x(c + v);
    g += `<text class="lbl" x="0" y="${y + 17}">${n}</text>
      <rect class="bar" x="${Math.min(a, b)}" y="${y}" width="${Math.max(2, Math.abs(b - a))}" height="24" rx="6" fill="${col}" style="transform-origin:${v >= 0 ? "left" : "right"};transition-delay:${i * 170}ms"/>
      <text x="${Math.max(a, b) + 8}" y="${y + 17}">${pct(v)}</text>`;
    if (i < steps.length - 1) g += `<line x1="${b}" x2="${b}" y1="${y + 24}" y2="${y + rowH}" stroke="#141418" stroke-opacity=".22" stroke-dasharray="2 3"/>`;
    c += v;
  });
  const y = 10 + steps.length * rowH + 8, a = x(0), b = x(d.observed);
  g += `<text class="lbl" x="0" y="${y + 17}" style="fill:#141418">Observed</text>
    <rect class="bar" x="${Math.min(a, b)}" y="${y}" width="${Math.max(2, Math.abs(b - a))}" height="24" rx="6" fill="#1b1a22" style="transform-origin:${d.observed >= 0 ? "left" : "right"};transition-delay:${steps.length * 170}ms"/>
    <text x="${Math.max(a, b) + 8}" y="${y + 17}" style="fill:#141418;font-weight:600">${pct(d.observed)}</text>`;
  return `<svg class="wf" viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

function reason(r) {
  const dec = r.decision;
  if (dec.decision === "TRADE") return `Every gate passed. RESIDUAL took the pair ${dec.direction > 0 ? "long the company" : "short the company"} against the hedge${dec.size < 1 ? `, at ${dec.size * 100}% size because the AI read the move as ${r.interpretation.label.replace(/_/g, " ")}` : ""}.`;
  const k = dec.reasons[0], g = dec.gates[k];
  const plain = {
    market_data: "Bitget did not list this stock, or enough history, at the time.",
    liquidity: "Too little volume after hours to trade this size cleanly.",
    reaction_open: "The early move had already half reversed.",
    residual_vs_cost: "The company part of the move was too small to beat trading costs.",
    robust: "The company part changed sign depending on the beta window.",
    hedge: "No hedge instrument tracked this stock closely enough.",
    ai_interpretation: "The AI read the move as not tradeable.",
    event_data: "The filing numbers could not be verified.",
  }[k];
  return `${plain || (GATE[k] + " failed.")}${dec.reasons.length > 1 ? ` ${dec.reasons.length - 1} other gate${dec.reasons.length > 2 ? "s" : ""} also failed.` : ""}`;
}

function show(id) {
  current = id;
  document.querySelectorAll(".dotg").forEach(el => el.classList.toggle("sel", el.dataset.id === id));
  const r = ROW[id], e = EV[id], a = r.analysis, s = e.surprise || {}, d = a.decomposition, dec = r.decision, it = r.interpretation;
  const trade = dec.decision === "TRADE", t = r.residual;
  const plain = d ? `${esc(e.ticker)} moved <b>${pct(d.observed)}</b> in the two hours after its release. The market explains <b>${pct(d.market)}</b>, the sector <b>${pct(d.sector)}</b>. The part that belongs to the company is <b class="${cls(d.residual)}">${pct(d.residual)}</b>.` : "";
  $("#stage").innerHTML = `
    <div class="stage-col">
      <div class="card">
        <div class="ev-head"><div><div class="ev-name">${esc(e.ticker)} <em>${d ? pct(d.residual) : ""}</em></div>
          <div class="ev-sub">${day(e.release_utc)} · revenue ${bn(s.revenue_actual)} vs guidance ${bn(s.revenue_guided_mid)} (${pp(s.guidance_surprise_pct)})</div></div></div>
        ${d ? waterfall(d) + `<p class="plain">${plain}</p>` : `<p class="plain">No breakdown: ${esc((a.gates.market_data || {}).detail || "market data missing")}.</p>`}
      </div>
    </div>
    <div class="stage-col">
      <div class="card verdict ${trade ? "trade" : ""}">
        <h4>Decision</h4>
        <div class="v">${trade ? "Trade" : "No trade"}</div>
        <p class="why">${esc(reason(r))}</p>
        ${trade && a.hedge ? `<div class="pair"><div class="leg ${dec.direction > 0 ? "long" : "short"}"><div class="side">${dec.direction > 0 ? "Long" : "Short"}</div><div class="sym">${esc(e.ticker)}</div></div>
          <div class="vs">VS</div><div class="leg ${dec.direction > 0 ? "short" : "long"}"><div class="side">${dec.direction > 0 ? "Short" : "Long"}</div><div class="sym">${esc(a.hedge.symbol.replace("USDT", ""))}</div></div></div>
          <p class="pnl">Hedge ratio ${a.hedge.beta.toFixed(2)} · paper result <b class="${cls(t && t.net)}">${t ? usd(t.net, 0) : "n/a"}</b>${t && t.funding_data !== "complete" ? " · funding data unavailable" : ""}</p>` : ""}
      </div>
      <div class="card"><h4>Gates</h4><ul class="gates">${Object.entries(dec.gates).map(([k, g], i) =>
        `<li style="transition-delay:${i * 70}ms" title="${esc(g.detail)}"><span class="tick ${g.pass ? "ok" : "bad"}">${g.pass ? "✓" : "✕"}</span>${esc(GATE[k] || k)}</li>`).join("")}</ul></div>
      ${it && it.status === "ok" ? `<div class="card"><h4>From the filing, via the AI read</h4><p class="quote">“${esc(it.evidence_quotes[0])}”</p>
        <p class="ai-label">Read as <b>${esc(it.label.replace(/_/g, " "))}</b> · quote verified in the press release</p></div>` : ""}
    </div>`;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $("#stage").querySelectorAll(".wf").forEach(w => w.classList.add("go"));
    $("#stage").querySelectorAll(".gates").forEach(w => w.classList.add("go"));
  }));
}

/* ---------- autoplay through the trades until the visitor clicks ---------- */
function startAuto() {
  if (REDUCE || QS.has("static")) return;
  const ids = D.rows.filter(r => r.decision.decision === "TRADE").map(r => r.event_id);
  let i = Math.max(0, ids.indexOf(current));
  const stage = $("#signal");
  let visible = false;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }, { threshold: .35 }).observe(stage);
  auto = setInterval(() => { if (!visible) return; i = (i + 1) % ids.length; show(ids[i]); }, 6500);
}
function stopAuto() { if (auto) { clearInterval(auto); auto = null; } }

/* ---------- results ---------- */
function results(basis) {
  const views = { primary: ["Complete funding data", D.summary], conservative: ["Worst case funding", D.summary_conservative_funding], observed_zero: ["Missing funding as zero", D.summary_observed_zero_funding] };
  $("#basis").innerHTML = Object.entries(views).map(([k, [n]]) => `<button class="chip ${k === basis ? "on" : ""}" data-b="${k}">${n}</button>`).join("");
  $("#basis").querySelectorAll("button").forEach(b => b.onclick = () => results(b.dataset.b));
  const S = views[basis][1];
  const items = [["Residual pair", "the hedged company trade", S.residual, "#6c4ee6"], ["Unhedged", "same signals, no hedge", S.unhedged, "#b99a55"], ["Naive headline", "beat goes long, same events", S.naive_same_events, "#d0453b"]];
  const max = Math.max(...items.map(i => Math.abs(i[2].total_net_pnl))) || 1;
  $("#bars").innerHTML = items.map(([n, sub, m, col]) => {
    const v = m.total_net_pnl, w = Math.abs(v) / max * 50;
    return `<div class="barrow"><div class="name">${n}<small>${sub}</small></div>
      <div class="track"><span class="zero" style="left:50%"></span><i style="left:50%;width:0;background:${col}" data-l="${v < 0 ? 50 - w : 50}%" data-w="${w}%"></i></div>
      <div class="val ${cls(v)}">${usd(v, 0)}</div></div>`;
  }).join("");
  requestAnimationFrame(() => requestAnimationFrame(() => $("#bars").querySelectorAll("i").forEach(i => { i.style.left = i.dataset.l; i.style.width = i.dataset.w; })));
  const tr = S.residual.trades;
  $("#res-note").innerHTML = {
    primary: `${tr} paper trades with complete funding data, $10,000 company notional each. On these events the plain headline trade did better than the residual pair. A sample this small proves nothing either way, which is why every number is published in the audit.`,
    conservative: `All ${tr} paper trades, with any missing funding charged at the worst rate seen on Bitget.`,
    observed_zero: `All ${tr} paper trades, with missing funding taken as zero. Shown for comparison; it flatters trades with unknown funding.`,
  }[basis];
}

/* ---------- motion ---------- */
function typeIn(el) {
  const text = el.dataset.text || "";
  if (REDUCE || QS.has("static")) { el.textContent = text; el.classList.add("done"); return; }
  let i = 0;
  const step = () => { el.textContent = text.slice(0, ++i); if (i < text.length) setTimeout(step, 36 + Math.random() * 36); else el.classList.add("done"); };
  setTimeout(step, 250);
}
function reveal() {
  IO = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in");
    e.target.querySelectorAll(".tw").forEach(typeIn);
    IO.unobserve(e.target);
  }), { threshold: .12 });
  document.querySelectorAll(".rv").forEach(el => IO.observe(el));
  if (QS.has("nohero")) $(".hero").style.display = "none";
  if (QS.has("static")) document.querySelectorAll(".rv").forEach(el => { el.classList.add("in"); el.querySelectorAll(".tw").forEach(typeIn); });
  // layout self check: ?check writes horizontal overflow into the page title
  if (QS.has("check")) setTimeout(() => {
    const over = document.documentElement.scrollWidth - innerWidth;
    const wide = [...document.querySelectorAll("#body *")].filter(n => n.getBoundingClientRect().right > innerWidth + 1).map(n => n.className || n.tagName).slice(0, 5);
    document.title = `CHECK overflow=${over} wide=${JSON.stringify(wide)}`;
  }, 1500);
}
})();
