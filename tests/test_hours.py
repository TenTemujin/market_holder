"""Horário de pregão: valores calculados à mão (UTC = local - offset)."""

from datetime import UTC, datetime

import pytest

from market_holder.domain.hours import market_status
from market_holder.domain.symbol import Symbol


def st(sym, y, mo, d, h, mi):
    return market_status(Symbol.parse(sym), datetime(y, mo, d, h, mi, tzinfo=UTC))


def test_us_equity_opens_0930_est_and_closes_1600():
    # 2026-11-25 é quarta; Nova York em EST (UTC-5): 09:30 local = 14:30Z
    s = st("EQ:US:AAPL", 2026, 11, 25, 14, 29)
    assert s["open"] is False and s["next_change"] == "2026-11-25T14:30:00+00:00"
    s = st("EQ:US:AAPL", 2026, 11, 25, 14, 30)
    assert s["open"] is True and s["next_change"] == "2026-11-25T21:00:00+00:00"


def test_us_equity_follows_daylight_saving():
    # julho: EDT (UTC-4), 09:30 local = 13:30Z
    assert st("EQ:US:AAPL", 2026, 7, 15, 13, 30)["open"] is True
    assert st("EQ:US:AAPL", 2026, 7, 15, 13, 29)["open"] is False


def test_weekend_is_closed_and_next_open_is_monday():
    s = st("EQ:US:AAPL", 2026, 11, 28, 15, 0)  # sábado
    assert s["open"] is False and s["next_change"] == "2026-11-30T14:30:00+00:00"


def test_b3_opens_1000_brt():
    assert st("EQ:B3:PETR4", 2026, 11, 25, 13, 0)["open"] is True  # UTC-3
    assert st("EQ:B3:PETR4", 2026, 11, 25, 12, 59)["open"] is False


def test_tokyo_lunch_break():
    s = st("EQ:TSE:7203", 2026, 11, 25, 2, 30)  # 11:30 JST, UTC+9
    assert s["open"] is False and s["next_change"] == "2026-11-25T03:30:00+00:00"


def test_crypto_always_open():
    s = st("CRYPTO:BINANCE:BTCUSDT", 2026, 11, 28, 3, 0)
    assert s == {"open": True, "next_change": None, "hours": "24/7"}


def test_fx_closes_friday_1700_ny_and_reopens_sunday():
    assert st("FX:YAHOO:EURUSD", 2026, 11, 27, 21, 59)["open"] is True
    s = st("FX:YAHOO:EURUSD", 2026, 11, 27, 22, 0)
    assert s["open"] is False and s["next_change"] == "2026-11-29T22:00:00+00:00"


def test_cme_commodity_has_daily_break():
    s = st("CMDTY:CME:GC", 2026, 11, 25, 22, 0)  # 17:00 EST, pausa
    assert s["open"] is False and s["next_change"] == "2026-11-25T23:00:00+00:00"
    assert st("CMDTY:CME:GC", 2026, 11, 25, 23, 0)["open"] is True


def test_macro_series_has_no_hours_and_naive_time_is_rejected():
    assert st("RATE:FRED:DGS10", 2026, 11, 25, 15, 0) is None
    with pytest.raises(ValueError):
        market_status(Symbol.parse("EQ:US:AAPL"), datetime(2026, 11, 25, 15, 0))
