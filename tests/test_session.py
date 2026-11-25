import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from market_holder.domain.models import Bar, Freq, Instrument, OrderStatus, OrderType, Side
from market_holder.domain.serde import fill_to_dict, order_from_dict, order_to_dict
from market_holder.domain.symbol import Symbol
from market_holder.engine.account import Account
from market_holder.engine.engine import Engine
from market_holder.engine.execution import ExecutionModel, FeeSchedule
from market_holder.session import Session

BTC = Symbol.parse("CRYPTO:BINANCE:BTCUSDT")
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def make_bars(n, seed=7):
    """Passeio aleatório determinístico; barras de 1 minuto, preços em múltiplos de 0.01."""
    rng, price, bars = random.Random(seed), D("40000"), []
    for i in range(n):
        o = price
        c = o + D(rng.randint(-300, 300)) / 100
        h = max(o, c) + D(rng.randint(0, 200)) / 100
        lo = min(o, c) - D(rng.randint(0, 200)) / 100
        vol = D(rng.randint(5, 50))
        bars.append(Bar(BTC, T0 + timedelta(minutes=i), Freq.M1, o, h, lo, c, vol))
        price = c
    return bars


def make_session(bars, **model):
    inst = Instrument(BTC, "USD", tick_size=D("0.01"), lot_size=D("0.001"))
    acc = Account("USD", {"USD": D(1_000_000)}, {BTC: inst})
    eng = Engine(acc, ExecutionModel(**model), FeeSchedule(bps=D(10)))
    return Session(eng, bars, T0)


def test_order_placed_now_fills_on_next_bar_open_and_events_flow():
    bars = [
        Bar(BTC, T0, Freq.M1, D(100), D(101), D(99), D(100)),
        Bar(BTC, T0 + timedelta(minutes=1), Freq.M1, D(102), D(103), D(101), D(102)),
    ]
    s = make_session(bars)
    events = []
    s.listeners.append(events.append)
    st = s.place(BTC, Side.BUY, OrderType.MARKET, D("1"))  # antes da 1ª barra: usa marca inicial
    assert st.status is OrderStatus.NEW and st.order.ts == T0
    (f1,) = s.step()  # ts da ordem == ts da 1ª barra: executa na abertura dela
    assert f1.price == D(100)
    assert [e["type"] for e in events] == ["order", "bar", "fill", "order", "clock"]
    s.step()
    snap = s.snapshot()
    assert snap["clock"]["done"] and snap["positions"][0]["qty"] == "1"
    assert snap["positions"][0]["mark"] == "102"
    # equity = 1.000.000 - 100 - fee(0,1) + 1 * (102 - 100) = 1.000.001,9 ... conferido abaixo
    assert D(snap["equity"]) == D(1_000_000) - D("0.1") + D(2)


def test_cancel_emits_order_event_and_blocks_fill():
    s = make_session(make_bars(3))
    st = s.place(BTC, Side.BUY, OrderType.LIMIT, D("1"), limit_price=D("1.00"))
    events = []
    s.listeners.append(events.append)
    assert s.cancel(st.order.id)
    assert events[0]["status"] == "CANCELED"
    assert s.step() == []


def test_run_until_stops_at_timestamp():
    s = make_session(make_bars(10))
    s.run_until(T0 + timedelta(minutes=4))
    assert s.clock.remaining == 5 and s.now == T0 + timedelta(minutes=4)


def test_order_serde_roundtrip():
    s = make_session(make_bars(1))
    st = s.place(BTC, Side.SELL, OrderType.STOP_LIMIT, D("0.5"),
                 limit_price=D("39000"), stop_price=D("39100"))
    assert order_from_dict(order_to_dict(st.order)) == st.order


def run_script(bars):
    """Roteiro fixo de ordens por passo; devolve execuções e o estado final."""
    s = make_session(bars, half_spread_bps=D(2), max_participation=D("0.5"))
    fills = []
    for i in range(len(bars)):
        if i == 5:
            s.place(BTC, Side.BUY, OrderType.MARKET, D("3"))
        if i == 20:
            mark = s.engine.account.marks[BTC]
            s.place(BTC, Side.SELL, OrderType.LIMIT, D("2"), limit_price=mark + 3)
        if i == 40:
            mark = s.engine.account.marks[BTC]
            s.place(BTC, Side.SELL, OrderType.STOP, D("1"), stop_price=mark - 4)
        fills += s.step()
    return [fill_to_dict(f) for f in fills], s.snapshot()


def test_replay_is_deterministic_across_runs():
    bars = make_bars(400)
    f1, snap1 = run_script(bars)
    f2, snap2 = run_script(bars)
    assert f1 and f1 == f2 and snap1 == snap2
    assert len(f1) >= 2  # o roteiro realmente negociou
