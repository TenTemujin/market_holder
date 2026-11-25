export function fmtChg(last: string, prev: string): { chg: number; pct: number } {
  const l = Number(last);
  const p = Number(prev);
  const chg = Number.isFinite(l - p) ? l - p : 0;
  return { chg, pct: p ? (chg / p) * 100 : 0 };
}
