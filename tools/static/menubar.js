// Menu bar and dialogs for the viewer. The menus come from lib/menu.js (data); this file draws them and runs the chosen action.
import { buildMenus } from "./lib/menu.js";

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

export function mountMenubar(host, getState, run) {
  let openIdx = -1, openMenus = [];
  const close = () => { openIdx = -1; host.querySelectorAll(".mb-drop").forEach((d) => d.remove()); host.querySelectorAll(".mb-top").forEach((b) => b.classList.remove("on")); };
  const draw = (items, parent) => {
    const box = el("div", "mb-drop");
    for (const it of items) {
      if (it.sep) { box.appendChild(el("div", "mb-sep")); continue; }
      const row = el("div", "mb-row" + (it.disabled ? " dis" : "") + (it.sub ? " has-sub" : ""));
      row.appendChild(el("span", "mb-chk", it.checked ? "✓" : ""));
      row.appendChild(el("span", "mb-lbl", it.label));
      if (it.shortcut) row.appendChild(el("span", "mb-key", it.shortcut));
      if (it.sub) {
        row.appendChild(el("span", "mb-arrow", "▸"));
        const open = () => { row.parentElement.querySelectorAll(":scope > .mb-row > .mb-drop").forEach((d) => d.remove()); const d = draw(it.sub, row); d.classList.add("sub"); row.appendChild(d); };
        row.onmouseenter = open;
        row.onclick = (e) => { e.stopPropagation(); open(); };
      } else if (!it.disabled) {
        row.onclick = (e) => { e.stopPropagation(); close(); run(it.id); };
      }
      box.appendChild(row);
    }
    return box;
  };
  const show = async (i) => {
    close();
    openIdx = i;
    const menus = buildMenus(await getState(i === 0));
    openMenus = menus;
    const b = host.querySelectorAll(".mb-top")[i];
    b.classList.add("on");
    const d = draw(menus[i].items, b);
    d.style.left = b.offsetLeft + "px";
    host.appendChild(d);
  };
  const labels = buildMenus({}).map((m) => m.label);
  host.innerHTML = "";
  labels.forEach((label, i) => {
    const b = el("div", "mb-top", label);
    b.onclick = (e) => { e.stopPropagation(); openIdx === i ? close() : show(i); };
    b.onmouseenter = () => { if (openIdx >= 0 && openIdx !== i) show(i); };
    host.appendChild(b);
  });
  addEventListener("click", close);
  addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  return { close };
}

// ---- dialogs ---------------------------------------------------------------------------------------------------------------------
export function dialog(title, body, buttons = [{ label: "Close" }]) {
  const wrap = el("div", "modal");
  const box = el("div", "mbox");
  box.appendChild(el("h3", "", title));
  const content = el("div", "mbody");
  if (typeof body === "string") content.innerHTML = body; else content.appendChild(body);
  box.appendChild(content);
  const bar = el("div", "mbtns");
  const close = () => wrap.remove();
  for (const b of buttons) {
    const x = el("span", "btn" + (b.primary ? " on" : ""), b.label);
    x.onclick = async () => { if (!b.onClick || (await b.onClick(content, close)) !== false) close(); };
    bar.appendChild(x);
  }
  box.appendChild(bar);
  wrap.appendChild(box);
  wrap.onclick = (e) => { if (e.target === wrap) close(); };
  document.body.appendChild(wrap);
  const first = content.querySelector("input,select");
  if (first) first.focus();
  return { close, content };
}

/** A one-field prompt; resolves with the text, or null when cancelled. */
export function ask(title, label, value = "", ok = "OK") {
  return new Promise((resolve) => {
    const d = dialog(title, `<label>${label}<input type="text" class="mfield" value="${value.replace(/"/g, "&quot;")}"></label>`, [
      { label: "Cancel", onClick: () => resolve(null) },
      { label: ok, primary: true, onClick: (c) => resolve(c.querySelector("input").value.trim() || null) },
    ]);
    d.content.querySelector("input").addEventListener("keydown", (e) => { if (e.key === "Enter") { resolve(e.target.value.trim() || null); d.close(); } });
  });
}
