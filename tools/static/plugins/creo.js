// Creo Parametric link (experimental): a tab with the parameters and dimensions of the model open in Creo. Backend: tools/creo_api.py, link: tools/creolink.py.
const CSS = `.creo-row{display:grid;grid-template-columns:1fr 84px 38px;gap:4px 6px;align-items:center;margin:3px 2px}.creo-row small{display:block;color:var(--dim)}
.creo-row input{width:100%;background:#14161a;border:1px solid var(--line);color:var(--fg);border-radius:5px;padding:3px 5px;font:inherit}`;
const PANE = `<h4>Creo Parametric link <span style="font-weight:400;color:var(--dim);text-transform:none">(experimental)</span></h4>
  <div id="creoStat" style="margin:4px 2px"></div>
  <div id="creoBox" style="display:none">
    <div style="margin:6px 2px;color:var(--dim)">Model in Creo: <b id="creoModel" style="color:var(--fg)"></b> <span class="btn" id="creoShow" title="Show it in the viewer">View</span></div>
    <label style="color:var(--dim);margin:2px"><input type="checkbox" id="creoAuto" checked> sync to cadchat whenever the model changes in Creo</label>
    <div style="margin:6px 0"><span class="btn" id="creoSync">Sync now</span><span class="btn" id="creoRegen">Regenerate</span></div>
    <h4>Parameters and dimensions</h4>
    <div id="creoParams"></div>
    <div id="creoRes" style="color:var(--dim);margin:6px 2px"></div>
  </div>`;

export function mount({ addTab, switchModel }) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);
  const tab = addTab("creo", "Creo", PANE);
  const $ = (id) => document.getElementById(id);
  let creoState = null, creoSig = "";
  async function creoPoll() {
    try { creoState = await (await fetch("/api/creo")).json(); } catch (e) { return; }
    const c = creoState, sig = JSON.stringify([c.running, c.connected, c.model, c.params, c.last_result, c.last_error, c.auto_sync]);
    if (sig === creoSig) return;                       // nothing changed: keep the inputs the user may be typing in
    creoSig = sig;
    const stat = $("creoStat");
    if (!c.running) {
      stat.innerHTML = `<span class="dot" style="background:#9aa0a6"></span>Link not running. Start it on the Windows machine with Creo: <code>creo\\start.cmd</code> (see creo/README.md).`;
      $("creoBox").style.display = "none";
      return;
    }
    stat.innerHTML = c.connected ? `<span class="dot" style="background:#6bd66b"></span>Connected to Creo` : `<span class="dot" style="background:#e06666"></span>Link running, Creo not connected`;
    if (c.last_error) stat.innerHTML += `<div style="color:#ffb0a8;margin-top:4px">${c.last_error.replace(/</g, "&lt;")}</div>`;
    $("creoBox").style.display = c.connected ? "block" : "none";
    if (!c.connected) return;
    $("creoModel").textContent = c.model ?? "(no model open)";
    $("creoShow").style.display = c.model_id ? "" : "none";
    $("creoAuto").checked = !!c.auto_sync;
    const host = $("creoParams");
    host.innerHTML = "";
    (c.params || []).filter((p) => p.kind !== "note").forEach((p) => {
      const d = document.createElement("div");
      d.className = "creo-row";
      d.innerHTML = `<span>${p.name}<small>${p.kind}${p.type && p.type !== "double" ? " · " + p.type : ""}</small></span><input ${p.type === "string" ? 'type="text"' : 'type="number" step="any"'} value="${String(p.value ?? "").replace(/"/g, "&quot;")}"><span class="btn" title="Set in Creo, regenerate, sync">Set</span>`;
      const inp = d.querySelector("input"), go = () => creoCmd({ cmd: "set", name: p.name, value: p.type === "string" ? inp.value : +inp.value });
      d.querySelector(".btn").onclick = go;
      inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
      host.appendChild(d);
    });
    const r = c.last_result;
    $("creoRes").textContent = r ? `${r.ok ? "✓" : "✗"} ${r.cmd}: ${r.message}` : "";
    $("creoRes").style.color = r && !r.ok ? "#ffb0a8" : "";
  }
  async function creoCmd(body) {
    $("creoRes").textContent = "working…";
    creoSig = "";                                       // force a redraw when the result arrives
    const r = await (await fetch("/api/creo/command", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify(body) })).json();
    if (!r.ok) $("creoRes").textContent = "✗ " + r.error;
  }
  $("creoSync").onclick = () => creoCmd({ cmd: "sync" });
  $("creoRegen").onclick = () => creoCmd({ cmd: "regenerate" });
  $("creoAuto").onchange = (e) => creoCmd({ cmd: "auto_sync", value: e.target.checked });
  $("creoShow").onclick = () => { const id = creoState?.model_id; if (id) switchModel(id); };
  setInterval(creoPoll, 2000);
  creoPoll();
  setInterval(creoPoll, 2000);
  creoPoll();
  if (location.hash === "#creo") tab.click();
}
