import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from market_holder.clock.replay import ReplayClock, ReplayPlayer
from market_holder.domain.models import Bar, Freq
from market_holder.domain.symbol import Symbol

A, B = Symbol.parse("CRYPTO:BINANCE:BTCUSDT"), Symbol.parse("CRYPTO:BINANCE:ETHUSDT")
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def bar(sym, minutes):
    return Bar(sym, T0 + timedelta(minutes=minutes), Freq.M1, D(1), D(1), D(1), D(1))


def test_batches_group_same_instant_with_stable_symbol_order():
    clock = ReplayClock([bar(B, 1), bar(A, 0), bar(A, 1), bar(B, 0)])
    assert clock.now == T0
    b0 = clock.next_batch()
    assert [(str(b.symbol), b.ts.minute) for b in b0] == [(str(A), 0), (str(B), 0)]
    assert clock.now == T0
    b1 = clock.next_batch()
    assert [(str(b.symbol), b.ts.minute) for b in b1] == [(str(A), 1), (str(B), 1)]
    assert clock.done and clock.next_batch() == []


def test_reset_restarts_replay_identically():
    clock = ReplayClock([bar(A, 0), bar(A, 1)])
    first = [clock.next_batch(), clock.next_batch()]
    clock.reset()
    assert [clock.next_batch(), clock.next_batch()] == first


def test_player_scales_sleep_by_speed_and_caps_it():
    clock = ReplayClock([bar(A, 0), bar(A, 1), bar(A, 600)])
    sleeps, steps = [], []

    async def fake_sleep(s):
        sleeps.append(s)

    def step():
        steps.append(int((clock.next_batch()[0].ts - T0).total_seconds() // 60))

    p = ReplayPlayer(clock, step, speed=60, max_sleep_s=5, sleep=fake_sleep)
    asyncio.run(p.run())
    assert steps == [0, 1, 600]
    assert sleeps == [1.0, 5]  # 60 s / 60 = 1 s; 599 min / 60 limitado a 5 s


def test_player_pause_blocks_until_resume():
    clock = ReplayClock([bar(A, i) for i in range(3)])
    steps = []

    async def scenario():
        async def fake_sleep(_):
            await asyncio.sleep(0)

        p = ReplayPlayer(clock, lambda: steps.append(clock.next_batch()), sleep=fake_sleep)
        p.pause()
        task = asyncio.create_task(p.run())
        for _ in range(5):
            await asyncio.sleep(0)
        assert steps == [] and p.paused
        p.resume()
        await task

    asyncio.run(scenario())
    assert len(steps) == 3


def test_player_rejects_non_positive_speed():
    import pytest

    p = ReplayPlayer(ReplayClock([]), lambda: None)
    with pytest.raises(ValueError):
        p.speed = 0
