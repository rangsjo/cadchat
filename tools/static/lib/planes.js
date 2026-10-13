// Section planes: {id, name, axis 0|1|2 (x|y|z), pos mm, flip, show, clip}.
export function defaultPlanes({ min, max }) {
  const mid = (a) => (min[a] + max[a]) / 2;
  const names = ["Across length (x)", "Across depth (y)", "Across height (z)"];
  return [0, 1, 2].map((a) => ({ id: a + 1, name: names[a], axis: a, pos: Math.round(mid(a) * 10) / 10, flip: false, show: true, clip: false }));
}

/** three.js convention: points with normal.p + constant < 0 are discarded. */
export function clipPlane({ axis, pos, flip }) {
  const normal = [0, 0, 0];
  normal[axis] = flip ? 1 : -1;
  return { normal, constant: flip ? 0 - pos : pos };
}

export const storageKey = (modelId) => `cad.planes.${modelId}`;
