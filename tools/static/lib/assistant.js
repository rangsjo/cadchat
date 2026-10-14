// Presence of the assistant (the process that watches the viewer's messages) and delivery state labels.
export function ago(seconds) {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  const d = Math.floor(seconds / 86400);
  return `${d} day${d > 1 ? "s" : ""} ago`;
}

export function presence(s, now) {
  const waiting = s.pending ? `${s.pending} message${s.pending > 1 ? "s" : ""} waiting. ` : "";
  if (s.listening) return { level: "ok", text: "Assistant listening", detail: waiting.trim() };
  if (s.last_seen == null) return { level: "off", text: "Assistant not connected", detail: `${waiting}Your messages are saved. Ask Claude to start the message watch.` };
  return { level: "off", text: `Assistant not listening (last seen ${ago(now - s.last_seen)})`, detail: `${waiting}Your messages are saved and handled when it is back.` };
}

export const stateLabel = (state) => ({ queued: "sent", seen: "seen", working: "working on it" })[state] ?? "";
