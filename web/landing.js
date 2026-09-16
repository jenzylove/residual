"use strict";
// Landing body: overview, signal room (strip + stage + autoplay), paper execution, proof.
(() => {
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x, d = 2) => x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const pp = (x, d = 1) => x == null ? "n/a" : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
const usd = (x, d = 0) => x == null ? "n/a" : (x < 0 ? "−" : x > 0 ? "+" : "") + "$" + Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const bn = m => m == null ? "n/a" : m >= 1000 ? "$" + (m / 1000).toFixed(1) + "B" : "$" + Math.round(m) + "M";
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
const day = iso => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const when = ms => new Date(ms).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
const GATE = {
  event_data: "Filing verified", market_data: "Market data", hedge: "Hedge fits", liquidity: "Liquidity",
  robust: "Robust betas", reaction_open: "Move still open", residual_vs_cost: "Clears cost", ai_interpretation: "AI read",
  variant: "Rule agrees"
};
const PLAIN = {
  market_data: "Bitget did not list this stock, or enough of its history, at the time.",
  liquidity: "Too little volume after hours to trade this size cleanly.",
  reaction_open: "The early move had already half reversed.",
  residual_vs_cost: "The company's own move was too small to beat trading costs.",
  robust: "The company's own move changed sign depending on the model window.",
  hedge: "No hedge instrument tracked this stock closely enough.",
  ai_interpretation: "The AI read the move as not tradeable.",
  variant: "The chosen rule needs the company move and the surprise to agree, and here they did not.",
  event_data: "The filing numbers could not be verified.",
};
const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
const QS = new URLSearchParams(location.search);

let D, EV = {}, ROW = {}, current = null, IO = null, auto = null;

fetch("data.json", { cache: "no-store" }).then(r => r.json()).then(d => {
  D = d; d.events.forEach(e => EV[e.event_id] = e); d.rows.forEach(r => ROW[r.event_id] = r);
  overview();
  strip();
  const trades = d.rows.filter(r => r.decision.decision === "TRADE");
  show((trades[trades.length - 1] || d.rows[d.rows.length - 1]).event_id);
  proof("conservative");
  const sv = document.querySelector(".status-val");
  if (sv) sv.textContent = D.rows.length + " real earnings events · SEC verified";
  realStrip();
  variantsTable();
  sizeStudy();
  demoMode();
  demoStrategy();
  reveal();
  startAuto();
  tour();
  liveStatus();
}).catch(e => { $("#ov-grid").innerHTML = `<div class="card wide"><p>Could not load data.json: ${esc(e.message)}</p></div>`; });

/* ---------- small visuals ---------- */
function spark(curves) {
  const W = 600, H = 80, all = curves.flat(), n = Math.max(...curves.map(c => c.length));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const x = i => i / Math.max(1, n - 1) * W, y = v => H - 4 - (v - lo) / ((hi - lo) || 1) * (H - 8);
  const path = c => c.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="#141418" stroke-opacity=".12"/>
    <path class="line" d="${path(curves[0])}" fill="none" stroke="#6c4ee6" stroke-width="2.2" vector-effect="non-scaling-stroke"/>
    <path class="line" d="${path(curves[1])}" fill="none" stroke="#d0453b" stroke-width="1.4" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/>
  </svg>`;
}
function dial(frac) {
  const r = 46, c = 2 * Math.PI * r;
  return `<svg class="dial" viewBox="0 0 112 112"><circle cx="56" cy="56" r="${r}" fill="none" stroke="rgba(20,20,24,.07)" stroke-width="10"/>
    <circle class="arc" cx="56" cy="56" r="${r}" fill="none" stroke="#6c4ee6" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${c}" data-off="${c * (1 - frac)}" transform="rotate(-90 56 56)"/>
    <text x="56" y="62" text-anchor="middle" font-size="17" fill="#141418">${Math.round(frac * 100)}%</text></svg>`;
}

/* ---------- overview ---------- */
function overview() {
  const rows = D.rows, trades = rows.filter(r => r.decision.decision === "TRADE"), traded = trades.filter(r => r.residual);
  const complete = traded.filter(r => r.residual.funding_data === "complete").length;
  const P = D.summary_conservative_funding.residual, N = D.summary_conservative_funding.naive_same_events;
  const latest = [...rows].sort((a, b) => EV[b.event_id].release_ms - EV[a.event_id].release_ms).slice(0, 4);
  const live = (D.live_log || []).slice(-1)[0];
  const next = live ? Object.entries(live.next_estimated_release || {})[0] : null;
  const badge = d => d === "TRADE" ? '<span class="badge b-trade">Trade</span>' : '<span class="badge b-no">No trade</span>';
  $("#ov-grid").innerHTML = `
    <div class="card wide rv">
      <h4>Paper result <span class="badge b-paper" style="margin-left:8px">Paper only</span></h4>
      <div style="display:flex;gap:48px;flex-wrap:wrap;align-items:flex-end">
        <div><div class="big ${cls(P.total_net_pnl)}">${usd(P.total_net_pnl, 0)}</div><p class="note">Strategy, all ${P.trades} trades, worst case funding</p></div>
        <div><div class="big ${cls(N.total_net_pnl)}">${usd(N.total_net_pnl, 0)}</div><p class="note">Plain headline trade, same releases</p></div>
      </div>
      ${spark([P.equity_curve, N.equity_curve])}
    </div>
    <div class="card rv">
      <h4>Decisions</h4>
      <div style="display:flex;align-items:center;gap:20px">${dial(trades.length / rows.length)}
        <div><div class="big">${trades.length}</div><p class="note" style="margin-top:6px">trades out of ${rows.length} releases</p></div></div>
    </div>
    <div class="card rv">
      <h4>Latest releases</h4>
      <ul class="mini">${latest.map(r => `<li><a href="#signal" data-open="${esc(r.event_id)}"><b>${esc(EV[r.event_id].ticker)}</b> <span class="muted">${day(EV[r.event_id].release_utc)}</span></a>${badge(r.decision.decision)}</li>`).join("")}</ul>
    </div>
    <div class="card rv" id="watcher-card">
      <h4>Watcher</h4>
      ${live ? `<div style="display:flex;gap:10px;align-items:center"><i class="dot live"></i><b>${live.decision === "NO_TRADE" ? "Watching, nothing to trade" : esc(live.decision)}</b></div>
        <p class="note">${next ? `Next expected release: ${esc(next[0])} around ${esc(next[1])}.` : ""} Last check ${esc(live.checked_at.slice(0, 10))}.</p>` : `<p class="note">No watcher run yet.</p>`}
    </div>
    <div class="card rv">
      <h4>Funding data</h4>
      <div class="big">${complete}<span class="muted" style="font-size:.45em"> of ${traded.length} trades complete</span></div>
      <div class="meter"><i style="background:#1f9d6c" data-w="${traded.length ? complete / traded.length * 100 : 0}%"></i><i style="background:#e3b54b" data-w="${traded.length ? (traded.length - complete) / traded.length * 100 : 0}%"></i></div>
    </div>`;
  document.querySelectorAll("[data-open]").forEach(a => a.onclick = e => { e.preventDefault(); stopAuto(); show(a.dataset.open); $("#signal").scrollIntoView({ behavior: "smooth" }); });
}

/* ---------- live watcher status (published by the scheduled watcher) ---------- */
function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(s)) return "";
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + " min ago";
  if (s < 172800) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
}

function liveStatus() {
  fetch("live.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null).then(L => {
    const el = $("#watcher-card");
    if (!L || !el) return;
    const next = Object.entries(L.next_estimated_release || {})[0];
    const fresh = (Date.now() - new Date(L.checked_at).getTime()) < 45 * 60_000;
    const probe = (L.market_probe || []).find(p => p && !p.error);
    el.innerHTML = `<h4>Watcher <span class="badge ${fresh ? "b-trade" : "b-no"}" style="margin-left:8px">${fresh ? "live" : "idle"}</span></h4>
      <div style="display:flex;gap:10px;align-items:center"><i class="dot live"></i><b>${L.decision === "NO_TRADE" ? "Watching, nothing to trade" : esc(L.decision)}</b></div>
      <p class="note">Checked ${esc(ago(L.checked_at))} (${esc((L.checked_at || "").replace("T", " ").slice(0, 16))} UTC). ${esc(L.reason || "")}.</p>
      ${next ? `<p class="note">Next expected release: <b>${esc(next[0])}</b> around ${esc(next[1])}.</p>` : ""}
      ${probe ? `<p class="note">Bitget live: ${esc(probe.symbol.replace("USDT", ""))} ${probe.bid} / ${probe.ask}, spread ${probe.spread_bps} bps.</p>` : ""}
      <p class="note">${(L.recent || []).length} recent checks published by the agent itself.</p>`;
  }).catch(() => {});
}

/* ---------- event strip ---------- */
function strip() {
  const rows = [...D.rows].sort((a, b) => EV[a.event_id].release_ms - EV[b.event_id].release_ms);
  const t0 = EV[rows[0].event_id].release_ms, t1 = EV[rows[rows.length - 1].event_id].release_ms;
  const W = 1000, H = 100, pad = 16, mid = 46;
  const x = ms => pad + (ms - t0) / (t1 - t0) * (W - pad * 2);
  const maxR = Math.max(...rows.map(r => Math.abs(r.analysis.residual || 0)));
  const placed = [], months = new Set();
  let g = `<line x1="${pad}" x2="${W - pad}" y1="${mid}" y2="${mid}" stroke="#141418" stroke-opacity=".12"/>`;
  rows.forEach(r => {
    const e = EV[r.event_id], cx = x(e.release_ms), res = r.analysis.residual;
    const rad = res == null ? 4 : 4 + Math.abs(res) / maxR * 11;
    let cy = mid, k = 0;
    while (placed.some(p => Math.hypot(p.x - cx, p.y - cy) < p.r + rad + 2) && k < 8) { k++; cy = mid + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * (rad + 6); }
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
      const c = el.querySelector("circle.d"), svg = $("#strip svg").getBoundingClientRect();
      tip.innerHTML = `<b>${esc(EV[id].ticker)}</b> ${day(EV[id].release_utc)} · ${ROW[id].decision.decision === "TRADE" ? "trade" : "no trade"} · company move ${pct(ROW[id].analysis.residual)}`;
      tip.style.left = (+c.getAttribute("cx") / W * svg.width) + "px"; tip.style.top = (+c.getAttribute("cy") / H * svg.height) + "px"; tip.style.opacity = 1;
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
  const W = 640, L = 92, R = 76, rowH = 44, H = 10 + (steps.length + 1) * rowH + 12;
  const x = v => L + (v - lo) / ((hi - lo) || 1) * (W - L - R);
  let g = `<line x1="${x(0)}" x2="${x(0)}" y1="2" y2="${H - 4}" stroke="#141418" stroke-opacity=".16"/>`, c = 0;
  steps.forEach(([n, v, col], i) => {
    const y = 10 + i * rowH, a = x(c), b = x(c + v);
    g += `<text class="lbl" x="0" y="${y + 17}">${n}</text>
      <rect class="bar" x="${Math.min(a, b)}" y="${y}" width="${Math.max(3, Math.abs(b - a))}" height="24" rx="6" fill="${col}" style="transform-origin:${v >= 0 ? "left" : "right"};animation-delay:${i * 160}ms"/>
      <text x="${Math.max(a, b) + 8}" y="${y + 17}">${pct(v)}</text>`;
    if (i < steps.length - 1) g += `<line x1="${b}" x2="${b}" y1="${y + 24}" y2="${y + rowH}" stroke="#141418" stroke-opacity=".22" stroke-dasharray="2 3"/>`;
    c += v;
  });
  const y = 10 + steps.length * rowH + 8, a = x(0), b = x(d.observed);
  g += `<text class="lbl" x="0" y="${y + 17}" style="fill:#141418">Observed</text>
    <rect class="bar" x="${Math.min(a, b)}" y="${y}" width="${Math.max(3, Math.abs(b - a))}" height="24" rx="6" fill="#1b1a22" style="transform-origin:${d.observed >= 0 ? "left" : "right"};animation-delay:${steps.length * 160}ms"/>
    <text x="${Math.max(a, b) + 8}" y="${y + 17}" style="fill:#141418;font-weight:600">${pct(d.observed)}</text>`;
  return `<svg class="wf" viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

function reason(r) {
  const dec = r.decision;
  const rule = r.variant ? ` using the ${r.variant.variant} rule, picked from earlier events` : "";
  if (dec.decision === "TRADE") return `Every gate passed. RESIDUAL took the pair ${dec.direction > 0 ? "long the company" : "short the company"} against the hedge${rule}${dec.size < 1 && r.interpretation ? `, at ${dec.size * 100}% size because the AI read the move as ${r.interpretation.label.replace(/_/g, " ")}` : ""}.`;
  const k = dec.reasons[0];
  return `${PLAIN[k] || GATE[k] + " failed."}${dec.reasons.length > 1 ? ` ${dec.reasons.length - 1} other gate${dec.reasons.length > 2 ? "s" : ""} also failed.` : ""}`;
}

function show(id) {
  current = id;
  document.querySelectorAll(".dotg").forEach(el => el.classList.toggle("sel", el.dataset.id === id));
  const r = ROW[id], e = EV[id], a = r.analysis, s = e.surprise || {}, d = a.decomposition, dec = r.decision, it = r.interpretation;
  const trade = dec.decision === "TRADE", t = r.residual;
  const plain = d ? `${esc(e.ticker)} moved <b>${pct(d.observed)}</b> in the two hours after its release. The market explains <b>${pct(d.market)}</b> and the sector <b>${pct(d.sector)}</b>. The part that belongs to the company is <b class="${cls(d.residual)}">${pct(d.residual)}</b>.` : "";
  $("#stage").innerHTML = `
    <div class="stage-col">
      <div class="card">
        <div class="ev-name">${esc(e.ticker)} <em>${d ? pct(d.residual) : ""}</em></div>
        <div class="ev-sub">${day(e.release_utc)} · <a href="${esc(e.source.press_release_url)}" target="_blank" rel="noopener" title="SEC press release, sha256 ${esc((e.source.sha256 || "").slice(0, 16))}">revenue ${bn(s.revenue_actual)}</a> against guidance of <a href="${esc(e.prior_source.press_release_url)}" target="_blank" rel="noopener">${bn(s.revenue_guided_mid)}</a> (${pp(s.guidance_surprise_pct)})${e.earnings.gross_margin ? ` · GAAP gross margin ${e.earnings.gross_margin.value}%` : ""}${e.earnings.eps_diluted ? ` · diluted EPS $${e.earnings.eps_diluted.value}` : ""}${e.consensus ? ` · analyst consensus EPS ${e.consensus.eps_estimate} vs ${e.consensus.eps_reported} reported (${pp(e.consensus.consensus_surprise_pct)}${e.consensus.quality === "ok" ? "" : ", basis mismatch: not traded"})` : ""}</div>
        ${d ? waterfall(d) + `<p class="plain">${plain}</p>` : `<p class="plain">No breakdown for this release: ${esc(PLAIN.market_data)}</p>`}
      </div>
    </div>
    <div class="stage-col">
      <div class="card verdict ${trade ? "trade" : ""}">
        <h4>Decision</h4>
        <div class="v">${trade ? "Trade" : "No trade"}</div>
        <p class="why">${esc(reason(r))}</p>
        ${trade && a.hedge ? `<div class="pair"><div class="leg ${dec.direction > 0 ? "long" : "short"}"><div class="side">${dec.direction > 0 ? "Long" : "Short"}</div><div class="sym">${esc(e.ticker)}</div></div>
          <div class="vs">VS</div><div class="leg ${dec.direction > 0 ? "short" : "long"}"><div class="side">${dec.direction > 0 ? "Short" : "Long"}</div><div class="sym">${esc(a.hedge.symbol.replace("USDT", ""))}</div></div></div>` : ""}
      </div>
      <div class="card"><h4>Gates</h4><ul class="gates">${Object.entries(dec.gates).map(([k, g], i) =>
        `<li style="animation-delay:${i * 60}ms" title="${esc(g.detail)}"><span class="tick ${g.pass ? "ok" : "bad"}">${g.pass ? "✓" : "✕"}</span>${esc(GATE[k] || k)}</li>`).join("")}</ul></div>
      ${it && it.status === "ok" ? `<div class="card"><h4>From the filing, via the AI read</h4><p class="quote">“${esc(it.evidence_quotes[0])}”</p>
        <p class="ai-label">Read as <b>${esc(it.label.replace(/_/g, " "))}</b> · quote checked against the press release</p></div>` : ""}
    </div>`;
  execution(r, e);
}

/* ---------- paper execution ---------- */
function execution(r, e) {
  const dec = r.decision, t = r.residual;
  if (dec.decision !== "TRADE" || !t) {
    $("#exec").innerHTML = `<div class="exec-grid"><div class="card full notrade">
      <div class="big">No trade</div>
      <p class="plain">${esc(e.ticker)} on ${day(e.release_utc)} was left alone. Nothing was sized and nothing was sent.</p>
      <ul class="gates" style="margin-top:24px">${dec.reasons.map((k, i) => `<li style="animation-delay:${i * 60}ms"><span class="tick bad">✕</span><span><b>${esc(GATE[k] || k)}</b> <span class="muted">· ${esc(PLAIN[k] || (dec.gates[k] || {}).detail || "")}</span></span></li>`).join("")}</ul>
    </div></div>`;
    return;
  }
  const at = t.attribution;
  const items = [["Company's own move", at.residual], ["Hedge mismatch", at.factor_error], ["Fees", at.fees], ["Slippage", at.slippage], ["Funding", at.funding]];
  const max = Math.max(...items.map(i => Math.abs(i[1]))) || 1;
  $("#exec").innerHTML = `<div class="exec-grid">
    <div class="card">
      <h4>The pair</h4>
      <div class="big ${cls(t.net)}">${usd(t.net, 2)}</div>
      <p class="note">Paper result after fees, slippage and funding · ${t.stopped ? "closed by the stop" : "closed at the 24 hour horizon"}</p>
      <div class="legs">${t.legs.map(l => `<div class="legrow"><span><b>${esc(l.symbol.replace("USDT", ""))}</b> <small>${l.role === "company" ? "company leg" : "hedge leg"} · ${l.side}</small></span><span class="muted">${l.entry_fill.toFixed(2)} → ${l.exit_fill.toFixed(2)}</span><span class="${cls(l.net)}">${usd(l.net, 2)}</span></div>`).join("")}</div>
      <dl class="kv"><dt>Opened</dt><dd>${when(t.entry_ms)}</dd><dt>Closed</dt><dd>${when(t.exit_ms)}</dd></dl>
      ${t.funding_data !== "complete" ? `<div class="warn">Bitget no longer publishes funding history for this period, so this trade is left out of the main result. A worst case funding charge of ${usd(t.funding_conservative, 2)} is used in the stress view.</div>` : ""}
    </div>
    <div class="card">
      <h4>Where the result came from</h4>
      <div class="attr">${items.map(([k, v]) => `<span>${k}</span><div class="track"><i style="left:${v < 0 ? 50 - Math.abs(v) / max * 50 : 50}%;width:${Math.abs(v) / max * 50}%;background:${v < 0 ? "#d0453b" : "#1f9d6c"}"></i></div><span class="${cls(v)}">${usd(v, 2)}</span>`).join("")}</div>
      <p class="note">Over the hold, ${esc(e.ticker)} moved ${pct(at.hold_returns.company)}. The market and sector model expected ${pct(at.hold_returns.factor_predicted)}. The gap is the company's own move, which is what the trade was betting on.</p>
    </div></div>`;
}

/* ---------- autoplay ---------- */
function startAuto() {
  if (REDUCE || QS.has("static")) return;
  const ids = D.rows.filter(r => r.decision.decision === "TRADE").map(r => r.event_id);
  let i = Math.max(0, ids.indexOf(current)), visible = false;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }, { threshold: .35 }).observe($("#stage"));
  auto = setInterval(() => { if (!visible) return; i = (i + 1) % ids.length; show(ids[i]); }, 7000);
}
function stopAuto() { if (auto) { clearInterval(auto); auto = null; } }

/* ---------- proof ---------- */
function curve(S) {
  const series = [["Residual pair", S.residual.equity_curve, "#6c4ee6", 2.6], ["Unhedged", S.unhedged.equity_curve, "#b99a55", 1.6], ["Plain headline, same releases", S.naive_same_events.equity_curve, "#d0453b", 1.6]];
  const W = 600, H = 260, pad = 52, all = series.flatMap(s => s[1]), n = Math.max(...series.map(s => s[1].length));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const x = i => pad + i / Math.max(1, n - 1) * (W - pad - 8), y = v => H - 24 - (v - lo) / ((hi - lo) || 1) * (H - 40);
  let g = `<line x1="${pad}" x2="${W - 8}" y1="${y(0)}" y2="${y(0)}" stroke="#141418" stroke-opacity=".15"/><text x="0" y="${y(hi) + 4}">${usd(hi)}</text><text x="0" y="${y(0) + 4}">$0</text><text x="0" y="${y(lo)}">${usd(lo)}</text><text x="${pad}" y="${H - 4}">first release</text><text x="${W - 8}" y="${H - 4}" text-anchor="end">latest</text>`;
  series.forEach(([, v, col, w], k) => g += `<polyline fill="none" stroke="${col}" stroke-width="${w}" ${k === 2 ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round" points="${v.map((p, i) => x(i) + "," + y(p)).join(" ")}"/>`);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${g}</svg><div class="legend">${series.map(s => `<span><i style="background:${s[2]}"></i>${esc(s[0])}</span>`).join("")}</div>`;
}

function proof(basis) {
  const views = { conservative: ["All trades, worst case funding", D.summary_conservative_funding], primary: ["Complete funding data only", D.summary], observed_zero: ["Missing funding as zero", D.summary_observed_zero_funding] };
  $("#basis").innerHTML = Object.entries(views).map(([k, [n]]) => `<button class="chip ${k === basis ? "on" : ""}" data-b="${k}">${n}</button>`).join("");
  $("#basis").querySelectorAll("button").forEach(b => b.onclick = () => proof(b.dataset.b));
  const S = views[basis][1];
  const items = [["Residual pair", "the hedged company trade", S.residual, "#6c4ee6"], ["Unhedged", "same signals, no hedge", S.unhedged, "#b99a55"], ["Plain headline", "buy beats, same releases", S.naive_same_events, "#d0453b"]];
  const max = Math.max(...items.map(i => Math.abs(i[2].total_net_pnl))) || 1;
  $("#bars").innerHTML = items.map(([n, sub, m, col]) => {
    const v = m.total_net_pnl, w = Math.abs(v) / max * 50;
    return `<div class="barrow"><div class="name">${n}<small>${sub}</small></div>
      <div class="track"><span class="zero"></span><i style="left:50%;width:0;background:${col}" data-l="${v < 0 ? 50 - w : 50}%" data-w="${w}%"></i></div>
      <div class="val ${cls(v)}">${usd(v, 0)}</div></div>`;
  }).join("");
  requestAnimationFrame(() => requestAnimationFrame(() => $("#bars").querySelectorAll("i").forEach(i => { i.style.left = i.dataset.l; i.style.width = i.dataset.w; })));
  const f = v => v == null ? "n/a" : v.toFixed(2);
  const W = D.summary_last_90d || {}, win = D.summary_last_90d_window;
  const rowR = (n, m) => m ? `<tr><td>${n}</td><td class="num">${f(m.sharpe_daily_ann)}</td><td class="num">${f(m.sortino_daily_ann)}</td><td class="num">${f(m.sharpe_per_trade)}</td><td class="num neg">${usd(m.max_drawdown, 0)}</td></tr>` : "";
  $("#bars").insertAdjacentHTML("beforeend", `<div class="ratios"><table><thead><tr><th>${esc(views[basis][0])}</th><th class="num">Sharpe</th><th class="num">Sortino</th><th class="num">Sharpe / trade</th><th class="num">Max DD</th></tr></thead><tbody>
    ${rowR("Residual pair", S.residual)}${rowR("Plain headline, same releases", S.naive_same_events)}</tbody></table>
    ${win && W.residual ? `<p class="note">Last 90 days of real history (${day(new Date(win.from_ms).toISOString())} to ${day(new Date(win.to_ms).toISOString())}, ${win.events} releases): residual Sharpe ${f(W.residual.sharpe_daily_ann)}, Sortino ${f(W.residual.sortino_daily_ann)}, max drawdown ${usd(W.residual.max_drawdown, 0)} over ${W.residual.trades} trades.</p>` : ""}
    <p class="note">Sharpe and Sortino use daily paper P&amp;L on a $100,000 book, annualised over 365 days because Bitget perpetuals trade every day.</p></div>`);
  const tr = S.residual.trades;
  $("#res-note").textContent = {
    primary: `${tr} paper trades with complete funding data, $10,000 on the company side each. On these releases the plain headline trade did better than the residual pair. A sample this small proves nothing either way, which is why every trade is published.`,
    conservative: `All ${tr} paper trades, with any missing funding charged at the worst rate seen on Bitget.`,
    observed_zero: `All ${tr} paper trades, with missing funding counted as zero. Shown for comparison only.`,
  }[basis];
  $("#curve").innerHTML = curve(S);
  demoProof();
}

function demoProof() {
  const x = D.demo_evidence, el = $("#demo-proof");
  if (!x || !el) return;
  el.hidden = false;
  el.innerHTML = `
    <div><h4>Verified on Bitget Demo</h4>
      <div class="big">${x.accepted_orders} real orders</div>
      <p class="note">${day(x.executed_at)} · ${esc(x.pair.replace(/USDT/g, ""))} opened and closed as a pair on Bitget Demo Trading, in ${esc((x.position_mode || "").replace("_", " "))}. An execution test of the order path, not a strategy trade. Net ${usd(x.realized.net, 2)} after Bitget's own fees.</p></div>
    <div class="orders">${x.orders.map(o => `<div class="order"><span><b>${esc(o.symbol.replace("USDT", ""))}</b> opened ${o.open_px} · closed ${o.close_px}</span><span class="muted">filled</span>
      <code>open #${esc(o.open)}</code><code>close #${esc(o.close)}</code></div>`).join("")}</div>`;
}

/* ---------- what is real ---------- */
function realStrip() {
  const verified = D.events.filter(e => e.status === "complete").length;
  const quotes = D.rows.filter(r => r.interpretation && r.interpretation.status === "ok").length;
  const demoOrders = (D.demo_evidence ? D.demo_evidence.accepted_orders : 0) + (D.demo_strategy_trades || []).reduce((a, t) => a + t.orders.length * 2, 0);
  const items = [
    [D.events.length, "real earnings releases", "/dashboard"],
    [verified, "fully verified against SEC filings", "https://github.com/jenzylove/residual/tree/main/data/sources"],
    [quotes, "AI reads with quotes checked", "#signal"],
    [D.orders.length, "paper orders, both legs", "ledger.csv"],
    [demoOrders, "real Bitget Demo orders", "#proof"],
    ["CI", "replay reproduced on every push", "https://github.com/jenzylove/residual/actions"],
  ];
  $("#real").innerHTML = items.map(([n, t, href]) => `<a href="${href}" ${href.startsWith("http") ? 'target="_blank" rel="noopener"' : ""}><b>${esc(n)}</b>${esc(t)}</a>`).join("");
}

/* ---------- variants and size study ---------- */
function variantsTable() {
  const S = D.summary_conservative_funding, f = v => v == null ? "n/a" : v.toFixed(2);
  const rows = [
    ["residual", "Strategy (rule picked walk forward)", "chooses among the three rules below using earlier events only", true],
    ["v_residual", "Residual rule", "trade the company's own move"],
    ["v_headline", "Headline, hedged", "trade the guidance surprise, hedged and gated"],
    ["v_agreement", "Agreement", "only when the company move and the surprise agree"],
    ["v_consensus", "Analyst consensus", "trade the EPS surprise vs analyst estimates (Alpha Vantage)"],
    ["naive_same_events", "Plain headline, same releases", "unhedged baseline"],
  ];
  $("#variants").innerHTML = `<div class="tscroll2"><table class="vtable"><thead><tr><th>Rule</th><th class="num">Trades</th><th class="num">P&amp;L</th><th class="num">Sharpe<small>n trades</small></th><th class="num">Hit</th></tr></thead><tbody>
    ${rows.map(([k, n, sub, hl]) => S[k] ? `<tr class="${hl ? "hl" : ""}"><td>${n}<small>${sub}</small></td><td class="num">${S[k].trades}</td><td class="num ${cls(S[k].total_net_pnl)}">${usd(S[k].total_net_pnl, 0)}</td><td class="num">${f(S[k].sharpe_daily_ann)}<small>n=${S[k].trades}</small></td><td class="num">${S[k].hit_rate == null ? "n/a" : Math.round(S[k].hit_rate * 100) + "%"}</td></tr>` : "").join("")}
    </tbody></table></div>
    <p class="note">The rules were declared before scoring, and each is published whether it wins or loses. All trades counted, missing funding charged at the worst observed rate.</p>`;
}

function sizeStudy() {
  const ss = D.size_study || [];
  if (!ss.length) { $("#sizes").innerHTML = `<p class="note">Size study not run.</p>`; return; }
  const W = 560, H = 210, pad = 46, xs = ss.map(s => s.notional);
  const vals = ss.flatMap(s => [s.primary.residual.total_net_pnl, s.primary.naive_same_events.total_net_pnl]);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const x = i => pad + i / Math.max(1, ss.length - 1) * (W - pad - 20), y = v => H - 30 - (v - lo) / ((hi - lo) || 1) * (H - 50);
  const line = (k, col, dash) => `<polyline fill="none" stroke="${col}" stroke-width="2.2" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${ss.map((s, i) => x(i) + "," + y(s.primary[k].total_net_pnl)).join(" ")}"/>` +
    ss.map((s, i) => `<circle cx="${x(i)}" cy="${y(s.primary[k].total_net_pnl)}" r="3.5" fill="${col}"/>`).join("");
  const cur = D.config.base_notional;
  $("#sizes").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}">
    <line x1="${pad}" x2="${W - 20}" y1="${y(0)}" y2="${y(0)}" stroke="#141418" stroke-opacity=".15"/>
    ${line("residual", "#6c4ee6")}${line("naive_same_events", "#d0453b", 1)}
    ${ss.map((s, i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" ${s.notional === cur ? 'style="fill:#6c4ee6;font-weight:600"' : ""}>$${(s.notional / 1000).toLocaleString()}k · ${s.trades} trades</text>`).join("")}
    <text x="0" y="${y(hi) + 4}">${usd(hi)}</text><text x="0" y="${y(lo)}">${usd(lo)}</text></svg>
    <div class="legend"><span><i style="background:#6c4ee6"></i>Strategy</span><span><i style="background:#d0453b"></i>Plain headline, same releases</span></div>
    <p class="note">Same walk forward, re run at four position sizes. Above $2.5k, Bitget's after hours liquidity rejects most releases (${ss.map(s => `$${s.notional / 1000}k: ${s.liquidity_rejects}`).join(", ")} liquidity rejections). The default is $${(cur / 1000).toLocaleString()}k.</p>`;
}

function demoMode() {
  const dm = D.demo_mode, el = $("#demo-mode");
  if (!dm || !el) return;
  el.hidden = false;
  const S = dm.summary_conservative_funding, tr = dm.rows.filter(r => r.decision.decision === "TRADE");
  el.innerHTML = `<h4>Demo executable mode · the same method on instruments Bitget Demo lists</h4>
    <p class="note" style="margin:0 0 16px">${esc(dm.note)} Companies: ${dm.companies.join(", ")}.</p>
    <div class="tscroll2"><table class="vtable"><thead><tr><th>Rule</th><th class="num">Trades</th><th class="num">P&amp;L</th><th class="num">Sharpe<small>n trades</small></th><th class="num">Hit</th></tr></thead><tbody>
      <tr class="hl"><td>Strategy<small>demo executable pairs</small></td><td class="num">${S.residual.trades}</td><td class="num ${cls(S.residual.total_net_pnl)}">${usd(S.residual.total_net_pnl, 0)}</td><td class="num">${S.residual.sharpe_daily_ann ?? "n/a"}</td><td class="num">${S.residual.hit_rate == null ? "n/a" : Math.round(S.residual.hit_rate * 100) + "%"}</td></tr>
      <tr><td>Plain headline, same releases<small>unhedged baseline</small></td><td class="num">${S.naive_same_events.trades}</td><td class="num ${cls(S.naive_same_events.total_net_pnl)}">${usd(S.naive_same_events.total_net_pnl, 0)}</td><td class="num">${S.naive_same_events.sharpe_daily_ann ?? "n/a"}</td><td class="num">${S.naive_same_events.hit_rate == null ? "n/a" : Math.round(S.naive_same_events.hit_rate * 100) + "%"}</td></tr>
    </tbody></table></div>
    <p class="note">Stress view (every trade, worst case funding). The ${tr.length} pairs: ${tr.map(r => esc(r.event_id.split("-")[0]) + " vs " + esc((r.hedge.symbol || "").replace("USDT", ""))).join(" · ")}. Each one could be placed on Bitget Demo, and one of them was.</p>`;
}

function demoStrategy() {
  const t = (D.demo_strategy_trades || []).slice(-1)[0], el = $("#demo-strat");
  if (!t || !el) return;
  el.hidden = false;
  el.innerHTML = `<div><h4>A strategy decision, executed on Bitget Demo</h4>
      <div class="big">${esc(t.event_id.split("-")[0])} ${t.decision.direction > 0 ? "long" : "short"}</div>
      <p class="note">The replay's decision for ${esc(t.event_id)}, placed on Bitget Demo Trading at ${esc(t.executed_at.slice(0, 10))} prices and closed. ${t.hedge_substitute ? `Demo does not list ${esc(t.strategy_hedge)}, so the best fitting listed stock (${esc(t.hedge_used.replace("USDT", ""))}, R² ${t.hedge_substitute.r2.toFixed(2)}) stood in as the hedge.` : ""} Net ${usd(t.realized.net, 2)} after Bitget's fees.</p></div>
    <div class="orders">${t.orders.map(o => `<div class="order"><span><b>${esc(o.symbol.replace("USDT", ""))}</b> ${o.side} · ${o.open_px} → ${o.close_px}</span><span class="muted">filled</span><code>open #${esc(o.open)}</code><code>close #${esc(o.close)}</code></div>`).join("")}</div>`;
}

/* ---------- guided tour ---------- */
function tour() {
  const steps = [
    ["#real", "Everything on this page comes from real data: SEC filings, Bitget prices, verified AI quotes and real Bitget Demo orders. Each chip links to its evidence."],
    ["#stage", "One real earnings release. The bars split the stock's early move into market, sector, liquidity and what belongs to the company."],
    ["#stage .verdict", "The decision and the reason in plain words. Every gate on the right had to pass, or RESIDUAL stands aside."],
    ["#how", "The workflow: SEC filing, verified numbers, market and sector removed, an AI second reading, strict gates, then a hedged pair."],
    ["#exec", "What happened after the entry: both legs, fees, slippage, funding, and where the result came from."],
    ["#proof", "Scored walk forward against the obvious trade, with Sharpe, Sortino and drawdown. Nothing tuned on the events it is judged on."],
    ["#variants", "Every rule we declared, published whether it won or lost."],
    ["#demo-proof", "Real orders on Bitget Demo Trading, with their order IDs."],
    ["#faq", "Straight answers to the questions a judge should ask. The full audit holds every table, source and hash."],
  ].filter(([sel]) => $(sel) && !$(sel).hidden);
  let i = 0;
  const box = $("#tour");
  const go = k => {
    document.querySelectorAll(".tour-focus").forEach(e => e.classList.remove("tour-focus"));
    i = Math.max(0, Math.min(steps.length - 1, k));
    const el = $(steps[i][0]);
    stopAuto();
    el.classList.add("in", "tour-focus");
    el.scrollIntoView({ behavior: REDUCE ? "auto" : "smooth", block: "center" });
    $("#tour-step").textContent = `Step ${i + 1} of ${steps.length}`;
    $("#tour-text").textContent = steps[i][1];
    $("#tour-next").textContent = i === steps.length - 1 ? "Finish" : "Next";
  };
  const end = () => { box.hidden = true; document.querySelectorAll(".tour-focus").forEach(e => e.classList.remove("tour-focus")); };
  $("#tour-start").onclick = () => { box.hidden = false; go(0); };
  $("#tour-next").onclick = () => i === steps.length - 1 ? end() : go(i + 1);
  $("#tour-prev").onclick = () => go(i - 1);
  $("#tour-close").onclick = end;
  document.addEventListener("keydown", e => { if (box.hidden) return; if (e.key === "Escape") end(); if (e.key === "ArrowRight") $("#tour-next").click(); if (e.key === "ArrowLeft") go(i - 1); });
}

/* ---------- motion ---------- */
function typeIn(el) {
  const text = el.dataset.text || "";
  if (REDUCE || QS.has("static")) { el.textContent = text; el.classList.add("done"); return; }
  let i = 0;
  const step = () => { el.textContent = text.slice(0, ++i); if (i < text.length) setTimeout(step, 34 + Math.random() * 34); else el.classList.add("done"); };
  setTimeout(step, 250);
}
function activate(t) {
  t.classList.add("in");
  t.querySelectorAll(".tw").forEach(typeIn);
  t.querySelectorAll(".meter i").forEach(i => i.style.width = i.dataset.w);
  t.querySelectorAll("circle.arc").forEach(a => a.style.strokeDashoffset = a.dataset.off);
}
function reveal() {
  document.querySelectorAll(".bento .card").forEach((c, i) => c.style.transitionDelay = `${i * 110}ms`);
  IO = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { activate(e.target); IO.unobserve(e.target); } }), { threshold: .12 });
  document.querySelectorAll(".rv").forEach(el => IO.observe(el));
  if (QS.has("nohero")) $(".hero").style.display = "none";
  // ?only=<section id> isolates one section for documentation screenshots
  const only = QS.get("only");
  if (only) {
    $(".hero").style.display = "none";
    document.querySelectorAll("#body > section, #body > nav, #body > footer").forEach(s => {
      if (s.id !== only) s.style.display = "none";
    });
    document.querySelector(".nav").style.position = "absolute";
  }
  if (QS.has("static")) document.querySelectorAll(".rv").forEach(activate);
  const grid = $(".bento");
  if (grid && !REDUCE) grid.addEventListener("pointermove", ev => {
    const r = grid.getBoundingClientRect(), nx = (ev.clientX - r.left) / r.width - .5, ny = (ev.clientY - r.top) / r.height - .5;
    grid.querySelectorAll(".card.in").forEach((c, i) => { const k = 4 + (i % 3) * 3; c.style.setProperty("--px", `${(-nx * k).toFixed(1)}px`); c.style.setProperty("--py", `${(-ny * k).toFixed(1)}px`); });
  });
  if (QS.has("check")) setTimeout(() => {
    const over = document.documentElement.scrollWidth - innerWidth;
    const wide = [...document.querySelectorAll("#body *")].filter(n => n.getBoundingClientRect().right > innerWidth + 1).map(n => n.className || n.tagName).slice(0, 5);
    const bars = [...document.querySelectorAll("#stage rect.bar")].map(b => Math.round(b.getBoundingClientRect().width));
    document.title = `CHECK overflow=${over} wide=${JSON.stringify(wide)} wfbars=${JSON.stringify(bars)}`;
  }, 2500);
}
})();
