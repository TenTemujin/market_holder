"""Modo ao vivo: relógio por push, polling só de barras fechadas e novas, caminho do replay."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from _util import make_engine
from market_holder.api.app import create_app
from market_holder.clock.live import LiveClock, LiveFeed, poll_interval
from market_holder.domain.models import Bar, Freq
from market_holder.domain.symbol import Symbol
from market_holder.engine.engine import Engine
from market_holder.providers.base import Capabilities
from market_holder.session import Session

SYM = Symbol.parse("EQ:B3:PETR4")
T0 = datetime(2026, 1, 5, 13, 0, tzinfo=UTC)


def mbar(i, o=100, sym=SYM):
    o = D(o)
    return Bar(sym, T0 + timedelta(minutes=i), Freq.M1, o, o + 1, o - 1, o + D("0.5"), D(10))


class Feed:
    """Provedor de teste: devolve as barras cujo ts cai em [start, end), inclusive a aberta."""

    capabilities = Capabilities("fake", frozenset(), frozenset({Freq.M1}), delay_s=0)

    def __init__(self, bars):
        self.bars = bars
        self.fail = False

    async def history(self, symbol, start, end, freq):
        if self.fail:
            raise RuntimeError("rede caiu")
        return [b for b in self.bars if start <= b.ts < end]


def make_live(bars, started=T0, now_box=None):
    engine: Engine = make_engine()
    clock = LiveClock(started)
    session = Session(engine, [], started, clock)
    feed = Feed(bars)
    now_box = now_box if now_box is not None else [started]
    lf = LiveFeed(
        lambda s: feed, [SYM], Freq.M1, clock, session.step,
        started=started, now=lambda: now_box[0], interval_s=1,
    )
    return session, feed, lf, now_box


def test_live_clock_batches_by_ts_and_never_done():
    c = LiveClock(T0)
    assert not c.done and c.next_batch() == []
    other = Symbol.parse("EQ:B3:VALE3")
    c.push([mbar(1), mbar(0), mbar(0, sym=other)])
    assert c.remaining == 3 and c.peek_ts() == T0
    assert [str(b.symbol) for b in c.next_batch()] == ["EQ:B3:PETR4", "EQ:B3:VALE3"]
    assert c.now == T0 and not c.done


def test_poll_interval_bounds():
    assert poll_interval(Freq.M1) == 10
    assert poll_interval(Freq.H1) == 60
    assert poll_interval(Freq.M5) == 50


def test_only_closed_bars_enter_and_each_bar_once():
    session, _, lf, now = make_live([mbar(0), mbar(1), mbar(2)])
    now[0] = T0 + timedelta(minutes=1, seconds=30)  # barra 0 fechou; 1 ainda aberta
    assert asyncio.run(lf.poll_once()) == 1
    assert [b.ts for b in session.history[SYM]] == [T0]
    assert asyncio.run(lf.poll_once()) == 0  # nada de novo: não repete a barra 0
    now[0] = T0 + timedelta(minutes=3)  # 1 e 2 fecharam
    assert asyncio.run(lf.poll_once()) == 2
    got = [b.ts for b in session.history[SYM]]
    assert got == [T0 + timedelta(minutes=i) for i in range(3)]


def test_bars_before_session_start_are_ignored():
    session, _, lf, now = make_live([mbar(-5), mbar(-1), mbar(0)], started=T0)
    now[0] = T0 + timedelta(minutes=2)
    asyncio.run(lf.poll_once())
    # -1 abre antes do início e fecha em T0 (não depois do início): fica de fora; 0 entra
    assert [b.ts for b in session.history[SYM]] == [T0]


def test_order_fills_on_next_live_bar_without_lookahead():
    session, _, lf, now = make_live([mbar(0, 100), mbar(1, 110)], started=T0)
    now[0] = T0 + timedelta(minutes=1, seconds=1)
    asyncio.run(lf.poll_once())  # barra 0 processada, session.now = T0
    st = session.place(SYM, *_buy(1))
    assert st.status.value == "NEW" and st.order.ts == T0
    now[0] = T0 + timedelta(minutes=2, seconds=1)
    asyncio.run(lf.poll_once())  # barra 1 (abre 110) fecha: a ordem executa nela, não na 0
    assert session.engine.fills[0].price == D(110)
    assert session.engine.fills[0].ts == T0 + timedelta(minutes=1)


def _buy(qty):
    from market_holder.domain.models import OrderType, Side

    return Side.BUY, OrderType.MARKET, D(qty)


def test_provider_failure_is_counted_and_next_poll_recovers():
    session, feed, lf, now = make_live([mbar(0)])
    now[0] = T0 + timedelta(minutes=2)
    feed.fail = True
    assert asyncio.run(lf.poll_once()) == 0 and lf.errors == 1
    feed.fail = False
    assert asyncio.run(lf.poll_once()) == 1 and session.history[SYM]


# --- API ---


class LiveApiProvider(Feed):
    """Barras de 1 min terminando bem antes de agora, para a semente ter contexto."""

    capabilities = Capabilities("fake", frozenset(), frozenset({Freq.M1, Freq.D1}), delay_s=7)

    def __init__(self):
        super().__init__([])

    async def history(self, symbol, start, end, freq):
        step = timedelta(seconds=60 if freq is Freq.M1 else 86400)
        t = start.replace(second=0, microsecond=0)
        out = []
        while t < end:
            if t >= start:
                out.append(Bar(symbol, t, freq, D(100), D(102), D(99), D(101), D(5)))
            t += step
        return out


@pytest.fixture
def client():
    prov = LiveApiProvider()
    app = create_app({"YAHOO": prov, "BINANCE": prov}, ":memory:")
    with TestClient(app) as c:
        yield c


LIVE = {
    "mode": "live",
    "symbols": [{"symbol": "EQ:US:AAPL", "currency": "USD"}],
    "freq": "1m",
    "cash": "100000",
}


def test_api_live_session_seeds_context_and_exposes_feed_info(client):
    s = client.post("/api/session", json=LIVE).json()
    assert s["meta"]["mode"] == "live" and s["meta"]["end"] is None
    assert s["meta"]["feed"]["EQ:US:AAPL"] == {"provider": "fake", "delay_s": 7, "official": False}
    bars = client.get("/api/session/bars", params={"symbol": "EQ:US:AAPL"}).json()["bars"]
    assert 0 < len(bars) <= 200
    now = datetime.now(UTC)
    assert all(datetime.fromisoformat(b["ts"]) + timedelta(seconds=60) <= now for b in bars)
    assert s["quotes"][0]["last"] == "101"


def test_api_live_rejects_clock_control(client):
    client.post("/api/session", json=LIVE)
    r = client.post("/api/clock", json={"action": "step"})
    assert r.status_code == 409 and "ao vivo" in r.json()["detail"]


def test_api_live_rejects_unsupported_freq_and_replay_needs_dates(client):
    assert client.post("/api/session", json={**LIVE, "freq": "tick"}).status_code == 422
    body = {k: v for k, v in LIVE.items() if k != "mode"}
    assert client.post("/api/session", json=body).status_code == 422


def test_api_book_only_for_binance(client):
    r = client.get("/api/book", params={"symbol": "EQ:US:AAPL"})
    assert r.status_code == 422


# --- ticks em tempo real ---


def test_tick_fills_market_order_immediately_and_updates_quote():
    from market_holder.clock.live import TickFeed

    session, _, _, _ = make_live([])
    events = []
    session.listeners.append(events.append)
    session.tick(SYM, T0 + timedelta(seconds=1), D("99"), D("101"))
    st = session.place(SYM, *_buy(2))
    assert st.status.value == "NEW"
    fills = session.tick(SYM, T0 + timedelta(seconds=2), D("100"), D("102"))
    assert len(fills) == 1 and fills[0].price == D("101")  # preço médio do tick
    assert session.engine.account.marks[SYM] == D("101")
    q = session.quotes()[0]
    assert q["bid"] == "100" and q["ask"] == "102" and q["last"] == "101"
    assert [e["type"] for e in events if e["type"] in ("tick", "fill")][-2:] == ["tick", "fill"]

    feed = TickFeed(None, [SYM], session.tick)  # tipo usado no app
    assert feed.interval_s == 1.0


def test_tick_does_not_fill_order_placed_after_it_and_rejects_bad_quote():
    session, _, _, _ = make_live([])
    session.tick(SYM, T0 + timedelta(seconds=5), D("100"), D("100"))
    session.place(SYM, *_buy(1))  # ts = agora (T0+5s)
    assert session.tick(SYM, T0 + timedelta(seconds=4), D("100"), D("100")) == []  # tick velho
    with pytest.raises(ValueError):
        session.tick(SYM, T0, D("100"), D("99"))


def test_clock_never_goes_backwards_after_bar_step():
    session, _, lf, now = make_live([mbar(0)])
    session.tick(SYM, T0 + timedelta(seconds=90), D("100"), D("100"))
    now[0] = T0 + timedelta(minutes=2)
    asyncio.run(lf.poll_once())  # barra T0 processada depois do tick de T0+90s
    assert session.now == T0 + timedelta(seconds=90)


def test_tick_feed_polls_and_survives_errors():
    from market_holder.clock.live import TickFeed

    got = []
    calls = {"n": 0}

    async def quotes(symbols):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("rede")
        return {SYM: (D("10"), D("11"))}

    f = TickFeed(quotes, [SYM], lambda s, ts, b, a: got.append((s, b, a)), now=lambda: T0)
    assert asyncio.run(f.poll_once()) == 0 and f.errors == 1
    assert asyncio.run(f.poll_once()) == 1 and got == [(SYM, D("10"), D("11"))]


# --- WebSocket ---


def _stream_feed(items, now_box, fail=None):
    from market_holder.clock.live import StreamTickFeed, TickFeed

    got = []

    async def stream(symbols):
        for it in items:
            yield it
        if fail:
            raise fail

    polled = []

    async def quotes(symbols):
        polled.append(1)
        return {}

    poller = TickFeed(quotes, [SYM], lambda *a: None)
    f = StreamTickFeed(
        stream, [SYM], lambda s, ts, b, a: got.append((ts, b, a)), poller,
        min_interval_s=0.5, now=lambda: now_box[0],
    )
    return f, got, polled


def test_stream_delivers_quotes_and_throttles_per_symbol():
    box = [T0]
    f, got, _ = _stream_feed([], box)

    async def stream(symbols):
        yield SYM, D("1"), D("2")
        yield SYM, D("3"), D("4")  # mesmo instante: descartada
        box[0] = T0 + timedelta(seconds=1)
        yield SYM, D("5"), D("6")  # 1 s depois: passa

    f.stream = stream
    assert asyncio.run(f.run_once()) == 2
    assert [(b, a) for _, b, a in got] == [(D("1"), D("2")), (D("5"), D("6"))]
    assert f.status["stream"] == "closed"


def test_stream_failure_is_recorded_and_not_raised():
    f, got, _ = _stream_feed([(SYM, D("1"), D("2"))], [T0], fail=RuntimeError("ws caiu"))
    assert asyncio.run(f.run_once()) == 1
    assert f.status["stream"] == "down" and "ws caiu" in f.status["last_tick_error"]


def test_stream_run_polls_while_disconnected_and_reconnects():
    from market_holder.clock.live import StreamTickFeed, TickFeed

    polled = []

    async def quotes(symbols):
        polled.append(1)
        return {}

    async def bad_stream(symbols):
        raise RuntimeError("sem rede")
        yield  # pragma: no cover

    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    poller = TickFeed(quotes, [SYM], lambda *a: None)
    f = StreamTickFeed(bad_stream, [SYM], lambda *a: None, poller, sleep=fake_sleep)
    try:
        asyncio.run(f.run())
    except asyncio.CancelledError:
        pass
    assert len(polled) >= 2 and f.reconnects >= 1  # polling durante a queda
