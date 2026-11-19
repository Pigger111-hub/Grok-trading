# CLAUDE.md

Notes for Claude sessions on this repository. Read this first, then `JOURNAL.md` (especially `NEXT_STEPS`) and `PRODUCT.md`.

## The owner

- Thai speaker, new to trading and to Claude, GitHub and coding. Reply in plain Thai, short sentences, explain terms the first time. Give click-by-click steps for anything they must do on GitHub (they did not know where the Merge button was).
- They check the dashboard daily on a phone and want it lively but honest (see `PRODUCT.md`). The brand color is olive green (เขียวขี้ม้า); green for gains is a separate, brighter emerald.
- They merge PRs themselves. Open a PR when asked; do not merge unless they say "merge ให้เลย" or similar.
- No real money, no exchange API keys, no live orders. Everything is a simulation (paper trading). Say so when results could be read as advice.
- The repo is named "Grok-trading" but Grok wrote none of it. Code came from Cursor Agent (PRs #1–#5) and Claude (PR #6 onward). The owner gets a morning report from Grok that is produced outside this repo; nothing here sends email or messages.

## What the project is

A research lab for BTC and ETH trading rules, plus a paper book that runs forward on simulated money.

- `crypto_lab/` — data download, backtest engine, strategies, walk-forward, sweeps, paper book, dashboard data.
  - Round three (Claude): `weights.py` (trend score × volatility sizing), `overfit.py` (Deflated Sharpe, PBO, rolling start dates), `stocks.py` (SPY, QQQ, TDEX.BK entry timing), `phase3.py` (reports).
- `scripts/run_all.py` — full research rerun. `scripts/update_lab.py` — what GitHub Actions runs. `scripts/run_phase3.py [--offline]` — round three reports.
- `results/` — generated reports. `JOURNAL.md` — every experiment in Thai, with tables between `RESULTS`/`COSTS` markers that `run_all.py` rewrites.
- `docs/` — the GitHub Pages dashboard (`index.html`, `dashboard.css`, `dashboard.js`) reading `docs/data/dashboard.json`.
- `.github/workflows/paper-dashboard.yml` — runs about 12 times a day, refreshes prices, rebuilds the paper book and `dashboard.json`, commits as github-actions[bot]. It never overwrites the three page files.

## Rules that keep results honest

- Signals use the bar's close; orders fill at the next bar's open. Never let a signal see a later price. Look-ahead tests must keep passing.
- Fee 0.10% and slippage 0.05% per side (`crypto_lab/assumptions.py`). Always compare with buy-and-hold over the same window.
- Do not tune and then report the tuned result as if it were out of sample. Count every variant tried (see `overfit.py`).
- New experiments go in `JOURNAL.md` after the last numbered one, with date, hypothesis, source, parameters, result versus buy-and-hold, a plain verdict and the next idea. Update `NEXT_STEPS`.

## Working on the dashboard

- Colors are OKLCH tokens at the top of `docs/dashboard.css`; charts read them through `cssColor()` in `dashboard.js`. Keep gains and losses marked with an arrow and sign, not color alone.
- Bump the `?v=` on both the CSS and JS links in `docs/index.html` whenever either file changes, or browsers keep the old copy for about ten minutes and show a half-old page.
- The page only re-presents `dashboard.json`; do not invent numbers the Python side does not produce.
- Check phone (390px) and desktop widths, light and dark, before pushing.

## Commands

```
pip install -r requirements.txt
python -m pytest
python scripts/run_phase3.py --offline
cd docs && python -m http.server 8765   # then open http://localhost:8765
```

Two tests in `tests/test_phase2.py` fail in some environments because vectorbt and the installed plotly disagree. That predates the round-three work; do not hide it.

## Cloud sessions

- The `grok-trading` cloud environment allows Yahoo Finance (stock prices). `pigger111-hub.github.io` and `unpkg.com` are not reachable from it, so check the page by serving `docs/` locally; install `lightweight-charts@4.2.1` from npm to stand in for the unpkg script.
- The container is temporary. Commit and push before finishing.
