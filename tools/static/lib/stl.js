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
