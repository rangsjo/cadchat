// Which overlays the viewer draws on top of the model. All can be switched on and off; the state is kept in the browser.
export const DISPLAY_ITEMS = [
  { key: "grid", label: "Floor grid" },
  { key: "planes", label: "Section planes" },
  { key: "axes", label: "Joint axes" },
  { key: "links", label: "Connections" },
  { key: "jointLabels", label: "Joint labels" },
  { key: "dims", label: "Dimension labels" },
  { key: "info", label: "Info bar" },
  { key: "badge", label: "Assistant badge" },
];

export const defaultDisplay = () => Object.fromEntries(DISPLAY_ITEMS.map((i) => [i.key, true]));

export function toggled(state, key) {
  if (!(key in defaultDisplay())) throw new Error(`unknown display item: ${key}`);
  return { ...state, [key]: !state[key] };
}

export const saveDisplay = (state) => JSON.stringify(state);

export function loadDisplay(text) {
  const out = defaultDisplay();
  try {
    const raw = JSON.parse(text);
    for (const k of Object.keys(out)) if (typeof raw?.[k] === "boolean") out[k] = raw[k];
  } catch (e) { /* no or damaged setting: defaults */ }
  return out;
}

export function preset(name) {
  if (name === "all") return defaultDisplay();
  if (name === "clean") return Object.fromEntries(DISPLAY_ITEMS.map((i) => [i.key, false]));
  throw new Error(`unknown preset: ${name}`);
}

/** The dimension/measurement overlay is drawn when dimension labels are on, and always while a measurement is being made. */
export const overlayVisible = (state, measuring) => state.dims || measuring;
