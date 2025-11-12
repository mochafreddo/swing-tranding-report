from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class HolidayEntry:
    date: str
    note: Optional[str]
    is_open: bool


def _cache_path(cache_dir: str, country_code: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"holidays_{country_code.lower()}.json")


def load_cached_holidays(cache_dir: str, country_code: str) -> Dict[str, HolidayEntry]:
    path = _cache_path(cache_dir, country_code)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}

    entries: Dict[str, HolidayEntry] = {}
    for key, value in data.items():
        entries[key] = HolidayEntry(
            date=key,
            note=value.get("note"),
            is_open=value.get("is_open", True),
        )
    return entries


def save_holidays(cache_dir: str, country_code: str, entries: Dict[str, HolidayEntry]) -> None:
    path = _cache_path(cache_dir, country_code)
    payload = {
        date: {"note": entry.note, "is_open": entry.is_open}
        for date, entry in entries.items()
    }
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)


def merge_holidays(
    cache_dir: str,
    country_code: str,
    fetched: list[dict[str, Any]],
) -> Dict[str, HolidayEntry]:
    cached = load_cached_holidays(cache_dir, country_code)
    for item in fetched:
        date = str(item.get("base_date") or item.get("TRD_DT") or "").replace("-", "")
        if not date:
            continue
        desc = item.get("base_event") or item.get("evnt_nm") or item.get("note")
        is_open = str(item.get("cntr_div_cd") or item.get("open_yn") or "N").upper() in {"Y", "OPEN"}
        cached[date] = HolidayEntry(date=date, note=desc, is_open=is_open)
    save_holidays(cache_dir, country_code, cached)
    return cached


def lookup_holiday(
    cache_dir: str,
    country_code: str,
    date: dt.date,
) -> Optional[HolidayEntry]:
    entries = load_cached_holidays(cache_dir, country_code)
    return entries.get(date.strftime("%Y%m%d"))


__all__ = [
    "HolidayEntry",
    "load_cached_holidays",
    "save_holidays",
    "merge_holidays",
    "lookup_holiday",
]

