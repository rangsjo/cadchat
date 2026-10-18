// Token usage display helpers (pure; the data comes from /api/usage, see tools/usage.py).
export function fmtTokens(n) {
  if (n < 1000) return String(Math.round(n));
  if (n < 10000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  if (n < 1e6) return Math.round(n / 1000) + "k";
  if (n < 1e7) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  return Math.round(n / 1e6) + "M";
}

const iso = (d) => d.toISOString().slice(0, 10);
/** n entries ending at `end` (YYYY-MM-DD, UTC), oldest first; days without usage are zero rows. */
export function lastDays(days, n, end) {
  const by = new Map(days.map((d) => [d.date, d]));
  const t = Date.parse(end + "T00:00:00Z");
  return Array.from({ length: n }, (_, i) => {
    const date = iso(new Date(t - (n - 1 - i) * 86400000));
    return by.get(date) ?? { date, input: 0, output: 0, cache_read: 0, cache_creation: 0, messages: 0 };
  });
}

export function scale(values) {
  const m = Math.max(0, ...values);
  return values.map((v) => (m ? v / m : 0));
}

export function badgeText(r) {
  if (!r.sources) return "no assistant usage found";
  const out = `${fmtTokens(r.today.output)} out today`;
  return r.today.messages ? `${out} · ${Math.floor(r.cache_share * 100)}% cached` : out;
}

/** One day as stacked segments, bottom to top: written (output), new input (input + cache creation), cached input; heights sum to `height`. */
export function barSegments(d, max, height) {
  const parts = [["output", d.output], ["new", d.input + d.cache_creation], ["cache", d.cache_read]];
  const total = parts.reduce((a, [, v]) => a + v, 0);
  if (!total || !max) return [];
  const full = Math.round((total / max) * height);
  const raw = parts.map(([, v]) => (v / total) * full);
  const h = raw.map(Math.floor);
  let rest = full - h.reduce((a, b) => a + b, 0);
  for (const i of raw.map((v, k) => [v - Math.floor(v), k]).sort((a, b) => b[0] - a[0]).map((x) => x[1])) if (rest-- > 0) h[i]++;
  return parts.map(([kind], i) => ({ kind, h: h[i] })).filter((s) => s.h > 0);
}
