# 설계 — 스크리너

스크리너는 매수 규칙 평가 전에 소수의 매매 가능한 유니버스를 구성합니다. KR(KIS 랭크)과 US(KIS 랭크 또는 기본목록)를 지원합니다.

## KR 스크리너(거래량 랭크)

- 소스: KIS `volume-rank` API(캐시 TTL로 장중 과도 호출 방지)
- 정규화: 종목명 보강, 중복 제거, 다음 기준 적용
  - `min_price`(가격 하한)
  - `min_dollar_volume`(평가 단계에서 평균 가격×거래량으로 확인)
- 캐시: 키는 limit/임계치를 포함하고, `timestamp`/`tickers`/`metadata.cache_status` 저장

## US 스크리너

두 가지 모드(설정):

- `kis`(권장): KIS 해외 랭크 API 사용. 지표는 다음 중 선택
  - `volume` / `market_cap` / `value`(거래대금)
  - 기본 거래소 `NASD`(필요 시 `NYSE`/`AMEX` 확장)
- `defaults`: 설정의 `screener.us_defaults` 사용

두 모드 모두 `--universe` 옵션에 따라 워치리스트와 병합됩니다.

- `watchlist` → only watchlist
- `screener` → only screener (KR+US combined)
- `both` → union (order preserved, de‑duplicated)

## CLI/설정

- CLI: `--screener-limit N`, `--universe watchlist|screener|both`.
- Config:
  - `screener.enabled`, `screener.limit`, `screener.only`, `screener.cache_ttl_minutes`
  - `screener.min_price`, `screener.min_dollar_volume`
  - `universe.markets: ["KR", "US"]`
  - `screener.us_mode: kis|defaults`, `screener.us_metric`, `screener.us_limit`, `screener.us_defaults: [..]`

## 로깅/메타데이터

- KR 스크리너 캐시 상태와 후보 수를 로깅
- US 스크리너 모드와 개수 로깅, 시장 상태(“open/closed”) 표기
- 실패는 리포트 Appendix에 기록하되, 다른 소스가 성공하면 경고로 완료
