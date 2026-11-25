"""Serialização JSON-segura de dados de mercado (Decimal como str, datetime ISO-8601)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from market_holder.domain.models import (
    Bar,
    Fill,
    Freq,
    Order,
    OrderType,
    Side,
    Tick,
    TimeInForce,
)
from market_holder.domain.symbol import Symbol


def bar_to_dict(bar: Bar) -> dict[str, Any]:
    return {
        "symbol": str(bar.symbol),
        "ts": bar.ts.isoformat(),
        "freq": bar.freq.value,
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
    }


def bar_from_dict(d: dict[str, Any]) -> Bar:
    return Bar(
        symbol=Symbol.parse(d["symbol"]),
        ts=datetime.fromisoformat(d["ts"]),
        freq=Freq(d["freq"]),
        open=Decimal(d["open"]),
        high=Decimal(d["high"]),
        low=Decimal(d["low"]),
        close=Decimal(d["close"]),
        volume=Decimal(d["volume"]),
    )


def order_to_dict(o: Order) -> dict[str, Any]:
    return {
        "id": o.id,
        "symbol": str(o.symbol),
        "side": o.side.value,
        "type": o.type.value,
        "qty": str(o.qty),
        "ts": o.ts.isoformat(),
        "limit_price": None if o.limit_price is None else str(o.limit_price),
        "stop_price": None if o.stop_price is None else str(o.stop_price),
        "tif": o.tif.value,
        "oco": o.oco,
        "display_qty": None if o.display_qty is None else str(o.display_qty),
    }


def order_from_dict(d: dict[str, Any]) -> Order:
    def dec(x: str | None) -> Decimal | None:
        return None if x is None else Decimal(x)

    return Order(
        id=d["id"],
        symbol=Symbol.parse(d["symbol"]),
        side=Side(d["side"]),
        type=OrderType(d["type"]),
        qty=Decimal(d["qty"]),
        ts=datetime.fromisoformat(d["ts"]),
        limit_price=dec(d["limit_price"]),
        stop_price=dec(d["stop_price"]),
        tif=TimeInForce(d["tif"]),
        oco=d.get("oco"),
        display_qty=dec(d.get("display_qty")),
    )


def fill_to_dict(f: Fill) -> dict[str, Any]:
    return {
        "order_id": f.order_id,
        "symbol": str(f.symbol),
        "side": f.side.value,
        "qty": str(f.qty),
        "price": str(f.price),
        "ts": f.ts.isoformat(),
        "fee": str(f.fee),
    }


def tick_to_dict(tick: Tick) -> dict[str, Any]:
    return {
        "symbol": str(tick.symbol),
        "ts": tick.ts.isoformat(),
        "price": str(tick.price),
        "size": str(tick.size),
        "source": tick.source,
        "delay_s": tick.delay_s,
        "simulated": tick.simulated,
    }


def tick_from_dict(d: dict[str, Any]) -> Tick:
    return Tick(
        symbol=Symbol.parse(d["symbol"]),
        ts=datetime.fromisoformat(d["ts"]),
        price=Decimal(d["price"]),
        size=Decimal(d["size"]),
        source=d["source"],
        delay_s=d["delay_s"],
        simulated=d["simulated"],
    )
