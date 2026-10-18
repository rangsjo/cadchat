// Floor grid sized to the model: cell size chosen from round numbers so the grid never has more than ~80 cells across the model.
const STEPS = [[10, 100], [25, 100], [50, 250], [100, 500], [250, 1000], [500, 2500], [1000, 5000]];

export function gridSpec(box) {
  const min = box?.min ?? [-300, -300, 0], max = box?.max ?? [300, 300, 0];
  const reach = Math.max(...[0, 1].map((i) => Math.max(Math.abs(min[i]), Math.abs(max[i])))) * 1.3;      // from the origin, plus a margin
  const width = Math.max(max[0] - min[0], max[1] - min[1], 300) * 1.5;
  const [cell, major] = STEPS.find(([c]) => width / c <= 80) ?? STEPS[STEPS.length - 1];
  const half = Math.max(Math.ceil(Math.max(reach, width / 2) / major), 1) * major;
  return { cell, major, size: 2 * half, z: Math.min(0, min[2]), label: `grid ${cell} mm` };
}
