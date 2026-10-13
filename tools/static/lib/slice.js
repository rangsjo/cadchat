// Slice an indexed triangle mesh with an axis-aligned plane into closed outlines.
// mesh = {positions: Float32Array, index: Uint32Array}; matrix = 16 numbers, column-major (three.js order).
const IN_PLANE = [[1, 2], [0, 2], [0, 1]];

export function sliceLoops(mesh, matrix, axis, pos) {
  const { positions, index } = mesh, m = matrix, n = positions.length / 3;
  const pts = new Array(n);
  for (let i = 0; i < n; i++) {
    const x = positions[3 * i], y = positions[3 * i + 1], z = positions[3 * i + 2];
    pts[i] = [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]];
  }
  const segs = [];
  for (let t = 0; t < index.length; t += 3) {
    const tri = [pts[index[t]], pts[index[t + 1]], pts[index[t + 2]]], hit = [];
    for (let e = 0; e < 3; e++) {
      const p = tri[e], q = tri[(e + 1) % 3], dp = p[axis] - pos, dq = q[axis] - pos;
      if ((dp < 0 && dq > 0) || (dp > 0 && dq < 0)) {
        const k = dp / (dp - dq);
        hit.push([0, 1, 2].map((c) => p[c] + (q[c] - p[c]) * k));
      }
    }
    if (hit.length === 2) segs.push(hit);
  }
  const key = (p) => p.map((c) => Math.round(c * 100)).join(",");
  const adj = new Map();
  segs.forEach((sg, i) => sg.forEach((p) => { const k = key(p); if (!adj.has(k)) adj.set(k, []); adj.get(k).push(i); }));
  const used = new Set(), loops = [];
  segs.forEach((sg, i) => {
    if (used.has(i)) return;
    used.add(i);
    const loop = [sg[0], sg[1]];
    for (let guard = 0; guard < segs.length + 2; guard++) {
      const end = loop[loop.length - 1], nxt = (adj.get(key(end)) || []).find((j) => !used.has(j));
      if (nxt === undefined) break;
      used.add(nxt);
      const [p, q] = segs[nxt];
      loop.push(key(p) === key(end) ? q : p);
    }
    if (loop.length > 3) loops.push(loop);
  });
  return loops;
}

/** Signed shoelace area of an outline in the plane perpendicular to `axis`. */
export function loopArea(loop, axis) {
  const [u, v] = IN_PLANE[axis];
  let a = 0;
  for (let i = 0; i < loop.length; i++) { const p = loop[i], q = loop[(i + 1) % loop.length]; a += (p[u] * q[v] - q[u] * p[v]) / 2; }
  return a;
}
