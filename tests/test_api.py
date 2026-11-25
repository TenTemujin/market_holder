from datetime import UTC, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from market_holder.api.app import create_app
from market_holder.domain.models import Bar, Freq
from market_holder.providers.base import Capabilities


class FakeProvider:
    """Barras diárias sintéticas: abertura 100 + i, fechamento 100 + i + 1."""

    capabilities = Capabilities("fake", frozenset(), frozenset({Freq.D1}), delay_s=0)

    async def search(self, q):
        return []

    async def history(self, symbol, start, end, freq):
        n = (end - start).days
        out = []
        for i in range(n):
            o = D(100 + i)
            ts = start + timedelta(days=i)
            out.append(Bar(symbol, ts, freq, o, o + 2, o - 1, o + 1, D(1000)))
        return out

    def stream(self, symbol):
        raise NotImplementedError


@pytest.fixture
def client():
    app = create_app({"YAHOO": FakeProvider(), "BINANCE": FakeProvider()}, ":memory:")
    with TestClient(app) as c:
        yield c


SESSION = {
    "symbols": [{"symbol": "EQ:US:AAPL", "currency": "USD"}],
    "freq": "1d",
    "start": "2024-01-01T00:00:00Z",
    "end": "2024-01-06T00:00:00Z",
    "cash": "100000",
}


def test_health_and_history(client):
    assert client.get("/api/health").json()["ok"]
    r = client.get("/api/history", params={
        "symbol": "EQ:US:AAPL", "freq": "1d", "start": "2024-01-01", "end": "2024-01-04"})
    assert [b["open"] for b in r.json()["bars"]] == ["100", "101", "102"]


def test_requires_session_first(client):
    assert client.get("/api/session").status_code == 409
    assert client.post("/api/orders", json={
        "symbol": "EQ:US:AAPL", "side": "BUY", "type": "MARKET", "qty": "1"}).status_code == 409


def test_full_flow_order_step_fill_portfolio(client):
    snap = client.post("/api/session", json=SESSION).json()
    assert snap["equity"] == "100000" and snap["clock"]["remaining"] == 5
    order = client.post("/api/orders", json={
        "symbol": "EQ:US:AAPL", "side": "BUY", "type": "MARKET", "qty": "10"}).json()
    assert order["status"] == "NEW" and order["order"]["id"] == "O1"
    clk = client.post("/api/clock", json={"action": "step"}).json()
    assert clk["remaining"] == 4
    snap = client.get("/api/session").json()
    (pos,) = snap["positions"]
    assert (D(pos["qty"]), D(pos["avg_price"]), D(pos["mark"])) == (D(10), D(100), D(101))
    assert snap["orders"][0]["status"] == "FILLED"
    assert D(snap["equity"]) == D(100000) + D(10)  # 10 * (101 - 100), sem taxa
    client.post("/api/clock", json={"action": "until", "until": "2024-01-06T00:00:00Z"})
    assert client.get("/api/session").json()["clock"]["done"]


def test_websocket_streams_snapshot_then_events(client):
    client.post("/api/session", json=SESSION)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        client.post("/api/orders", json={
            "symbol": "EQ:US:AAPL", "side": "BUY", "type": "MARKET", "qty": "1"})
        client.post("/api/clock", json={"action": "step"})
        types = [ws.receive_json()["type"] for _ in range(5)]
        assert types == ["order", "bar", "fill", "order", "clock"]


def test_cancel_and_unknown_order(client):
    client.post("/api/session", json=SESSION)
    client.post("/api/orders", json={
        "symbol": "EQ:US:AAPL", "side": "BUY", "type": "LIMIT", "qty": "1", "limit_price": "50"})
    assert client.delete("/api/orders/O1").json() == {"canceled": True}
    assert client.delete("/api/orders/O1").json() == {"canceled": False}
    assert client.delete("/api/orders/O9").status_code == 404


@pytest.mark.parametrize(("path", "body", "code"), [
    ("/api/session", {**SESSION, "symbols": [{"symbol": "XX:Y:Z", "currency": "USD"}]}, 422),
    ("/api/session", {**SESSION, "end": "2023-01-01T00:00:00Z"}, 422),
    ("/api/session", {**SESSION, "symbols": []}, 422),
])
def test_session_validation_errors(client, path, body, code):
    assert client.post(path, json=body).status_code == code


def test_order_validation_error_is_rejected_not_crashed(client):
    client.post("/api/session", json=SESSION)
    r = client.post("/api/orders", json={
        "symbol": "EQ:US:AAPL", "side": "BUY", "type": "LIMIT", "qty": "1"})
    assert r.status_code == 422  # LIMIT sem limit_price


def test_clock_speed_pause_play(client):
    client.post("/api/session", json=SESSION)
    assert client.post("/api/clock", json={"action": "speed", "speed": 0}).status_code == 422
    r = client.post("/api/clock", json={"action": "speed", "speed": 1000}).json()
    assert r["speed"] == 1000
    assert client.post("/api/clock", json={"action": "pause"}).json()["paused"] is True
    assert client.post("/api/clock", json={"action": "play"}).json()["paused"] is False
    assert UTC  # fuso usado nas datas da sessão


def test_snapshot_has_id_meta_quotes_fills_and_bars_never_look_ahead(client):
    snap = client.post("/api/session", json=SESSION).json()
    assert snap["id"] == 1 and snap["meta"]["freq"] == "1d"
    assert snap["meta"]["symbols"][0]["symbol"] == "EQ:US:AAPL"
    (q,) = snap["quotes"]
    assert (D(q["last"]), q["ts"]) == (D(100), None)  # antes da 1ª barra: abertura inicial
    assert client.get("/api/session/bars", params={"symbol": "EQ:US:AAPL"}).json() == {"bars": []}
    order = {"symbol": "EQ:US:AAPL", "side": "BUY", "type": "MARKET", "qty": "1"}
    client.post("/api/orders", json=order)
    client.post("/api/clock", json={"action": "step"})
    client.post("/api/clock", json={"action": "step"})
    snap = client.get("/api/session").json()
    q = snap["quotes"][0]
    assert (D(q["last"]), D(q["prev_close"])) == (D(102), D(101))
    assert len(snap["fills"]) == 1 and snap["fills"][0]["order_id"] == "O1"
    bars = client.get("/api/session/bars", params={"symbol": "EQ:US:AAPL"}).json()["bars"]
    assert [b["open"] for b in bars] == ["100", "101"]  # 2 barras processadas, nenhuma futura
    assert client.get("/api/session/bars", params={"symbol": "EQ:US:ZZZ"}).status_code == 404
    again = client.post("/api/session", json=SESSION).json()
    assert again["id"] == 2  # nova sessão, novo id


def test_foreign_currency_gets_automatic_fx_rate(client):
    body = {**SESSION, "symbols": [{"symbol": "EQ:XETRA:SAP", "currency": "EUR"},
                                   {"symbol": "EQ:LSE:SHEL", "currency": "GBX"}]}
    assert client.post("/api/session", json=body).status_code == 200


def test_search_merges_providers(client):
    assert client.get("/api/search", params={"q": "apple"}).json() == {"results": []}


def test_advanced_api_endpoints_options_quant_algos_modify_and_corp_actions(client):
    client.post("/api/session", json=SESSION)
    # 1. Option chain and option order
    chain = client.get(
        "/api/options/chain", params={"symbol": "EQ:US:AAPL", "expiry_days": 30}
    ).json()
    assert chain["spot"] == 100.0 and len(chain["chain"]) == 13
    opt_res = client.post(
        "/api/options/order",
        json={
            "underlying": "EQ:US:AAPL",
            "right": "CALL",
            "strike": "100",
            "expiry_days": 30,
            "side": "BUY",
            "qty": "1",
            "price": "3.50",
        },
    )
    assert opt_res.status_code == 200
    assert opt_res.json()["symbol"].startswith("OPT:US:AAPL_30D_C100")

    # 2. Modify working limit order
    o = client.post(
        "/api/orders",
        json={
            "symbol": "EQ:US:AAPL",
            "side": "BUY",
            "type": "LIMIT",
            "qty": "10",
            "limit_price": "90",
        },
    ).json()
    oid = o["order"]["id"]
    mod = client.patch(f"/api/orders/{oid}", json={"limit_price": "95"}).json()
    assert mod["order"]["limit_price"] == "95"

    # 3. Algo order (TWAP) & Headless fast_forward
    algo = client.post(
        "/api/orders/algo",
        json={"symbol": "EQ:US:AAPL", "side": "BUY", "algo": "TWAP", "qty": "20", "slices": 2},
    ).json()
    assert algo["algo"] == "TWAP" and algo["filled_slices"] == 1
    ff = client.post("/api/clock", json={"action": "fast_forward", "steps": 10}).json()
    assert ff["done"] is True

    # 4. Quant endpoints (Screener, Correlation, Monte Carlo)
    eqs = client.get("/api/quant/screener").json()
    assert len(eqs["rows"]) >= 1
    corr = client.get("/api/quant/correlation").json()
    assert "EQ:US:AAPL" in corr["symbols"]
    mc = client.get("/api/quant/montecarlo", params={"paths": 60, "horizon": 15}).json()
    assert mc["paths"] == 60 and len(mc["fan_paths"]) == 25

    # 5. Corporate action (Split 2:1)
    ca = client.post(
        "/api/session/corporate_action",
        json={"symbol": "EQ:US:AAPL", "kind": "SPLIT", "value": "2"},
    )
    assert ca.status_code == 200 and ca.json()["kind"] == "SPLIT"
