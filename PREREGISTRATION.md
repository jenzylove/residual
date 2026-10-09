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
