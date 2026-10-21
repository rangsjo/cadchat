// First-start wizard: what the project can do, and how to connect an AI agent. Pure parts here, the dialog is in app.js.
export const TOUR = [
  { title: "Describe it, get a model", text: "Models are Python scripts (build123d). Ask in the chat, or write them: parts with named dimensions, joints that move, presets like open and folded." },
  { title: "Click and ask", text: "Click a part, press the chat button and say what to change: 'make this leg 60 mm'. The assistant edits the script, rebuilds and answers with the numbers." },
  { title: "Measure and check", text: "Measure between points, add section planes, see dimensions. Moving a joint checks collisions live, so a fold that hits something is flagged." },
  { title: "Woodworking joints", text: "Dowels, dados, rabbets, half laps and mortise and tenon cut both boards to fit with usual proportions. The Make tab gives the cut list and print plates." },
  { title: "Projects and history", text: "Each project keeps its models, its chat and every earlier build. Restore any version, save named ones, switch project from File." },
  { title: "Take it to the workshop", text: "File ▸ Export ▸ Workshop site makes a static page for your phone: views, dimensions, tap-to-measure and the cut list. No server needed." },
];

export function recommendProvider(providers, detected) {
  const hit = providers.find((p) => p.id !== "custom" && detected[p.id]?.installed);
  return hit ? hit.id : "claude";
}

export const recommendedMode = (provider) => (provider.listens ? "session" : "message");

export const needsWizard = (settings, assistant) => !settings.setup_done && !assistant?.listening;

export function summary(provider, mode, { command } = {}) {
  const who = provider.id === "custom" && command ? `${provider.name} (${command})` : provider.name;
  return mode === "message"
    ? `${who} runs once per message: each answer is a fresh run, nothing from earlier messages is resent.`
    : `${who} runs as a live session in a terminal, listens to the chat and keeps its context between messages.`;
}

export const canContinue = (provider, command) => provider.id !== "custom" || command.trim().length > 0;
