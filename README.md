# qqq-overnight-drift

One rule, one ETF at a time, held **overnight only**.

> **Every trading day, IF QQQ's latest close is above its 200-day moving average:
> BUY at the close → SELL at the next open → sit in CASH all day → repeat.
> IF QQQ is below its 200-day average: stay in cash, no trade.**
>
> *What* you buy (QQQ 1× / QLD 2× / TQQQ 3×) is picked from QQQ's 20-day realized
> volatility: **< 18% → TQQQ · > 28% → QQQ · in between → QLD**.

QQQ's gains pile up overnight; the daytime session is where the volatility and
the crashes are. Sitting in cash all day keeps the good half. The 200-day filter
is what survives the crashes — it parks in cash *before* them, it does not ride
them out.

Validated 2000–2026 (data through 2026-08-28, incl. dot-com and 2008), net of
0.5 bp/side:
**+24.4% CAGR, Sharpe 1.20, MaxDD −33.5%.** Read [Risks](#risks) before using
leverage or real money.

---

## Quickstart

```bash
uv sync                                  # one-time: create .venv from uv.lock
uv run python scripts/backtest.py        # reproduce every number below (~5s)
uv run python scripts/today.py           # tonight's decision (needs Alpaca keys)
```

## Backtest

```bash
uv run python scripts/backtest.py                              # deployed settings
uv run python scripts/backtest.py --spread-bps 1               # pessimistic costs
uv run python scripts/backtest.py --lo 0.15 --hi 0.25          # move the vol thresholds
uv run python scripts/test_strategy.py                         # self-check (no-lookahead etc.)
```

Data ships in `data/{QQQ,QLD,TQQQ}_daily_yf.csv` — **no downloads, no API key
needed to backtest.** One run prints the crash-period table, the fixed-instrument
comparison, split-half robustness, threshold sensitivity, and the instrument mix.

**Results, net 0.5 bp/side:**

| Period | CAGR | Sharpe | MaxDD | In-market |
|---|---:|---:|---:|---:|
| **Full 2000–2026** | **+24.4%** | **1.20** | −33.5% | 74% |
| Dot-com bust 2000–2002 | +0.6% | 0.11 | −18.3% | **24%** |
| Dot-com + recovery 2000–2004 | +13.8% | 0.99 | −24.0% | 45% |
| GFC 2007–2009 | +21.1% | 1.29 | −16.0% | 61% |
| 2022 bear | −9.3% | −1.51 | −9.5% | **7%** |
| Deployed era 2010–2026 | +29.5% | 1.26 | −33.5% | 85% |

**Versus the alternatives** (2010–2026, the window where all three ETFs really
trade):

| Strategy | CAGR | Sharpe | MaxDD |
|---|---:|---:|---:|
| **Vol-switch (deployed)** | **+29.5%** | **1.26** | −33.5% |
| Always TQQQ (3×) | +34.7% | 1.19 | −49.7% |
| Always QLD (2×) | +21.3% | 1.11 | −36.2% |
| Always QQQ (1×) | +10.6% | 1.10 | −19.5% |
| Overnight QQQ, no trend filter | +13.0% | 1.03 | −27.4% |
| QQQ buy & hold | +19.4% | 0.96 | −35.1% |

Over the *full* 2000–2026 window QQQ buy & hold makes +8.7% / Sharpe 0.45 /
**−83% drawdown** — the deployed rule roughly triples that CAGR at 40% of the
drawdown, because it sat out both crashes.

Why it's credible rather than data-mined: both sample halves hold up
independently (Sharpe 1.33 / 1.21), the threshold plateau is flat (Sharpe ~1.26
for any lo∈[15%,18%], hi∈[25%,30%]), and it stacks two documented anomalies (the
overnight/night effect + 200-day trend following) rather than a fitted indicator.

**How the pre-2010 years are handled.** TQQQ was born Feb 2010, QLD Jun 2006. All
*signals* use real QQQ only (from 1999) — no synthetic data drives any decision.
Only the leveraged *payoff* before inception is reconstructed, as
`overnight_Lx = L × overnight_QQQ − drag`, calibrated on the real-ETF overlap
(OLS slope 1.97 / 2.95, correlation 0.989 / 0.997; drag 0.6 bp/night for 2×,
1.1 bp/night for 3×). During the crashes the rule is mostly in cash, so this fill
barely touches the survival result.

## Deploy

Needs free Alpaca market-data keys (no funding, paper account is fine) in `.env`:

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

Then, **once per trading day, after ~3:40pm ET:**

```bash
uv run python scripts/today.py                     # auto-pick instrument, $10k
uv run python scripts/today.py --capital 5000      # smaller account
uv run python scripts/today.py --instrument QLD    # override the vol picker
```

It prints one of two answers (all times **New York**; subtract 3h in California):

- **BUY 🟢** with an exact share count. Both orders go in the same afternoon —
  you never wake up for the open:
  1. **Before 3:45pm ET** (the MOC cutoff): place a **Market-On-Close BUY** →
     fills at today's 4:00pm close.
  2. **That evening, once it fills:** place a **Market-On-Open SELL** for the
     same shares → fills at tomorrow's 9:30am open.
  3. Sleep. Re-run tomorrow afternoon.
- **CASH ⚪** — QQQ is below its 200-day average. Place nothing, re-run tomorrow.

Committing to sell at the open sight-unseen is exactly what the backtest assumes
(official auction prices), so no discretion is needed.

`today.py` is a **signal tool — it does not place orders.** Example output:

```
  QQQ close     : 716.43
  200d average : 655.17   (+9.3% vs price)
  trend           : ABOVE ✅
  20d realized vol: 18.4%   -> QLD (mid vol)
  DECISION: BUY QLD  🟢
    $10,000 capital -> BUY 110 QLD @ ~90.17  (~$9,919)
```

**Broker notes (verified July 2026):**
- **Schwab MOC (the BUY): ✅ supported**, must be placed before 3:45pm ET.
- **Schwab MOO (the SELL): not confirmed** — Schwab's documented order types
  don't clearly list Market-On-Open. Check your order ticket. If it's absent:
  (a) queue a plain market SELL (Day) while closed and verify with 1 share that
  Schwab holds it to the open, (b) be up at 9:30am ET to sell, or (c) run the
  SELL through **IBKR**, which does support MOO.
- QQQ/QLD/TQQQ are commission-free at Schwab, and the leverage is *inside* the
  ETF — **no margin account needed**, and you cannot be margin-called.
- Overnight holds are **not** PDT day-trades, so the $25k rule doesn't apply.

## Risks

1. **Bull-flattered sample (mitigated, not eliminated).** Real leveraged-ETF data
   only exists from 2006/2010, the best stretch ever for leveraged tech. The
   pre-2010 stress test shows the rule survives both crashes via the trend
   filter, but that leverage is reconstructed, not lived. No deployed ETF has
   traded a crash live.
2. **The drawdowns are brutal.** −33% deployed, −50% for always-TQQQ. Sharpe
   looks calm; the equity curve will not. Most people bail at the bottom.
3. **Overnight gap risk.** You hold *while asleep*. A ~33% overnight gap in QQQ
   takes **TQQQ to near zero** (QLD needs ~50%). This tail is real and is **not**
   in the smooth backtest — it is the reason to size TQQQ small.
4. **Taxes.** Everything is a short-term gain → run this in an **IRA/401k**, or
   the tax drag erases the edge.
5. **Anomaly decay.** Overnight edges can weaken (SPY's did post-2016; QQQ's
   held). Leverage amplifies whatever is left, in both directions.
6. **The gate is forward paper-tracking.** Prove it live before scaling.

## Files

```
scripts/strategy.py        the rule itself (thresholds, signals) — shared, so the
                           backtest and the daily runner can't drift apart
scripts/backtest.py        full-history backtest + robustness checks
scripts/today.py           tonight's decision (Alpaca daily bars)
scripts/test_strategy.py   self-check: no lookahead, cash off-trend, real sleeves
data/*_daily_yf.csv        QQQ / QLD / TQQQ daily OHLC (yfinance, through 2026-08-28)
```

Refresh the data with:

```bash
uv run --with yfinance python -c "
import yfinance as yf, pandas as pd
for s in ('QQQ','QLD','TQQQ'):
    d = yf.download(s, start='1999-01-01', auto_adjust=True, progress=False, actions=False)
    d.columns = d.columns.get_level_values(0)
    d[['Open','High','Low','Close','Volume']].dropna().to_csv(f'data/{s}_daily_yf.csv')
"

```
