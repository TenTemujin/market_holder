"""Corpos de requisição da API. Decimais chegam como string ou número; datas viram UTC."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from market_holder.domain.models import Freq, OrderType, Side, TimeInForce


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]


class SymbolCfg(BaseModel):
    symbol: str
    currency: str
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal(1)
    multiplier: Decimal = Decimal(1)
    borrow_rate_annual: Decimal = Decimal(0)
    locate_limit: Decimal | None = None


class ModelCfg(BaseModel):
    half_spread_bps: Decimal = Decimal(0)
    impact_bps: Decimal = Decimal(0)
    max_participation: Decimal | None = None


class FeeCfg(BaseModel):
    bps: Decimal = Decimal(0)
    per_order: Decimal = Decimal(0)
    minimum: Decimal = Decimal(0)


class MarginCfg(BaseModel):
    initial_rate: Decimal = Decimal("0.5")
    maintenance_rate: Decimal = Decimal("0.25")
    allow_short: bool = True
    auto_liquidate: bool = False


class SessionReq(BaseModel):
    symbols: list[SymbolCfg] = Field(min_length=1)
    freq: Freq = Freq.D1
    mode: Literal["replay", "live"] = "replay"
    start: UtcDatetime | None = None  # só replay
    end: UtcDatetime | None = None  # só replay
    base_currency: str = "USD"
    cash: Decimal
    fx: dict[str, Decimal] = {}  # moeda -> taxa para a base
    model: ModelCfg = ModelCfg()
    fees: FeeCfg = FeeCfg()
    margin: MarginCfg = MarginCfg()
    scenario: str | None = None


class OrderReq(BaseModel):
    symbol: str
    side: Side
    type: OrderType
    qty: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    tif: TimeInForce = TimeInForce.DAY
    oco: str | None = None
    display_qty: Decimal | None = None


class ModifyOrderReq(BaseModel):
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None


class AlgoOrderReq(BaseModel):
    symbol: str
    side: Side
    algo: Literal["TWAP", "VWAP"] = "TWAP"
    qty: Decimal
    slices: int = 5


class OptionOrderReq(BaseModel):
    underlying: str
    right: Literal["CALL", "PUT"]
    strike: Decimal
    expiry_days: int = 30
    side: Side
    qty: Decimal
    price: Decimal


class CorporateActionReq(BaseModel):
    symbol: str
    kind: Literal["SPLIT", "DIVIDEND"]
    value: Decimal


class BotReq(BaseModel):
    symbol: str
    strategy: Literal["SMA_CROSS", "RSI_REV", "TURTLE_20", "VWAP_TREND"] = "SMA_CROSS"
    qty: Decimal
    params: dict[str, float] = {}


class BracketReq(BaseModel):
    symbol: str
    side: Side
    qty: Decimal
    type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: Decimal | None = None
    stop_price: Decimal  # stop-loss
    target_price: Decimal  # take-profit
    tif: TimeInForce = TimeInForce.DAY


class ExitsReq(BaseModel):
    symbol: str
    stop_price: Decimal | None = None
    target_price: Decimal | None = None


class ClockReq(BaseModel):
    action: Literal["play", "pause", "step", "speed", "until", "fast_forward"]
    speed: float | None = None
    until: UtcDatetime | None = None
    steps: int = 10000
