from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from .config import Config, load_config
from .data.cache import load_json, save_json
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .report.sell_report import SellReportRow, write_sell_report
from .signals.sell_rules import SellEvaluation, SellSettings, evaluate_sell_signals


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def run_sell(*, provider: Optional[str]) -> int:
    logger = logging.getLogger(__name__)
    cfg: Config = load_config(provider_override=provider)

    holdings = cfg.holdings.holdings
    if not holdings:
        logger.warning("No holdings configured. Generating empty sell report.")

    tickers = [h.ticker for h in holdings if h.ticker]
    unique_tickers = list(dict.fromkeys(tickers))

    failures: List[str] = []
    market_data: Dict[str, List[Dict[str, Any]]] = {}
    cache_hint: Optional[str] = None
    fatal_failure = False

    kis_client: Optional[KISClient] = None
    pykrx_client: Optional[PykrxClient] = None
    pykrx_init_error: Optional[str] = None
    pykrx_warning_added = False
    missing_logged: set[str] = set()

    def ensure_pykrx_client() -> Optional[PykrxClient]:
        nonlocal pykrx_client, pykrx_init_error
        if pykrx_client is not None:
            return pykrx_client
        if pykrx_init_error:
            return None
        try:
            pykrx_client = PykrxClient(cache_dir=cfg.data_dir)
            logger.info("PyKRX client initialized")
            return pykrx_client
        except PykrxNotInstalledError as exc:
            pykrx_init_error = str(exc)
            logger.warning("PyKRX unavailable: %s", exc)
        except PykrxClientError as exc:
            pykrx_init_error = str(exc)
            logger.error("PyKRX init failed: %s", exc)
        return None

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
        failures.append(f"Provider '{cfg.data_provider}' not supported for sell command")
        logger.error("Unsupported provider '%s'", cfg.data_provider)
        fatal_failure = True

    target_bars = max(cfg.min_history_bars, 200)

    if cfg.data_provider == "kis" and kis_client:
        for ticker in unique_tickers:
            cache_key = f"candles_{ticker}"
            cached = load_json(cfg.data_dir, cache_key)
            if isinstance(cached, list) and cached:
                market_data[ticker] = cached
            try:
                candles = kis_client.daily_candles(ticker, count=target_bars)
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
                    fallback_error = pykrx_init_error
                    if fallback_client is not None:
                        try:
                            candles = fallback_client.daily_candles(
                                ticker, count=target_bars
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
                    msg = f"{ticker}: {exc}"
                    if fallback_client is None and fallback_error:
                        msg += f" (PyKRX fallback unavailable: {fallback_error})"
                    failures.append(msg)
                    logger.error(msg)
    elif cfg.data_provider == "pykrx" and pykrx_client:
        for ticker in unique_tickers:
            try:
                candles = pykrx_client.daily_candles(ticker, count=target_bars)
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

        if unique_tickers and not pykrx_warning_added:
            failures.append("Warning: PyKRX provider data is end-of-day and may lag intraday feeds.")
            pykrx_warning_added = True

    results: List[SellReportRow] = []
    order = {"SELL": 0, "REVIEW": 1, "HOLD": 2}

    settings = SellSettings(
        atr_trail_multiplier=cfg.sell_atr_multiplier,
        time_stop_days=cfg.sell_time_stop_days,
        require_sma200=cfg.sell_require_sma200,
        ema_lengths=(cfg.sell_ema_short, cfg.sell_ema_long),
        rsi_period=cfg.sell_rsi_period,
        rsi_floor=cfg.sell_rsi_floor,
        rsi_floor_alt=cfg.sell_rsi_floor_alt,
        min_bars=max(cfg.sell_min_bars, 2),
    )

    for holding in holdings:
        ticker = holding.ticker
        candles = market_data.get(ticker)
        if not candles:
            if ticker not in missing_logged:
                failures.append(f"{ticker}: No market data available for sell evaluation")
                missing_logged.add(ticker)
            continue
        evaluation: SellEvaluation = evaluate_sell_signals(
            ticker,
            candles,
            {
                "entry_price": holding.entry_price,
                "entry_date": holding.entry_date,
                "stop_override": holding.stop_override,
                "target_override": holding.target_override,
                "strategy": holding.strategy,
            },
            settings,
        )
        last_close = candles[-1]["close"] if candles else None
        entry_price = holding.entry_price or None
        if entry_price is not None and (isinstance(entry_price, float) and math.isnan(entry_price)):
            entry_price = None

        last_price = last_close
        if last_price is not None and isinstance(last_price, float) and math.isnan(last_price):
            last_price = None

        pnl_pct = None
        if entry_price and entry_price != 0 and last_price not in (None, 0):
            try:
                pnl_pct = (last_price - entry_price) / entry_price
            except TypeError:
                pnl_pct = None

        row = SellReportRow(
            ticker=ticker,
            name=ticker,
            quantity=holding.quantity,
            entry_price=entry_price,
            entry_date=holding.entry_date,
            last_price=last_price,
            pnl_pct=pnl_pct,
            action=evaluation.action,
            reasons=evaluation.reasons,
            stop_price=evaluation.stop_price,
            target_price=evaluation.target_price,
            notes=holding.notes,
            currency=holding.entry_currency,
        )
        results.append(row)

    results.sort(key=lambda r: (order.get(r.action, 99), r.ticker))

    out_path = write_sell_report(
        report_dir=cfg.report_dir,
        provider=cfg.data_provider,
        evaluated=results,
        failures=failures,
        cache_hint=cache_hint,
        atr_trail_multiplier=cfg.sell_atr_multiplier,
        time_stop_days=cfg.sell_time_stop_days,
    )

    logger.info("Sell report written to: %s", out_path)

    if fatal_failure:
        logger.error("Sell evaluation completed with fatal errors. See report for details.")
        return 1

    if failures:
        logger.warning("Sell evaluation completed with warnings. See report for details.")

    return 0


__all__ = ["run_sell"]
