// Part grouping by name, so any model gets sensible colours and labels without configuration.
const SUFFIX = /_(L|R|left|right|front|back|\d+)$/i;
const PALETTE = [0xd9a066, 0x6fa8dc, 0x93c47d, 0xe06666, 0xc27ba0, 0xf6b26b, 0x76a5af, 0xb4a7d6, 0xffd966, 0x8e7cc3, 0x6aa84f, 0xcc4125];

export function stem(name) {
  let s = name;
  while (SUFFIX.test(s)) s = s.replace(SUFFIX, "");
  return s || name;
}

export const roleOf = (part) => part.role || stem(part.name).split("_")[0];

const hsl = (h) => {            // overflow colours: evenly spread hues
  const c = (n) => { const k = (n + h / 30) % 12; return 0.6 - 0.35 * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  return (Math.round(c(0) * 255) << 16) | (Math.round(c(8) * 255) << 8) | Math.round(c(4) * 255);
};

export function roleColors(parts) {
  const out = new Map();
  for (const p of parts) {
    const r = roleOf(p);
    if (!out.has(r)) out.set(r, out.size < PALETTE.length ? PALETTE[out.size] : hsl((out.size * 47) % 360));
  }
  return out;
}
