# Real option-quote logging (log-only)

Purpose: measure the real bid/ask half-spread on the exact NIFTY option legs the weekly strategy
would trade, and compare it with the backtest's own per-unit slippage model. The profitability
verdict depends on whether the real half-spread sits above or below the model. This is
data collection only. **No orders, no trades, no credentials.**

Files:

| File | Role |
|------|------|
| `scripts/log_option_quotes.py` | Fetches one snapshot, builds the legs, appends rows to the log |
| `scripts/summarize_quote_log.py` | Reads the log, reports half-spread vs model per role and moneyness |
| `paper_trading/tracker/QUOTE_LOG.csv` | Append-only log. Header only until the first run |
| `tests/test_log_option_quotes.py` | Offline tests (fixture `tests/fixtures/nse_option_chain_sample.json`) |

## How to run

From the repo root, with the project venv:

```bash
# one snapshot, NSE source, appends only inside 11:00-13:00 IST on trading days
.venv/bin/python scripts/log_option_quotes.py

# dry run (fetch and print, write nothing)
.venv/bin/python scripts/log_option_quotes.py --dry-run

# fallback source (no bid/ask; LTP, OI, volume only). Needs --vix because Groww has no VIX
.venv/bin/python scripts/log_option_quotes.py --source groww --vix 14.5

# offline replay of a saved payload (tests, or re-running a captured response)
.venv/bin/python scripts/log_option_quotes.py --from-json path/to/capture.json --log /tmp/x.csv --force

# summary of everything logged so far
.venv/bin/python scripts/summarize_quote_log.py
```

Exit codes: `0` rows appended; `2` source unavailable (blocked, HTTP error, bad JSON) or no VIX /
spot / strikes in the response; `3` nothing written (market closed, outside the window, or the
snapshot timestamp is already in the log).

### When to run

- Window: 11:00-13:00 IST, Monday to Friday, NSE trading days. The script enforces this and
  refuses to write outside it unless `--force` is given. `--force` rows are marked
  `in_window=0, forced=1` so they can be excluded.
- Cadence: every 10 minutes is enough. The NSE chain is a snapshot; running more often mostly
  duplicates timestamps, which the script skips.
- Each run makes at most 4 HTTP requests (NSE homepage for cookies, option-chain-v3 for the window
  expiry, option-chain-v3 for the next expiry, allIndices), with about 1 s between them. Do not put
  it in a tight loop.

### Cron (owner's machine)

The machine runs in UTC (`/etc/timezone` = `Etc/UTC`). IST is UTC+05:30, so the 11:00-13:00 IST
window is 05:30-07:30 UTC. This entry uses UTC and needs no `CRON_TZ`. Ticks outside the window
fail the gate and exit 3 before any HTTP request:

```cron
*/10 5-7 * * 1-5  cd /home/shivamguptanit/github/nifty-options-backtester && .venv/bin/python scripts/log_option_quotes.py >> logs/quote_logger.log 2>&1
```

If the cron implementation supports `CRON_TZ` (check it first), the IST form is equivalent:
`CRON_TZ=Asia/Kolkata` then `*/10 11-13 * * 1-5`.

Check that the daemon runs (`pgrep -a cron`). The `cron` package is not always installed; on
2026-10-24 `crontab` was missing and the package was not installed.

The script itself skips NSE holidays (`market_day_gate`), so no holiday list is needed in cron.
Create `logs/` first (`mkdir -p logs`); it is gitignored.

Daily summary (optional):

```cron
CRON_TZ=Asia/Kolkata
35 13 * * 1-5  cd /home/shivamguptanit/github/nifty-options-backtester && .venv/bin/python scripts/summarize_quote_log.py >> logs/quote_summary.log 2>&1
```

## What is recorded

One row per leg per expiry per snapshot. Two expiries per snapshot:

- `expiry_role=window`: the weekly expiry with DTE in `[WeeklyBacktestConfig.min_dte_entry,
  max_dte_entry]` = [3, 8], chosen with the repo's `get_weekly_expiry_in_range`. Today, that is
  normally the Tuesday expiry, following the 2025-09-01 Tuesday cutover.
  `dte_in_window=1` on these rows.
- `expiry_role=next`: the expiry after that one, for comparison.

Structures per expiry:

- `IC`: `WeeklyIronCondor.generate_legs` (short and long CE, short and long PE).
- `PCS`: `WeeklyPutCreditSpread.generate_legs` (short and long PE).
- `ATM_STRADDLE`: CE and PE at `round(spot/50)*50`.
- `neighbour` rows: the IC and PCS legs' strikes at -2, -1, +1, +2 strike steps (50 pts) on the
  same option type. These are not traded; they show how the spread changes away from the leg.

`rule_selected=1` marks the structure that `select_weekly_strategy_name(vix, ret_5d)` would pick.
Without `--ret-5d` the rule falls back to PCS, as `run_signal_combined` does. Both structures are
logged either way.

Columns (`QUOTE_LOG.csv` header is authoritative):

| Column | Source / meaning |
|--------|------------------|
| `timestamp_ist` | Exchange timestamp of the snapshot (NSE `records.timestamp`). Also the dedupe key with `source`. Falls back to fetch time |
| `fetched_at_ist` | Wall clock when the script ran |
| `source` | `nse` or `groww`. A `--from-json` replay keeps the source of the payload it contains |
| `in_window`, `forced` | 1 if inside 11:00-13:00 IST on a trading day; 1 if the gate was bypassed |
| `spot` | NSE `records.underlyingValue` (fallback: allIndices NIFTY 50 `last`) |
| `vix` | NSE allIndices `INDIA VIX` `last`, or `--vix` |
| `ret_5d` | `--ret-5d` if passed. Otherwise, for NSE, spot / allIndices `oneWeekAgoVal` - 1: the close one week back, which is five trading days back when no holiday falls between (spot is intraday). Label only: it sets `rule_selected`, not the quotes |
| `expiry`, `expiry_role`, `dte`, `dte_in_window` | Expiry `DD-Mon-YYYY` as NSE lists it; calendar DTE |
| `structure`, `rule_selected`, `role`, `offset_strikes` | Leg construction (see above). `role` is `short`, `long`, `atm` or `neighbour` |
| `strike`, `option_type`, `moneyness`, `moneyness_bucket`, `vix_bucket` | Strike and option type; strike/spot; buckets `lt1pct`, `1to2pct`, `2to4pct`, `gt4pct`; `vix_lt13` / `vix_ge13` |
| `bid`, `ask` | NSE option-chain-v3 `buyPrice1` (best bid), `sellPrice1` (best ask). Legacy `bidprice`/`askPrice` also accepted. Best price only |
| `bid_qty`, `ask_qty` | NSE `buyQuantity1`, `sellQuantity1`: quantity at the best price only (blank if the field is absent) |
| `last`, `volume`, `oi` | NSE `lastPrice`, `totalTradedVolume`, `openInterest` |
| `mid`, `spread`, `half_spread` | (ask+bid)/2, ask-bid, spread/2. Blank unless `quote_status=ok` |
| `quote_status` | `ok`, `one_sided` (bid or ask is 0), `no_quote`, `crossed` (ask < bid), `not_listed` (expiry not in the chain), `strike_not_listed` |
| `model_slip_unit` | `ChainBacktest._slip_unit(vix, strike, spot)` with the chain engine's own function and default multiplier 1.0 |
| `half_spread_to_model` | `half_spread / model_slip_unit`: the implied slippage multiplier for this leg |
| `model_multiplier` | The multiplier used for `model_slip_unit` (1.0) |

## How to read the result

`summarize_quote_log.py` prints:

1. Counts by `quote_status`, snapshots, and distinct dates.
2. `half_spread_to_model` (n, median, mean, p90) by role, by moneyness bucket, and for structure
   legs by VIX bucket. Only `quote_status=ok` rows are used.
3. The headline: the median of `half_spread_to_model` over structure legs (short, long, atm). This
   is the implied slippage multiplier.
4. Where that multiplier sits against the break-even reference points in the owner's brief:
   baseline 0.47x, VIX >= 13 subset 0.80x, hold-to-expiry 0.90x. Below a threshold means the real
   cost is tolerable for that structure on this model; above means it is not.
5. Warnings when there are fewer than 20 snapshots or fewer than 5 distinct dates.

Read the headline together with the `neighbour` and moneyness rows. Wider strikes have wider
spreads, so the multiplier depends on which strikes the strategy actually sells.

Do not decide from a few days. Wait for enough snapshots across dates and VIX regimes before
treating the median as stable, and check the p90 as well. The brief's break-even values are
reference numbers from the owner's earlier analysis. This script does not re-derive them.

## Limitations

- **Live, not EOD.** The NSE option chain is a point-in-time snapshot. It is not the archive's end
  of day settle. Spreads are best measured in the window, not after close.
- **Best price only.** `bidprice`, `askPrice` and their quantities describe the top of book only.
  Depth beyond the best level is not recorded, so the cost of filling a full lot through a
  thin book is not captured.
- **1 lot assumed.** Quantities are not used for sizing. The quote is the top-of-book price for
  any size, and `bid_qty`/`ask_qty` are informational.
- **Field names are checked against one closing book, not a window snapshot.** On 2026-10-24 the
  option-chain-v3 response for 2026-10-23 (after the close) had `buyPrice1 < sellPrice1` on the
  ATM strikes. The bid/ask mapping rests on those names. On the first in-window run, check that
  `bid < ask` on most two-sided rows and that `bid_qty` and `ask_qty` are populated. If they are
  blank, `parse_nse_chain` needs fixing.
- **NSE moves endpoints.** `/api/option-chain-indices` returned HTTP 404 on 2026-10-24, so the
  script uses `/api/option-chain-v3`, one request per expiry. The NSE JSON needs
  `Accept-Encoding: gzip, deflate`. `br` is undecodable without the `brotli` package, and the
  script's session overrides it.
- **NSE may block the IP.** The script makes one attempt per endpoint and reports `HTTP 403`,
  `HTTP 404`, a non-JSON body, or an empty chain as `source_unavailable`. It does not loop. `--source groww` returns LTP, OI and volume
  with no bid or ask, so it cannot measure spreads. It is a fallback for spot and OI only.
- **Model slippage is the chain engine's entry-side value at multiplier 1.0.** The
  `CombinedBacktestEngine` applies 0.75x on entry. The chain backtest uses 1.0x. The
  `model_slip_unit` column matches the chain backtest, so the comparison is apples to apples
  with it, not with the monthly engine.
- **Weekday mix.** Every weekday in the window is logged. The strategy trades on Mon and Tue
  only in `run_signal_combined`. Filter by the `timestamp_ist` date if the Mon/Tue subset is needed.
- **Strike grid.** Only strikes on the 50-point lattice are considered. Neighbour rows that fall
  outside the chain are logged as `strike_not_listed`.
- **Half-spread is not the full execution cost.** It excludes market impact, queue position and
  the behaviour of a resting order. Use it as the minimum cost to cross from mid to touch.

## Scheduler on this machine (systemd user timer, not cron)

`cron` is not installed here, so collection runs from a systemd user timer (UTC, no `CRON_TZ` needed):
`~/.config/systemd/user/nifty-quote-logger.{service,timer}`, `OnCalendar=Mon..Fri *-*-* 05,06,07:00/10:00 UTC`
(the script itself only logs inside 11:00-13:00 IST and exits 3 otherwise; the unit treats exit 3 as success).
Linger is enabled, so it runs without a login session. Output: `logs/quote_logger.log`.
Check: `systemctl --user list-timers nifty-quote-logger.timer`, `tail logs/quote_logger.log`,
`wc -l paper_trading/tracker/QUOTE_LOG.csv` (about 61 rows per snapshot).
