// Model switcher decisions (pure, so they can be tested without a browser).
export function chooseModel({ models, latest, stored }) {
  if (stored && models.some((m) => m.id === stored)) return stored;
  if (latest) return latest;
  return models[0]?.id ?? null;
}

/** Which model was (re)published between two stamp maps? null on first load or when nothing changed. */
export function publishedSince(prev, next) {
  if (!prev) return null;
  let best = null;
  for (const [id, stamp] of Object.entries(next)) {
    if ((prev[id] === undefined || stamp > prev[id]) && (best === null || stamp > next[best])) best = id;
  }
  return best;
}
