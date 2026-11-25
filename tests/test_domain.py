from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from market_holder.domain.models import (
    Bar,
    Fill,
    Freq,
    Order,
    OrderType,
    Position,
    Side,
    Tick,
)
from market_holder.domain.serde import bar_from_dict, bar_to_dict, tick_from_dict, tick_to_dict
from market_holder.domain.symbol import AssetClass, Symbol

T0 = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)
SYM = Symbol.parse("crypto:binance:btcusdt")


def test_symbol_parse_normalizes_and_roundtrips():
    assert SYM == Symbol(AssetClass.CRYPTO, "BINANCE", "BTCUSDT")
    assert str(SYM) == "CRYPTO:BINANCE:BTCUSDT"
    assert Symbol.parse(str(SYM)) == SYM


@pytest.mark.parametrize("bad", ["EQ:B3", "XX:B3:PETR4", "EQ::PETR4", "EQ:B3:A:B"])
def test_symbol_parse_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        Symbol.parse(bad)


def test_bar_rejects_inconsistent_ohlc_and_naive_time():
    ok = dict(symbol=SYM, ts=T0, freq=Freq.M1, open=D(10), high=D(12), low=D(9), close=D(11))
    Bar(**ok)
    with pytest.raises(ValueError):
        Bar(**{**ok, "high": D(10)})  # high < close
    with pytest.raises(ValueError):
        Bar(**{**ok, "low": D("10.5")})  # low > open
    with pytest.raises(ValueError):
        Bar(**{**ok, "ts": T0.replace(tzinfo=None)})
    with pytest.raises(ValueError):
        Bar(**{**ok, "ts": T0.astimezone(timezone(timedelta(hours=-3)))})


def test_order_field_rules_per_type():
    base = dict(id="1", symbol=SYM, side=Side.BUY, qty=D(1), ts=T0)
    Order(type=OrderType.MARKET, **base)
    Order(type=OrderType.LIMIT, limit_price=D(10), **base)
    Order(type=OrderType.STOP, stop_price=D(10), **base)
    Order(type=OrderType.STOP_LIMIT, limit_price=D(10), stop_price=D(11), **base)
    with pytest.raises(ValueError):
        Order(type=OrderType.MARKET, limit_price=D(10), **base)
    with pytest.raises(ValueError):
        Order(type=OrderType.LIMIT, **base)
    with pytest.raises(ValueError):
        Order(type=OrderType.STOP_LIMIT, limit_price=D(10), **base)
    with pytest.raises(ValueError):
        Order(type=OrderType.MARKET, **{**base, "qty": D(0)})


def test_fill_and_tick_validation():
    with pytest.raises(ValueError):
        Fill("1", SYM, Side.BUY, D(1), D(0), T0)
    with pytest.raises(ValueError):
        Tick(SYM, T0, D(-1))


def test_position_open_add_reduce_close_long():
    p = Position(SYM)
    assert p.apply(Side.BUY, D(10), D(100)) == 0
    assert p.apply(Side.BUY, D(10), D(110)) == 0
    assert (p.qty, p.avg_price) == (D(20), D(105))
    # vende 5 a 120: lucro 5 * (120 - 105) = 75
    assert p.apply(Side.SELL, D(5), D(120)) == D(75)
    assert (p.qty, p.avg_price) == (D(15), D(105))
    # fecha 15 a 100: prejuízo 15 * (100 - 105) = -75
    assert p.apply(Side.SELL, D(15), D(100)) == D(-75)
    assert (p.qty, p.avg_price) == (D(0), D(0))


def test_position_short_pnl_and_flip():
    p = Position(SYM)
    p.apply(Side.SELL, D(10), D(100))
    assert p.qty == D(-10)
    # recompra 4 a 90: lucro de short 4 * (100 - 90) = 40
    assert p.apply(Side.BUY, D(4), D(90)) == D(40)
    assert (p.qty, p.avg_price) == (D(-6), D(100))
    # compra 10 a 110: fecha 6 com prejuízo 6 * (100 - 110) = -60, vira comprado 4 a 110
    assert p.apply(Side.BUY, D(10), D(110)) == D(-60)
    assert (p.qty, p.avg_price) == (D(4), D(110))


def test_serde_roundtrip_bar_and_tick():
    bar = Bar(SYM, T0, Freq.M1, D("10.5"), D("12"), D("9.25"), D("11"), D("1234.5"))
    assert bar_from_dict(bar_to_dict(bar)) == bar
    tick = Tick(SYM, T0, D("43000.12"), D("0.5"), source="binance", delay_s=0)
    assert tick_from_dict(tick_to_dict(tick)) == tick
