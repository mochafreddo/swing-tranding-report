# 설계 — 시그널(매수 & 매도)

본 문서는 매수 후보 평가와 매도/보류 규칙, 그리고 조정 가능한 임계치를 정의합니다.

## 매수(Buy) 평가

입력: 티커별 최소 `MIN_HISTORY_BARS` 봉(기본 200). 지표: EMA(20/50), RSI(14), ATR(14), SMA(200)

필터(별도 표기 없으면 모두 통과 필요)
- EMA 크로스: 당일 EMA20 > EMA50 이고, 전일 EMA20 ≤ EMA50
- RSI 리바운드: RSI14가 30 위로 재돌파하되 70 미만 유지
- ATR‑갭: |시가−전일종가|/전일종가 ≤ `GAP_ATR_MULTIPLIER × ATR / 전일종가`(폴백: 고정 3%)
- SMA200 컨텍스트(옵션): 가격/EMA20/EMA50 모두 SMA200 상방
- EMA 기울기(옵션): EMA20/EMA50이 전일 대비 상승
- 유동성 하한: 최근 20봉 평균(가격×거래량) ≥ `MIN_DOLLAR_VOLUME`
- ETF/ETN/레버리지/인버스 제외(옵션, 명칭 휴리스틱)

스코어링: 교차/RSI/SMA200/기울기/갭/유동성/RS 여부를 가산. RS(상대강도)는 N일 수익률을 벤치마크와 비교(지수 시리즈 연동 전까지 설정값 사용)

Config keys (selection):
- `strategy.min_history_bars`, `strategy.gap_atr_multiplier`
- `strategy.use_sma200_filter`, `strategy.require_slope_up`, `strategy.exclude_etf_etn`
- `screener.min_dollar_volume`, `screener.min_price`
- `strategy.rs_lookback_days`, `strategy.rs_benchmark_return`

## 매도/보류 규칙

입력: 보유 목록(`holdings.yaml`). 지표: EMA(20/50), RSI(14), ATR(14), SMA(200)

규칙(강한 신호 우선)
- SELL
  - ATR 트레일 스톱 충족: `close ≤ close − k×ATR` (k=`SELL_ATR_MULTIPLIER`)
  - RSI 급락: RSI < `SELL_RSI_FLOOR_ALT`(예: 30)
  - EMA 데드크로스: EMA20이 EMA50 하향 돌파
- REVIEW
  - 가격이 두 EMA 아래(SELL이 아닐 때)
  - RSI < `SELL_RSI_FLOOR`(예: 50)
  - SMA200 하방 컨텍스트(`SELL_REQUIRE_SMA200`가 true일 때)
  - 시간 스톱: `entry_date`로부터 경과일 ≥ `SELL_TIME_STOP_DAYS`
- 수동 오버라이드: `stop_override`, `target_override`는 리포트에 반영

Config keys:
- `SELL_ATR_MULTIPLIER`, `SELL_TIME_STOP_DAYS`, `SELL_REQUIRE_SMA200`
- `SELL_EMA_SHORT`, `SELL_EMA_LONG`, `SELL_RSI_PERIOD`
- `SELL_RSI_FLOOR`, `SELL_RSI_FLOOR_ALT`, `SELL_MIN_BARS`

출력: 상태/사유/스톱·타깃 가이드/P&L%를 포함한 표, 요약 테이블과 종목별 상세 섹션
