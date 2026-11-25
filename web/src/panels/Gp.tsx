import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { Bar } from "../api";
import { num, px } from "../fmt";
import { useBars, useMarket, useTick } from "../store";

const PERIOD_S: Record<string, number> = { "1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800 };
const toTime = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp;
type C = { time: UTCTimestamp; open: number; high: number; low: number; close: number };
const candle = (b: Bar): C => ({
  time: toTime(b.ts), open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close),
});

export function Gp({ symbol }: { symbol: string }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const lastCandle = useRef<C | null>(null);
  const [legend, setLegend] = useState<C | null>(null);
  const bars = useBars(symbol);
  const { snapshot } = useMarket();
  const tick = useTick(symbol);
  const period = PERIOD_S[snapshot?.meta.freq ?? "1h"] ?? 3600;

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#000000" }, textColor: "#ffa028", fontFamily: "Consolas, monospace" },
      grid: { vertLines: { color: "#161616" }, horzLines: { color: "#161616" } },
      timeScale: { timeVisible: true, borderColor: "#5a3a10" },
      rightPriceScale: { borderColor: "#5a3a10" },
      crosshair: { vertLine: { color: "#ffa02880" }, horzLine: { color: "#ffa02880" } },
    });
    const s = c.addSeries(CandlestickSeries, {
      upColor: "#00d26a", downColor: "#ff3b3b", wickUpColor: "#00d26a", wickDownColor: "#ff3b3b", borderVisible: false,
    });
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
      lines.current = [];
    };
  }, [symbol]);

  useEffect(() => {
    const data = bars.map(candle);
    series.current?.setData(data);
    lastCandle.current = data[data.length - 1] ?? null;
    setLegend(lastCandle.current);
  }, [bars]);

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

  // fills as markers and working orders as price lines
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
            lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `${o.order.id} ${o.order.side} ${tag}`,
          }),
        );
      add(o.order.limit_price, "LMT");
      add(o.order.stop_price, "STP");
    }
  }, [snapshot, symbol, period]);

  return (
    <div className="chart-wrap">
      {legend && (
        <div className="legend">
          <span className="dim">O</span> {px(legend.open)} <span className="dim">H</span> {px(legend.high)}{" "}
          <span className="dim">L</span> {px(legend.low)} <span className="dim">C</span>{" "}
          <span className={legend.close >= legend.open ? "up" : "down"}>{px(legend.close)}</span>
        </div>
      )}
      <div ref={el} className="chart" data-testid="chart" data-bars={bars.length} />
      {bars.length === 0 && <div className="chart-empty dim">No bars yet: advance the clock in REPLAY.</div>}
    </div>
  );
}
