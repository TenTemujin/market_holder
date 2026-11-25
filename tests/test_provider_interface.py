from datetime import datetime
from decimal import Decimal as D

import pytest

from market_holder.domain.models import Bar, Freq, Instrument
from market_holder.domain.symbol import AssetClass, Symbol
from market_holder.providers.base import Capabilities, Provider


class FakeProvider:
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name="fake",
            asset_classes=frozenset({AssetClass.EQ}),
            freqs=frozenset({Freq.D1}),
            delay_s=900,
        )

    async def search(self, query: str) -> list[Instrument]:
        return []

    async def history(
        self, symbol: Symbol, start: datetime, end: datetime, freq: Freq
    ) -> list[Bar]:
        return []

    def stream(self, symbol: Symbol):
        raise NotImplementedError


def test_fake_satisfies_provider_protocol():
    assert isinstance(FakeProvider(), Provider)


def test_object_without_methods_is_not_a_provider():
    assert not isinstance(object(), Provider)


def test_instrument_rejects_bad_tick_size():
    with pytest.raises(ValueError):
        Instrument(Symbol.parse("EQ:B3:PETR4"), "BRL", tick_size=D(0))
