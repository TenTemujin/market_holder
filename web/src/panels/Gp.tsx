import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineSeries,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Bar } from "../api";
import { num, px, secName } from "../fmt";
import { useBars, useMarket, useTick } from "../store";

const PERIOD_S: Record<string, number> = { "1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800 };
const toTime = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp;
type C = { time: UTCTimestamp; open: number; high: number; low: number; close: number };
const candle = (b: Bar): C => ({
  time: toTime(b.ts), open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close),
});

function calcSma(data: C[], period: number) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    sum += data[i].close;
    if (i >= period) sum -= data[i - period].close;
    if (i >= period - 1) out.push({ time: data[i].time, value: sum / period });
  }
  return out;
}

function calcEma(data: C[], period: number) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  if (!data.length) return out;
  const k = 2 / (period + 1);
  let ema = data[0].close;
  for (let i = 0; i < data.length; i++) {
    ema = i === 0 ? data[0].close : data[i].close * k + ema * (1 - k);
    out.push({ time: data[i].time, value: ema });
  }
  return out;
}

function calcVwap(bars: Bar[]) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  let cumPV = 0;
  let cumV = 0;
  for (const b of bars) {
    const typ = (Number(b.high) + Number(b.low) + Number(b.close)) / 3;
    const v = Math.max(1, Number(b.volume));
    cumPV += typ * v;
    cumV += v;
    out.push({ time: toTime(b.ts), value: cumPV / cumV });
  }
  return out;
}

function calcBollinger(data: C[], period = 20, mult = 2) {
  const upper: { time: UTCTimestamp; value: number }[] = [];
  const lower: { time: UTCTimestamp; value: number }[] = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const mean = slice.reduce((a, c) => a + c.close, 0) / period;
    const sd = Math.sqrt(slice.reduce((a, c) => a + (c.close - mean) ** 2, 0) / period);
    upper.push({ time: data[i].time, value: mean + mult * sd });
    lower.push({ time: data[i].time, value: mean - mult * sd });
  }
  return { upper, lower };
}

function calcRsiLast(data: C[], period = 14): number | null {
  if (data.length < period + 1) return null;
  let gains = 0;
  let losses = 0;
  for (let i = data.length - period; i < data.length; i++) {
    const d = data[i].close - data[i - 1].close;
    if (d >= 0) gains += d;
    else losses -= d;
  }
  if (losses === 0) return 100;
  const rs = (gains / period) / (losses / period);
  return 100 - 100 / (1 + rs);
}

interface Annotation {
  id: string;
  price: number;
  label: string;
  color: string;
}

export function Gp({ symbol }: { symbol: string }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const smaSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLoSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const lastCandle = useRef<C | null>(null);
  const [legend, setLegend] = useState<C | null>(null);

  const [showSma, setShowSma] = useState(true);
  const [showEma, setShowEma] = useState(false);
  const [showVwap, setShowVwap] = useState(true);
  const [showBb, setShowBb] = useState(false);
  const [showVpvr, setShowVpvr] = useState(true);
  const [drawMode, setDrawMode] = useState<"" | "HLINE" | "FIB">("");
  const [annotations, setAnnotations] = useState<Annotation[]>(() => {
    try {
      const raw = window.localStorage.getItem(`mh.draw.${symbol}`);
      return raw ? (JSON.parse(raw) as Annotation[]) : [];
    } catch {
      return [];
    }
  });
  const [selectedOrderId, setSelectedOrderId] = useState("");
  const [dragFeedback, setDragFeedback] = useState("");

  const bars = useBars(symbol);
  const { snapshot, refresh } = useMarket();
  const tick = useTick(symbol);
  const period = PERIOD_S[snapshot?.meta.freq ?? "1h"] ?? 3600;

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(`mh.draw.${symbol}`);
      setAnnotations(raw ? (JSON.parse(raw) as Annotation[]) : []);
    } catch {
      setAnnotations([]);
    }
  }, [symbol]);

  const saveAnnotations = (next: Annotation[]) => {
    setAnnotations(next);
    window.localStorage.setItem(`mh.draw.${symbol}`, JSON.stringify(next));
  };

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#000000" }, textColor: "#ffa028", fontFamily: "Consolas, monospace" },
      grid: { vertLines: { color: "#141414" }, horzLines: { color: "#141414" } },
      timeScale: { timeVisible: true, borderColor: "#5a3a10" },
      rightPriceScale: { borderColor: "#5a3a10" },
      crosshair: { vertLine: { color: "#ffa02880" }, horzLine: { color: "#ffa02880" } },
    });
    const s = c.addSeries(CandlestickSeries, {
      upColor: "#00d26a", downColor: "#ff3b3b", wickUpColor: "#00d26a", wickDownColor: "#ff3b3b", borderVisible: false,
    });
    smaSeries.current = c.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    emaSeries.current = c.addSeries(LineSeries, { color: "#c084fc", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    vwapSeries.current = c.addSeries(LineSeries, { color: "#ffd400", lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    bbUpSeries.current = c.addSeries(LineSeries, { color: "#64748b", lineWidth: 1, lineStyle: 3, priceLineVisible: false, lastValueVisible: false });
    bbLoSeries.current = c.addSeries(LineSeries, { color: "#64748b", lineWidth: 1, lineStyle: 3, priceLineVisible: false, lastValueVisible: false });

    c.subscribeCrosshairMove((p) => {
      const d = p.seriesData.get(s) as C | undefined;
      setLegend(d ?? lastCandle.current);
    });
    chart.current = c;
    series.current = s;
    markers.current = createSeriesMarkers(s, []);
    return () => {
      c.remove();
      chart.current = series.current = markers.current = null;
      smaSeries.current = emaSeries.current = vwapSeries.current = bbUpSeries.current = bbLoSeries.current = null;
      lines.current = [];
    };
  }, [symbol]);

  useEffect(() => {
    const data = bars.map(candle);
    series.current?.setData(data);
    lastCandle.current = data[data.length - 1] ?? null;
    setLegend(lastCandle.current);

    smaSeries.current?.setData(showSma ? calcSma(data, 20) : []);
    emaSeries.current?.setData(showEma ? calcEma(data, 9) : []);
    vwapSeries.current?.setData(showVwap ? calcVwap(bars) : []);
    if (showBb) {
      const bb = calcBollinger(data, 20, 2);
      bbUpSeries.current?.setData(bb.upper);
      bbLoSeries.current?.setData(bb.lower);
    } else {
      bbUpSeries.current?.setData([]);
      bbLoSeries.current?.setData([]);
    }
  }, [bars, showSma, showEma, showVwap, showBb]);

  // live quotes build the forming candle between closed bars
  useEffect(() => {
    const s = series.current;
    if (!s || !tick || !tick.n) return;
    const t = (Math.floor(Date.now() / 1000 / period) * period) as UTCTimestamp;
    const cur = lastCandle.current;
    const next: C =
      cur && cur.time === t
        ? { ...cur, high: Math.max(cur.high, tick.price), low: Math.min(cur.low, tick.price), close: tick.price }
        : { time: t, open: tick.price, high: tick.price, low: tick.price, close: tick.price };
    if (cur && t < cur.time) return;
    lastCandle.current = next;
    s.update(next);
    setLegend(next);
  }, [tick, period]);

  // fills as markers, working orders & persistent annotations as price lines
  useEffect(() => {
    const s = series.current;
    if (!s || !snapshot) return;
    const ms: SeriesMarker<Time>[] = snapshot.fills
      .filter((f) => f.symbol === symbol)
      .map((f) => ({
        time: (Math.floor(Date.parse(f.ts) / 1000 / period) * period) as UTCTimestamp,
        position: f.side === "BUY" ? "belowBar" : "aboveBar",
        shape: f.side === "BUY" ? "arrowUp" : "arrowDown",
        color: f.side === "BUY" ? "#00d26a" : "#ff3b3b",
        text: `${f.side === "BUY" ? "B" : "S"} ${Number(f.qty)} @ ${Number(f.price)}`,
      }));
    ms.sort((a, b) => (a.time as number) - (b.time as number));
    markers.current?.setMarkers(ms);

    lines.current.forEach((l) => s.removePriceLine(l));
    lines.current = [];
    const pos = snapshot.positions.find((p) => p.symbol === symbol);
    if (pos)
      lines.current.push(
        s.createPriceLine({
          price: Number(pos.avg_price), color: "#ffd400", lineWidth: 1, lineStyle: 0,
          axisLabelVisible: true, title: `POS ${num(pos.qty, 4)}`,
        }),
      );
    for (const o of snapshot.orders) {
      if (o.order.symbol !== symbol || !["NEW", "PARTIALLY_FILLED"].includes(o.status)) continue;
      const add = (price: string | null, tag: string) =>
        price && lines.current.push(
          s.createPriceLine({
            price: Number(price), color: o.order.side === "BUY" ? "#00d26a" : "#ff3b3b",
            lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: `${o.order.id} ${o.order.side} ${tag}`,
          }),
        );
      add(o.order.limit_price, "LMT");
      add(o.order.stop_price, "STP");
    }
    for (const ann of annotations) {
      lines.current.push(
        s.createPriceLine({
          price: ann.price, color: ann.color, lineWidth: 1, lineStyle: 1,
          axisLabelVisible: true, title: ann.label,
        }),
      );
    }
  }, [snapshot, symbol, period, annotations]);

  // Volume Profile (VPVR) buckets & Point of Control (POC)
  const vpvr = useMemo(() => {
    if (!showVpvr || bars.length < 2) return null;
    const recent = bars.slice(-120);
    const lo = Math.min(...recent.map((b) => Number(b.low)));
    const hi = Math.max(...recent.map((b) => Number(b.high)));
    if (hi <= lo) return null;
    const bins = 16;
    const step = (hi - lo) / bins;
    const vols = new Array<number>(bins).fill(0);
    for (const b of recent) {
      const mid = (Number(b.high) + Number(b.low) + Number(b.close)) / 3;
      const idx = Math.min(bins - 1, Math.max(0, Math.floor((mid - lo) / step)));
      vols[idx] += Math.max(1, Number(b.volume));
    }
    const maxV = Math.max(1, ...vols);
    const pocIdx = vols.indexOf(maxV);
    return {
      buckets: vols.map((v, i) => ({
        price: lo + (i + 0.5) * step,
        pct: (v / maxV) * 100,
        isPoc: i === pocIdx,
      })).reverse(),
      pocPrice: lo + (pocIdx + 0.5) * step,
    };
  }, [bars, showVpvr]);

  const activeOrders = (snapshot?.orders ?? []).filter(
    (o) => o.order.symbol === symbol && ["NEW", "PARTIALLY_FILLED"].includes(o.status),
  );

  // Click on chart canvas to place HLINE, FIB retracement or move selected working order
  const onChartClick = async (e: React.MouseEvent<HTMLDivElement>) => {
    if (!series.current || !el.current) return;
    const rect = el.current.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const clickedPrice = series.current.coordinateToPrice(y);
    if (clickedPrice === null || clickedPrice <= 0) return;
    const cfg = snapshot?.meta.symbols?.find((c) => c.symbol === symbol);
    const tickSize = Number(cfg?.tick_size ?? 0.01) || 0.01;
    const snapped = Math.round(clickedPrice / tickSize) * tickSize;

    if (selectedOrderId) {
      const ord = activeOrders.find((o) => o.order.id === selectedOrderId);
      if (ord) {
        const isStop = ord.order.type === "STOP";
        try {
          await api("PATCH", `/api/orders/${ord.order.id}`, isStop ? { stop_price: String(snapped.toFixed(4)) } : { limit_price: String(snapped.toFixed(4)) });
          setDragFeedback(`Moved ${ord.order.id} to ${px(snapped)}`);
          setSelectedOrderId("");
          void refresh();
        } catch (err) {
          setDragFeedback(String(err));
        }
        return;
      }
    }

    if (drawMode === "HLINE") {
      saveAnnotations([...annotations, { id: `A${Date.now()}`, price: snapped, label: `S/R ${px(snapped)}`, color: "#38bdf8" }]);
      setDrawMode("");
    } else if (drawMode === "FIB" && bars.length > 1) {
      const recent = bars.slice(-60);
      const lo = Math.min(...recent.map((b) => Number(b.low)));
      const hi = Math.max(...recent.map((b) => Number(b.high)));
      const levels = [0.236, 0.382, 0.5, 0.618, 0.786];
      const fibs: Annotation[] = levels.map((lvl) => {
        const p = hi - (hi - lo) * lvl;
        return { id: `FIB${lvl}-${Date.now()}`, price: p, label: `FIB ${(lvl * 100).toFixed(1)}%`, color: "#f472b6" };
      });
      saveAnnotations([...annotations, ...fibs]);
      setDrawMode("");
    }
  };

  const rsi14 = useMemo(() => calcRsiLast(bars.map(candle), 14), [bars]);

  return (
    <div className="gp-root">
      <div className="gp-toolbar">
        <button className={showSma ? "mini on" : "mini"} onClick={() => setShowSma(!showSma)} title="20-Period Simple Moving Average">SMA20</button>
        <button className={showEma ? "mini on" : "mini"} onClick={() => setShowEma(!showEma)} title="9-Period Exponential Moving Average">EMA9</button>
        <button className={showVwap ? "mini on" : "mini"} onClick={() => setShowVwap(!showVwap)} title="Session Volume-Weighted Average Price">VWAP</button>
        <button className={showBb ? "mini on" : "mini"} onClick={() => setShowBb(!showBb)} title="Bollinger Bands (20, 2σ)">BB(20,2)</button>
        <button className={showVpvr ? "mini on" : "mini"} onClick={() => setShowVpvr(!showVpvr)} title="Volume Profile Visible Range">VPVR</button>
        <span className="sep">|</span>
        <button className={drawMode === "HLINE" ? "mini on" : "mini"} onClick={() => setDrawMode(drawMode === "HLINE" ? "" : "HLINE")}>+ S/R Line</button>
        <button className={drawMode === "FIB" ? "mini on" : "mini"} onClick={() => setDrawMode(drawMode === "FIB" ? "" : "FIB")}>+ Auto Fib</button>
        {annotations.length > 0 && <button className="mini" onClick={() => saveAnnotations([])}>Clear Drawings ({annotations.length})</button>}
        {activeOrders.length > 0 && (
          <>
            <span className="sep">|</span>
            <select
              aria-label="Move Order on Chart"
              value={selectedOrderId}
              onChange={(e) => { setSelectedOrderId(e.target.value); setDragFeedback(e.target.value ? "Click chart at desired price to move order" : ""); }}
              className="mini-sel"
            >
              <option value="">Move Working Order…</option>
              {activeOrders.map((o) => (
                <option key={o.order.id} value={o.order.id}>
                  {o.order.id} {o.order.side} {o.order.type} @ {px(o.order.limit_price ?? o.order.stop_price)}
                </option>
              ))}
            </select>
          </>
        )}
        {rsi14 !== null && <span className="kv" style={{ marginLeft: "auto" }}>RSI(14) <b className={rsi14 >= 70 ? "down" : rsi14 <= 30 ? "up" : ""}>{num(rsi14, 1)}</b></span>}
        {vpvr && <span className="kv">POC <b>{px(vpvr.pocPrice)}</b></span>}
      </div>

      <div className="chart-wrap" onClick={onChartClick}>
        {legend && (
          <div className="legend">
            <b className="sym">{secName(symbol)}</b>{" "}
            <span className="dim">O</span> {px(legend.open)} <span className="dim">H</span> {px(legend.high)}{" "}
            <span className="dim">L</span> {px(legend.low)} <span className="dim">C</span>{" "}
            <span className={legend.close >= legend.open ? "up" : "down"}>{px(legend.close)}</span>
            {showSma && <span style={{ color: "#38bdf8" }}> · SMA20</span>}
            {showEma && <span style={{ color: "#c084fc" }}> · EMA9</span>}
            {showVwap && <span style={{ color: "#ffd400" }}> · VWAP</span>}
            {(drawMode || selectedOrderId || dragFeedback) && (
              <span className="warn" style={{ marginLeft: 8 }}>
                {selectedOrderId ? `CLICK CHART TO MOVE ${selectedOrderId}` : drawMode ? `CLICK CHART TO PLACE ${drawMode}` : dragFeedback}
              </span>
            )}
          </div>
        )}
        {vpvr && (
          <div className="vpvr-overlay" aria-label="Volume Profile">
            {vpvr.buckets.map((b, i) => (
              <div key={i} className="vpvr-row" title={`Price ~${px(b.price)}`}>
                <div className={`vpvr-bar ${b.isPoc ? "poc" : ""}`} style={{ width: `${b.pct}%` }} />
              </div>
            ))}
          </div>
        )}
        <div ref={el} className="chart" data-testid="chart" data-bars={bars.length} />
        {bars.length === 0 && <div className="chart-empty dim">No bars yet: advance the clock in REPLAY.</div>}
      </div>
    </div>
  );
}
