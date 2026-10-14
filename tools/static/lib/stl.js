// ASCII STL from indexed meshes with a column-major 4x4 matrix each.
const num = (v) => String(+v.toFixed(6));

export function toAsciiStl(name, meshes) {
  const out = [`solid ${name}`];
  for (const { positions, index, matrix: m } of meshes) {
    const v = (i) => {
      const x = positions[3 * i], y = positions[3 * i + 1], z = positions[3 * i + 2];
      return [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]];
    };
    for (let t = 0; t < index.length; t += 3) {
      const a = v(index[t]), b = v(index[t + 1]), c = v(index[t + 2]);
      const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], w = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
      let n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
      const len = Math.hypot(...n);
      n = len > 1e-12 ? n.map((x) => x / len) : [0, 0, 0];
      out.push(`facet normal ${n.map(num).join(" ")}`, " outer loop");
      for (const p of [a, b, c]) out.push(`  vertex ${p.map(num).join(" ")}`);
      out.push(" endloop", "endfacet");
    }
  }
  out.push(`endsolid ${name}`);
  return out.join("\n") + "\n";
}

/** Binary STL (80 byte header, uint32 count, 50 bytes per triangle): ~5x smaller and much faster to build than ASCII. */
export function toBinaryStl(meshes) {
  let n = 0;
  for (const m of meshes) n += m.index.length / 3;
  const out = new Uint8Array(84 + 50 * n), dv = new DataView(out.buffer);
  dv.setUint32(80, n, true);
  let o = 84;
  const a = [0, 0, 0], b = [0, 0, 0], c = [0, 0, 0];
  for (const { positions: P, index, matrix: m } of meshes) {
    const put = (i, v) => {
      const x = P[3 * i], y = P[3 * i + 1], z = P[3 * i + 2];
      v[0] = m[0] * x + m[4] * y + m[8] * z + m[12]; v[1] = m[1] * x + m[5] * y + m[9] * z + m[13]; v[2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    };
    for (let t = 0; t < index.length; t += 3) {
      put(index[t], a); put(index[t + 1], b); put(index[t + 2], c);
      const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], wx = c[0] - a[0], wy = c[1] - a[1], wz = c[2] - a[2];
      let nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
      const len = Math.hypot(nx, ny, nz);
      if (len > 1e-12) { nx /= len; ny /= len; nz /= len; } else { nx = ny = nz = 0; }
      dv.setFloat32(o, nx, true); dv.setFloat32(o + 4, ny, true); dv.setFloat32(o + 8, nz, true);
      dv.setFloat32(o + 12, a[0], true); dv.setFloat32(o + 16, a[1], true); dv.setFloat32(o + 20, a[2], true);
      dv.setFloat32(o + 24, b[0], true); dv.setFloat32(o + 28, b[1], true); dv.setFloat32(o + 32, b[2], true);
      dv.setFloat32(o + 36, c[0], true); dv.setFloat32(o + 40, c[1], true); dv.setFloat32(o + 44, c[2], true);
      o += 50;                                                    // 48 bytes + 2 attribute bytes
    }
  }
  return out;
}
