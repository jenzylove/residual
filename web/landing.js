"use strict";
// Landing body: overview, event timeline, signal room, paper execution, results, operator mode.
(() => {
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x, d = 2) => x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const pp = (x, d = 1) => x == null ? "n/a" : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
const usd = (x, d = 0) => x == null ? "n/a" : (x < 0 ? "−" : x > 0 ? "+" : "") + "$" + Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const bn = m => m == null ? "n/a" : m >= 1000 ? "$" + (m / 1000).toFixed(1) + "B" : "$" + Math.round(m) + "M";
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
const day = iso => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const when = ms => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const GATE = {
  event_data: "Earnings data verified", market_data: "Market data available", hedge: "Hedge instrument fits",
  liquidity: "Liquidity sufficient", robust: "Robust across beta windows", reaction_open: "Reaction not yet complete",
  residual_vs_cost: "Residual clears cost", ai_interpretation: "AI interpretation"
};
const badge = d => d === "TRADE" ? '<span class="badge b-trade">Trade</span>' : '<span class="badge b-no">No trade</span>';

let D, EV = {}, ROW = {}, current = null;
let IO = null;  // declared before any render call: timeline() observes new cards through it
const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;

fetch("data.json", { cache: "no-store" }).then(r => r.json()).then(d => {
  D = d; d.events.forEach(e => EV[e.event_id] = e); d.rows.forEach(r => ROW[r.event_id] = r);
  overview(); timeline("all"); results("primary"); operator();
  const firstTrade = [...d.rows].reverse().find(r => r.decision.decision === "TRADE") || d.rows[d.rows.length - 1];
  openSignal(firstTrade.event_id, false);
  reveal();
}).catch(e => { $("#ov-grid").innerHTML = `<div class="card"><p>Could not load data.json: ${esc(e.message)}</p></div>`; });

function oneLine(r) {
  const dec = r.decision;
  if (dec.decision === "TRADE") {
    const net = r.residual ? r.residual.net : null;
    return `${dec.structure}, size ×${dec.size}. Net ${usd(net)}${r.residual && r.residual.funding_data !== "complete" ? " (funding data unavailable)" : ""}.`;
  }
  const k = dec.reasons[0];
  const g = dec.gates[k];
  return `${GATE[k] || k} failed. ${g ? g.detail : ""}`.slice(0, 120);
}

/* ---------- small visuals ---------- */
function spark(curves) {
  const W = 600, H = 70, all = curves.flat(), n = Math.max(...curves.map(c => c.length));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const x = i => i / Math.max(1, n - 1) * W, y = v => H - 4 - (v - lo) / ((hi - lo) || 1) * (H - 8);
  const cols = ["#6c4ee6", "#d0453b"];
  const path = c => c.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  const area = c => path(c) + ` L ${x(c.length - 1)} ${H} L 0 ${H} Z`;
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6c4ee6" stop-opacity=".22"/><stop offset="1" stop-color="#6c4ee6" stop-opacity="0"/></linearGradient></defs>
    <line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="#141418" stroke-opacity=".12"/>
    <path d="${area(curves[0])}" fill="url(#sg)"/>
    ${curves.map((c, i) => `<path class="line" d="${path(c)}" fill="none" stroke="${cols[i]}" stroke-width="${i ? 1.4 : 2.2}" ${i ? 'stroke-dasharray="5 4"' : ""} vector-effect="non-scaling-stroke"/>`).join("")}
  </svg>`;
}
function dial(frac) {
  const r = 48, c = 2 * Math.PI * r;
  return `<svg class="dial" viewBox="0 0 120 120"><circle cx="60" cy="60" r="${r}" fill="none" stroke="rgba(20,20,24,.07)" stroke-width="10"/>
    <circle class="arc" cx="60" cy="60" r="${r}" fill="none" stroke="#6c4ee6" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${c}" data-off="${c * (1 - frac)}" transform="rotate(-90 60 60)"/>
    <text x="60" y="66" text-anchor="middle" font-size="18" fill="#141418">${Math.round(frac * 100)}%</text></svg>`;
}

/* ---------- 01 overview ---------- */
function overview() {
  const rows = D.rows, trades = rows.filter(r => r.decision.decision === "TRADE");
  const traded = trades.filter(r => r.residual);
  const complete = traded.filter(r => r.residual.funding_data === "complete").length;
  const P = D.summary.residual;
  const latest = [...rows].sort((a, b) => EV[b.event_id].release_ms - EV[a.event_id].release_ms).slice(0, 4);
  const live = (D.live_log || []).slice(-1)[0];
  const nextRel = live ? Object.entries(live.next_estimated_release || {})[0] : null;
  $("#ov-grid").innerHTML = `
    <div class="card wide rv">
      <h4>Aggregate result <span class="badge b-paper" style="margin-left:8px">Paper only</span></h4>
      <div style="display:flex;gap:40px;flex-wrap:wrap;align-items:flex-end">
        <div><div class="big ${cls(P.total_net_pnl)}" data-count="${P.total_net_pnl}">${usd(P.total_net_pnl, 2)}</div><p class="note">Residual pair, funding complete trades only (${P.trades} counted)</p></div>
        <div><div class="big ${cls(D.summary.naive_same_events.total_net_pnl)}">${usd(D.summary.naive_same_events.total_net_pnl, 2)}</div><p class="note">Naive headline on the same events</p></div>
      </div>
      ${spark([P.equity_curve, D.summary.naive_same_events.equity_curve])}
      <p class="note">Like for like, the naive headline direction beat the residual signal in this sample. With ${P.trades} to ${traded.length} trades nothing here is statistically meaningful. We show it anyway.</p>
    </div>
    <div class="card rv">
      <h4>Decisions</h4>
      <div style="display:flex;align-items:center;gap:18px">${dial(trades.length / rows.length)}
      <div class="big">${trades.length}<span class="muted" style="font-size:.5em"> trades<br>${rows.length - trades.length} no trade</span></div></div>
      <p class="note">${rows.length} real earnings releases, each decided walk forward.</p>
    </div>
    <div class="card rv">
      <h4>Latest events</h4>
      <ul class="mini-list">${latest.map(r => `<li><a href="#signal" data-open="${esc(r.event_id)}"><b>${esc(EV[r.event_id].ticker)}</b> <span class="muted">${day(EV[r.event_id].release_utc)}</span></a>${badge(r.decision.decision)}</li>`).join("")}</ul>
    </div>
    <div class="card rv">
      <h4>Watcher status</h4>
      ${live ? `<div style="display:flex;align-items:center;gap:10px"><i class="dot live"></i><b>${esc(live.decision)}</b></div>
      <p class="note">Last check ${esc(live.checked_at.replace("T", " ").slice(0, 16))} UTC. ${esc(live.reason)}.${nextRel ? ` Next estimated release ${esc(nextRel[0])} around ${esc(nextRel[1])}.` : ""}</p>
      <p class="note">Snapshot of the last local run; this page does not poll.</p>` : `<p class="note">No watcher run recorded.</p>`}
    </div>
    <div class="card rv">
      <h4>Funding data quality</h4>
      <div class="big">${complete}<span class="muted" style="font-size:.5em"> of ${traded.length} trades complete</span></div>
      <div class="meter"><i style="width:0;background:#1f9d6c" data-w="${traded.length ? complete / traded.length * 100 : 0}%"></i><i style="width:0;background:#e3b54b" data-w="${traded.length ? (traded.length - complete) / traded.length * 100 : 0}%"></i></div>
      <p class="note">Bitget serves funding history only from about June 2026. Trades without it are excluded from the primary result.</p>
    </div>`;
  document.querySelectorAll("[data-open]").forEach(a => a.onclick = e => { e.preventDefault(); openSignal(a.dataset.open, true); });
}

/* ---------- 02 timeline ---------- */
function timeline(filter) {
  const f = $("#tl-filter");
  f.innerHTML = [["all", "All"], ["TRADE", "Trades"], ["NO_TRADE", "No trade"]]
    .map(([k, n]) => `<button class="chip ${filter === k ? "on" : ""}" data-f="${k}">${n}</button>`).join("");
  f.querySelectorAll("button").forEach(b => b.onclick = () => timeline(b.dataset.f));
  const rows = [...D.rows].sort((a, b) => EV[b.event_id].release_ms - EV[a.event_id].release_ms)
    .filter(r => filter === "all" || r.decision.decision === filter);
  $("#tl-track").innerHTML = rows.map((r, idx) => {
    const e = EV[r.event_id], s = e.surprise || {}, a = r.analysis, d = a.decomposition;
    return `<article class="card ev rv ${current === r.event_id ? "sel" : ""}" data-id="${esc(r.event_id)}" tabindex="0" style="transition-delay:${Math.min(idx, 6) * 70}ms">
      <span class="ev-no">${String(idx + 1).padStart(2, "0")}</span>
      <div class="ev-top"><div><div class="ev-tk">${esc(e.ticker)}</div><div class="ev-date">${day(e.release_utc)} · ${esc(e.release_session.replace("_", " "))}</div></div>${badge(r.decision.decision)}</div>
      <div class="ev-row"><span class="muted">Revenue vs guidance</span><span class="num">${bn(s.revenue_actual)} / ${bn(s.revenue_guided_mid)} <b class="${cls(s.guidance_surprise_pct)}">${pp(s.guidance_surprise_pct)}</b></span></div>
      <div class="ev-row"><span class="muted">Initial reaction</span><span class="num ${cls(d?.observed)}">${d ? pct(d.observed) : "n/a"}</span></div>
      <div class="ev-row"><span class="muted">Residual</span><span class="num ${cls(d?.residual)}"><b>${d ? pct(d.residual) : "n/a"}</b></span></div>
      <div class="ev-line">${esc(oneLine(r))}</div>
    </article>`;
  }).join("");
  $("#tl-track").querySelectorAll(".ev").forEach(c => {
    c.onclick = () => openSignal(c.dataset.id, true);
    c.onkeydown = ev => { if (ev.key === "Enter") openSignal(c.dataset.id, true); };
  });
  if (IO) $("#tl-track").querySelectorAll(".rv").forEach(el => IO.observe(el));
}

/* ---------- 03 signal room ---------- */
function waterfall(d) {
  const steps = [["Market", d.market, "#9a93b5"], ["Sector", d.sector, "#b99a55"], ["Liquidity", d.liquidity, "#c5c2d0"], ["Residual", d.residual, "#6c4ee6"]];
  let cum = 0; const pts = [0];
  steps.forEach(s => { cum += s[1]; pts.push(cum); });
  const lo = Math.min(0, ...pts, d.observed), hi = Math.max(0, ...pts, d.observed);
  const W = 620, H = 250, L = 96, R = 70, rowH = 40;
  const x = v => L + (v - lo) / ((hi - lo) || 1) * (W - L - R);
  let g = `<line x1="${x(0)}" x2="${x(0)}" y1="4" y2="${H - 8}" stroke="#141418" stroke-opacity=".18"/>`;
  let c = 0;
  steps.forEach(([n, v, col], i) => {
    const y = 10 + i * rowH, a = x(c), b = x(c + v);
    g += `<text class="lbl" x="0" y="${y + 17}">${n}</text>
      <rect class="bar" x="${Math.min(a, b)}" y="${y}" width="${Math.max(2, Math.abs(b - a))}" height="24" rx="6" fill="${col}" style="transform-origin:${v >= 0 ? "left" : "right"};transition-delay:${i * 180}ms"/>
      <text x="${Math.max(a, b) + 8}" y="${y + 17}">${pct(v)}</text>`;
    if (i < steps.length - 1) g += `<line x1="${b}" x2="${b}" y1="${y + 24}" y2="${y + rowH}" stroke="#141418" stroke-opacity=".25" stroke-dasharray="2 3"/>`;
    c += v;
  });
  const y = 10 + steps.length * rowH + 12, a = x(0), b = x(d.observed);
  g += `<text class="lbl" x="0" y="${y + 17}" style="fill:#141418">Observed</text>
    <rect class="bar" x="${Math.min(a, b)}" y="${y}" width="${Math.max(2, Math.abs(b - a))}" height="24" rx="6" fill="#141418" style="transform-origin:${d.observed >= 0 ? "left" : "right"};transition-delay:${steps.length * 180}ms"/>
    <text x="${Math.max(a, b) + 8}" y="${y + 17}" style="fill:#141418;font-weight:600">${pct(d.observed)}</text>`;
  return `<svg class="wf" viewBox="0 0 ${W} ${H + 14}" width="100%">${g}</svg>`;
}

function openSignal(id, scroll) {
  current = id;
  document.querySelectorAll(".ev").forEach(c => c.classList.toggle("sel", c.dataset.id === id));
  const r = ROW[id], e = EV[id], a = r.analysis, s = e.surprise || {}, d = a.decomposition, dec = r.decision, it = r.interpretation;
  const E = e.earnings;
  const snip = (label, f) => f ? `<p class="muted" style="margin:10px 0 0;font-size:12px">${label}</p><div class="snip">“${esc(f.snippet)}”</div>
    <p class="note" style="margin:0"><a href="${esc(f.source_url)}" target="_blank" rel="noopener">source</a> · sha256 <span class="mono">${esc(f.source_sha256.slice(0, 16))}…</span> · ${f.verified ? '<span class="pos">re-derived and verified</span>' : '<span class="neg">unverified</span>'}</p>` : "";
  const hedge = a.hedge;
  const pairHtml = dec.decision === "TRADE" && hedge ? `
      <div class="pair">
        <div class="leg ${dec.direction > 0 ? "long" : "short"}"><div class="side">${dec.direction > 0 ? "Long" : "Short"}</div><div class="sym">${esc(e.company_symbol)}</div></div>
        <div class="vs">VS</div>
        <div class="leg ${dec.direction > 0 ? "short" : "long"}"><div class="side">${dec.direction > 0 ? "Short" : "Long"}</div><div class="sym">${esc(hedge.symbol)}</div></div>
      </div>` : "";
  $("#sig").innerHTML = `
    <div class="sig-head rv in">
      <h2 class="sig-title">${esc(e.ticker)} <em>${d ? pct(d.residual) : "n/a"}</em></h2>
      <div style="text-align:right">${badge(dec.decision)}<p class="note" style="margin-top:8px">${esc(e.release_utc.replace("T", " ").replace("Z", " UTC"))} · SEC acceptance time</p></div>
    </div>
    <div class="col">
      <div class="card">
        <h4>What moved the stock · release hour to +2h</h4>
        ${d ? waterfall(d) + `<div class="eq"><span>Observed <b>${pct(d.observed)}</b></span><span>− market <b>${pct(d.market)}</b></span><span>− sector <b>${pct(d.sector)}</b></span><span>− liquidity <b>${pct(d.liquidity)}</b></span><span>= residual <b class="${cls(d.residual)}">${pct(d.residual)}</b></span></div>
        <p class="note">Market β ${a.model.beta_market.toFixed(2)} on QQQ, sector β ${a.model.beta_sector.toFixed(2)} on a ${a.peers.length} name peer basket, estimated on ${a.model.n_hours} hourly Bitget bars before the release.</p>`
        : `<p class="note">No decomposition: ${esc((a.gates.market_data || {}).detail || "market data missing")}.</p>`}
      </div>
      <div class="card">
        <h4>Evidence from the filing</h4>
        <dl class="kv"><dt>Reported revenue</dt><dd>${bn(s.revenue_actual)}</dd><dt>Guidance baseline</dt><dd>${bn(s.revenue_guided_mid)} <span class="muted">company outlook midpoint from the prior release, not consensus</span></dd>
        <dt>Guidance surprise</dt><dd class="${cls(s.guidance_surprise_pct)}">${pp(s.guidance_surprise_pct)} (${esc(s.vs_guidance_band)} the guided range)</dd><dt>Next quarter guide</dt><dd>${bn(s.next_quarter_guidance_mid)} · ${esc(s.guidance_direction)}</dd></dl>
        ${snip("Reported", E.revenue_actual)}${snip("Guidance baseline (prior release)", E.revenue_guidance_prior)}
      </div>
    </div>
    <div class="col">
      <div class="card"><h4>Risk gate</h4><ul class="gates">${Object.entries(dec.gates).map(([k, g], i) =>
        `<li style="transition-delay:${i * 90}ms"><span class="tick ${g.pass ? "ok" : "bad"}">${g.pass ? "✓" : "✕"}</span><span><b>${esc(GATE[k] || k)}</b><small>${esc(g.detail)}</small></span></li>`).join("")}</ul></div>
      <div class="card"><h4>AI interpretation</h4>${it && it.status === "ok"
        ? `<p style="margin:0"><b style="text-transform:capitalize">${esc(it.label.replace(/_/g, " "))}</b> <span class="muted">· confidence ${it.confidence.toFixed(2)} · ${esc(it.model)}</span></p><p class="note">${esc(it.rationale)}</p>${it.evidence_quotes.map(q => `<p class="quote">“${esc(q)}”</p>`).join("")}<p class="note">Every quote was checked against the press release. The label only scales size; it never sets a number.</p>`
        : `<p class="note">${it ? esc(it.status + ": " + (it.detail || "")) : "Not run: the event stopped at an earlier gate."}</p>`}</div>
      <div class="card"><h4>Proposed pair</h4>${pairHtml}
        ${hedge ? `<dl class="kv"><dt>Hedge ratio</dt><dd>${hedge.beta.toFixed(3)} (OLS, R² ${hedge.r2.toFixed(2)}, ${hedge.n_hours} hours)</dd><dt>Candidates</dt><dd>${(a.hedge_candidates || []).map(c => `${esc(c.symbol)} R² ${c.r2.toFixed(2)}`).join(" · ")}</dd><dt>Walk forward rule</dt><dd>${r.params.mode > 0 ? "continuation" : "reversal"}, k = ${r.params.k} · ${esc(r.params.source)}</dd></dl>`
        : `<p class="note">No hedge instrument had enough history, so no pair can be proposed.</p>`}
        ${dec.decision !== "TRADE" ? `<p class="note">Not executed: see the failed gates above.</p>` : ""}
      </div>
    </div>`;
  execution(r, e);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.querySelectorAll(".wf").forEach(w => w.classList.add("go"));
    document.querySelectorAll(".gates").forEach(w => w.classList.add("go"));
    document.querySelectorAll("#exec .track i").forEach(i => { i.style.left = i.dataset.l; i.style.width = i.dataset.w; });
  }));
  if (scroll) $("#signal").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- 04 paper execution ---------- */
function execution(r, e) {
  const dec = r.decision, t = r.residual;
  if (dec.decision !== "TRADE" || !t) {
    const failed = dec.reasons.map(k => [k, dec.gates[k]]);
    $("#exec").innerHTML = `<div class="exec-grid"><div class="card notrade">
      <div class="big">NO_TRADE</div>
      <p class="note" style="font-size:14px">${esc(e.ticker)} on ${day(e.release_utc)} did not execute. Nothing was sent, nothing was sized.</p>
      <ul class="gates go" style="margin-top:18px">${failed.map(([k, g]) => `<li><span class="tick bad">✕</span><span><b>${esc(GATE[k] || k)}</b><small>${esc(g ? g.detail : "")}</small></span></li>`).join("")}</ul>
    </div></div>`;
    return;
  }
  const at = t.attribution, comp = t.legs.find(l => l.role === "company"), hed = t.legs.find(l => l.role === "hedge");
  const items = [["Company leg", at.company_leg], ["Hedge leg", at.hedge_leg], ["Residual (thesis)", at.residual], ["Factor and hedge error", at.factor_error], ["Slippage", at.slippage], ["Fees", at.fees], ["Funding", at.funding], ["Timing, signal to fill", at.timing_signal_to_fill]];
  const max = Math.max(...items.map(i => Math.abs(i[1]))) || 1;
  $("#exec").innerHTML = `<div class="exec-grid">
    <div class="card">
      <h4>The pair</h4>
      <div class="big ${cls(t.net)}">${usd(t.net, 2)}</div><p class="note">Net after fees, slippage and funding · ${t.stopped ? "stopped out" : "exited at the " + t.holding_hours + "h horizon"}</p>
      <div class="tscroll" style="margin-top:14px"><table><thead><tr><th>Leg</th><th>Side</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Exit</th><th class="num">Net</th></tr></thead><tbody>
      ${t.legs.map(l => `<tr><td>${esc(l.symbol)}</td><td>${l.side}</td><td class="num">${l.qty.toFixed(3)}</td><td class="num">${l.entry_fill.toFixed(2)}</td><td class="num">${l.exit_fill.toFixed(2)}</td><td class="num ${cls(l.net)}">${usd(l.net, 2)}</td></tr>`).join("")}</tbody></table></div>
      <dl class="kv" style="margin-top:14px"><dt>Entry</dt><dd>${when(t.entry_ms)}</dd><dt>Exit</dt><dd>${when(t.exit_ms)} ${t.stopped ? "(stop)" : "(horizon)"}</dd>
      <dt>Fees</dt><dd>${usd(-t.fees, 2)}</dd><dt>Slippage</dt><dd>${usd(-t.slippage, 2)}</dd><dt>Funding</dt><dd>${usd(t.funding, 2)}</dd>
      <dt>Hedge notional</dt><dd>$${Math.round(hed ? hed.notional : 0).toLocaleString()} against $${Math.round(comp.notional).toLocaleString()}</dd></dl>
      ${t.funding_data !== "complete" ? `<div class="warn">⚠ Bitget no longer serves funding history for this holding period. This trade is excluded from the primary result; the conservative view charges ${usd(t.funding_conservative, 2)} of worst case funding instead.</div>` : ""}
    </div>
    <div class="card">
      <h4>Attribution</h4>
      <div class="attr">${items.map(([k, v]) => `<span>${k}</span><div class="track"><i data-l="${v < 0 ? 50 - Math.abs(v) / max * 50 : 50}%" data-w="${Math.abs(v) / max * 50}%" style="left:50%;width:0;background:${v < 0 ? "#d0453b" : "#1f9d6c"}"></i></div><span class="num ${cls(v)}">${usd(v, 2)}</span>`).join("")}</div>
      <p class="note">Residual plus factor error, minus slippage and fees, plus funding equals net ${usd(at.net, 2)}. Over the hold ${esc(e.ticker)} moved ${pct(at.hold_returns.company)}; the factor model predicted ${pct(at.hold_returns.factor_predicted)}.</p>
    </div></div>`;
}

/* ---------- 05 results ---------- */
function lineChart(series) {
  const W = 640, H = 230, pad = 44, all = series.flatMap(s => s.values), n = Math.max(...series.map(s => s.values.length));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const x = i => pad + i / Math.max(1, n - 1) * (W - pad - 10), y = v => H - 22 - (v - lo) / ((hi - lo) || 1) * (H - 36);
  let g = `<line x1="${pad}" x2="${W - 10}" y1="${y(0)}" y2="${y(0)}" stroke="#141418" stroke-opacity=".15"/><text x="0" y="${y(hi) + 4}">${usd(hi)}</text><text x="0" y="${y(lo)}">${usd(lo)}</text>`;
  series.forEach(s => g += `<polyline fill="none" stroke="${s.color}" stroke-width="${s.w || 1.8}" ${s.dash ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round" points="${s.values.map((v, i) => x(i) + "," + y(v)).join(" ")}"/>`);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%">${g}</svg><div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>`;
}

function results(basis) {
  const views = { primary: ["Funding complete (primary)", D.summary], conservative: ["Conservative funding", D.summary_conservative_funding], observed_zero: ["Observed zero funding", D.summary_observed_zero_funding] };
  const b = $("#res-basis");
  b.innerHTML = Object.entries(views).map(([k, [n]]) => `<button class="chip ${k === basis ? "on" : ""}" data-b="${k}">${n}</button>`).join("");
  b.querySelectorAll("button").forEach(x => x.onclick = () => results(x.dataset.b));
  const S = views[basis][1];
  const order = [["residual", "Residual pair (AI gated)"], ["unhedged", "Unhedged, same signals"], ["naive_same_events", "Naive headline, same events"], ["naive", "Naive headline, every event"], ["no_trade", "No trade"]];
  const row = (n, m, hl) => m ? `<tr class="${hl ? "hl" : ""}"><td>${n}</td><td class="num ${cls(m.total_net_pnl)}">${usd(m.total_net_pnl, 2)}</td><td class="num">${m.trades}</td><td class="num">${m.excluded_funding_unavailable || 0}</td><td class="num">${m.hit_rate == null ? "n/a" : Math.round(m.hit_rate * 100) + "%"}</td><td class="num neg">${usd(m.max_drawdown, 2)}</td></tr>` : "";
  const note = {
    primary: "Only trades whose holding period has complete Bitget funding history are counted.",
    conservative: "Every trade counts; missing funding is charged against the position at the worst observed rate for that symbol.",
    observed_zero: "Every trade counts; missing funding is taken as zero. Shown for comparison only: this flatters trades with unknown funding.",
  }[basis];
  const ab = D.ablation_no_ai && basis === "primary" ? row("Residual without AI gate (ablation)", D.ablation_no_ai.summary.residual) : "";
  const srcs = D.events.slice().sort((a, b) => b.release_ms - a.release_ms);
  $("#res").innerHTML = `<div class="res-grid">
    <div class="card"><h4>${esc(views[basis][0])}</h4><div class="tscroll"><table><thead><tr><th>Strategy</th><th class="num">Net P&amp;L</th><th class="num">Trades</th><th class="num">Excluded</th><th class="num">Hit rate</th><th class="num">Max drawdown</th></tr></thead><tbody>
      ${order.map(([k, n], i) => row(n, S[k], i === 0)).join("")}${ab}</tbody></table></div>
      <p class="note">${note} ${esc(D.evaluation)}.</p></div>
    <div class="card"><h4>Cumulative net P&amp;L by event</h4>${lineChart([
      { name: "Residual", values: S.residual.equity_curve, color: "#6c4ee6", w: 2.6 },
      { name: "Unhedged", values: S.unhedged.equity_curve, color: "#b99a55" },
      { name: "Naive, same events", values: S.naive_same_events.equity_curve, color: "#d0453b", dash: 1 }])}</div>
    <div class="card full"><h4>Download the evidence</h4>
      <div class="dl"><a href="data.json" download>Full results · data.json</a><a href="ledger.csv" download>Paper ledger · ledger.csv</a><a href="events.json" download>Earnings dataset · events.json</a><a href="https://github.com/jenzylove/residual/tree/main/data/sources" target="_blank" rel="noopener">Archived SEC sources</a></div>
      <div class="tscroll" style="margin-top:16px;max-height:320px;overflow-y:auto"><table><thead><tr><th>Event</th><th>Press release</th><th>SHA-256</th><th>8-K</th></tr></thead><tbody>
      ${srcs.map(e => `<tr><td>${esc(e.event_id)}</td><td><a href="${esc(e.source.press_release_url)}" target="_blank" rel="noopener">${esc(e.source.press_release_url.split("/").pop())}</a></td><td class="mono">${esc((e.source.sha256 || "").slice(0, 20))}…</td><td><a href="${esc(e.source.filing_index_url)}" target="_blank" rel="noopener">${esc(e.accession)}</a></td></tr>`).join("")}
      </tbody></table></div></div>
  </div>`;
}

/* ---------- 06 operator ---------- */
function operator() {
  const o = D.operator || {}, logs = (D.live_log || []).slice(-6).reverse();
  const on = (v, a, b) => v ? `<span class="okc">${a}</span>` : `<span class="offc">${b}</span>`;
  const sampleRow = D.rows[0] ? Object.keys(D.rows[0]).join(", ") : "";
  $("#op-body").innerHTML = `
    <div class="op-cell"><h5>CLI</h5><pre><span class="k">$</span> python -m residual verify --offline
<span class="k">$</span> python -m residual replay --offline
<span class="k">$</span> python -m residual build
<span class="k">$</span> python -m residual snapshot
<span class="k">$</span> python -m residual live --loop 600
<span class="k">$</span> python -m residual demo-check
<span class="k">$</span> python -m residual demo-roundtrip --notional 50
<span class="k">$</span> python -m unittest discover -s tests</pre></div>
    <div class="op-cell"><h5>Dataset files</h5><pre>data/events.json          ${D.events.length} events, provenance per field
data/sources/*.htm        SEC press releases, byte exact
data/snapshots/*.json     Bitget hourly candles, fees, funding
data/interpretations/     LLM prompt hash, raw output, validation
data/results.json         replay, baselines, attribution
data/ledger.csv           ${D.orders.length} paper orders, both legs
data/live_log.jsonl       watcher runs</pre></div>
    <div class="op-cell"><h5>Schema · result row</h5><pre>${esc(sampleRow)}

decision: decision, direction, size, structure, gates{name:{pass,detail}}, reasons
analysis: model, decomposition, hedge, costs, robustness_residuals</pre></div>
    <div class="op-cell"><h5>Replay status</h5><pre>generated   ${esc(D.generated_at)}
model       ${esc(D.model_version)}
extractor   ${esc(D.extractor_version)}
mode        ${esc(o.replay_mode || "n/a")}
ai gate     ${on(o.ai_gate ?? D.config.ai_gate, "on", "off")}
events      ${D.rows.length} · trades ${D.rows.filter(r => r.decision.decision === "TRADE").length}</pre></div>
    <div class="op-cell"><h5>Execution adapter</h5><pre>adapter     ${on(o.execution_adapter === "bitget_demo", "bitget_demo", esc(o.execution_adapter || "local_paper"))}
demo keys   ${on(o.demo_credentials_configured, "configured", "not configured")}
product     ${esc(o.demo_product_type || "n/a")}
doh         ${on(!o.doh_fallback_enabled, "off (system DNS)", "fallback enabled")}
replay      local paper accounting
live        demo orders when keys are set</pre></div>
    <div class="op-cell"><h5>Live watcher log</h5><pre>${logs.length ? logs.map(l => `${esc(l.checked_at.slice(0, 16))}  ${esc(l.decision)}\n  ${esc(l.reason)}`).join("\n") : "no runs recorded"}</pre></div>`;
}

/* ---------- motion ---------- */

function typeIn(el) {
  const text = el.dataset.text || "";
  if (REDUCE) { el.textContent = text; el.classList.add("done"); return; }
  let i = 0;
  const step = () => { el.textContent = text.slice(0, ++i); if (i < text.length) setTimeout(step, 38 + Math.random() * 40); else el.classList.add("done"); };
  setTimeout(step, 250);
}

function reveal() {
  // stagger bento cards and give each its own drift phase
  document.querySelectorAll(".bento .card").forEach((c, i) => {
    c.style.transitionDelay = `${i * 110}ms`;
    c.style.setProperty("--dd", `${(i * 1.3).toFixed(1)}s`);
  });
  IO = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    const t = e.target;
    t.classList.add("in");
    t.querySelectorAll("[data-w]").forEach(i => { if (!i.dataset.l) i.style.width = i.dataset.w; });
    t.querySelectorAll("circle.arc").forEach(a => a.style.strokeDashoffset = a.dataset.off);
    t.querySelectorAll(".tw").forEach(typeIn);
    IO.unobserve(t);
  }), { threshold: .12 });
  document.querySelectorAll(".rv").forEach(el => IO.observe(el));
  // ?static reveals everything at once (for screenshots and print)
  const qs = new URLSearchParams(location.search);
  if (qs.has("nohero")) document.querySelector(".hero").style.display = "none";
  if (qs.has("static")) {
    document.querySelectorAll(".rv").forEach(el => { el.classList.add("in"); el.style.transitionDelay = "0ms"; });
    document.querySelectorAll("[data-w]").forEach(i => { if (!i.dataset.l) i.style.width = i.dataset.w; });
    document.querySelectorAll("circle.arc").forEach(a => a.style.strokeDashoffset = a.dataset.off);
    document.querySelectorAll(".tw").forEach(el => { el.textContent = el.dataset.text; el.classList.add("done"); });
  }

  // cursor parallax on the bento, like floating glass panes
  const grid = document.querySelector(".bento");
  if (grid && !REDUCE) grid.addEventListener("pointermove", ev => {
    const r = grid.getBoundingClientRect();
    const nx = (ev.clientX - r.left) / r.width - .5, ny = (ev.clientY - r.top) / r.height - .5;
    grid.querySelectorAll(".card.in").forEach((c, i) => {
      const depth = 4 + (i % 3) * 3;
      c.style.setProperty("--px", `${(-nx * depth).toFixed(1)}px`);
      c.style.setProperty("--py", `${(-ny * depth).toFixed(1)}px`);
    });
  });
}
})();
