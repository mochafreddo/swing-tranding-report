from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .config import Config, load_config, load_watchlist
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .data.cache import load_json, save_json
from .report.markdown import write_report
from .signals.evaluator import EvaluationSettings, evaluate_ticker
from .screener import KISScreener, ScreenRequest


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def run_scan(
    *,
    limit: Optional[int],
    watchlist_path: Optional[str],
    provider: Optional[str],
    screener_limit: Optional[int] = None,
    universe: Optional[str] = None,
) -> int:
    logger = logging.getLogger(__name__)
    cfg: Config = load_config(provider_override=provider, limit_override=limit)

    tickers = load_watchlist(watchlist_path)
    if cfg.screen_limit and tickers:
        tickers = tickers[: cfg.screen_limit]

    failures: list[str] = []
    market_data: dict[str, list[dict]] = {}
    cache_hint: Optional[str] = None
    fatal_failure = False

    kis_client: Optional[KISClient] = None
    pykrx_client: Optional[PykrxClient] = None
    pykrx_import_error: Optional[str] = None
    pykrx_warning_added = False
    screener_meta_map: Dict[str, Dict[str, Any]] = {}

    def ensure_pykrx_client() -> Optional[PykrxClient]:
        nonlocal pykrx_client, pykrx_import_error
        if pykrx_client is not None:
            return pykrx_client
        if pykrx_import_error:
            return None
        try:
            pykrx_client = PykrxClient()
            logger.info("PyKRX client initialized for fallback/provider usage")
            return pykrx_client
        except PykrxNotInstalledError as exc:
            pykrx_import_error = str(exc)
            logger.warning("PyKRX unavailable: %s", exc)
        except PykrxClientError as exc:
            pykrx_import_error = str(exc)
            logger.error("PyKRX init failed: %s", exc)
        return None

    if screener_limit is None:
        screener_limit = cfg.screener_limit

    if universe == "watchlist":
        screener_enabled = False
        screener_only = False
    elif universe == "screener":
        screener_enabled = True
        screener_only = True
    elif universe == "both":
        screener_enabled = True
        screener_only = False
    else:
        screener_enabled = cfg.screener_enabled
        screener_only = cfg.screener_only if screener_enabled else False

    if cfg.data_provider == "kis":
        if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
            msg = (
                "KIS credentials missing. Set KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL in .env (see docs/kis-setup.md)."
            )
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            creds = KISCredentials(
                app_key=cfg.kis_app_key,
                app_secret=cfg.kis_app_secret,
                base_url=cfg.kis_base_url,
                env=_infer_env_from_base(cfg.kis_base_url),
            )
            min_interval = None
            if cfg.kis_min_interval_ms is not None:
                min_interval = max(0.0, cfg.kis_min_interval_ms / 1000.0)
            kis_client = KISClient(
                creds, cache_dir=cfg.data_dir, min_interval=min_interval
            )
            cache_hint = kis_client.cache_status
    elif cfg.data_provider == "pykrx":
        client = ensure_pykrx_client()
        if client is None:
            msg = (
                "PyKRX provider selected but pykrx package is unavailable. Install with 'uv add pykrx'."
            )
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            pykrx_client = client
            cache_hint = "pykrx"
    else:
        if screener_enabled:
            msg = "Screener currently supports KIS provider only."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True

    if screener_enabled:
        if not kis_client:
            msg = "Screener enabled but KIS client unavailable."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            req = ScreenRequest(
                limit=screener_limit,
                min_price=cfg.min_price,
                min_dollar_volume=cfg.min_dollar_volume,
            )
            screener = KISScreener(
                kis_client,
                cache_dir=cfg.data_dir,
                cache_ttl_minutes=cfg.screener_cache_ttl_minutes,
            )
            screen_result = screener.screen(req)
            tickers_from_screener = screen_result.tickers
            screener_meta_map = screen_result.metadata.get("by_ticker", {})
            cache_status = screen_result.metadata.get("cache_status", "refresh")
            if not screener_only:
                if tickers:
                    logger.info("Screener combined with watchlist (%s tickers)", len(tickers))
                tickers = list(dict.fromkeys(tickers + tickers_from_screener))
            else:
                tickers = tickers_from_screener
            logger.info(
                "Screener selected %s tickers (cache: %s)",
                len(tickers_from_screener),
                cache_status,
            )

    if cfg.data_provider == "kis" and kis_client:
        for ticker in tickers:
            cache_key = f"candles_{ticker}"
            cached = load_json(cfg.data_dir, cache_key)
            if isinstance(cached, list) and cached:
                market_data[ticker] = cached
            try:
                candles = kis_client.daily_candles(ticker, count=200)
                if candles:
                    market_data[ticker] = candles
                    save_json(cfg.data_dir, cache_key, candles)
                    logger.info("Fetched %s candles for %s", len(candles), ticker)
                else:
                    msg = f"{ticker}: No candle data returned"
                    failures.append(msg)
                    logger.warning(msg)
            except (KISClientError, KISAuthError) as exc:
                if ticker in market_data:
                    msg = f"{ticker}: API error, using cached data ({exc})"
                    failures.append(msg)
                    logger.warning(msg)
                else:
                    fallback_client = ensure_pykrx_client()
                    fallback_error: Optional[str] = None
                    if fallback_client is not None:
                        try:
                            candles = fallback_client.daily_candles(
                                ticker, count=max(cfg.min_history_bars, 200)
                            )
                        except PykrxClientError as py_exc:
                            fallback_client = None
                            fallback_error = str(py_exc)
                        else:
                            if candles:
                                market_data[ticker] = candles
                                logger.warning(
                                    "%s: KIS error (%s); used PyKRX fallback (%s candles)",
                                    ticker,
                                    exc,
                                    len(candles),
                                )
                                failures.append(
                                    f"{ticker}: KIS error ({exc}); used PyKRX fallback"
                                )
                                if not pykrx_warning_added:
                                    failures.append(
                                        "Warning: PyKRX fallback data is end-of-day and may differ from KIS."
                                    )
                                    pykrx_warning_added = True
                                continue
                            fallback_error = "No data from PyKRX"
                            fallback_client = None
                    else:
                        fallback_error = pykrx_import_error

                    msg = f"{ticker}: {exc}"
                    if fallback_client is None and fallback_error:
                        msg += f" (PyKRX fallback unavailable: {fallback_error})"
                    failures.append(msg)
                    logger.error(msg)
    elif cfg.data_provider == "pykrx" and pykrx_client:
        for ticker in tickers:
            try:
                candles = pykrx_client.daily_candles(
                    ticker, count=max(cfg.min_history_bars, 200)
                )
            except PykrxClientError as exc:
                msg = f"{ticker}: PyKRX error ({exc})"
                failures.append(msg)
                logger.error(msg)
                continue

            if candles:
                market_data[ticker] = candles
                logger.info("Fetched %s candles via PyKRX for %s", len(candles), ticker)
            else:
                msg = f"{ticker}: PyKRX returned no data"
                failures.append(msg)
                logger.warning(msg)

        if tickers and not pykrx_warning_added:
            failures.append(
                "Warning: PyKRX provider data is end-of-day and may lag intraday feeds."
            )
            pykrx_warning_added = True
    else:
        if tickers:
            failures.append(f"Provider '{cfg.data_provider}' not yet implemented")
            fatal_failure = True

    if not tickers:
        msg = "No tickers provided (watchlist empty or missing)"
        failures.append(msg)
        logger.error(msg)
        fatal_failure = True

    candidates = []
    eval_settings = EvaluationSettings(
        use_sma200_filter=cfg.use_sma200_filter,
        gap_atr_multiplier=cfg.gap_atr_multiplier,
        min_dollar_volume=cfg.min_dollar_volume,
        min_history_bars=cfg.min_history_bars,
        exclude_etf_etn=cfg.exclude_etf_etn,
        require_slope_up=cfg.require_slope_up,
        rs_lookback_days=cfg.rs_lookback_days,
        rs_benchmark_return=cfg.rs_benchmark_return,
        min_price=cfg.min_price,
    )
    for ticker in tickers:
        candles = market_data.get(ticker)
        if not candles:
            continue
        meta = screener_meta_map.get(ticker, {})
        result = evaluate_ticker(ticker, candles, eval_settings, meta)
        if result.candidate:
            candidates.append(result.candidate)
        elif result.reason and result.reason != "Did not meet signal criteria":
            failures.append(f"{ticker}: {result.reason}")
            logger.warning("%s: %s", ticker, result.reason)

    candidates.sort(key=lambda c: c.get("score_value", 0.0), reverse=True)

    if tickers and not market_data:
        fatal_failure = True
        logger.error("Failed to retrieve market data for requested tickers")

    out_path = write_report(
        report_dir=cfg.report_dir,
        provider=cfg.data_provider,
        universe_count=len(tickers),
        candidates=candidates,
        failures=failures,
        cache_hint=cache_hint,
        report_type="buy",
    )

    logger.info("Buy report written to: %s", out_path)

    if fatal_failure:
        logger.error("Scan completed with fatal errors. See failures section in report.")
        return 1

    if failures:
        logger.warning("Scan completed with warnings. See report for details.")

    return 0
