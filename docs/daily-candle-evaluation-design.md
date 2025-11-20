# Daily Candle Evaluation Design (KIS + Hybrid Strategy)

## 1. Background and Problem

The project consumes daily OHLCV candles from KIS (and PyKRX) and runs swing‑trading logic on them (buy/sell, hybrid strategy, reports).

Two practical issues arise:

- KIS daily price APIs can return a **last candle that represents “today” while the session is still in progress** (intraday snapshot).
- The current implementation implicitly assumes **“last element in `candles` == fully completed daily bar”** and always evaluates on `candles[-1]`.

For swing trading based on end‑of‑day signals, we want:

- To **only evaluate on completed daily candles**, i.e., *yesterday’s* close while the market is open.
- To avoid mixing incomplete intraday candles into EMA/RSI/ATR conditions and hybrid pattern detection.

This document specifies how we improve that behavior.


## 2. KIS Daily Candle Behavior (Summary)

From KIS examples (via MCP) and observed data:

- **Domestic stocks**
  - APIs:  
    - `inquire_daily_price` (`/uapi/domestic-stock/v1/quotations/inquire-daily-price`)  
    - `inquire_daily_itemchartprice` (`/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, `FID_PERIOD_DIV_CODE = D`).
  - Documentation describes *daily / weekly / monthly OHLC series*, but does **not** guarantee that “today’s bar is only present after the close”.
  - In practice, domestic daily APIs often behave like EOD feeds, but we cannot rely on that as a hard guarantee.

- **Overseas stocks**
  - API: `dailyprice` (`/uapi/overseas-price/v1/quotations/dailyprice`).
  - Empirically (e.g., TMO NAS/NYSE data), KIS returns a **today bar during the ongoing US regular session**:
    - date == today
    - very small volume compared to recent days
    - high/low/close changing intraday
  - That bar is **not a completed daily candle** in the EOD sense.

- **PyKRX**
  - PyKRX is an EOD source for KR; returned candles are **completed daily bars**.

Conclusion:

- We **cannot** assume “`candles[-1]` is always a fully closed bar”.
- We **must** decide in our own logic whether we use `candles[-1]` or `candles[-2]` (or earlier), depending on:
  - Exchange session state (intraday vs after close)
  - Volume profile of the last bar
  - Data source (KIS vs PyKRX).


## 3. Design Goals

1. **Use completed daily candles only**
   - During regular trading hours, evaluate strategies using the **previous day’s** close.
   - After the market close (and before the next open), use the **latest completed bar** (the last element).

2. **Isolate intraday artifacts**
   - Avoid treating thin, partial “today” bars as full EOD candles in EMA/RSI/ATR and hybrid pattern detection.

3. **Source‑aware behavior**
   - Treat PyKRX (EOD) as always “safe to use last bar”.
   - Treat KIS daily APIs as potentially intraday and apply additional checks.

4. **Minimal, local changes**
   - Do not redesign indicators (`indicators.py`).
   - Implement the behavior in a small reusable helper and adjust only the decision‑level functions.

5. **Testable and explicit**
   - Provide clear unit and integration test cases to validate behavior across KR/US, KIS/PyKRX, intraday/after‑close scenarios.


## 4. Core Concept: Evaluation Index + Option B Slicing

### 4.1 Evaluation Index (`idx_eval`)

We introduce the concept of an **evaluation index**:

- `idx_eval` is the index of the candle that represents the **effective “latest completed bar”** for strategy evaluation.
- Example:
  - During US intraday on 2025‑11‑19:
    - `candles[-1]` is today (2025‑11‑19) and still changing.
    - `idx_eval` should be `len(candles) - 2` (2025‑11‑18).
  - After US close:
    - `candles[-1]` is the completed bar for 2025‑11‑19.
    - `idx_eval` should be `len(candles) - 1`.

### 4.2 Option B: Slice Data to `idx_eval`

We follow the “Option B” pattern:

- Instead of modifying internal pattern functions to accept an explicit index, we:
  - Compute `idx_eval` once.
  - Slice all sequences to **include only data up to `idx_eval`**:
    - `candles_eval = candles[: idx_eval + 1]`
    - `closes_eval = closes[: idx_eval + 1]`
    - `sma_eval = sma_trend[: idx_eval + 1]`, etc.
  - Pass only `*_eval` sequences into pattern/sell functions.
- Inside pattern/sell functions, existing logic remains valid:
  - `idx = len(closes) - 1`
  - `today = candles[-1]`
  - `yest = candles[-2]`
  - All of these now refer to the **chosen evaluation bar**, not necessarily the raw last array element.

This minimizes code churn and reduces the risk of off‑by‑one bugs.


## 5. Helper: `choose_eval_index`

We centralize the intraday vs EOD decision in a helper:

```python
def choose_eval_index(
    candles: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
    provider: str = "kis",
    now: datetime | None = None,
    lookback_for_volume: int = 5,
) -> int:
    ...
```

### 5.1 Inputs

- `candles`: list of OHLCV dicts, ascending by date.
- `meta`:
  - Optional per‑ticker metadata:
    - `currency`: `"KRW" | "USD" | ..."`
    - `exchange`: `"KRX" | "NAS" | "NYS" | ..."`
    - `data_source` / `provider`: `"kis" | "pykrx" | ..."` (used to skip intraday logic for EOD-only feeds)
    - potential future fields: `country`, `market`.
- `provider`:
  - `"kis"` | `"pykrx"` | other.
- `now`:
  - Optional timezone‑aware current time, for unit testing and controlled evaluation.
- `lookback_for_volume`:
  - Number of prior days to use for volume average when applying the thin‑volume heuristic.

### 5.2 Basic Rules

1. **Trivial sizes**
   - `n = len(candles)`
   - `n == 0` → return `-1` (caller must handle).
   - `n == 1` → return `0` (only one bar; use it).

2. **Source‑aware shortcut**
   - If `provider == "pykrx"`:
     - PyKRX is EOD; always use the last bar:
       - `return n - 1`.

3. **Default (KIS)**
   - Start with `idx_eval = n - 1`.
   - Then adjust based on exchange session state + volume heuristics.


## 6. Exchange Session Model

We model the regular sessions for KRX and major US exchanges.

### 6.1 Timezones

- Korean stocks:
  - Timezone: `Asia/Seoul`
- US stocks (NYSE/NASDAQ, etc.):
  - Timezone: `America/New_York`
  - Must be **DST‑aware**.

### 6.2 Session States

Per exchange, we classify the current time into a coarse state:

- **KRX (Korean stocks)**
  - Regular session: 09:00–15:30 (Seoul time)
  - States:
    - `INTRADAY`: 09:00 ≤ now < 15:30
    - `AFTER_CLOSE`: 15:30 ≤ now < next day 09:00

- **US (NYSE/NASDAQ)**
  - Regular session: 09:30–16:00 (New York time)
  - States:
    - `PRE_OPEN`: 00:00 ≤ now < 09:30
    - `INTRADAY`: 09:30 ≤ now < 16:00
    - `AFTER_CLOSE`: 16:00 ≤ now < 24:00
  - We also consult `data/holidays_us.json` (loaded via `SAB_DATA_DIR` when available) to treat known holidays as `STATE_CLOSED`, even if the local clock falls inside the usual intraday window.

For US, we also have a holiday calendar (`refresh_us_holidays` in `sab/scan.py`); if today is a US holiday, we treat the session as closed even if clock time falls into “intraday” range.


## 7. Volume‑Based Heuristic

Time alone doesn’t always distinguish between:

- “legitimate thin day” vs
- “intraday partial candle for today”.

We add a conservative volume heuristic for the last bar.

### 7.1 Computation

Given `candles` and `lookback_for_volume`:

- `last = candles[-1]`
- `prev_window = candles[-(lookback_for_volume + 1):-1]`
- `v_last = float(last.get("volume") or 0.0)`
- `avg_vol = mean(volume(c) for c in prev_window)`, if `prev_window` is non‑empty.

Define:

```python
very_thin_today = (
    avg_vol > VOL_FLOOR and
    v_last < avg_vol * THIN_RATIO
)
```

Where:

- `VOL_FLOOR`:
  - a small absolute threshold (e.g., 1,000 shares) to avoid triggering on inherently illiquid names.
- `THIN_RATIO`:
  - a fractional threshold, e.g., `0.2` (20% of recent average), configurable via settings/env if needed.

### 7.2 Usage

- For **US + KIS**:
  - If session state is `INTRADAY`, we will *generally* drop today and use yesterday (`idx_eval = n - 2`).
  - We also may apply `very_thin_today` in `PRE_OPEN` / `AFTER_CLOSE` to avoid early‑generated partial candles.

- For **KR + KIS**:
  - KRX dailies tend to be EOD, but to be robust:
    - We can drop the last bar only if:
      - session state is `INTRADAY` and
      - `very_thin_today` is true.


## 8. Final Decision Logic

Putting it together:

1. `n = len(candles)`
2. Handle trivial sizes and `provider == "pykrx"` (always `n - 1`).
3. Determine exchange/market:
   - From `meta["currency"]`, `meta["exchange"]` or a small mapping (e.g., suffix `.US` → US).
4. Compute `state = get_exchange_state(market, now)`:
   - `INTRADAY`, `PRE_OPEN`, `AFTER_CLOSE`.
   - For US: skip `INTRADAY` if `today` is a holiday.
5. Compute `very_thin_today` as described above.
6. Decide `idx_eval`:

   - **US + KIS**
     - If `state == INTRADAY`:  
       → `idx_eval = n - 2`
     - Else if `state in {PRE_OPEN, AFTER_CLOSE}` and `very_thin_today`:  
       → `idx_eval = n - 2`
     - Else:  
       → `idx_eval = n - 1`

   - **KR + KIS**
     - If `state == INTRADAY` and `very_thin_today`:  
       → `idx_eval = n - 2`
     - Else:  
       → `idx_eval = n - 1`

7. Guard for underflow:

   - If `idx_eval < 0`: set `idx_eval = 0`.

8. Return `idx_eval`.

This logic aims to:

- Use yesterday’s bar while the market is open (or when today’s bar is clearly partial).
- Use the latest bar once the session is closed and the volume looks normal.
- Always use the last bar for PyKRX/EOD feeds.


## 9. Integration Points in the Codebase

We will apply this helper and Option B slicing at all **decision‑level** functions that currently assume “last candle == evaluation candle”.

### 9.1 Buy Side

- `sab/signals/hybrid_buy.py`
  - `evaluate_ticker_hybrid`:
    - Currently:
      - uses `candles[-1]`, `candles[-2]`, `sma_trend[-1]`, `ema_short[-1]`, `rsi_vals[-1]`, etc.
    - New behavior:
      - Compute `idx_eval = choose_eval_index(...)` using KIS/PyKRX + meta.
      - Slice:
        - `candles_eval = candles[: idx_eval + 1]`
        - `closes_eval`, `sma_eval`, `ema_short_eval`, `ema_mid_eval`, `rsi_eval`.
      - Call pattern functions with `*_eval`:
        - `_detect_trend_pullback_bounce(closes_eval, sma_eval, ema_short_eval, ema_mid_eval, rsi_eval, candles_eval, settings)`
        - `_detect_swing_high_breakout(...)`
        - `_detect_rsi_oversold_reversal(...)`
      - Use `latest = candles[idx_eval]`, `prev = candles[idx_eval - 1]` when constructing the final candidate (price, pct_change, high/low, indicators).

- `sab/signals/evaluator.py`
  - `evaluate_ticker` (EMA20/50 strategy):
    - Same pattern:
      - Determine `idx_eval`.
      - Use `latest = candles[idx_eval]`, `previous = candles[idx_eval - 1]`.
      - Reference indicators by index:
        - `ema20[idx_eval]`, `ema20[idx_eval - 1]`, `rsi14[idx_eval]`, `atr14[idx_eval]`, `sma200[idx_eval]`.
      - Liquidity window: use candles up to `idx_eval` only (`candles_eval[-20:]`).

### 9.2 Sell Side

- `sab/signals/hybrid_sell.py`
  - `evaluate_sell_signals_hybrid`:
    - Use `idx_eval` and:
      - `latest = candles[idx_eval]`, `last_close = latest["close"]`.
      - EMA/SMA/RSI from index `idx_eval`.
      - Last 3 candles for “three consecutive bearish candles”:
        - `start = max(0, idx_eval - 2)`
        - `last_three = candles[start: idx_eval + 1]`.

- `sab/signals/sell_rules.py`
  - `evaluate_sell_signals`:
    - Use `idx_eval` and:
      - `latest = candles[idx_eval]`, `close_today = latest["close"]`.
      - `atr_today = atr_values[idx_eval]`.
      - EMA/SMA and RSI from `idx_eval` and `idx_eval - 1`.

These changes keep indicators intact and confine the “which day are we evaluating?” logic to a single, testable helper.

### 9.3 Reporting Alignment

- `SellEvaluation` / `HybridSellEvaluation` now carry `eval_price`, `eval_index`, and `eval_date`.
- `sab/sell.py` uses those values when building `SellReportRow`, so the “Last / P&L” numbers in the Markdown report match the bar used for the SELL/REVIEW decision.
- `reports/*.sell.md` annotate “Last close” with the evaluation date when available, making it clear whether the run happened during intraday hours or after the session close.


## 10. Edge Cases and Special Considerations

- **Early close / partial session days (e.g., US holidays)**
  - The exchange state function should consider holiday calendars and early‑close schedules where practical.
  - For now, we at least avoid treating holidays as intraday, using available US holiday data.

- **Illiquid symbols**
  - For genuinely illiquid tickers, average volume can be extremely low.
  - `VOL_FLOOR` ensures we do not overreact to tiny absolute volumes.
  - Additional safeguards (e.g., require ≥ 60–90 days of history before applying the volume heuristic) can be added later.

- **Data gaps**
  - Large gaps in dates (missing days) may indicate data issues.
  - We can optionally detect date gaps and mark those tickers as `REVIEW` instead of blindly trusting the last bar.

- **EOD vs intraday mixing (KIS vs PyKRX fallback)**
  - When KIS fails and we fall back to PyKRX, the last bar meaning changes.
  - We should tag meta with `source = "pykrx"` and let `choose_eval_index` treat it as pure EOD.

- **Timezones & DST**
  - For US markets, we must use timezone‑aware `datetime` with DST rules for America/New_York.
  - All session calculations should be done in the relevant exchange timezone to avoid off‑by‑one‑hour errors at DST boundaries.


## 11. Testing Strategy

We validate the design at two levels: the helper and the evaluation functions.

### 11.1 Unit Tests: `choose_eval_index`

Target: a small, pure function (or module) that can be tested without hitting APIs.

Key cases:

1. **US, intraday, KIS daily**
   - Setup:
     - `provider = "kis"`, `meta.exchange = "NAS"`, `currency = "USD"`.
     - `candles` length ≥ 7, last bar date = today.
     - Last bar volume ≪ average of previous 5 bars.
     - `now` = 11:00 America/New_York (`INTRADAY`).
   - Expect:
     - `idx_eval == len(candles) - 2`.

2. **US, after close, normal volume**
   - `now` = 17:00 America/New_York (`AFTER_CLOSE`).
   - Last bar volume ≈ recent average.
   - Expect:
     - `idx_eval == len(candles) - 1`.

3. **US, pre‑open/after‑close with ultra‑thin last bar**
   - `now` = 08:00 or 19:00 America/New_York.
   - Last bar volume ≪ average; `very_thin_today` true.
   - Expect:
     - `idx_eval == len(candles) - 2`.

4. **KR, intraday, thin vs normal**
   - `provider = "kis"`, `meta.currency = "KRW"`.
   - `now` = 10:00 Asia/Seoul (`INTRADAY`).
   - Case A: normal last‑bar volume ⇒ `idx_eval == len(candles) - 1`.
   - Case B: very thin last‑bar volume ⇒ `idx_eval == len(candles) - 2`.

5. **PyKRX data**
   - `provider = "pykrx"`.
   - Any `now`.
   - Expect:
     - `idx_eval == len(candles) - 1`.

6. **Trivial lengths**
   - `len(candles) == 0` ⇒ `idx_eval == -1`.
   - `len(candles) == 1` ⇒ `idx_eval == 0`.

7. **US holiday**
   - `now` during what would normally be `INTRADAY`, but `today` is marked as US holiday.
   - We treat the market as closed; last completed bar should be used:
     - `idx_eval == len(candles) - 1`.


### 11.2 Integration Tests: Evaluation Functions

We test that buy/sell evaluations use the correct bar and indicators.

1. **Hybrid buy, US, intraday**
   - Use a synthetic candle series where:
     - Day N‑1 meets the hybrid pattern criteria.
     - Day N is a partial bar with thin volume.
   - `now` = intraday US time.
   - Expect:
     - `evaluate_ticker_hybrid` uses day N‑1 values for price, RSI, EMA, pattern detection.
     - Candidate’s `price`, `rsi14`, `sma20` match N‑1, not N.

2. **Hybrid buy, US, after close**
   - Same series, but `now` = after US close, with last bar volume normal.
   - Expect:
     - Evaluation uses day N as the latest bar.

3. **EMA20/50 buy (domestic), intraday vs after close**
   - KR ticker, with candles such that:
     - EMA cross + RSI rebound occur on a specific day.
   - Test:
     - During intraday (10:00 Seoul), with thin last bar:
       - Use N‑1 bar for signals.
     - After close:
       - Use N (latest) bar.

4. **Sell rules (generic + hybrid), intraday vs after close**
   - Build a holding and candle history such that:
     - A sell trigger (e.g., RSI < 50, EMA cross, three bearish candles) appears on a certain bar.
   - Ensure:
     - During intraday, the logic **does not prematurely react** to a partial today bar.
     - After close, the same trigger is recognized when the bar is complete.

5. **Real fixture regression (e.g., TMO)**
   - Use `data/candles_overseas_NYS_TMO.json` as a fixture.
   - Set `now` to:
     - A US intraday time for the last date in the file.
     - A US after‑close time for that date.
   - Verify:
     - Intraday: evaluation uses the previous day’s candle.
     - After close: evaluation uses the last candle.


## 12. Future Work / Roadmap (High‑Level)

- Add a small `sab/signals/session.py` (or similar) module to:
  - Encapsulate exchange timezone and session state logic.
  - Provide reusable helpers: `get_exchange_state(meta, now)`, `is_us_holiday(date)`, etc.
- Make `VOL_FLOOR` and `THIN_RATIO` configurable via config/env.
- Optionally record the **evaluation date** explicitly in candidates (e.g., `eval_date`), so reports clearly show whether signals are based on yesterday or today.
- Extend to other asset classes (ETFs, futures) if/when daily candles are used similarly.
