"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x, d = 2) => x == null || Number.isNaN(x) ? "n/a" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const pp = (x, d = 2) => x == null ? "n/a" : (x >= 0 ? "+" : "") + Number(x).toFixed(d) + "%";
const usd = (x, d = 2) => x == null ? "n/a" : (x < 0 ? "-" : x > 0 ? "+" : "") + "$" + Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const bn = m => m == null ? "n/a" : m >= 1000 ? "$" + (m / 1000).toFixed(2) + "B" : "$" + m.toFixed(0) + "M";
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
const when = ms => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const GATE_NAMES = {
  event_data: "Event data", market_data: "Market data", hedge: "Hedge available", liquidity: "Liquidity",
  robust: "Robust to model", reaction_open: "Reaction not complete", residual_vs_cost: "Residual > cost",
  ai_interpretation: "AI interpretation"
};

let D = null, EV = {}, selected = null;

fetch("data.json", { cache: "no-store" }).then(r => {
  if (!r.ok) throw new Error("data.json missing: run `python -m residual replay`");
  return r.json();
}).then(d => { D = d; D.events.forEach(e => EV[e.event_id] = e); render(); })
  .catch(e => { $("#tab-board").innerHTML = `<div class="card"><h3>No data</h3><p>${esc(e.message)}</p></div>`; });

document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab));
});

function render() {
  const s = D.summary.residual, n = D.summary.naive_same_events;
  const rej = D.rows.filter(r => r.decision.decision !== "TRADE").length;
  $("#kpis").innerHTML = [
    ["Events", D.rows.length], ["Paired trades", s.trades], ["NO_TRADE", rej],
    ["Net P&L", `<span class="${cls(s.total_net_pnl)}">${usd(s.total_net_pnl, 0)}</span>`],
    ["Hit rate", s.hit_rate == null ? "n/a" : (s.hit_rate * 100).toFixed(0) + "%"],
    ["Naive, same events", `<span class="${cls(n.total_net_pnl)}">${usd(n.total_net_pnl, 0)}</span>`],
  ].map(([k, v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join("");
  renderBoard(); renderResults(); renderLive(); renderMethod(); renderOperator();
  $("#foot").innerHTML = `Generated ${esc(D.generated_at)} · model ${esc(D.model_version)} · extractor ${esc(D.extractor_version)} · AI gate ${D.config.ai_gate ? "on" : "off"} · paper trading only, Bitget USDT-M perpetual market data`;
  const first = D.rows.find(r => r.decision.decision === "TRADE") || D.rows[0];
  if (first) select(first.event_id);
}

function badge(dec) {
  if (dec === "TRADE") return '<span class="badge b-trade">TRADE</span>';
  if (dec === "PENDING") return '<span class="badge b-pend">PENDING</span>';
  return '<span class="badge b-no">NO_TRADE</span>';
}

function renderBoard() {
  const rows = [...D.rows].sort((a, b) => EV[b.event_id].release_ms - EV[a.event_id].release_ms);
  $("#board").innerHTML = `<thead><tr><th>Company</th><th>Release</th><th class="num">Revenue</th><th class="num">Guided mid</th>
    <th class="num">Guidance surprise</th><th>Guidance</th><th class="num">Residual</th><th>Decision</th><th class="num">P&amp;L</th></tr></thead><tbody>` +
    rows.map(r => {
      const e = EV[r.event_id], s = e.surprise || {}, res = r.analysis.residual;
      const pnl = r.residual ? r.residual.net : null;
      return `<tr data-id="${esc(r.event_id)}"><td><b>${esc(e.ticker)}</b></td><td>${esc(e.release_utc.slice(0, 16).replace("T", " "))}</td>
        <td class="num">${bn(s.revenue_actual)}</td><td class="num">${bn(s.revenue_guided_mid)}</td>
        <td class="num ${cls(s.guidance_surprise_pct)}">${s.guidance_surprise_pct == null ? "n/a" : pp(s.guidance_surprise_pct, 1)}</td>
        <td>${esc(s.guidance_direction || "n/a")}</td><td class="num ${cls(res)}">${res == null ? "n/a" : pct(res)}</td>
        <td>${badge(r.decision.decision)}</td><td class="num ${cls(pnl)}">${pnl == null ? "" : usd(pnl, 0)}</td></tr>`;
    }).join("") + "</tbody>";
  $("#board").querySelectorAll("tbody tr").forEach(tr => tr.onclick = () => select(tr.dataset.id));
}

function select(id) {
  selected = id;
  $("#board").querySelectorAll("tbody tr").forEach(tr => tr.classList.toggle("sel", tr.dataset.id === id));
  const r = D.rows.find(x => x.event_id === id), e = EV[id], a = r.analysis, dec = r.decision;
  const s = e.surprise || {}, d = a.decomposition;
  let html = `<div class="card"><h2>${esc(e.ticker)} · ${esc(e.release_utc.slice(0, 10))} ${badge(dec.decision)}</h2>
    <p class="muted" style="margin:0">Released ${esc(e.release_utc.replace("T", " ").replace("Z", " UTC"))} (${esc(e.release_session.replace("_", " "))}) · ${esc(e.company_symbol)} on Bitget</p></div>`;

  // Surprise decomposition
  if (d) {
    const dirTxt = dec.decision === "TRADE" ? dec.structure : "NO_TRADE (" + dec.reasons.map(k => GATE_NAMES[k] || k).join(", ") + ")";
    html += `<div class="card"><h3>Surprise decomposition</h3><pre class="decomp">` + esc(
      `Reported revenue:        ${bn(s.revenue_actual)} vs ${bn(s.revenue_guided_mid)} company guidance midpoint\n` +
      `Company-guidance surprise: ${pp(s.guidance_surprise_pct, 1)} (${s.vs_guidance_band} the guided range; not analyst consensus)\n` +
      `Guidance:                ${s.guidance_direction} (next quarter ${bn(s.next_quarter_guidance_mid)}, guided growth ${pp(s.guided_sequential_growth_pct, 1)} vs ${pp(s.prior_guided_sequential_growth_pct, 1)} prior)\n` +
      `Market contribution:     ${pct(d.market)}   (beta ${a.model.beta_market.toFixed(2)} x QQQ ${pct(a.window_returns.market)})\n` +
      `Sector contribution:     ${pct(d.sector)}   (beta ${a.model.beta_sector.toFixed(2)} x ${a.window_returns.sector_members}-name basket ex-market)\n` +
      `Liquidity effect:        ${pct(d.liquidity)}\n` +
      `Observed company move:   ${pct(d.observed)}   (release hour to +2h)\n` +
      `Estimated residual:      ${pct(d.residual)}\n` +
      `Decision:                ${dirTxt}`) + `</pre>` + decompBar(d) + `</div>`;
  } else {
    html += `<div class="card"><h3>Surprise decomposition</h3><p>${s.guidance_surprise_pct != null ? `Reported ${bn(s.revenue_actual)} vs ${bn(s.revenue_guided_mid)} company guidance midpoint (company-guidance surprise ${pp(s.guidance_surprise_pct, 1)}).` : "Earnings data incomplete."} No decomposition: ${esc((a.gates.market_data || a.gates.event_data || {}).detail || "")}</p></div>`;
  }

  // Strategy card
  if (dec.decision === "TRADE" && r.residual) {
    const t = r.residual, comp = t.legs.find(l => l.role === "company"), hed = t.legs.find(l => l.role === "hedge");
    html += `<div class="card"><h3>Strategy card</h3><dl class="kv">
      <dt>Company instrument</dt><dd>${esc(comp.symbol)} · ${comp.side} ${comp.qty.toFixed(3)} @ ${comp.entry_fill.toFixed(2)}</dd>
      <dt>Hedge instrument</dt><dd>${hed ? `${esc(hed.symbol)} · ${hed.side} ${hed.qty.toFixed(3)} @ ${hed.entry_fill.toFixed(2)}` : "none"}</dd>
      <dt>Direction</dt><dd>${esc(dec.structure)}</dd>
      <dt>Hedge ratio</dt><dd>${a.hedge.beta.toFixed(3)} (OLS on ${a.hedge.n_hours} pre-event hours, R² ${a.hedge.r2.toFixed(2)})</dd>
      <dt>Expected residual</dt><dd>${pct(a.residual)} · params ${r.params.mode > 0 ? "continuation" : "reversal"}, k=${r.params.k} (${esc(r.params.source)})</dd>
      <dt>Size</dt><dd>$${(comp.notional).toLocaleString()} company notional (x${dec.size})</dd>
      <dt>Entry</dt><dd>${when(t.entry_ms)}</dd>
      <dt>Event horizon</dt><dd>${D.config.hold_hours}h → exit ${when(t.exit_ms)}${t.stopped ? " (stopped)" : ""}</dd>
      <dt>Maximum loss</dt><dd>$${(D.config.max_loss_frac * comp.notional).toFixed(0)} (stop on hourly close)</dd>
      <dt>Exit condition</dt><dd>horizon reached or pair mark-to-market ≤ −max loss</dd>
      <dt>Realized</dt><dd class="${cls(t.net)}"><b>${usd(t.net)}</b> net · fees ${usd(-t.fees)} · slippage ${usd(-t.slippage)} · funding ${usd(t.funding)} (${esc(t.funding_data)})</dd>
    </dl></div>`;
    html += attributionCard(t.attribution);
    html += `<div class="card"><h3>Paper execution · both legs</h3><div class="table-scroll"><table><thead><tr><th>Leg</th><th>Symbol</th><th>Side</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Exit</th><th class="num">Fees</th><th class="num">Funding</th><th class="num">Net</th></tr></thead><tbody>` +
      t.legs.map(l => `<tr><td>${l.role}</td><td>${esc(l.symbol)}</td><td>${l.side}</td><td class="num">${l.qty.toFixed(4)}</td><td class="num">${l.entry_fill.toFixed(2)}</td><td class="num">${l.exit_fill.toFixed(2)}</td><td class="num">${usd(-l.fees)}</td><td class="num">${usd(l.funding)}</td><td class="num ${cls(l.net)}">${usd(l.net)}</td></tr>`).join("") +
      `</tbody></table></div><p class="note">Balance after event: ${r.balance_after ? "$" + r.balance_after.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "n/a"}</p></div>`;
  }

  // Gates
  html += `<div class="card"><h3>Risk and trade gate</h3><ul class="gates">` +
    Object.entries(dec.gates).map(([k, g]) => `<li><span class="${g.pass ? "pos" : "neg"}">${g.pass ? "✓" : "✗"}</span><b>${esc(GATE_NAMES[k] || k)}</b><span class="muted">${esc(g.detail)}</span></li>`).join("") + `</ul></div>`;

  // AI interpretation
  const it = r.interpretation;
  html += `<div class="card"><h3>AI interpretation</h3>` + (it && it.status === "ok"
    ? `<p><b>${esc(it.label.replace(/_/g, " "))}</b> · confidence ${it.confidence.toFixed(2)} · ${esc(it.model)}</p><p>${esc(it.rationale)}</p>` +
      it.evidence_quotes.map(q => `<p class="note">“${esc(q)}” <span class="pos">✓ found in source</span></p>`).join("")
    : `<p class="muted">${it ? esc(it.status + ": " + (it.detail || "")) : "AI gate disabled for this run (deterministic core)."}</p>`) + `</div>`;

  html += evidenceCard(e, a, r);
  $("#detail").innerHTML = html;
}

function decompBar(d) {
  const parts = [["market", d.market, "#7a8599"], ["sector", d.sector, "#b08a3e"], ["liquidity", d.liquidity, "#8b8f98"], ["residual", d.residual, "#2f5bd3"]];
  const W = 520, H = 70, max = Math.max(Math.abs(d.observed), ...parts.map(p => Math.abs(p[1]))) * 1.15 || 1;
  const x = v => W / 2 + v / max * (W / 2 - 10);
  let y = 6, out = "";
  parts.concat([["observed", d.observed, "#16181d"]]).forEach(([k, v, c]) => {
    out += `<rect x="${Math.min(x(0), x(v))}" y="${y}" width="${Math.abs(x(v) - x(0))}" height="9" fill="${c}" rx="2"/><text x="4" y="${y + 8}">${k}</text>`;
    y += 12;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="margin-top:8px"><line x1="${W / 2}" x2="${W / 2}" y1="0" y2="${H}" stroke="currentColor" opacity=".25"/>${out}</svg>`;
}

function attributionCard(at) {
  if (!at) return "";
  const items = [["Company leg", at.company_leg], ["Hedge leg", at.hedge_leg], ["Residual (thesis)", at.residual], ["Factor / hedge error", at.factor_error],
    ["Execution slippage", at.slippage], ["Fees", at.fees], ["Funding", at.funding], ["Timing (signal→fill)", at.timing_signal_to_fill]];
  const max = Math.max(...items.map(i => Math.abs(i[1]))) || 1;
  return `<div class="card"><h3>Post-event attribution</h3><table><tbody>` + items.map(([k, v]) =>
    `<tr><td>${k}</td><td style="width:45%"><div class="bar"><i style="left:${v < 0 ? 50 - Math.abs(v) / max * 50 : 50}%;width:${Math.abs(v) / max * 50}%;background:${v < 0 ? "var(--neg)" : "var(--pos)"}"></i></div></td><td class="num ${cls(v)}">${usd(v)}</td></tr>`).join("") +
    `</tbody></table><p class="note">Residual + factor error − slippage − fees + funding = net ${usd(at.net)}. Over the hold the company moved ${pct(at.hold_returns.company)}; the factor model predicted ${pct(at.hold_returns.factor_predicted)}.</p></div>`;
}

function evidenceCard(e, a, r) {
  const fld = (name, f) => f ? `<tr><td>${name}</td><td class="num">${f.unit === "USD_millions" ? bn(f.value) : f.value}${f.low != null ? ` <span class="muted">(${bn(f.low)}–${bn(f.high)})</span>` : ""}</td><td><span class="snip">${esc(f.snippet)}</span><br><a href="${esc(f.source_url)}" target="_blank" rel="noopener">source</a> · sha256 ${esc(f.source_sha256.slice(0, 12))}… · ${f.verified ? '<span class="pos">verified</span>' : '<span class="neg">unverified</span>'}</td></tr>` : `<tr><td>${name}</td><td class="muted">not found</td><td></td></tr>`;
  const E = e.earnings;
  let h = `<div class="card"><h3>Evidence</h3><dl class="kv">
    <dt>Press release</dt><dd><a href="${esc(e.source.press_release_url)}" target="_blank" rel="noopener">${esc(e.source.press_release_url.split("/").pop())}</a> · <a href="${esc(e.source.filing_index_url)}" target="_blank" rel="noopener">8-K ${esc(e.accession)}</a></dd>
    <dt>Guidance baseline</dt><dd><a href="${esc(e.prior_source.press_release_url)}" target="_blank" rel="noopener">prior release ${esc(e.prior_source.accession)}</a> (company outlook midpoint, not consensus)</dd>
    <dt>Event timestamp</dt><dd>${esc(e.release_utc)} (SEC acceptance time)</dd>`;
  if (a.times) h += `<dt>Market timestamps</dt><dd>pre ${when(a.times.t_pre)} · observe ${when(a.times.t_obs)} · exit ${when(a.times.t_exit)}</dd>`;
  if (a.prices) h += `<dt>Market snapshot</dt><dd>${esc(e.company_symbol)} ${a.prices.company_pre} → ${a.prices.company_obs} · QQQUSDT ${a.prices.market_pre} → ${a.prices.market_obs}</dd>`;
  if (a.model) h += `<dt>Factor model</dt><dd>β<sub>m</sub> ${a.model.beta_market.toFixed(3)} · β<sub>s</sub> ${a.model.beta_sector.toFixed(3)} · b<sub>s|m</sub> ${a.model.b_sector_market.toFixed(3)} · R² ${a.model.r2.toFixed(2)} · ${a.model.n_hours} hourly obs · σ<sub>resid</sub> ${pct(a.model.resid_sigma_h, 3)}/h</dd>
    <dt>Robustness</dt><dd>${Object.entries(a.robustness_residuals).map(([w, v]) => `${w}d: ${pct(v)}`).join(" · ")}</dd>
    <dt>Sector basket</dt><dd>${a.peers.map(esc).join(", ")}</dd>
    <dt>Hedge candidates</dt><dd>${(a.hedge_candidates || []).map(c => `${esc(c.symbol)} β ${c.beta.toFixed(2)} R² ${c.r2.toFixed(2)}`).join(" · ") || "none"}</dd>
    <dt>Costs</dt><dd>taker ${(a.costs.taker_fee * 1e4).toFixed(1)} bps · spread est ${(a.costs.spread_est_company * 1e4).toFixed(1)} bps · round trip ${pct(a.costs.round_trip)}</dd>`;
  h += `<dt>Model version</dt><dd>${esc(D.model_version)} · ${esc(D.extractor_version)}</dd>
    <dt>Reproducible input</dt><dd><code>data/snapshots/${esc(e.event_id)}.json</code> + <code>data/events.json</code></dd></dl>
    <div class="table-scroll" style="margin-top:10px"><table class="evid"><thead><tr><th>Field</th><th class="num">Value</th><th>Verbatim source snippet</th></tr></thead><tbody>` +
    fld("Revenue (actual)", E.revenue_actual) + fld("Revenue outlook (prior)", E.revenue_guidance_prior) +
    fld("Revenue outlook (next)", E.revenue_guidance_next) + fld("Revenue (prior quarter)", E.revenue_prior_actual) +
    fld("Diluted EPS", E.eps_diluted) + `</tbody></table></div>` +
    (e.commentary ? `<p class="note"><b>Management commentary</b> (${esc(e.commentary.speaker)}): “${esc(e.commentary.text.slice(0, 400))}${e.commentary.text.length > 400 ? "…" : ""}”</p>` : "") + `</div>`;
  return h;
}

function lineChart(series, W = 640, H = 220) {
  const all = series.flatMap(s => s.values), n = Math.max(...series.map(s => s.values.length));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all), pad = 28;
  const x = i => pad + i / Math.max(1, n - 1) * (W - pad - 8), y = v => H - 18 - (v - lo) / ((hi - lo) || 1) * (H - 30);
  let g = `<line x1="${pad}" x2="${W - 8}" y1="${y(0)}" y2="${y(0)}" stroke="currentColor" opacity=".25"/>`;
  g += `<text x="2" y="${y(hi) + 4}">${usd(hi, 0)}</text><text x="2" y="${y(lo)}">${usd(lo, 0)}</text>`;
  series.forEach(s => {
    g += `<polyline fill="none" stroke="${s.color}" stroke-width="${s.w || 2}" ${s.dash ? 'stroke-dasharray="4 3"' : ""} points="${s.values.map((v, i) => x(i) + "," + y(v)).join(" ")}"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${g}</svg><div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>`;
}

function renderResults() {
  const S = D.summary, C = D.summary_conservative_funding;
  const order = [["residual", "Residual (hedged pair)"], ["unhedged", "Unhedged company trade (same signals)"],
    ["naive_same_events", "Naive headline on the same events (like-for-like)"], ["naive", "Naive headline on every event"], ["no_trade", "No-trade"]];
  const ab = D.ablation_no_ai;
  const row = (name, m) => `<tr><td>${name}</td><td class="num ${cls(m.total_net_pnl)}">${usd(m.total_net_pnl)}</td><td class="num">${m.trades}</td><td class="num">${m.excluded_funding_unavailable || 0}</td><td class="num">${m.hit_rate == null ? "n/a" : (m.hit_rate * 100).toFixed(0) + "%"}</td><td class="num">${m.avg_pnl_per_trade == null ? "n/a" : usd(m.avg_pnl_per_trade)}</td><td class="num neg">${usd(m.max_drawdown)}</td><td class="num">${m.avg_holding_hours ?? "n/a"}</td></tr>`;
  const table = (title, T, note, withAb) => `<div class="card"><h3>${title}</h3><div class="table-scroll"><table><thead><tr><th>Strategy</th><th class="num">Net P&amp;L</th><th class="num">Trades counted</th><th class="num">Excluded (no funding data)</th><th class="num">Hit rate</th><th class="num">Avg/trade</th><th class="num">Max DD</th><th class="num">Avg hold (h)</th></tr></thead><tbody>` +
    order.map(([k, n]) => T[k] ? row(n, T[k]) : "").join("") + (withAb && ab ? row("Residual without AI gate (ablation)", ab.summary.residual) : "") +
    `</tbody></table></div><p class="note">${note}</p></div>`;
  let h = table(`Primary result · walk-forward over ${D.rows.length} real events`, S,
    `Only trades whose holding period has complete Bitget funding history are counted; trades in periods where Bitget no longer serves funding are excluded (counted as $0). ${esc(D.evaluation)}. Same entry time (release hour +${D.config.obs_hours}h), ${D.config.hold_hours}h horizon, Bitget taker fees and estimated slippage for every strategy. Small sample: not evidence of a statistically significant edge.`, true);
  if (C) h += table("Sensitivity · all trades with conservative funding", C,
    "Every trade is counted. Where Bitget funding history is unavailable, each settlement is charged against the position at the largest absolute funding rate observed for that symbol (or the worst across symbols if none was observed).", false);
  const pw = D.summary_post_warmup;
  if (pw) h += `<div class="card"><h3>After warm-up (parameters learned walk-forward)</h3><p>Residual ${usd(pw.residual.total_net_pnl)} over ${pw.residual.trades} trades · unhedged ${usd(pw.unhedged.total_net_pnl)} · naive (same events) ${usd((pw.naive_same_events || {}).total_net_pnl)}</p></div>`;
  h += `<div class="grid2"><div class="card"><h3>Cumulative net P&amp;L by event</h3>` + lineChart([
    { name: "Residual pair", values: S.residual.equity_curve, color: "var(--accent)", w: 2.5 },
    { name: "Unhedged", values: S.unhedged.equity_curve, color: "#b08a3e" },
    { name: "Naive (same events)", values: S.naive_same_events.equity_curve, color: "var(--neg)", dash: 1 },
    { name: "No-trade", values: S.no_trade.equity_curve, color: "#8b8f98" }]) + `</div>`;
  const traded = D.rows.filter(r => r.residual);
  const tot = k => traded.reduce((a, r) => a + (r.residual.attribution[k] || 0), 0);
  h += `<div class="card"><h3>Aggregate attribution (${traded.length} trades)</h3>` + attributionCard({
    company_leg: tot("company_leg"), hedge_leg: tot("hedge_leg"), residual: tot("residual"), factor_error: tot("factor_error"),
    slippage: tot("slippage"), fees: tot("fees"), funding: tot("funding"), timing_signal_to_fill: tot("timing_signal_to_fill"), net: tot("net"),
    hold_returns: { company: NaN, factor_predicted: NaN }
  }).replace(/<p class="note">.*?<\/p>/s, "").replace('<div class="card"><h3>Post-event attribution</h3>', "") + `</div></div>`;
  h += `<div class="card"><h3>Event-by-event</h3><div class="table-scroll"><table><thead><tr><th>Event</th><th>Decision</th><th>Params</th><th class="num">Residual</th><th class="num">Pair net</th><th class="num">Company leg</th><th class="num">Hedge leg</th><th class="num">Unhedged</th><th class="num">Naive</th><th>Rejected because</th></tr></thead><tbody>` +
    D.rows.map(r => `<tr><td><a href="#" data-go="${esc(r.event_id)}">${esc(r.event_id)}</a></td><td>${badge(r.decision.decision)}</td><td>${r.params.mode > 0 ? "cont" : "rev"} k=${r.params.k}</td>
      <td class="num ${cls(r.analysis.residual)}">${r.analysis.residual == null ? "n/a" : pct(r.analysis.residual)}</td>
      <td class="num ${cls(r.residual?.net)}">${r.residual ? usd(r.residual.net) + (r.residual.funding_data !== "complete" ? ' <span class="muted" title="excluded from primary result: Bitget funding history unavailable">*</span>' : "") : ""}</td>
      <td class="num">${r.residual ? usd(r.residual.attribution.company_leg) : ""}</td><td class="num">${r.residual ? usd(r.residual.attribution.hedge_leg) : ""}</td>
      <td class="num ${cls(r.unhedged?.net)}">${r.unhedged ? usd(r.unhedged.net) : ""}</td><td class="num ${cls(r.naive?.net)}">${r.naive ? usd(r.naive.net) : ""}</td>
      <td class="muted">${esc(r.decision.reasons.map(k => GATE_NAMES[k] || k).join(", "))}</td></tr>`).join("") + `</tbody></table></div>
    <p class="note">* excluded from the primary result: Bitget funding history unavailable for the holding period. Paper ledger with every order for both legs: <code>data/ledger.csv</code> (${D.orders.length} orders). These are local paper records built from Bitget public market data; no Bitget Demo Trading orders are placed.</p></div>`;
  $("#tab-results").innerHTML = h;
  $("#tab-results").querySelectorAll("[data-go]").forEach(a => a.onclick = ev => {
    ev.preventDefault(); document.querySelector('[data-tab="board"]').click(); select(a.dataset.go);
  });
}

function renderLive() {
  const log = (D.live_log || []).slice().reverse();
  if (!log.length) { $("#tab-live").innerHTML = `<div class="card"><p>No live watcher runs recorded yet. Run <code>python -m residual live</code>.</p></div>`; return; }
  const last = log[0];
  let h = `<div class="card"><p class="note" style="margin:0"><b>Static snapshot.</b> This page is a static site; it shows the watcher log as of the last local <code>python -m residual live</code> run and last export. It does not update on its own.</p></div>`;
  h += `<div class="card"><h3>Latest check · ${esc(last.checked_at)}</h3><p>${badge(last.decision.split(",")[0])} ${esc(last.reason)}</p>
    <p class="note">Next estimated releases (last filing + 91 days): ${Object.entries(last.next_estimated_release || {}).slice(0, 5).map(([t, d]) => `${esc(t)} ~${esc(d)}`).join(" · ")}</p></div>`;
  if (last.market_probe) h += `<div class="card"><h3>Live Bitget liquidity probe</h3><div class="table-scroll"><table><thead><tr><th>Symbol</th><th class="num">Bid</th><th class="num">Ask</th><th class="num">Spread</th><th class="num">Bid depth ≤10bps</th><th class="num">Ask depth ≤10bps</th><th class="num">Funding</th></tr></thead><tbody>` +
    last.market_probe.map(p => p.error ? `<tr><td>${esc(p.symbol)}</td><td colspan="6" class="neg">${esc(p.error)}</td></tr>` : `<tr><td>${esc(p.symbol)}</td><td class="num">${p.bid}</td><td class="num">${p.ask}</td><td class="num">${p.spread_bps} bps</td><td class="num">$${p.bid_depth_10bps_usdt.toLocaleString()}</td><td class="num">$${p.ask_depth_10bps_usdt.toLocaleString()}</td><td class="num">${(p.funding_rate * 100).toFixed(4)}%</td></tr>`).join("") + `</tbody></table></div></div>`;
  h += `<div class="card"><h3>Watcher log</h3><div class="table-scroll"><table><thead><tr><th>Checked</th><th>Decision</th><th>Detail</th></tr></thead><tbody>` +
    log.map(l => {
      const demoOrders = [...(l.new_events || []).map(n => n.position), ...(l.closed_positions || [])]
        .filter(p => p && p.execution === "bitget_demo")
        .flatMap(p => p.demo_legs.flatMap(g => [g.open_order, g.close_order].filter(Boolean).map(o => `${g.demo_symbol} ${o.side} #${o.orderId} @ ${o.priceAvg}`)));
      return `<tr><td>${esc(l.checked_at)}</td><td>${esc(l.decision)}</td><td class="muted" style="white-space:normal">${esc(l.reason)}${(l.new_events || []).map(n => ` · ${esc(n.event_id)}: ${esc(n.decision)} (${esc(n.reason || "")})`).join("")}${demoOrders.length ? `<br><b>Bitget Demo orders:</b> ${demoOrders.map(esc).join(" · ")}` : ""}</td></tr>`;
    }).join("") + `</tbody></table></div></div>`;
  $("#tab-live").innerHTML = h;
}

function renderOperator() {
  const o = D.operator || {};
  const srcs = D.events.slice().sort((a, b) => b.release_ms - a.release_ms);
  $("#tab-operator").innerHTML = `
  <div class="card"><h3>Downloads</h3>
    <p><a href="data.json" download>data.json</a> (full results) · <a href="ledger.csv" download>ledger.csv</a> (${D.orders.length} paper orders, both legs) · <a href="events.json" download>events.json</a> (earnings dataset with provenance) · <a href="https://github.com/jenzylove/residual/tree/main/data/sources" target="_blank" rel="noopener">archived SEC sources</a></p></div>
  <div class="card"><h3>Execution and replay status</h3><dl class="kv">
    <dt>Execution adapter</dt><dd>${esc(o.execution_adapter || "local_paper")}</dd>
    <dt>Bitget Demo keys</dt><dd>${o.demo_credentials_configured ? "configured" : "not configured"} · product ${esc(o.demo_product_type || "n/a")}</dd>
    <dt>DNS fallback</dt><dd>${o.doh_fallback_enabled ? "enabled" : "off (system DNS)"}</dd>
    <dt>Replay</dt><dd>${esc(o.replay_mode || "n/a")} · generated ${esc(D.generated_at)} · ${esc(D.model_version)} · ${esc(D.extractor_version)}</dd>
    <dt>AI gate</dt><dd>${(o.ai_gate ?? D.config.ai_gate) ? "on" : "off"}</dd></dl></div>
  <div class="card"><h3>Commands</h3><pre style="margin:0;font-family:var(--mono);font-size:12.5px;line-height:1.7">python -m residual verify --offline
python -m residual replay --offline
python -m residual build
python -m residual snapshot
python -m residual live --loop 600
python -m residual demo-check
python -m residual demo-roundtrip --notional 50
python -m unittest discover -s tests</pre></div>
  <div class="card"><h3>Sources and hashes</h3><div class="table-scroll"><table><thead><tr><th>Event</th><th>Press release</th><th>SHA-256</th><th>8-K</th></tr></thead><tbody>
    ${srcs.map(e => `<tr><td>${esc(e.event_id)}</td><td><a href="${esc(e.source.press_release_url)}" target="_blank" rel="noopener">${esc(e.source.press_release_url.split("/").pop())}</a></td><td style="font-family:var(--mono);font-size:12px">${esc(e.source.sha256 || "")}</td><td><a href="${esc(e.source.filing_index_url)}" target="_blank" rel="noopener">${esc(e.accession)}</a></td></tr>`).join("")}
  </tbody></table></div></div>`;
}

function renderMethod() {
  const c = D.config;
  $("#tab-method").innerHTML = `<div class="card" style="max-width:900px"><h3>How RESIDUAL decides</h3>
  <ol>
    <li><b>Event collector.</b> SEC EDGAR Item 2.02 8-K filings; the event timestamp is the SEC acceptance time.</li>
    <li><b>Earnings extractor.</b> Deterministic patterns pull reported revenue and the next-quarter revenue outlook from the Exhibit 99.1 press release. Each value keeps its verbatim snippet, source URL and document SHA-256, and is re-derived before use. The surprise is a <b>company-guidance surprise</b>: reported revenue vs the company's own prior-quarter outlook midpoint, cited to the prior release. It is not an analyst-consensus surprise. EPS and gross margin are optional evidence fields; the model does not use them.</li>
    <li><b>Factor estimator.</b> Hourly Bitget perp returns over the ${c.lookback_days} days before the event: company on QQQ (market) and an equal-weight basket of sector peers orthogonalized to the market. Betas at ${c.beta_windows_days.join("/")}-day windows.</li>
    <li><b>Residual calculator.</b> Observed move from the release hour to +${c.obs_hours}h minus market contribution, sector contribution and a liquidity (half-spread) effect.</li>
    <li><b>Trade constructor.</b> Company leg vs a single hedge instrument (SMH/QQQ/SPY, best historical R²); hedge ratio = OLS beta, never an LLM value.</li>
    <li><b>AI interpretation.</b> An LLM labels the residual durable / temporary / already priced / contradicted by guidance / too uncertain, citing verbatim quotes that are checked against the press release. The label only scales size (1.0 / 0.5 / 0).</li>
    <li><b>Risk gate.</b> NO_TRADE if data is incomplete, the hedge is unavailable or weak, liquidity is thin, the residual is below k× round-trip cost, the sign is not robust across beta windows, or the early move has already half-reversed.</li>
    <li><b>Paper executor.</b> Both legs filled at the next hourly open with slippage, Bitget taker fees and funding; ${c.hold_hours}h horizon, stop at ${(c.max_loss_frac * 100).toFixed(1)}% of company notional.</li>
    <li><b>Evaluator.</b> Realized P&amp;L split into company leg, hedge leg, residual, factor error, slippage, fees, funding and timing. Direction (continuation vs reversal) and k are learned walk-forward from earlier events only.</li>
  </ol>
  <p class="note">Reproduce offline from the committed dataset: <code>python -m residual verify --offline && python -m residual replay --offline</code>. Market data comes from Bitget's public REST API. Historical replay is local paper accounting; live-mode trades execute on Bitget Demo Trading when demo credentials are configured. No real-money orders are ever placed.</p></div>`;
}
