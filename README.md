# qqq-day-trade

We set out to find a transparent if/else rule that beats the market for a **$10k
account**. Most candidates lose to just buying SPY (see the research journey
lower down). **One survived** — validated across 27 years including the dot-com
crash and 2008.

## ⭐ THE STRATEGY WE RUN

> **Every trading day, IF QQQ's latest close is above its 200-day moving average:
> BUY at the close → SELL at the next open → sit in CASH during the day → repeat.
> IF QQQ is below its 200-day average: stay fully in cash (no trade).**

The key word is **OVERNIGHT ONLY.** You are in the market *only* from the close to
the next open, and in **cash every trading day** and whenever the trend is down.
You repeat this **every day** — it is not a one-time buy.

- **Why overnight only?** QQQ's gains pile up overnight; the daytime session is
  where the crashes and volatility happen. Sitting in cash all day keeps the good
  part and skips the ugly part — that is what drops the drawdown and doubles the
  Sharpe.
- **This is NOT the simpler "hold while above the 200-day" rule.** That weaker
  version (hold continuously day + night while above the SMA) makes only +7.9%
  CAGR / Sharpe **0.54** / −58% drawdown — barely better than doing nothing. The
  overnight-only version makes +9.0% / Sharpe **0.99** / −25% drawdown. The
  difference is entirely "cash during the day." (See "Two versions" below.)
- **The cost:** it trades every day (~2 orders/day). That daily discipline is the
  whole reason to automate it or use market-on-close / market-on-open orders.
- The **signal is always QQQ's trend**; *what to buy* (QQQ / QLD / TQQQ) is now
  **auto-picked by QQQ's volatility regime** — see "Which instrument" below.
- Held **overnight only** = not a PDT day-trade; one ETF, so trading cost ≈ 0.
- Made money *through* the dot-com bust (+2%/yr) and 2008 (+3%/yr, via QLD) while
  buy-and-hold got halved.

### Two versions — why "overnight only" is the whole point

QQQ, 1999–2026, net of cost:

| Version | What you do | CAGR | Sharpe | MaxDD | Trades/yr |
|---|---|---|---|---|---|
| Buy & hold | never sell | +10.8% | 0.52 | −83% | 0 |
| Hold while >200-SMA | hold *continuously* (day+night), cash when below | +7.9% | 0.54 | −58% | ~7 |
| **Overnight only >200-SMA** | in market **only overnight**, cash all day + when below | +9.0% | **0.99** | **−25%** | ~361 |

The simple "hold while above the 200-day" is easy (7 trades/yr) but barely beats
buy-and-hold. The overnight-only version is the winner but trades daily. If you
want the low-effort route, honestly just buy-and-hold QQQ/SPY — the middle row
isn't worth the bother.

### Which instrument — auto-picked by the volatility regime ⭐

Best way to add leverage is a **leveraged ETF**, not retail margin: they finance
at institutional rates (cheaper than IBKR's ~5.5% / Schwab's ~12%), need no
margin account, can't be margin-called, and are commission-free. Holding
*overnight only* dodges most of their daytime volatility-decay.

You no longer pick a fixed instrument. On each night you're in the market, the
tool picks the leverage from **QQQ's 20-day realized volatility** — a
self-contained VIX proxy (no extra data feed). The idea: leveraged-ETF decay is
tiny in calm trends and toxic in choppy ones, so lever up when it's quiet and
de-lever when it's stormy.

> **rvol < 18% → TQQQ (3×)  ·  rvol > 28% → QQQ (1×)  ·  in between → QLD (2×)**
> (Trend filter unchanged: below the 200-day SMA you're in cash regardless.)

**This beats holding *any* single instrument on Sharpe.** Net of cost, 2010–2026
(the window where all three ETFs actually trade), 0.5bp/side:

| Strategy | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| **Vol-switch (DEPLOYED)** | **+29.1%** | **1.25** | −33.5% |
| Always TQQQ (3×) | +34.1% | 1.18 | −49.7% |
| Always QLD (2×) | +20.9% | 1.09 | −36.2% |
| Always QQQ (1×) | +10.4% | 1.08 | −19.5% |

It captures ~85% of always-TQQQ's return with **16 points less drawdown**, and
tops every fixed choice on Sharpe. Why it's credible, not data-mined:

- **Both sample halves independently:** Sharpe 1.35 (2010–18) and 1.17 (2018–26).
  In the harder recent half it beats always-TQQQ on Sharpe (1.17 vs 1.07) with
  −27.5% vs −49.7% drawdown.
- **Flat threshold plateau:** Sharpe stays ~1.25 for any lo∈[15%,18%],
  hi∈[25%,30%] — not a knife-edge fit.
- Mix over the period: TQQQ 70% of trade-nights, QLD 24%, QQQ 6%.

Backtest: `python scripts/regime_switch.py`. Each ETF's **own actual overnight
return** is used (real leveraged-ETF decay, not synthetic 2×/3×).

**Caveat:** because it sits in TQQQ ~70% of the time, it inherits TQQQ's
bull-flattered sample — it is strictly *better than* picking one instrument, not
risk-free. TQQQ itself never traded the dot-com bust. But we no longer rely on
that gap: the whole vol-switch has now been stress-tested back to 2000 with
calibrated-synthetic leverage, and it survives — see next. Read the risks before
using leverage.

### Stress-tested through the crashes it never traded ⭐

The honest hole in the table above: TQQQ was born Feb 2010, so the deployed
window (2010–2026) is *entirely* post-GFC — it had never touched the dot-com
crash or 2008. We closed that gap. QQQ data runs to 1999, and the survival
mechanism is the **200-day trend filter, not the leverage**, so we can
reconstruct the missing years faithfully:

- **Signals use real QQQ only** (SMA, realized vol) — zero synthetic data drives
  any decision.
- **Leveraged *payoff* before inception is synthetic:** `overnight_Lx =
  L × overnight_QQQ − drag`, calibrated against the real ETFs in overlap (OLS
  slope **1.97 / 2.95**, correlation **0.989 / 0.997**; drag 0.6 bp/night for 2×,
  1.1 bp/night for 3×). Real QLD is used from 2006, real TQQQ from 2010.
- Crucially, during the crashes the rule is mostly **in cash**, so the synthetic
  payoff barely touches the survival result — it only fills the minority of
  in-market (and mostly de-levered) nights.

Full deployed vol-switch, 2000–2026, net 0.5 bp/side (`scripts/crisis_backtest.py`):

| Period | CAGR | Sharpe | MaxDD | In-market | vs QQQ buy&hold |
|---|---:|---:|---:|---:|---|
| **Full 2000–2026** | **+24.2%** | **1.19** | −33.5% | 74% | QQQ −83% in 2000–03 |
| Dot-com bust 2000–2002 | +0.6% | 0.11 | −18.3% | **24%** | flat vs −83% carnage |
| Dot-com + recovery 2000–2004 | +13.8% | 0.99 | −24.0% | 45% | ended +40% |
| GFC 2007–2009 | +21.1% | 1.29 | −16.0% | 61% | *made money* |
| 2022 bear | −9.3% | −1.51 | −9.5% | **7%** | vs QQQ o/n −20.5% |
| Deployed era 2010–2026 | +29.1% | 1.25 | −33.5% | 85% | — |

**The trend filter is what saves it.** In the dot-com bust it parked in cash 76%
of nights and came out *flat* while QQQ fell −83% (a leveraged buy-&-hold would
have been wiped out). In 2022 it was in cash 93% of nights. It doesn't earn in a
crash — it **steps aside**, then re-engages into the recovery (GFC: +21%, Sharpe
1.29). Across the full 27 years spanning both crashes it holds Sharpe **1.19**,
so the edge is *not* a post-2010 tech-bull artifact.

**Still a caveat, not a live record:** pre-2010 leverage is synthetic (well
calibrated, but synthetic), and none of the deployed ETFs have traded a crash
*live*. This is strong out-of-sample evidence with a sound survival mechanism —
the gate remains forward paper-tracking.

### 🔵 Running today's pick

```bash
uv run python scripts/today.py                       # 📅 RUN THIS DAILY — auto-picks QQQ/QLD/TQQQ, $10k
uv run python scripts/today.py --capital 5000         # auto, smaller account
uv run python scripts/today.py --instrument QLD       # force a fixed instrument (override)
```

> 📅 **The one command to run every afternoon** is `uv run python scripts/today.py`.
> (The `daily_panel.py` / `backtest.py` commands further down are one-time / research
> only — you do **not** run those daily.)

`today.py` now prints the day's realized vol and the instrument the regime
picks, e.g. `20d realized vol: 22.8% -> QLD (mid vol)`. Force a fixed one with
`--instrument {QQQ,QLD,TQQQ}` if you want to override the picker.

All times below are **New York time (ET)** — the market runs on ET no matter where
you are (in California subtract 3h: 1:00pm buy / 6:30am sell).

The whole routine happens **once, in the afternoon — you never wake up for the
open.** Run it after ~3:40pm ET (price is basically final). It prints one of:

- **BUY 🟢** — with the exact share count. Then, all in the afternoon:
  1. **By ~3:45pm ET** (before the MOC cutoff): place a **Market-On-Close (MOC)
     BUY** → fills at today's **4:00pm** close.
  2. **That same evening**, once the buy has filled: place a **Market-On-Open
     (MOO) SELL** for the same shares → auto-fills at tomorrow's **9:30am** open.
  3. Go to sleep. Both orders execute themselves. Re-run tomorrow afternoon.
- **CASH ⚪** — QQQ is below its 200-day average; place no trade, re-run tomorrow.

**So: buy 4:00pm ET, sell 9:30am ET next day (~17.5h overnight hold), but you set
BOTH orders in the afternoon.** You commit to sell at whatever the open is, sight
unseen — which is exactly what the backtest assumes (official open price), so no
discretion is needed.

Broker notes (verified July 2026):
- **Schwab MOC (the BUY): ✅ supported**, but must be placed **before 3:45pm ET**.
- **Schwab MOO (the SELL): NOT confirmed** — Schwab's documented order types don't
  clearly list "Market on Open." Check your own order ticket's type/timing
  dropdown. If it's absent, either (a) queue a plain market SELL (Day) while
  closed and confirm Schwab holds it to the open (test with 1 share), (b) be up
  briefly at 9:30am ET to sell, or (c) run the SELL through **IBKR**, which does
  support MOO. So on Schwab the auto-buy is solid; the auto-sell-at-open is the
  part to verify before relying on it.

Example (2026-07-22): QQQ 705.35 vs 200-day 642.35 (+9.8%) → BUY; 20d realized
vol 22.8% → regime picks **QLD**, so at $10k that's **113 QLD**. It is a signal
tool — it does **not** place orders; you place the MOC/MOO yourself (or wire IBKR
execution later).

### ⚠️ Risks — read before using leverage or real money

1. **Bull-flattered sample (mitigated, not eliminated).** TQQQ/QLD real numbers
   lean on 2010–2026, the best decade ever for leveraged tech, and TQQQ never
   traded the dot-com bust. The calibrated-synthetic stress test back to 2000
   (above) shows the full vol-switch *survives* both crashes via the trend
   filter — but pre-2010 leverage is reconstructed, not lived. QLD surviving 2008
   (+4%/yr) is the main *real*-data out-of-sample comfort.
2. **The drawdowns are brutal.** QLD −36%, TQQQ −50%. Sharpe looks calm; the
   equity curve will not. Most people bail at the bottom and miss the recovery.
3. **Overnight gap / tail risk.** You hold *while asleep*. A ~33% overnight gap in
   QQQ takes **TQQQ to near zero** (QLD needs ~50%). This tail is real and is
   **not** in the smooth backtest — it is the reason to size TQQQ small.
4. **Taxes.** All short-term gains → run this in an **IRA/401k**, not a taxable
   account, or the tax drag erases the edge.
5. **Anomaly decay.** Overnight edges can weaken (SPY's did post-2016); leverage
   amplifies whatever's left, up or down.
6. **The gate is forward paper-tracking.** A leveraged strategy on real money
   earns *more* caution, not less. Prove it live before scaling.

---

## The research journey (how we got here, and what lost)

The original goal was a **same-day-swing / overnight** rule on the S&P 500. The
honest finding: most transparent daily rules lose to SPY once costs are in — the
edge (~7 bps/night for stock mean-reversion) is smaller than the spread. The
winner above is an *index-timing* rule, not stock-picking. The rest of this doc
is the evidence trail.

## The one constraint that shapes the design: PDT

At **$10k** (under the $25k Pattern Day Trader line), round-tripping a position
*same day* is capped at **3 day-trades per rolling 5 days**. Holding **overnight**
(buy near close, sell at/after next open) is **not** a day-trade — no PDT limit —
and conveniently that is exactly where the only real edge lives. So the account's
natural style is **enter late-day → hold overnight → exit next morning**.

## Data (no downloads needed to backtest)

`scripts/daily_panel.py` builds `data/daily.parquet` — true session open/close per
ticker — by collapsing the sibling repo's 10-year, split-adjusted, 5-minute SIP
bar cache (721 point-in-time S&P members). That open/close split is all the
overnight and same-day rules need. SPY benchmark comes from the sibling's
`market/SPY_daily.parquet`.

```bash
python scripts/daily_panel.py      # build the daily panel (~75s, one-time)
python scripts/backtest.py         # test the whole rule family vs baselines
python scripts/backtest.py --cost-bps 0     # gross (raw anomaly)
python scripts/backtest.py --k 5 --cost-bps 2
```

## Rules tested (all transparent, no ML, no lookahead)

| family | rule | enter → exit | PDT? |
|---|---|---|---|
| overnight | `overnight_all` buy every liquid name | close → next open | no |
| overnight | `mr_overnight` buy K most-oversold (RSI2) | close → next open | no |
| overnight | `mom_overnight` buy K strongest 5-day movers | close → next open | no |
| overnight | `random_overnight` **dartboard** | close → next open | no |
| one-day | `mr_1day` buy K oversold, hold a full day | close → next close | no |
| same-day | `gap_fade` buy biggest gap-downs | open → close | **yes** |
| same-day | `gap_mom` buy biggest gap-ups | open → close | **yes** |

## Results (2016-07 → 2026-07, K=10, $vol > $20M, in-sample)

**Gross (cost = 0) — where the raw edge is:**

| strategy | CAGR | Sharpe | MaxDD | verdict |
|---|---|---|---|---|
| `mr_overnight` | **+18.8%** | **1.09** | −40.7% | real edge, beats dartboard + SPY gross |
| `gap_fade` | +23.3% | 0.82 | −42.6% | edge but high-variance |
| `mr_1day` | +21.5% | 0.82 | −56.9% | edge, deep drawdown |
| `mom_overnight` | +16.3% | 0.83 | −49.2% | ≈ SPY |
| `overnight_all` | +10.3% | 0.86 | −31.7% | ≈ dartboard (weak) |
| `random_overnight` (dartboard) | +8.2% | 0.66 | −31.7% | — |
| **SPY buy & hold** | +13.5% | 0.80 | −34.2% | the bar to beat |
| `gap_mom` (chase gap-ups) | −29.7% | −1.07 | −97.6% | **reliably loses** |

**Net at 5 bps/side (the default realistic cost): every daily-rebalance rule goes
negative and loses to SPY.** The cost of trading the whole basket every day
(~10 bps round trip × 252 ≈ 25%/yr) is larger than the anomaly.

**Best realistic case** (`mr_overnight`, K=5, RSI2<5, 2 bps/side ≈ very liquid
names + patient limit orders): ~+9% CAGR, Sharpe ~0.57 — positive, clears the
dartboard, but still under SPY buy-and-hold.

## The one strategy that DID beat SPY: leveraged overnight-QQQ + trend filter

Hold **QQQ overnight** (buy near close, sell next open) **only when QQQ > its
200-day SMA** (cash otherwise). `scripts/spy_overnight.py` (SPY) and the QQQ
variant. Net of costs (0.5bp/side, $0 commission), 2016-2026:

| Strategy | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| QQQ o/n+trend 1.0× | +11.1% | 1.12 | −19.3% |
| QQQ o/n+trend 1.3× | +13.0% | 1.02 | −24.6% |
| QQQ o/n+trend 1.5× | **+14.2%** | **0.97** | −28.0% |
| SPY buy & hold | +13.5% | 0.80 | −34.2% |

At ~1.3-1.5× it beats SPY on return, Sharpe, AND drawdown, and it held up in BOTH
sample halves (Sharpe 1.21 → 1.02). The overnight-*SPY* version decayed (0.66 in
the 2nd half); QQQ did not. It works because it's a single penny-spread ETF (≈0
cost, unlike a 20-name stock basket), and the trend filter cuts the bear markets
where overnight returns turn toxic.

### Validated on 27 years incl. dot-com bust + 2008 (yfinance daily, net of cost)

| Strategy | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| QQQ o/n+trend **1.0×** (no margin, Schwab-able) | +9.0% | **0.99** | −24.8% |
| QQQ o/n+trend 1.3× | +10.3% | 0.89 | −32.0% |
| SPY buy & hold | +8.7% | 0.53 | −55.2% |
| QQQ buy & hold | +10.8% | 0.52 | −83.0% |

The **1× version beats SPY on return, Sharpe, AND drawdown with no leverage.**
Crash behavior (strat 1.3× vs SPY b&h): dot-com 2000-02 **+2.1%/yr** vs −14.6%;
GFC 2008-09 **+3.2%/yr** vs −10.6%. The trend filter parks in cash before crashes;
worst strategy year in 27 = −8% vs SPY's −37% (2008). It survived a true
out-of-sample stress test (found on 2016-26, confirmed on 1999-2015).
Data: `data/{QQQ,SPY}_daily_yf.csv`.

**Why it's credible:** stacks two documented anomalies (overnight/night effect +
200d trend-following), not a data-mined fluke; cleanly executable via
market-on-close + market-on-open auction orders (exact backtest prices).

**Remaining caveats:** (1) overnight anomalies can decay — SPY's weakened post-2016
(QQQ's held). (2) All short-term-gains taxes → run in an IRA, not a taxable
account. (3) Leverage adds overnight gap risk and needs cheap margin (IBKR ~5.5%,
NOT Schwab's ~12%); 1× has neither issue. (4) Forward paper-tracking is the only
uncontaminated test.

## Verdict on the STOCK rules (not the deployed strategy)

This is the verdict on the *stock-picking* family above — it explains why we
pivoted to the QQQ index-timing rule at the top of this doc.

1. **Short-term mean-reversion, held overnight** is the only *stock* rule with a
   real, dartboard-beating edge (buy the most oversold liquid S&P names at the
   close, sell at the next open). Gross Sharpe ~1.1.
2. Its edge is **~7 bps/night** — smaller than a retail round-trip cost unless
   execution is excellent. Net, it does not beat buying and holding SPY.
3. Institutional reality: the mean-reversion edge is real but is harvested by
   desks paying ~0 in costs; retail costs eat it. No simple *stock* if/else rule
   here consistently beats SPY net of costs — which is why the **deployed
   strategy is the single-ETF overnight-QQQ + trend rule at the top**, whose cost
   is ≈0 and which cleared SPY over 27 years.
4. **Don't chase intraday momentum/gap-ups** — that is the one robust way to lose.

### Where it could still be worth pursuing
- The `mr_overnight` signal is genuinely predictive → the lever is **execution
  cost** (limit-on-close / MOO fills), not more indicators.
- It is overnight-only and lightly correlated to the market → possibly additive
  as an **overlay on top of** SPY buy-and-hold rather than a replacement.
- Everything above is **in-sample across the decade**. A real out-of-sample split
  and a market-regime filter (it bled in 2018/2022) are the next honest tests
  before any paper trading.

## Execution (not yet wired)

Reuse `ml-stock-forward-return/scripts/{check_ibkr_conn,execute_picks}.py` —
`ib_async`, WSL→Windows Gateway, staged `print`/`whatif`/`live` modes, circuit
breakers. IBKR account `U27177562` (open, to be funded ~$10k). **Paper
(port 4002) until a rule survives out-of-sample + forward paper tracking.**

Note: for the leveraged-ETF versions (QLD/TQQQ) you do **not** need an IBKR
margin account — the leverage is inside the ETF. QQQ/QLD run commission-free at
Schwab; you only need IBKR if you later want programmatic MOC/MOO execution.

---

*Built in Claude Code session `63f6fb6f-1d90-45b6-b863-6a666055adb2`.*
