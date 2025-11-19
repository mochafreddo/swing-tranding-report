from __future__ import annotations

from sab import sell


def test_infer_currency_handles_us_full_suffix():
    assert sell._infer_currency_from_ticker("ESLT.NASDAQ") == "USD"
    assert sell._infer_currency_from_ticker("TSM.NYSE") == "USD"


def test_infer_currency_defaults_to_krw_when_no_suffix():
    assert sell._infer_currency_from_ticker("005930") == "KRW"
