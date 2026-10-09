# Preregistration: the frozen method on companies it has never seen

Committed 9 October 2026, before any Bitget market data for the companies below was downloaded.
The commit timestamp on GitHub is the record of that order.

## Why

The published study trades 15 times across 80 releases from 20 companies. Its one significant result
is about selection: the releases it chose to trade beat random sets of releases drawn from the same
pool (p = 0.00174, permutation, seeded). Direction choice is not significant (p = 0.198). A sample this
small can be lucky. The cleanest test is to run the unchanged method on companies it was never
developed on, and publish whatever comes out.

## What is frozen

The method as of commit `aceec0a93dcc31853eaea6dfd4f88b03239288c5`: `residual/strategy.py`,
`residual/factors.py`, `residual/market.py`, `residual/pipeline.py`, `residual/interpret.py`, every
gate, threshold, parameter grid, window, cost model, sizing rule and the walk-forward selector.
The sector peer baskets (`PEERS`) and hedge candidates (`HEDGES`) in `residual/universe.py` are not
changed either: new companies are scored against the existing baskets, so no original event's inputs
change.

The only edits allowed after this commit:

1. adding the companies below to `COMPANIES` in `residual/universe.py`, with the sector group listed here;
2. adding their extraction patterns to `ACTUAL` and `GUIDE` in `residual/extract.py`, which read the
   reported revenue and the revenue outlook out of each filed release, each value verified against
   its source snippet and document hash exactly as for the original 20;
3. downloading their filings and Bitget snapshots, then running the replay.

If an extraction pattern cannot be written for a release, that release is recorded as data incomplete
and does not trade. No gate, threshold or parameter is touched to rescue or suppress a result.

## Inclusion rule

A company enters if all of these hold, checked on 8 to 9 October 2026 without looking at any price data:

- Bitget lists a USDT perpetual for its stock;
- it files quarterly results with the SEC on Form 8-K, Item 2.02 (foreign filers on 6-K are out);
- its filed earnings release (Exhibit 99.1) states a numeric outlook, in dollars, for next quarter's
  total revenue or net sales. Product revenue only, "core" non-GAAP revenue, percent growth only and
  full year only outlooks do not qualify;
- at least one of its releases between 15 October 2025 and 30 September 2026 came at least 22 days
  after its Bitget perpetual started trading (the method needs 21 days of hourly history);
- it fits one of the four existing sector groups.

## The companies

| Group | Companies |
|---|---|
| semis | ALAB, AMAT, AMKR, CRDO, LRCX, SNDK, TER |
| hardware | AAOI, CGNX, CIEN, COHR, CSCO, DELL, FLEX, LITE, NTAP, OUST, STX, VRT |
| software | ADBE, APP, BB, PL, TWLO, ZM |
| internet | NFLX, RDDT |

26 companies. Sector groups follow what each company sells: chips and chip equipment (semis);
networking, optical, storage, servers, power and industrial electronics (hardware); software and data
subscriptions (software); consumer internet (internet).

Excluded after checking, with the reason:

- RKLB: qualifies on guidance, but aerospace fits none of the four groups and the method has no
  basket for it.
- SNOW (product revenue only); GLW and CBRS ("core" non-GAAP revenue); WDC, ORCL, WMT, AXON, KTOS,
  AAL (percent growth only).
- Full year outlook only, or no revenue outlook in the release: AAPL, GOOGL, MSFT, TSLA and the other
  candidates marked as such in `data/preregistration_screen.json`.
- Foreign filers on 6-K: ASML, TSM, ARM, BABA, JD, NIO, FUTU, NOK and others.
- Perpetual listed too late for any release in the window.

## What will be reported, whatever it shows

Three populations, never mixed:

1. **Original 20, as published** at commit `aceec0a`: +$189.66 over 15 trades, Sharpe 0.593 daily,
   selection p = 0.00174, direction p = 0.198 (conservative funding view).
2. **New companies only**: every release of the 26 companies above, scored inside the combined
   walk-forward.
3. **Combined**: all companies, one walk-forward, as the method would have run had it watched the wider
   universe from the start.

For each: net P&L, trades, Sharpe (daily and per trade), Sortino, max drawdown, turnover, rolling
30 day Sharpe, the frozen holdout, and both permutation tests, against the same baselines
(unhedged, headline direction on the same releases, headline direction on every eligible release).

## Predictions, stated before the data

- **H1.** On the new companies only, the releases the strategy trades beat random sets of the same size
  from the same eligible pool: selection p below 0.05.
- **H2.** On the new companies only, trading the headline direction on every eligible release loses
  money, and the strategy does better than that.
- **H3.** Direction choice stays insignificant (p above 0.05). This one we expect to hold.

If H1 or H2 fails, the README and the site say so in the scorecard, not in a footnote.

## Known contact with the data

Choosing the companies required reading their earnings releases, which state reported revenue and
outlook. The author has general awareness of some of these companies' share price moves from the
news. No Bitget candle, funding or order book data for any of them had been downloaded when this
file was committed.

## Amendment, 9 October 2026, same morning

The sentence above saying no Bitget data had been downloaded is too absolute. Hourly candles for
ADBE, AMAT, CSCO, DELL, LRCX and NFLX already sit inside existing snapshots in `data/snapshots/`,
downloaded in September as sector basket peers for the original 20 companies. They cover only the
windows around the original companies' releases, and they were not examined when choosing the
companies here: the selection used the inclusion rule and the filed releases only. Nothing else in
this file changes.

A second point found while preparing the extraction. On 21 September, SEC identifiers for eleven
candidates were added to `residual/edgar.py` (ARM, SNOW, NOW, DELL, ANET, ADBE, CSCO, AMAT, LRCX, ADI,
ORCL; NFLX was already listed), and only ADI and ANET joined the study. No snapshot, AI reading,
consensus file or event record for any of the others exists anywhere in the repository history, so
none of them was ever scored. Why they were not added then is not recorded. Their inclusion now
follows the rule above, not that earlier list.

## Outcome, 9 October 2026 (results commit `aa9d939`)

Appended after the run; nothing above was edited.

- 107 releases from the 26 companies; 69 came before a usable Bitget market, 37 could be analysed, and
  the gates passed 2 (LRCX-2026-07-29 +$33.10, DELL-2026-09-01 +$138.22). Thin books and hedges that
  did not fit blocked most of the rest.
- **H1** (selection p below 0.05 on the new companies): p = 0.020. Passes on paper, on two trades only.
- **H2** (headline trade loses on the new companies, strategy beats it): **failed.** The headline trade on
  every eligible new release made +$362.12 over 37 trades, against the strategy's +$171.31.
- **H3** (direction stays insignificant): held, p = 0.25.
- Combined, all 46 companies: 17 trades, +$360.97, Sharpe 1.037 daily, selection p = 0.008,
  direction p = 0.078. The original 20 slice is unchanged at 15 trades and +$189.66.

One deviation from the plan: CRDO-2026-03-03 is recorded as data incomplete because Credo's December
2025 release is missing from the SEC submissions list, so the March release has no prior quarter
outlook to compare against. No pattern or gate was changed for it.

## Correction after the run, 9 October 2026

A bug in the worst case funding view, found after the outcome above was written. Bitget keeps about
90 days of funding history, and the point in time cap only looked at settlements before each release,
so every release before the summer had no earlier settlement and was charged zero: the "worst case"
view was identical to counting missing funding as zero. Those releases are now charged the worst rate
in the contract's whole collected history (later data, used only to make a result worse).

No trade decision changed. The predictions are unaffected: both new company trades had complete
funding data. In the conservative view the new companies' headline trade on every eligible release is
now +$318.76 (H2 still failed), combined the strategy is +$226.06 over 17 trades, Sharpe 0.652 daily,
selection p = 0.012, and the original 20 slice is +$54.74 instead of the +$189.66 quoted above. The
README reports the corrected figures.

## Second correction, 9 October 2026

The worst case charge above is a stress test, not an estimate of what funding would have cost. The
headline view now charges trades without Bitget funding history the contract's average absolute
rate, always against the position, and the worst case view is published beside it. We chose the
average after seeing the worst case result. A median was tried first and rejected: most settlements
are exactly zero, so it charged almost nothing. No trade decision changed.

Headline (average funding): combined +$349.98 over 17 trades, Sharpe 1.005 daily, selection
p = 0.009; original 20 +$178.67; new companies unchanged at +$171.31, with the headline trade on
every eligible new release at +$355.59 (H2 still failed). Worst case view: combined +$226.06,
Sharpe 0.652.
