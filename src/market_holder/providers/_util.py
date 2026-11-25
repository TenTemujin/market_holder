"""Utilidades comuns aos adaptadores."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from market_holder.domain.symbol import AssetClass, Symbol


def check_symbol(
    symbol: Symbol, provider: str, classes: frozenset[AssetClass], market: str | None = None
) -> None:
    if symbol.asset_class not in classes or (market and symbol.market != market):
        raise ValueError(f"{provider} não atende {symbol}")


def utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def last_day(end: datetime) -> date:
    """Último dia civil UTC incluído em um intervalo [start, end)."""
    return (end - timedelta(microseconds=1)).date()
