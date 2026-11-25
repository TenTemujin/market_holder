"""API REST + WebSocket. Uma sessão por servidor (jogo de um jogador).

Rodar: uvicorn market_holder.api.app:create_app --factory --reload
Eventos no WebSocket /ws: snapshot (ao conectar), bar, fill, order, clock.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from market_holder.api.schemas import BracketReq, ClockReq, ExitsReq, OrderReq, SessionReq, _utc
from market_holder.clock.live import PERIOD_S, LiveClock, LiveFeed, StreamTickFeed, TickFeed
from market_holder.clock.replay import ReplayPlayer
from market_holder.domain.models import Bar, Freq, Instrument, OrderType
from market_holder.domain.serde import bar_to_dict
from market_holder.domain.symbol import AssetClass, Symbol
from market_holder.engine.account import Account, MarginPolicy
from market_holder.engine.engine import Engine
from market_holder.engine.execution import ExecutionModel, FeeSchedule
from market_holder.providers.base import Provider
from market_holder.providers.bcb import BcbProvider
from market_holder.providers.binance import BinanceProvider
from market_holder.providers.cache import BarCache, CachedProvider
from market_holder.providers.fred import FredProvider
from market_holder.providers.http import FetchError
from market_holder.providers.tesouro import TesouroProvider
from market_holder.providers.yahoo import YahooProvider
from market_holder.session import Session, state_to_dict


def _has_websockets() -> bool:
    try:
        import websockets  # noqa: F401
    except ImportError:
        return False
    return True


def default_providers() -> dict[str, Provider]:
    return {
        "BINANCE": BinanceProvider(),
        "BCB": BcbProvider(),
        "FRED": FredProvider(),
        "TESOURO": TesouroProvider(),
        "YAHOO": YahooProvider(),  # fallback para todos os outros mercados (US, B3, CME...)
    }


class State:
    def __init__(self) -> None:
        self.session: Session | None = None
        self.player: ReplayPlayer | None = None
        self.task: asyncio.Task | None = None
        self.tick_task: asyncio.Task | None = None
        self.clients: set[asyncio.Queue] = set()
        self.next_id = 0

    def broadcast(self, event: dict[str, Any]) -> None:
        for q in list(self.clients):
            q.put_nowait(event)

    def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        if self.tick_task and not self.tick_task.done():
            self.tick_task.cancel()
        self.session = self.player = self.task = self.tick_task = None


def create_app(
    providers: dict[str, Provider] | None = None, cache_path: str = "data/cache.sqlite"
) -> FastAPI:
    if cache_path != ":memory:":
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    cache = BarCache(cache_path)
    provs = {k: CachedProvider(p, cache) for k, p in (providers or default_providers()).items()}
    state = State()
    app = FastAPI(title="Market Holder")

    def provider_for(sym: Symbol) -> CachedProvider:
        p = provs.get(sym.market) or provs.get("YAHOO")
        if p is None:
            raise HTTPException(422, f"nenhum provedor para {sym}")
        return p

    def parse_symbol(text: str) -> Symbol:
        try:
            return Symbol.parse(text)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    def need_session() -> Session:
        if state.session is None:
            raise HTTPException(409, "nenhuma sessão ativa; use POST /api/session")
        return state.session

    async def load_bars(sym: Symbol, start, end, freq: Freq) -> list[Bar]:
        try:
            return await provider_for(sym).history(sym, start, end, freq)
        except FetchError as e:
            raise HTTPException(502, f"falha no provedor: {e}") from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "providers": sorted(provs)}

    @app.get("/api/history")
    async def history(symbol: str, freq: Freq, start: str, end: str) -> dict[str, Any]:
        try:
            s, e = _utc(datetime.fromisoformat(start)), _utc(datetime.fromisoformat(end))
        except ValueError as exc:
            raise HTTPException(422, f"data inválida: {exc}") from exc
        bars = await load_bars(parse_symbol(symbol), s, e, freq)
        return {"bars": [bar_to_dict(b) for b in bars]}

    @app.get("/api/search")
    async def search(q: str) -> dict[str, Any]:
        """Busca global de ativos: Yahoo (bolsas do mundo, índices, câmbio, futuros) e Binance."""
        found: list[Instrument] = []
        for name in ("YAHOO", "BINANCE"):
            if name not in provs:
                continue
            try:
                found += await provs[name].search(q)
            except Exception:  # noqa: BLE001 - uma fonte fora do ar não derruba a busca
                continue
        return {"results": [
            {"symbol": str(i.symbol), "currency": i.currency, "name": i.name} for i in found
        ]}

    async def auto_fx(ccy: str, base: str, ref: datetime) -> Decimal | None:
        """Taxa ccy->base (simulação: valor fixo na data de referência, sem olhar o futuro)."""
        minor = {"GBX": ("GBP", Decimal(100)), "ILA": ("ILS", Decimal(100)),
                 "ZAC": ("ZAR", Decimal(100))}
        ccy, div = minor.get(ccy, (ccy, Decimal(1)))
        if ccy == base or {ccy, base} <= {"USD", "USDT", "USDC"}:
            return Decimal(1) / div
        for pair, inv in ((f"{ccy}{base}", False), (f"{base}{ccy}", True)):
            sym = Symbol(AssetClass.FX, "YAHOO", pair)
            try:
                lo, hi = ref - timedelta(days=10), ref + timedelta(days=1)
                got = await load_bars(sym, lo, hi, Freq.D1)
            except Exception:  # noqa: BLE001
                continue
            past = [b for b in got if b.ts <= ref] or got
            if past and past[-1].close > 0:
                return (1 / past[-1].close if inv else past[-1].close) / div
        return None

    @app.get("/api/book")
    async def book(symbol: str, limit: int = 10) -> dict[str, Any]:
        sym = parse_symbol(symbol)
        inner = getattr(provider_for(sym), "inner", None)
        if sym.market != "BINANCE" or not hasattr(inner, "book"):
            raise HTTPException(422, "livro real só para cripto da Binance")
        try:
            data = await inner.book(sym, min(limit, 20))
            return {"symbol": str(sym), "source": "binance", **data}
        except FetchError as e:
            raise HTTPException(502, f"falha no provedor: {e}") from e

    @app.post("/api/session")
    async def create_session(req: SessionReq) -> dict[str, Any]:
        live = req.mode == "live"
        now = datetime.now(UTC)
        if live:
            period = timedelta(seconds=PERIOD_S[req.freq]) if req.freq in PERIOD_S else None
            if period is None:
                raise HTTPException(422, f"modo ao vivo não atende {req.freq}")
            start, end = now - 200 * period, now
        else:
            if req.start is None or req.end is None:
                raise HTTPException(422, "replay exige start e end")
            start, end = req.start, req.end
            if end <= start:
                raise HTTPException(422, "end deve ser posterior a start")
        instruments: dict[Symbol, Instrument] = {}
        bars: list[Bar] = []
        for cfg in req.symbols:
            sym = parse_symbol(cfg.symbol)
            try:
                instruments[sym] = Instrument(
                    sym, cfg.currency, tick_size=cfg.tick_size, lot_size=cfg.lot_size,
                    multiplier=cfg.multiplier,
                )
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            got = await load_bars(sym, start, end, req.freq)
            if live:  # só barras fechadas servem de contexto
                got = [b for b in got if b.ts + period <= now]
            if not got:
                raise HTTPException(422, f"sem dados para {sym} no período")
            bars += got
        account = Account(
            req.base_currency,
            {req.base_currency: req.cash},
            instruments,
            MarginPolicy(**req.margin.model_dump()),
        )
        for ccy, rate in req.fx.items():
            account.set_fx(ccy, rate)
        for inst in instruments.values():
            if inst.currency not in account.fx:
                rate = await auto_fx(inst.currency, req.base_currency, start if not live else now)
                if rate is not None:
                    account.set_fx(inst.currency, rate)
            if inst.currency not in account.fx:
                raise HTTPException(422, f"falta taxa de câmbio para {inst.currency}")
        engine = Engine(
            account, ExecutionModel(**req.model.model_dump()), FeeSchedule(**req.fees.model_dump())
        )
        state.stop()
        if live:
            clock = LiveClock(now)
            state.session = Session(engine, [], now, clock)
            state.session.seed(bars)
        else:
            state.session = Session(engine, bars, start)
        state.next_id += 1
        state.session.id = state.next_id
        state.session.meta = {
            "mode": req.mode,
            "freq": req.freq.value,
            "start": start.isoformat(),
            "end": None if live else end.isoformat(),
            "symbols": [c.model_dump(mode="json") for c in req.symbols],
            "feed": {
                str(sym): {
                    "provider": provider_for(sym).capabilities.name,
                    "delay_s": provider_for(sym).capabilities.delay_s,
                    "official": provider_for(sym).capabilities.official,
                }
                for sym in instruments
            },
        }
        state.session.listeners.append(state.broadcast)
        if live:
            feed = LiveFeed(
                # ao vivo consulta o provedor direto: o cache só serve intervalos fechados e,
                # em polling incremental, devolvia vazio (findings F4)
                lambda sym: getattr(provider_for(sym), "inner", provider_for(sym)),
                list(instruments), req.freq, clock, state.session.step,
                started=now, status=state.session.live, on_error=lambda sym, e: state.broadcast(
                    {"type": "feed_error", "symbol": str(sym), "error": str(e)}
                ),
            )
            state.task = asyncio.create_task(feed.run())
            session = state.session
            raw = {s: getattr(provider_for(s), "inner", provider_for(s)) for s in instruments}
            tickable = [s for s, p in raw.items() if hasattr(p, "quotes")]
            if tickable:  # fontes com cotação em tempo real (hoje: Binance): ordens casam em ~1 s
                inner = raw[tickable[0]]
                tf = TickFeed(inner.quotes, tickable, session.tick, status=session.live)
                feed_t = tf
                if hasattr(inner, "quote_stream") and _has_websockets():
                    feed_t = StreamTickFeed(
                        inner.quote_stream, tickable, session.tick, tf, status=session.live
                    )
                state.tick_task = asyncio.create_task(feed_t.run())
                session.meta["ticks"] = [str(s) for s in tickable]
        state.broadcast({"type": "snapshot", **state.session.snapshot()})
        return state.session.snapshot()

    @app.get("/api/session")
    async def get_session() -> dict[str, Any]:
        return need_session().snapshot()

    @app.get("/api/session/bars")
    async def session_bars(symbol: str, limit: int = 5000) -> dict[str, Any]:
        session = need_session()
        sym = parse_symbol(symbol)
        if sym not in session.engine.account.instruments:
            raise HTTPException(404, f"{sym} não está na sessão")
        bars = session.history.get(sym, [])[-max(1, min(limit, 20000)) :]
        return {"bars": [bar_to_dict(b) for b in bars]}

    @app.post("/api/clock")
    async def clock(req: ClockReq) -> dict[str, Any]:
        session = need_session()
        if session.meta.get("mode") == "live":
            raise HTTPException(409, "modo ao vivo: o tempo é o relógio real, sem controle")
        if req.action == "step":
            session.step()
        elif req.action == "until":
            if req.until is None:
                raise HTTPException(422, "until é obrigatório")
            session.run_until(req.until)
        else:
            if state.player is None:
                state.player = ReplayPlayer(session.clock, session.step)
            if req.action == "speed":
                if req.speed is None or req.speed <= 0:
                    raise HTTPException(422, "speed deve ser positiva")
                state.player.speed = req.speed
            elif req.action == "pause":
                state.player.pause()
            elif req.action == "play":
                state.player.resume()
                if state.task is None or state.task.done():
                    state.task = asyncio.create_task(state.player.run())
        return {**session.clock_state(), "speed": state.player.speed if state.player else None,
                "paused": state.player.paused if state.player else None}

    @app.post("/api/orders")
    async def place_order(req: OrderReq) -> dict[str, Any]:
        session = need_session()
        try:
            st = session.place(
                parse_symbol(req.symbol), req.side, req.type, req.qty,
                req.limit_price, req.stop_price, req.tif, req.oco,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return state_to_dict(st)

    @app.post("/api/orders/bracket")
    async def place_bracket(req: BracketReq) -> dict[str, Any]:
        session = need_session()
        try:
            st = session.place_bracket(
                parse_symbol(req.symbol), req.side, req.qty, OrderType(req.type),
                req.stop_price, req.target_price, req.limit_price, req.tif,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return state_to_dict(st)

    @app.post("/api/exits")
    async def place_exits(req: ExitsReq) -> dict[str, Any]:
        session = need_session()
        try:
            sts = session.place_exits(parse_symbol(req.symbol), req.stop_price, req.target_price)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"orders": [state_to_dict(st) for st in sts]}

    @app.get("/api/orders")
    async def list_orders() -> dict[str, Any]:
        s = need_session()
        return {"orders": [state_to_dict(st) for st in s.engine.orders.values()]}

    @app.delete("/api/orders/{order_id}")
    async def cancel_order(order_id: str) -> dict[str, Any]:
        s = need_session()
        if order_id not in s.engine.orders:
            raise HTTPException(404, "ordem não encontrada")
        return {"canceled": s.cancel(order_id)}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q: asyncio.Queue = asyncio.Queue()
        state.clients.add(q)
        try:
            if state.session is not None:
                await websocket.send_json({"type": "snapshot", **state.session.snapshot()})
            while True:
                await websocket.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            state.clients.discard(q)

    return app
