# Daily Candle Evaluation – TODO / Roadmap (Short)

## Implementation

- [x] Introduce `choose_eval_index` helper
  - [x] Implement exchange session detection (KRX/US, tz‑aware) and US holiday handling
  - [x] Add volume‑based thin‑candle heuristic (configurable `VOL_FLOOR`, `THIN_RATIO`)
  - [ ] Make helper accept `meta`, `provider`, and optional `now` for testing

- [x] Wire `choose_eval_index` into buy logic
  - [x] `evaluate_ticker_hybrid` (hybrid_buy): compute `idx_eval`, slice to `*_eval`, use `idx_eval` for candidate fields
  - [x] `evaluate_ticker` (evaluator): use `idx_eval` for latest/previous candle and all indicator indices; limit liquidity window to `idx_eval`

- [x] Wire `choose_eval_index` into sell logic
  - [x] `evaluate_sell_signals` (sell_rules): use `idx_eval` for ATR/EMA/RSI/price and stop/target logic
  - [x] `evaluate_sell_signals_hybrid` (hybrid_sell): use `idx_eval` and adjust “three bearish candles” window to end at `idx_eval`

- [ ] Tag meta/source
  - [ ] Ensure meta contains enough info to identify KR vs US and KIS vs PyKRX (`currency`, `exchange`, `source/provider`)

## Testing

- [ ] Unit tests for `choose_eval_index`
  - [x] US + KIS: intraday vs after‑close vs pre‑open, including thin‑volume last bar
  - [x] KR + KIS: intraday with normal vs thin last bar
  - [ ] PyKRX: always use last bar
  - [ ] Edge cases: 0/1 candles, US holidays

- [ ] Integration tests for evaluation functions
  - [x] Hybrid buy: confirm that intraday uses previous day, after close uses last day
  - [x] EMA20/50 buy (evaluator): same behavior for KR and US symbols
  - [x] Generic + hybrid sell: verify no premature sells on partial intraday candles
  - [ ] Fixture‑based regression (e.g., TMO JSON) with synthetic `now` times
