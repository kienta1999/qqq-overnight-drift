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

Three ways to run it: the **daily routine** below (a GitHub Action posts the
signal, you place two orders by hand), **signal only** (run the script
yourself), or **automated via IBKR** (the script places the orders).

### Daily routine — the one to actually use

**Where the decision lives:**

| Link | What it's for |
|---|---|
| [**Today's decision** — issue #1](https://github.com/kienta1999/qqq-overnight-drift/issues/1) | The signal. Same URL every day; the workflow overwrites this one issue. Bookmark it. |
| [**Actions**](https://github.com/kienta1999/qqq-overnight-drift/actions) | Re-run it by hand if the post is stale. |

A GitHub Action posts to issue #1 at 09:07 / 14:07 / 15:07 ET on weekdays.
Nothing notifies you — editing an issue body sends no email — so you go and look.

**Check the date first.** On the `decision for YYYY-MM-DD` line:

- **today's date** → final, act on it.
- **yesterday's date** → stale, or it's the 09:07 morning preview. Go to
  [Actions](https://github.com/kienta1999/qqq-overnight-drift/actions) →
  *Daily signal* → **Run workflow**, wait ~40s, refresh the issue.

Yesterday's post is the wrong trade about once every three weeks: over
2010–2026 the action differs from the prior day on 5.7% of days (2.4% trend
flips, 4.4% instrument changes). Never reuse it.

**The schedule.** ET is the market; PT is where the operator is. Both zones
observe DST together, so the 3-hour offset never shifts.

| PT | ET | Do |
|---|---|---|
| 12:07 PM | 3:07 PM | fresh signal lands on issue #1 |
| by **12:45 PM** | **3:45 PM** | place the **MOC buy** — the exchange cutoff is 3:50 PM ET, hard |
| 1:00 PM | 4:00 PM | the MOC fills, at the official closing price |
| ~1:05 PM | ~4:05 PM | confirm the fill, then place the **MOO sell** |
| 6:30 AM next day | 9:30 AM | the sell fills in the opening auction — nothing to do |

**The two orders**, in the IBKR Client Portal order ticket.

*Buy — at 12:45 PT, once the issue says BUY:*

| Field | Value |
|---|---|
| Symbol | `QQQ` / `QLD` / `TQQQ`, whichever the issue names |
| Side | **Buy** |
| Quantity | the share count from the issue |
| Order Type | **Market on Close** |
| Time-in-Force | `Day` — the only one MOC accepts |
| Price Management Algo | leave **unchecked** |

*Sell — right after the buy fills:*

| Field | Value |
|---|---|
| Symbol | the same ETF |
| Side | **Sell** |
| Quantity | the same share count |
| Order Type | **Market** |
| Time-in-Force | **At the Opening** |

`Market` + `At the Opening` **is** the market-on-open order — IBKR has no "MOO"
entry in the order-type list. Leaving the TIF on `Day` gives a plain market
order that fires into continuous trading at 9:30 instead of the opening
auction, which is not the price the backtest assumes.

**You cannot place both at 12:45.** You are flat until the MOC fills, so a sell
order at that point is a short sale and gets rejected. Two sittings, five
minutes apart. The sell is the leg that must not be forgotten — miss it and you
hold 2×/3× leverage through a full trading day, the exact exposure this
strategy exists to avoid. Set an alarm.

**If the issue says CASH ⚪, place nothing.** No buy, no sell. Sitting out is
what produces the drawdown profile.

**The account must be margin-type.** US stocks settle T+1, so a daily round
trip is always spending unsettled proceeds. A Reg-T **margin** account handles
that fine; a **cash** account blocks the next buy until the prior sale settles
— that halves the strategy and accumulates good-faith violations. You never
borrow a dollar (the leverage is inside the ETF), but the account type has to
be margin. Check *Settings → Account Configuration*. Overnight holds are never
PDT day-trades, so pattern-day-trader rules don't apply either way.

**Costs.** IBKR Pro Fixed is $0.005/share, $1.00 minimum per order — about
$2.60 per round trip at $20k, ~$46/month, ~$555/yr (2.8% of capital, since
~214 nights/yr are in-market). That is a real ~2.8pp haircut to CAGR and it
does *not* shrink as the account grows, because per-share pricing scales with
the low share price of TQQQ. IBKR Lite or any zero-commission broker removes it
entirely — the order ticket shows the commission before you submit, so check
what yours says.

### Signal only

Needs free Alpaca market-data keys (no funding, paper account is fine) in `.env`:

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

Once per trading day, after ~3:40pm ET:

```bash
uv run python scripts/today.py                     # auto-pick instrument, $10k
uv run python scripts/today.py --capital 5000      # smaller account
uv run python scripts/today.py --instrument QLD    # override the vol picker
```

It prints **BUY 🟢** with an exact share count, or **CASH ⚪** (QQQ below its
200-day average — place nothing). Example:

```
  QQQ close     : 716.43
  200d average : 655.17   (+9.3% vs price)
  trend           : ABOVE ✅
  20d realized vol: 18.4%   -> QLD (mid vol)
  DECISION: BUY QLD  🟢
    $10,000 capital -> BUY 110 QLD @ ~90.17  (~$9,919)
```

### Automated via IBKR

Account **U27177562**. No borrowing — the leverage is inside the ETF — but the
account type must be margin, not cash (see the T+1 settlement note above).
Sizing is all-in: `shares = floor(NetLiquidation / price)`.

**First, check the plumbing** (read-only, places nothing):

```bash
uv run python scripts/ibkr.py --port 4002     # 4002 = Gateway paper
uv run python scripts/ibkr.py --port 4001     # 4001 = LIVE
```

**The two daily commands.** `--leg` defaults to `auto`: flat → buy leg, holding
→ sell leg, so the same command does the right thing at both ends of the day.

```bash
# 1. Afternoon, BEFORE 3:50pm ET — market-on-close BUY (fills at 16:00)
uv run python scripts/execute.py --port 4001 --mode live

# 2. That evening (or before 9:28am ET) — market-on-open SELL (fills at 09:30)
uv run python scripts/execute.py --port 4001 --leg sell --mode live
```

**Always dry-run first.** Drop `--mode live` for a plan that sends nothing:

```bash
uv run python scripts/execute.py --port 4001                    # print: plan only
uv run python scripts/execute.py --port 4001 --mode whatif      # IBKR cost preview
uv run python scripts/execute.py --port 4001 --capital 2000     # cap the money deployed
```

Safety rails, all on by default:

| rail | what it does |
|---|---|
| `--port` required | no default, so live (4001) vs paper (4002) is always deliberate |
| staged modes | `print` → `whatif` → `live`; the first two send nothing |
| typed confirmation | a live `U…` account makes you type the account number |
| position-aware legs | can't double-buy while holding, can't sell while flat |
| trend gate | below the 200-day SMA the buy leg is a no-op |
| `--max-notional` | aborts if buy notional exceeds equity × 1.02 |
| `--buffer-bps 50` | sizes against a padded price so the close can't overdraw into margin |
| order cancel | live mode clears working orders before placing |
| clock warnings | flags a buy past the 15:50 MOC cutoff, or a sell after the open |

Re-running is safe: the script reads your actual IBKR position, so a repeat run
reconciles rather than duplicating.

**Order types:** the BUY is a true `MOC`, the SELL is `MKT` with `tif=OPG`
(market-on-open). Both are auction orders, so they fill at the official close and
open — exactly the prices the backtest assumes. No discretion, and you never have
to be awake for the open.

**If you'd rather use Schwab:** MOC is supported (before 3:45pm ET), but
market-on-open is **not confirmed** — check your order ticket. QQQ/QLD/TQQQ are
commission-free there. Overnight holds are not PDT day-trades either way.

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
scripts/ibkr.py            IB Gateway connection + account snapshot
scripts/execute.py         places the MOC buy / MOO sell on IBKR
scripts/test_strategy.py   self-check: no lookahead, cash off-trend, real sleeves
scripts/gold.py            side study: the same rule on GLD/UGL (see Tried and rejected)
scripts/day_gold_night_qqq.py  side study: filling the idle sessions with gold
data/*_daily_yf.csv        QQQ / QLD / TQQQ / GLD / UGL / IAU / GDX daily OHLC (yfinance)
```

Refresh the data with:

```bash
uv run --with yfinance python -c "
import yfinance as yf, pandas as pd
for s in ('QQQ','QLD','TQQQ','GLD','UGL','IAU','GDX'):
    d = yf.download(s, start='1999-01-01', auto_adjust=True, progress=False, actions=False)
    d.columns = d.columns.get_level_values(0)
    d[['Open','High','Low','Close','Volume']].dropna().to_csv(f'data/{s}_daily_yf.csv')
"

```


## Tried and rejected

**Shorting QQQ during the day.** The mirror trade does not exist. The day
session is only negative before 2003; since 2010 it drifts **+2 to +3.4 bp/day**,
so every short variant tested (unconditional, only-when-flat, only-when-trending,
rvol > 28%, below the 50d, and the combinations) loses money out of sample —
2010-2026 Sharpe between −0.03 and −0.67, at every SMA window from 20 to 200.
The overnight edge is that nights are *more* positive, not that days are negative.
*Trap it hid:* an intraday trade opens at today's **open**, so its filter can only
use data through yesterday's close. Unlagged, `close < 50d SMA` peeks at the close
it trades into and reports Sharpe 1.9 on a rule that actually loses.
`test_intraday_filters_must_be_lagged_a_day` pins this.

**Gold instead of QQQ** (`uv run python scripts/gold.py`). The gap effect is
*purer* in gold than in QQQ — GLD's entire return is overnight (+10.7% CAGR)
and its day session is flat (−0.1%), which makes sense: gold futures trade
nearly 24h, so GLD's gap absorbs the whole Asia/London session. IAU shows the
same, so it is a market and not one fund's NAV print. But it does not pay as
well: the rule on GLD earns **+5.0% CAGR / Sharpe 0.53** since 2010 (UGL 2x:
+9.2%, Sharpe 0.53) against **+29.5% / 1.26** for the deployed QQQ book. The
200d filter does not earn its keep on gold either — it halves CAGR to halve the
drawdown, Sharpe flat at 0.53-0.72 across every window from 100d to 250d.
Where gold *is* worth something is as a **diversifier**: the two nightly return
streams correlate **+0.04**, and 75/25 QQQ/gold lifts the 1x book from Sharpe
1.09 / −19.5% MaxDD to **1.19 / −14.2%** — better risk, less money.

**Filling the idle sessions with gold** (`uv run python scripts/day_gold_night_qqq.py`).
The book is idle all day, and idle entirely on ~26% of nights. Buying gold in
those pockets and swapping back into the QQQ sleeve at the close does not work:

- **The day leg loses.** GLD's day session runs +0.3 to +0.9 bp/day gross across
  every era and needs 1.0 bp to clear a round trip — a coin flip the spread eats.
  Stacked on the book it takes Sharpe **1.26 → 1.06** (2x UGL: → 0.78). Filtering
  it by gold's own 200d or by QQQ cash days does not save it.
- **The night leg pays a little, and costs exactly what it pays.** Holding gold
  on QQQ cash nights adds ~+1.6% CAGR (29.5% → 31.1% since 2010) for +0.03 Sharpe
  — but it deepens max drawdown in *every* era (−16.0→−22.5, −18.6→−19.5,
  −27.5→−32.0, −24.7→−28.3). It is more risk-taking time, not better risk.
- **There is no crisis premium.** The story was "cash nights are bear markets,
  exactly when gold is bid." False: gold returns **+4.41 bp** on an average night
  and **+3.96 bp** on a QQQ cash night. Cash nights are slightly *worse* gold
  nights, and the leg wins only 51.8% of them.

The lesson generalises: gold diversified the book (Sharpe 1.09 → 1.19) only when
capital was **split and held simultaneously**. Filling idle time *sequentially*
diversifies nothing — it just buys more hours of exposure.

## Gold: what is actually interesting

Nothing here is deployed — `execute.py` still runs QQQ only. Run
`uv run python scripts/gold.py` for all of it.

**1. Gold miners have the widest overnight/intraday split of anything tested.**
GDX overnight is **+30.5% CAGR, Sharpe 1.25** since 2006; its day session
compounds to **−19.0%/yr**; buy & hold is +5.6%. The mechanism is structural —
GDX is an *equity that only trades US hours* sitting on an underlying that
trades all night, so gold's overnight move can only reach the miners through
the gap. It is positive in all four eras (+66.1% / +7.3% / +32.3% / +16.4%),
but clearly decaying.

**2. It is not merely levered gold.** GDX's night is a 1.56x gold-gap position
(corr +0.87). Strip that beta out and the residual still pays **+12.4% CAGR at
Sharpe 1.09** — so there is miner-specific overnight return on top of the gold
exposure, and you get the 1.6x without a leveraged ETF's decay.

**3. The 200d filter is actively harmful on GDX** — the reverse of QQQ. It cuts
the overnight book from +30.5% to **+8.5%** (Sharpe 1.25 → 0.58). Gold's gap
does not care which side of a moving average the miners closed on; filtering
just removes paid nights. Do not port the QQQ rule over unexamined.

**4. Shorting GDX intraday is dead, and died recently.** +31.4% / +29.8% CAGR
in 2006-2011 and 2012-2015, then **−7.5% and −11.5%** in 2016-2020 and 2021-2026
as the day leg went from −14 bp/day to +2.4 bp/day. Same decay as the QQQ short,
and that is before borrow fees on a 33%-vol short.

**5. The only gold idea that improved the deployed book** — held *simultaneously*
with split capital, 2010+, correlation **+0.04**:

| Split | CAGR | Sharpe | MaxDD |
|---|---:|---:|---:|
| 100% QQQ book (deployed) | +29.1% | 1.25 | −33.5% |
| 85 / 15 QQQ / UGL 2x | +26.6% | 1.31 | −24.5% |
| **75 / 25 QQQ / UGL 2x** | +24.8% | **1.34** | −24.2% |
| 75 / 25 QQQ / GLD | +23.3% | 1.31 | −22.8% |
| 75 / 25 QQQ / GDX | +23.5% | 1.28 | −24.4% |

That is a real trade: ~9 points of max drawdown for ~4 points of CAGR. It is a
risk preference, not free money — take it only if −33.5% is the number that
would make you abandon the strategy.
