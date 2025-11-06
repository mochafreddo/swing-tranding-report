from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _fmt_number(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "-"
    try:
        if digits == 0:
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    try:
        return f"{value * 100:+.1f}%"
    except (TypeError, ValueError):
        return "-"


@dataclass
class SellReportRow:
    ticker: str
    name: str
    quantity: Optional[float]
    entry_price: Optional[float]
    entry_date: Optional[str]
    last_price: Optional[float]
    pnl_pct: Optional[float]
    action: str
    reasons: List[str]
    stop_price: Optional[float]
    target_price: Optional[float]
    notes: Optional[str] = None
    currency: Optional[str] = None


def write_sell_report(
    *,
    report_dir: str,
    provider: str,
    evaluated: Iterable[SellReportRow],
    failures: Iterable[str] | None = None,
    cache_hint: str | None = None,
    atr_trail_multiplier: float | None = None,
    time_stop_days: int | None = None,
) -> str:
    _ensure_dir(report_dir)

    today = _dt.datetime.now().strftime("%Y-%m-%d")
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    suffix = ".sell.md"
    base = os.path.join(report_dir, f"{today}{suffix}")
    out_path = base
    if os.path.exists(out_path):
        i = 1
        while True:
            candidate = os.path.join(report_dir, f"{today}-{i}{suffix}")
            if not os.path.exists(candidate):
                out_path = candidate
                break
            i += 1

    rows = list(evaluated)
    failures_list = list(failures or [])

    rules: List[str] = []
    if atr_trail_multiplier is not None:
        rules.append(f"ATR trail ×{atr_trail_multiplier:g}")
    if time_stop_days is not None and time_stop_days > 0:
        rules.append(f"Time stop {time_stop_days}d")

    lines: List[str] = []
    lines.append(f"# Holdings Sell Review — {today}")
    lines.append(f"- Run at: {now_str} KST")
    cache_note = f" (cache: {cache_hint})" if cache_hint else ""
    lines.append(f"- Provider: {provider}{cache_note}")
    lines.append(f"- Evaluated holdings: {len(rows)}")
    if rules:
        lines.append(f"- Rules: {', '.join(rules)}")
    if failures_list:
        lines.append(f"- Notes: {len(failures_list)} issue(s) logged (see Appendix)")
    lines.append("")

    if rows:
        lines.append("## Holdings Summary")
        lines.append("| Ticker | Qty | Entry | Last | P/L% | State | Stop | Target |")
        lines.append("|--------|----:|------:|-----:|-----:|-------|------|--------|")
        for row in rows:
            lines.append(
                "| {ticker} | {qty} | {entry} | {last} | {pnl} | {state} | {stop} | {target} |".format(
                    ticker=row.ticker,
                    qty=_fmt_number(row.quantity, 0),
                    entry=_fmt_number(row.entry_price, 0),
                    last=_fmt_number(row.last_price, 0),
                    pnl=_fmt_percent(row.pnl_pct),
                    state=row.action,
                    stop=_fmt_number(row.stop_price, 0),
                    target=_fmt_number(row.target_price, 0),
                )
            )
        lines.append("")

        for row in rows:
            title = f"## [{row.action}] {row.ticker}"
            if row.name and row.name != row.ticker:
                title += f" — {row.name}"
            lines.append(title)
            entry_details = []
            if row.quantity is not None:
                entry_details.append(f"Qty {row.quantity:g}")
            if row.entry_price is not None:
                entry_details.append(f"Entry {row.entry_price:,.0f}")
            if row.entry_date:
                entry_details.append(f"since {row.entry_date}")
            if entry_details:
                lines.append(f"- Position: {' / '.join(entry_details)}")
            if row.last_price is not None:
                lines.append(f"- Last close: {_fmt_number(row.last_price, 0)}")
            lines.append(f"- P/L: {_fmt_percent(row.pnl_pct)}")
            if row.stop_price is not None or row.target_price is not None:
                stop_txt = _fmt_number(row.stop_price, 0)
                target_txt = _fmt_number(row.target_price, 0)
                lines.append(f"- Risk guide: Stop {stop_txt} / Target {target_txt}")
            if row.notes:
                lines.append(f"- Notes: {row.notes}")
            if row.reasons:
                lines.append("- Reasons:")
                for reason in row.reasons:
                    lines.append(f"  - {reason}")
            lines.append("")
    else:
        lines.append("_No holdings evaluated._")
        lines.append("")

    if failures_list:
        lines.append("### Appendix — Issues")
        for item in failures_list:
            lines.append(f"- {item}")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))

    return out_path


__all__ = ["SellReportRow", "write_sell_report"]

