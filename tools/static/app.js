import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { roleColors, roleOf } from "./lib/roles.js";
import { groupParts, orientation, gridLayout, bedCheck, packPlates } from "./lib/layout.js";
import { sliceLoops as sliceCore } from "./lib/slice.js";
import { toBinaryStl } from "./lib/stl.js";
import { decodeMesh } from "./lib/mesh.js";
import { defaultPlanes as defaultPlanesFor, clipPlane, storageKey } from "./lib/planes.js";
import { chooseModel, publishedSince } from "./lib/models.js";
import { presence, stateLabel } from "./lib/assistant.js";
import { DISPLAY_ITEMS, loadDisplay, saveDisplay, toggled, preset, overlayVisible } from "./lib/display.js";
import { mountMenubar, dialog, ask } from "./menubar.js";
import { toAsciiStl } from "./lib/stl.js";
import { gridSpec } from "./lib/grid.js";
import { TOUR, recommendProvider, recommendedMode, needsWizard, summary, canContinue } from "./lib/wizard.js";
import { fmtTokens, lastDays, scale, badgeText, barSegments } from "./lib/usage.js";

const $ = (id) => document.getElementById(id);
// If the server was restarted with a new token (an old version without a persisted token), reload once to pick it up.
const rawFetch = window.fetch.bind(window);
let reloading = false;
window.fetch = async (...a) => {
  const r = await rawFetch(...a);
  if (r.status === 403 && !reloading) { reloading = true; location.reload(); }
  return r;
};
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(devicePixelRatio);
$("view").appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x2b2d31);
const camera = new THREE.PerspectiveCamera(35, 1, 10, 100000);
camera.up.set(0, 0, 1);
camera.position.set(3000, -3000, 2200);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 350);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(2000, -3000, 4000);
scene.add(sun);
// floor grid: sized to the model (lib/grid.js): fine cells with brighter lines every few cells and the axes through the origin
let grid = new THREE.Group();
scene.add(grid);
function rebuildGrid() {
  const b = meshes.length ? boxOf(meshes) : null, g = gridSpec(b ? { min: b.min.toArray(), max: b.max.toArray() } : null);
  scene.remove(grid);
  grid = new THREE.Group();
  const fine = new THREE.GridHelper(g.size, Math.round(g.size / g.cell), 0x555a62, 0x34373d);
  const coarse = new THREE.GridHelper(g.size, Math.round(g.size / g.major), 0x6a707a, 0x555a62);
  for (const h of [fine, coarse]) { h.rotation.x = Math.PI / 2; h.material.transparent = true; grid.add(h); }
  fine.material.opacity = 0.55; coarse.material.opacity = 0.9; coarse.position.z = 0.3;
  grid.position.z = g.z - 0.5;
  scene.add(grid);
  $("gridNote").textContent = g.label + (g.z ? ` · floor at z ${Math.round(g.z)}` : "");
  grid.visible = disp.grid && !layoutMode;
  $("gridNote").style.display = grid.visible ? "" : "none";
}
scene.add(new THREE.AxesHelper(300));

// ---------------------------------------------------------------- state
let model = null, curModel = null, modelStamp = 0, stamps = null, modelList = [];
let roleCol = new Map();
let process = "wood", bed = { x: 220, y: 220, z: 250 };
let group = new THREE.Group();
scene.add(group);
let meshes = [], byName = {}, jointsByName = {};
const values = {};            // joint angles, degrees
const selected = new Set();
let selPoint = null, selNormal = null;
let isolate = false, showDims = false, measureMode = false, autoOpenChat = true;
let colorMode = "role", showAxes = true, showLinks = true, activeCon = null;
let disp = loadDisplay((() => { try { return localStorage.getItem("cad.display"); } catch (e) { return null; } })());
let collisions = [], activeTab = "pose";
let inspectMode = false, inspG = null;
let layoutMode = false, layoutMeshes = [], layoutGroups = [], layoutLabels = [], layoutObj = null;
const overlay = new THREE.Group();      // dims + measurement
const kinOverlay = new THREE.Group();   // joint axes + connection links
scene.add(overlay, kinOverlay);
let labels = [];                        // {el, pos(Vector3) | fn}
let mPts = [];
const fmt = (v) => v.toFixed(1);

const KIND = { revolute: 0x4fc3f7, fixed: 0x81c784, dimension: 0xce93d8 };
const JOINT_COL = [0x4fa3ff, 0x2ee6c4, 0xff9f43, 0xff5fa2, 0xb388ff, 0xffe066, 0x7bd88f, 0xff7a7a];
const css = (c) => "#" + c.toString(16).padStart(6, "0");

function resize() {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.setViewOffset(innerWidth, innerHeight, -175, 0, innerWidth, innerHeight);   // centre the scene right of the side panel
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();

// ---------------------------------------------------------------- kinematics
function jointMatrix(name) {            // rotation of one joint about its (base-frame) axis
  const j = jointsByName[name];
  const o = new THREE.Vector3(...j.origin), ax = new THREE.Vector3(...j.axis).normalize();
  if (j.type === "prismatic") return new THREE.Matrix4().makeTranslation(...ax.multiplyScalar(values[name] ?? 0).toArray());
  const a = ((values[name] ?? 0) * Math.PI) / 180;
  return new THREE.Matrix4().makeTranslation(o.x, o.y, o.z)
    .multiply(new THREE.Matrix4().makeRotationAxis(ax, a))
    .multiply(new THREE.Matrix4().makeTranslation(-o.x, -o.y, -o.z));
}
function chainMatrix(name) {            // leaf joint first, then parents: M = R_parent * ... * R_leaf
  const M = new THREE.Matrix4();
  for (let j = name; j; j = jointsByName[j].parent) M.premultiply(jointMatrix(j));
  return M;
}
function driveMimics() {            // coupled joints follow their driver (piecewise-linear table)
  model.joints.forEach((j) => {
    if (!j.mimic) return;
    const t = j.mimic.table, x = values[j.mimic.of] ?? 0;
    let y = x <= t[0][0] ? t[0][1] : t[t.length - 1][1];
    for (let i = 1; i < t.length; i++) if (x <= t[i][0]) { y = t[i - 1][1] + ((t[i][1] - t[i - 1][1]) * (x - t[i - 1][0])) / (t[i][0] - t[i - 1][0]); break; }
    values[j.name] = y;
  });
}
function applyPose() {
  const tp = performance.now();
  driveMimics();
  meshes.forEach((m) => {
    m.matrix.copy(m.userData.joint ? chainMatrix(m.userData.joint) : new THREE.Matrix4());
    m.matrixWorldNeedsUpdate = true;
  });
  group.updateMatrixWorld(true);
  updateKin();
  updateInfo();
  drawDims();
  rebuildCaps();
  perf.pose = performance.now() - tp;
}

// ---------------------------------------------------------------- build
function partColor(m) {
  const n = m.userData.part.name;
  if (colorMode === "role") return roleCol.get(roleOf(m.userData.part)) ?? 0xd9a066;
  const j = m.userData.joint;
  if (!j) return 0x6f7782;                                   // fixed to the frame
  return JOINT_COL[model.joints.findIndex((x) => x.name === j) % JOINT_COL.length];
}
function restyle() {
  const hit = new Set(collisions.flatMap((c) => [c[0], c[1]]));
  meshes.forEach((m) => {
    m.material.color.setHex(hit.has(m.userData.part.name) ? 0xe04a3a : partColor(m));
    const on = selected.has(m) || (activeCon && activeCon.parts.includes(m.userData.part.name));
    m.material.emissive.setHex(on ? 0x553300 : 0);
    m.userData.row?.classList.toggle("sel", selected.has(m));
    m.visible = !isolate || selected.size === 0 || selected.has(m);
  });
  layoutMeshes.forEach((lm) => {
    const g = lm.userData.group, on = g.meshes.some((m) => selected.has(m));
    lm.material.color.setHex(g.meshes.some((m) => hit.has(m.userData.part.name)) ? 0xe04a3a : partColor(g.meshes[0]));
    lm.material.emissive.setHex(on ? 0x553300 : 0);
    lm.userData.row?.classList.toggle("sel", on);
  });
  const lg = $("legend");
  lg.innerHTML = "";
  const items = colorMode === "role"
    ? [...roleCol].map(([r, c]) => [r, c])
    : [["Fixed to the frame", 0x6f7782], ...model.joints.map((j, i) => [`Moves with ${j.label}`, JOINT_COL[i % JOINT_COL.length]])];
  items.push(["Collision", 0xe04a3a]);
  items.forEach(([t, c]) => { const d = document.createElement("div"); d.innerHTML = `<span class="chip" style="background:${css(c)}"></span>${t}`; lg.appendChild(d); });
  document.querySelectorAll("#colors .btn").forEach((b) => b.classList.toggle("on", b.dataset.m === colorMode));
  $("tIso").classList.toggle("on", isolate);
  $("tDim").classList.toggle("on", showDims);
  $("tMeas").classList.toggle("on", measureMode);
}

function build() {
  const keep = new Set([...selected].map((m) => m.userData.part.name));
  scene.remove(group);
  group = new THREE.Group();
  scene.add(group);
  meshes = []; byName = {}; selected.clear();
  roleCol = roleColors(model.parts);
  jointsByName = Object.fromEntries(model.joints.map((j) => [j.name, j]));
  for (const p of model.parts) {
    const g = new THREE.BufferGeometry();
    const mesh = decodeMesh(p.v64, p.t64);
    g.setAttribute("position", new THREE.BufferAttribute(mesh.positions, 3));
    g.setIndex(new THREE.BufferAttribute(mesh.index, 1));
    g.computeVertexNormals();
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xd9a066, roughness: 0.7, metalness: 0.05 }));
    m.matrixAutoUpdate = false;
    m.userData = { part: p, joint: p.joint };
    m.add(new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color: 0x20160c })));
    group.add(m);
    meshes.push(m);
    byName[p.name] = m;
  }
  $("count")?.remove();
  const list = $("parts");
  list.innerHTML = "";
  meshes.forEach((m) => {
    const d = document.createElement("div");
    d.className = "row";
    d.textContent = m.userData.part.name;
    d.onclick = (e) => {
      if (e.shiftKey || e.ctrlKey || e.metaKey) toggle(m); else setSelection([m]);
      if (isolate) fitSelection();
    };
    m.userData.row = d;
    list.appendChild(d);
  });
  meshes.filter((m) => keep.has(m.userData.part.name)).forEach((m) => selected.add(m));
  buildKin();
  restyle();
  applyPose();
  buildLayout();
  if (!planesLoaded) loadPlanes();
  applySection();
  syncPlaneEditor();
}

// ---------------------------------------------------------------- joint axes + connection links
let axisObjs = [], linkObjs = [];
function buildKin() {
  kinOverlay.clear();
  axisObjs = []; linkObjs = [];
  model.joints.forEach((j, i) => {
    const col = JOINT_COL[i % JOINT_COL.length];
    const o = new THREE.Vector3(...j.origin), ax = new THREE.Vector3(...j.axis).normalize();
    const len = Math.abs(ax.z) > 0.5 ? 260 : 800;
    const geo = new THREE.BufferGeometry().setFromPoints([o.clone().addScaledVector(ax, -len / 2), o.clone().addScaledVector(ax, len / 2)]);
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: col, depthTest: false, linewidth: 2 }));
    line.renderOrder = 5;
    line.matrixAutoUpdate = false;
    const dot = new THREE.Mesh(new THREE.SphereGeometry(12, 12, 8), new THREE.MeshBasicMaterial({ color: col, depthTest: false }));
    dot.position.copy(o); dot.renderOrder = 6;
    const holder = new THREE.Group();
    holder.matrixAutoUpdate = false;
    holder.add(line, dot);
    kinOverlay.add(holder);
    axisObjs.push({ j, holder, origin: o });
    addLabelEntry({ el: mkLabel(`${j.label}`, "j"), pos: new THREE.Vector3(), joint: j, origin: o, holder });
  });
  (model.constraints || []).forEach((c) => {
    if (!c.a || !c.b || !byName[c.a] || !byName[c.b]) return;
    const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
    const mat = new THREE.LineDashedMaterial({ color: KIND[c.kind] ?? 0xffffff, dashSize: 14, gapSize: 9, depthTest: false });
    const line = new THREE.Line(geo, mat);
    line.renderOrder = 4;
    line.frustumCulled = false;
    kinOverlay.add(line);
    linkObjs.push({ c, line });
  });
}
function mkLabel(text, cls = "") {
  const el = document.createElement("div");
  el.className = "lb " + cls;
  el.textContent = text;
  $("labels").appendChild(el);
  return el;
}
let kinLabels = [];
function addLabelEntry(l) { kinLabels.push(l); }
const centerOf = (m) => new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3());
function updateKin() {
  axisObjs.forEach(({ j, holder }) => {
    holder.matrix.copy(j.parent ? chainMatrix(j.parent) : new THREE.Matrix4());
    holder.matrixWorldNeedsUpdate = true;
    holder.visible = showAxes && (!activeCon || activeCon.joint === j.name || !activeCon.joint);
  });
  linkObjs.forEach(({ c, line }) => {
    const a = centerOf(byName[c.a]), b = centerOf(byName[c.b]);
    line.geometry.setFromPoints([a, b]);
    line.computeLineDistances();
    line.visible = showLinks && (!activeCon || activeCon === c);
  });
  kinLabels.forEach((l) => {
    const mat = l.holder.matrix;
    l.pos.copy(l.origin).applyMatrix4(mat);
    l.el.style.opacity = showAxes ? 1 : 0;
    l.el.textContent = `${l.joint.label}: ${Math.round(values[l.joint.name] ?? 0)}${unitOf(l.joint.name)}`;
    l.hidden = !showAxes || !disp.jointLabels || (activeTab !== "cons" && !activeCon) || (activeCon && activeCon.joint && activeCon.joint !== l.joint.name);
  });
}

// ---------------------------------------------------------------- camera
function boxOf(objs) {
  const b = new THREE.Box3();
  objs.forEach((o) => b.union(new THREE.Box3().setFromObject(o, true)));
  return b;
}
const visibleMeshes = () => (layoutMode ? layoutMeshes : meshes.filter((m) => m.visible));
function fitBox(box, dir, k = 2.1) {
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length();
  const d = dir ? dir.clone().normalize() : camera.position.clone().sub(controls.target).normalize();
  controls.target.copy(c);
  camera.position.copy(c).addScaledVector(d, Math.max(r * k, 200));
  controls.update();
}
const fit = () => fitBox(boxOf(visibleMeshes()));
const fitSelection = () => fitBox(boxOf(selected.size ? [...selected] : visibleMeshes()));
const look = (x, y, z) => fitBox(boxOf(selected.size && isolate ? [...selected] : visibleMeshes()), new THREE.Vector3(x, y, z));
const VIEW_FN = { iso: () => look(0.6, -0.6, 0.5), top: () => look(0, -0.001, 1), front: () => look(0, -1, 0.05), side: () => look(1, 0, 0.05), fit: () => fitSelection() };

// ---------------------------------------------------------------- selection
function setSelection(list, point = null, normal = null) {
  selected.clear(); list.forEach((m) => selected.add(m));
  selPoint = point; selNormal = normal; activeCon = null; refreshSel();
}
function toggle(m, point = null, normal = null) {
  selected.has(m) ? selected.delete(m) : selected.add(m);
  selPoint = point; selNormal = normal; refreshSel();
}
function refreshSel() {
  restyle(); updateInfo(); drawDims(); updateKin(); markCons();
  const n = selected.size;
  $("ctitle").textContent = n === 0 ? "Chat with Claude" : n === 1 ? `About: ${[...selected][0].userData.part.name}` : `About: ${n} parts`;
}
function updateInfo() {
  if (layoutMode && selected.size) {
    const gs = layoutGroups.filter((g) => g.meshes.some((m) => selected.has(m)));
    $("infotxt").textContent = gs.map((g) => `${g.label}: ${g.dims.map((v) => fmt(v)).join(" × ")} mm (L × W × T), ${g.qty} pcs, ${(g.part.volume / 1000).toFixed(1)} cm³ each`).join("  |  ");
    return;
  }
  if (activeCon) { $("infotxt").textContent = `${activeCon.label} — ${activeCon.expr}` + (activeCon.params?.length ? `  [params: ${activeCon.params.join(", ")}]` : ""); return; }
  const sel = selected.size ? [...selected] : visibleMeshes();
  if (!sel.length) { $("infotxt").textContent = "Nothing to show."; return; }
  const s = boxOf(sel).getSize(new THREE.Vector3());
  const vol = sel.reduce((a, m) => a + m.userData.part.volume, 0) / 1000;
  const dims = `${fmt(s.x)} × ${fmt(s.y)} × ${fmt(s.z)} mm`;
  let t;
  if (!selected.size) t = `Whole model: ${dims} (current pose) · ${sel.length} parts · ${vol.toFixed(0)} cm³`;
  else if (selected.size === 1) {
    const m = sel[0], j = m.userData.joint;
    t = `${m.userData.part.name}: ${dims} · ${vol.toFixed(1)} cm³ · ${j ? "moves with " + jointsByName[j].label : "fixed to the frame"}` + (selPoint ? ` · point (${selPoint.map(fmt).join(", ")})` : "");
  } else t = `${selected.size} parts selected: bounding box ${dims} · ${vol.toFixed(0)} cm³`;
  $("infotxt").textContent = t;
}

// ---------------------------------------------------------------- dimensions + measuring overlay
function clearOverlay() { overlay.clear(); labels.forEach((l) => l.el.remove()); labels = []; }
function addLabel(text, pos, cls = "") { labels.push({ el: mkLabel(text, cls), pos: pos.clone() }); }
function drawDims() {
  clearOverlay();
  if (showDims) {
    const sel = selected.size ? [...selected] : visibleMeshes();
    if (sel.length) {
      const b = boxOf(sel), s = b.getSize(new THREE.Vector3()), { min, max } = b;
      overlay.add(new THREE.Box3Helper(b, 0xffd27a));
      addLabel(fmt(s.x), new THREE.Vector3((min.x + max.x) / 2, min.y, min.z));
      addLabel(fmt(s.y), new THREE.Vector3(max.x, (min.y + max.y) / 2, min.z));
      addLabel(fmt(s.z), new THREE.Vector3(max.x, max.y, (min.z + max.z) / 2));
    }
  }
  const r = Math.max(6, camera.position.distanceTo(controls.target) * 0.008);
  mPts.forEach((p) => {
    const s = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 8), new THREE.MeshBasicMaterial({ color: 0x7ad0ff, depthTest: false }));
    s.position.copy(p); s.renderOrder = 10; overlay.add(s);
  });
  if (mPts.length === 2) {
    const [a, b] = mPts, d = b.clone().sub(a);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0x7ad0ff, depthTest: false }));
    line.renderOrder = 10; overlay.add(line);
    addLabel(`${fmt(d.length())} mm  (Δx ${fmt(d.x)}, Δy ${fmt(d.y)}, Δz ${fmt(d.z)})`, a.clone().add(b).multiplyScalar(0.5), "m");
  }
}
function snap(hit) {
  const m = hit.object, pos = m.geometry.attributes.position, f = hit.face;
  const limit = camera.position.distanceTo(hit.point) * 0.03;
  let best = hit.point.clone(), bd = limit;
  for (const i of [f.a, f.b, f.c]) {
    const v = new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
    const d = v.distanceTo(hit.point);
    if (d < bd) { bd = d; best = v; }
  }
  return best;
}

// ---------------------------------------------------------------- picking
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
function pick(ev) {
  mouse.set((ev.clientX / innerWidth) * 2 - 1, -(ev.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  return ray.intersectObjects(visibleMeshes(), false)[0];
}
let down = null;
renderer.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener("pointerup", (e) => {
  if (inspectMode) {                       // click the part in the 3D cell to place the cross section there
    const r = viewRects()[3];
    if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) <= 4 && inRect(e, r) && inspMesh) {
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.x) / r.w) * 2 - 1, -((e.clientY - r.y) / r.h) * 2 + 1), icam);
      const h = ray.intersectObject(inspMesh, false)[0];
      if (h) {
        const lo = inspBox.min.getComponent(secAxis), hi = inspBox.max.getComponent(secAxis);
        secFrac = Math.min(1, Math.max(0, (h.point.getComponent(secAxis) - lo) / (hi - lo)));
        $("secPos").value = Math.round(secFrac * 100);
        buildSection();
      }
    }
    return;
  }
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const hit = pick(e);
  if (measureMode) {
    if (!hit) { $("infotxt").textContent = "Measure: that click missed the model, click on a part."; return; }
    if (mPts.length >= 2) mPts = [];
    mPts.push(snap(hit)); drawDims();
    $("infotxt").textContent = mPts.length === 2 ? `Distance ${fmt(mPts[0].distanceTo(mPts[1]))} mm` : "Measure: now click the second point.";
    return;
  }
  if (layoutMode) {
    if (!hit) { setSelection([]); return; }
    setSelection(hit.object.userData.group.meshes);
    return;
  }
  if (secPicking && hit && selPlane) { setSecPos(Math.round(hit.point.getComponent(selPlane.axis))); secPicking = false; $("secPick").classList.remove("on"); return; }
  const multi = e.shiftKey || e.ctrlKey || e.metaKey;
  if (!hit) { if (!multi) setSelection([]); return; }
  const m = hit.object, n = hit.face.normal.clone().transformDirection(m.matrixWorld);
  const point = hit.point.toArray().map((v) => +v.toFixed(1)), normal = [n.x, n.y, n.z].map((v) => +v.toFixed(2));
  multi ? toggle(m, point, normal) : setSelection([m], point, normal);
  if (autoOpenChat && !multi) openChat(e.clientX + 16, e.clientY + 16);
});
renderer.domElement.addEventListener("pointermove", (e) => {
  const tip = $("tip");
  if (inspectMode) { tip.style.display = "none"; return; }
  const hit = pick(e);
  if (hit) { tip.style.display = "block"; tip.style.left = e.clientX + 12 + "px"; tip.style.top = e.clientY + 12 + "px"; tip.textContent = hit.object.userData.part.name; }
  else tip.style.display = "none";
});

// ---------------------------------------------------------------- tools
function setMeasure(on) {
  measureMode = on; if (!on) mPts = [];
  renderer.domElement.style.cursor = on ? "crosshair" : "";
  restyle(); drawDims(); applyDisplay();
  if (on) $("infotxt").textContent = "Measure: click a corner or point on the model, then a second one (clicks snap to corners). Esc or M ends.";
}
$("tIso").onclick = () => { isolate = !isolate; restyle(); fitSelection(); };
$("tDim").onclick = () => { showDims = !showDims; restyle(); drawDims(); };
$("tMeas").onclick = () => setMeasure(!measureMode);
$("tClear").onclick = () => { mPts = []; setMeasure(false); setSelection([]); };
function step(dir) {
  if (inspectMode) { const i = layoutGroups.indexOf(inspG); inspect(layoutGroups[(i + dir + layoutGroups.length) % layoutGroups.length]); return; }
  const cur = selected.size === 1 ? meshes.indexOf([...selected][0]) : -1;
  setSelection([meshes[(cur + dir + meshes.length) % meshes.length]]);
  if (isolate) fitSelection();
}
$("prev").onclick = () => step(-1);
$("next").onclick = () => step(1);
$("ask").onclick = () => openChat();
// ---------------------------------------------------------------- display toggles (the eye button, key H)
function applyDisplay() {
  showAxes = disp.axes; showLinks = disp.links;
  grid.visible = disp.grid && !layoutMode;
  $("gridNote").style.display = grid.visible ? "" : "none";
  planeGroup.visible = disp.planes && !layoutMode;
  overlay.visible = overlayVisible(disp, measureMode);                      // a measurement is always shown while measuring
  $("info").style.visibility = disp.info ? "" : "hidden";
  $("apill").style.display = disp.badge ? "" : "none";
  $("sAxes")?.classList.toggle("on", disp.axes); $("sLinks")?.classList.toggle("on", disp.links);
  DISPLAY_ITEMS.forEach((i) => { const c = $("d-" + i.key); if (c) c.checked = disp[i.key]; });
  try { localStorage.setItem("cad.display", saveDisplay(disp)); } catch (e) { /* private mode */ }
  if (model) updateKin();
}
function setDisp(next) { disp = next; applyDisplay(); }
DISPLAY_ITEMS.forEach((i) => {
  const l = document.createElement("label");
  l.innerHTML = `<input type="checkbox" id="d-${i.key}"> ${i.label}`;
  l.querySelector("input").onchange = () => setDisp(toggled(disp, i.key));
  $("dispItems").appendChild(l);
});
$("dispBtn").onclick = () => { const m = $("dispMenu"); m.style.display = m.style.display === "none" ? "block" : "none"; };
$("dispAll").onclick = () => setDisp(preset("all"));
$("dispClean").onclick = () => setDisp(preset("clean"));
addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") { if (e.key === "Escape") e.target.blur(); return; }
  const k = e.key.toLowerCase();
  if (k === "i") $("tIso").click();
  else if (k === "d") $("tDim").click();
  else if (k === "m") $("tMeas").click();
  else if (k === "s") $("tSec").click();
  else if (k === "a") setSelection([...meshes]);
  else if (k === "arrowleft") step(-1);
  else if (k === "arrowright") step(1);
  else if (k === "escape") $("tClear").click();
  else if (k === "1") VIEW_FN.iso();
  else if (k === "2") VIEW_FN.top();
  else if (k === "3") VIEW_FN.front();
  else if (k === "4") VIEW_FN.side();
  else if (k === "f") VIEW_FN.fit();
  else if (k === "g") setDisp(toggled(disp, "grid"));
  else if (k === "h") setDisp(Object.values(disp).some(Boolean) ? preset("clean") : preset("all"));
});

// ---------------------------------------------------------------- tabs
document.querySelectorAll("#tabs div").forEach((t) => (t.onclick = () => {
  document.querySelectorAll("#tabs div").forEach((x) => x.classList.toggle("on", x === t));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "p-" + t.dataset.p));
  activeTab = t.dataset.p;
  setLayout(activeTab === "make");
  updateKin();
}));

// ---------------------------------------------------------------- pose: presets + sliders + collisions
function buildPoseUI() {
  $("presets").innerHTML = "";
  Object.keys(model.presets).forEach((n) => {
    const b = document.createElement("span");
    b.className = "btn"; b.textContent = n;
    b.onclick = () => { Object.assign(values, model.presets[n]); syncSliders(); applyPose(); scheduleCheck(); };
    $("presets").appendChild(b);
  });
  const host = $("joints");
  host.innerHTML = "";
  let grp = null;
  model.joints.forEach((j, i) => {
    if (j.mimic) return;                                                    // driven by another joint: no slider of its own
    if (j.group !== grp) { grp = j.group; const h = document.createElement("h4"); h.textContent = grp; host.appendChild(h); }
    const d = document.createElement("div");
    d.className = "sl";
    d.innerHTML = `<label><span><span class="chip" style="background:${css(JOINT_COL[i % JOINT_COL.length])}"></span>${j.label}</span><b id="v-${j.name}">0°</b></label>
      <input type="range" id="s-${j.name}" min="${j.min}" max="${j.max}" step="1" value="${values[j.name] ?? 0}">`;
    host.appendChild(d);
    d.querySelector("input").oninput = (e) => {
      const v = +e.target.value;
      setJoint(j.name, v);
      if ($("link").checked) {
        const twin = j.name.endsWith("_R") ? j.name.slice(0, -1) + "L" : j.name.endsWith("_L") ? j.name.slice(0, -1) + "R" : null;
        if (twin && jointsByName[twin]) setJoint(twin, v);
      }
      applyPose(); scheduleCheck();
    };
  });
  syncSliders();
}
const unitOf = (name) => (jointsByName[name]?.type === "prismatic" ? " mm" : "°");
function setJoint(name, v) { values[name] = v; const s = $("s-" + name); if (s) s.value = v; const l = $("v-" + name); if (l) l.textContent = Math.round(v) + unitOf(name); }
function syncSliders() { model.joints.forEach((j) => setJoint(j.name, values[j.name] ?? 0)); }
let checkTimer = null, checkSeq = 0;
function scheduleCheck() { $("coll").textContent = "Checking collisions…"; $("coll").className = ""; clearTimeout(checkTimer); checkTimer = setTimeout(runCheck, 250); }
async function runCheck() {
  const seq = ++checkSeq, tc = performance.now();
  try {
    const res = await fetch("/api/check", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify({ m: curModel, values }) });
    if (res.status === 403) { location.reload(); return; }          // the server was restarted and issued a new token
    const r = await res.json();
    if (seq !== checkSeq) return;
    if (!r.ok) { $("coll").textContent = "Collision check failed: " + r.error; $("coll").className = "bad"; return; }
    collisions = r.collisions; perf.check = performance.now() - tc;
    const c = $("coll");
    if (!collisions.length) { c.className = ""; c.textContent = "✓ No collisions in this pose"; }
    else { c.className = "bad"; c.innerHTML = `⚠ ${collisions.length} collision${collisions.length > 1 ? "s" : ""}<br>` + collisions.slice(0, 6).map((x) => `${x[0]} × ${x[1]} (${(x[2] / 1000).toFixed(1)} cm³)`).join("<br>"); }
    restyle();
  } catch (e) { /* server busy */ }
}

// ---------------------------------------------------------------- constraints panel
function markCons() { document.querySelectorAll("#cons .con").forEach((d) => d.classList.toggle("sel", activeCon && d.dataset.id === activeCon.id)); }
function buildConsUI() {
  $("colors").innerHTML = "";
  [["role", "Role"], ["joint", "Mobility"]].forEach(([m, t]) => {
    const b = document.createElement("span");
    b.className = "btn"; b.dataset.m = m; b.textContent = t;
    b.onclick = () => { colorMode = m; restyle(); };
    $("colors").appendChild(b);
  });
  const host = $("cons");
  host.innerHTML = "";
  const cons = model.constraints || [];
  $("ccount").textContent = `(${cons.length})`;
  ["revolute", "fixed", "dimension"].forEach((k) => {
    const list = cons.filter((c) => c.kind === k);
    if (!list.length) return;
    const h = document.createElement("h4");
    h.innerHTML = `<span class="chip" style="background:${css(KIND[k])}"></span>${{ revolute: "Joints (movable)", fixed: "Fixed connections", dimension: "Parametric relations" }[k]} (${list.length})`;
    host.appendChild(h);
    list.forEach((c) => {
      const d = document.createElement("div");
      d.className = "con"; d.dataset.id = c.id;
      d.style.setProperty("--k", css(KIND[k]));
      d.innerHTML = `${c.label}<small>${c.expr}</small>`;
      d.onclick = () => {
        if (activeCon === c) { activeCon = null; restyle(); updateInfo(); updateKin(); markCons(); return; }
        activeCon = c;
        selected.clear();
        restyle(); updateInfo(); updateKin(); markCons();
        fitBox(boxOf(c.parts.map((n) => byName[n]).filter(Boolean)));
      };
      host.appendChild(d);
    });
  });
  const lk = (id, flag) => { $(id).onclick = () => { flag(); $(id).classList.toggle("on"); updateKin(); }; };
  lk("sAxes", () => setDisp(toggled(disp, "axes")));
  lk("sLinks", () => setDisp(toggled(disp, "links")));
}

// ---------------------------------------------------------------- parameters panel
function buildParamsUI() {
  const host = $("params");
  host.innerHTML = "";
  let grp = null;
  (model.params || []).forEach((p) => {
    if (p.group !== grp) { grp = p.group; const h = document.createElement("h4"); h.textContent = grp; host.appendChild(h); }
    const d = document.createElement("div");
    d.className = "par";
    d.innerHTML = `<span>${p.name}<small>${p.desc}${p.value !== p.default ? ` (default ${p.default})` : ""}</small></span><input type="number" step="any" data-n="${p.name}" value="${p.value}">`;
    const inp = d.querySelector("input");
    inp.oninput = () => inp.classList.toggle("chg", +inp.value !== p.value);
    d.querySelector("span").onclick = () => {
      const parts = new Set((model.constraints || []).filter((c) => c.params?.includes(p.name)).flatMap((c) => c.parts));
      setSelection([...parts].map((n) => byName[n]).filter(Boolean));
      $("infotxt").textContent = `${p.name} = ${p.value} ${p.unit} drives ${parts.size} parts (highlighted)`;
    };
    host.appendChild(d);
  });
}
async function applyParams(reset) {
  const vals = {};
  document.querySelectorAll("#params input").forEach((i) => (vals[i.dataset.n] = reset ? model.params.find((p) => p.name === i.dataset.n).default : +i.value));
  $("pstat").textContent = "Rebuilding the model…";
  try {
    const r = await (await fetch("/api/params", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify({ m: curModel, values: vals }) })).json();
    $("pstat").textContent = r.ok ? "Rebuilt." : "Error: " + r.error;
  } catch (e) { $("pstat").textContent = "Server error"; }
}
$("pApply").onclick = () => applyParams(false);
$("pReset").onclick = () => applyParams(true);


// ---------------------------------------------------------------- manufacturing layout
const layoutGrid = new THREE.Group();
layoutGrid.visible = false;
scene.add(layoutGrid);
const LAYOUT_W = 3600;
function buildLayout() {
  if (layoutObj) scene.remove(layoutObj);
  layoutLabels.forEach((l) => l.el.remove());
  layoutLabels = []; layoutMeshes = []; layoutGroups = [];
  layoutObj = new THREE.Group();
  layoutObj.visible = layoutMode;
  scene.add(layoutObj);
  layoutGroups = groupParts(model.parts);
  layoutGroups.forEach((g) => (g.meshes = g.names.map((n) => byName[n])));
  gridLayout(layoutGroups, { width: LAYOUT_W });
  layoutGroups.forEach((g) => {
    const x = g.x, y = g.y;
    g.short = g.label.length > 26 ? g.label.slice(0, 24) + "…" : g.label;
    const o = orientation(g.order);
    const R = new THREE.Matrix4().set(o[0][0], o[0][1], o[0][2], 0, o[1][0], o[1][1], o[1][2], 0, o[2][0], o[2][1], o[2][2], 0, 0, 0, 0, 1);
    const b = g.bbox, lo = new THREE.Vector3(b[0], b[1], b[2]), hi = new THREE.Vector3(b[3], b[4], b[5]);
    const p1 = lo.clone().applyMatrix4(R), p2 = hi.clone().applyMatrix4(R);
    const mn = new THREE.Vector3(Math.min(p1.x, p2.x), Math.min(p1.y, p2.y), Math.min(p1.z, p2.z));
    const [L, W, T] = g.dims;
    g.base = new THREE.Matrix4().makeTranslation(-mn.x, -mn.y, -mn.z).multiply(R);          // part lying flat with its corner at the origin
    const M = new THREE.Matrix4().makeTranslation(x, y, 0).multiply(g.base);
    const geo = g.meshes[0].geometry;
    const lm = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0xd9a066, roughness: 0.7, metalness: 0.05 }));
    lm.matrixAutoUpdate = false; lm.matrix.copy(M);
    lm.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 30), new THREE.LineBasicMaterial({ color: 0x20160c })));
    lm.userData = { part: g.part, group: g };
    g.layoutMesh = lm;
    layoutObj.add(lm); layoutMeshes.push(lm);
    // dimension lines + labels
    const pts = [];
    const off = 22;
    pts.push(new THREE.Vector3(x, y - off, 0), new THREE.Vector3(x + L, y - off, 0),
      new THREE.Vector3(x, y - off - 8, 0), new THREE.Vector3(x, y - off + 8, 0),
      new THREE.Vector3(x + L, y - off - 8, 0), new THREE.Vector3(x + L, y - off + 8, 0),
      new THREE.Vector3(x - off, y, 0), new THREE.Vector3(x - off, y + W, 0),
      new THREE.Vector3(x - off - 8, y, 0), new THREE.Vector3(x - off + 8, y, 0),
      new THREE.Vector3(x - off - 8, y + W, 0), new THREE.Vector3(x - off + 8, y + W, 0));
    const dl = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xffd27a, depthTest: false }));
    dl.renderOrder = 5;
    layoutObj.add(dl);
    const mk = (text, pos, cls = "", span = null) => { const el = mkLabel(text, cls); layoutLabels.push({ el, pos, hidden: !layoutMode, span, w: el.offsetWidth }); };
    mk(fmt(L), new THREE.Vector3(x + L / 2, y - off - 14, 0), "", [new THREE.Vector3(x, y, 0), new THREE.Vector3(x + L, y, 0)]);
    mk(fmt(W), new THREE.Vector3(x - off - 22, y + W / 2, 0), "", [new THREE.Vector3(x, y, 0), new THREE.Vector3(x, y + W, 0)]);
    const fit = process === "print" ? bedCheck(g, bed) : { fits: true, reason: "" };
    g.fit = fit;
    mk(`${g.short}${g.qty > 1 ? " ×" + g.qty : ""} · T ${fmt(T)}${fit.fits ? "" : " · too big for the bed"}`, new THREE.Vector3(x + L / 2, y + W + 22, 0), fit.fits ? "m" : "bad", [new THREE.Vector3(x, y, 0), new THREE.Vector3(x + L, y, 0)]);
  });
  // grid with the origin at a corner: 100 mm cells, 500 mm bold lines
  layoutGrid.clear();
  const total = new THREE.Box3().setFromObject(layoutObj);
  const gw = Math.ceil((total.max.x + 200) / 500) * 500, gh = Math.ceil((total.max.y + 200) / 500) * 500;
  const thin = [], bold = [];
  for (let gx = 0; gx <= gw; gx += 100) (gx % 500 ? thin : bold).push(new THREE.Vector3(gx, 0, -0.5), new THREE.Vector3(gx, gh, -0.5));
  for (let gy = 0; gy <= gh; gy += 100) (gy % 500 ? thin : bold).push(new THREE.Vector3(0, gy, -0.5), new THREE.Vector3(gw, gy, -0.5));
  layoutGrid.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(thin), new THREE.LineBasicMaterial({ color: 0x3a3d43 })));
  layoutGrid.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(bold), new THREE.LineBasicMaterial({ color: 0x6b7078 })));
  const ax = new THREE.AxesHelper(250); ax.position.z = 0.2; layoutGrid.add(ax);
  for (let gx = 0; gx <= gw; gx += 500) layoutLabels.push({ el: mkLabel(String(gx), "g"), pos: new THREE.Vector3(gx, -45, 0), hidden: !layoutMode, grid: true });
  for (let gy = 500; gy <= gh; gy += 500) layoutLabels.push({ el: mkLabel(String(gy), "g"), pos: new THREE.Vector3(-55, gy, 0), hidden: !layoutMode, grid: true });
  layoutLabels.push({ el: mkLabel("origin (0, 0)", "g"), pos: new THREE.Vector3(-20, -45, 0), hidden: !layoutMode, grid: true });
  buildCutList();
  setLayoutVisibility();
}
function setLayoutVisibility() {
  layoutObj.visible = layoutMode; layoutGrid.visible = layoutMode;
  group.visible = !layoutMode; kinOverlay.visible = !layoutMode; planeGroup.visible = !layoutMode && disp.planes; capAll.visible = !layoutMode;
  grid.visible = !layoutMode && disp.grid;
  layoutLabels.forEach((l) => (l.hidden = !layoutMode));
  labels.forEach((l) => l.el.style.display = "none");
}
function fitLayout() {
  const b = boxOf(layoutMeshes);
  if (b.isEmpty()) return;
  const c = b.getCenter(new THREE.Vector3()), sz = b.getSize(new THREE.Vector3());
  const t = Math.tan((camera.fov * Math.PI) / 360), asp = (innerWidth - 350) / innerHeight;
  const dist = Math.max((sz.y + 260) / (2 * t), (sz.x + 260) / (2 * t * asp)) * 1.05;
  controls.target.set(c.x, c.y - 40, 0);
  camera.position.set(c.x, c.y - 40 - 0.001, dist);
  controls.update();
}
function setLayout(on) {
  if (!model || on === layoutMode) return;
  if (!on && inspectMode) setInspect(false);
  layoutMode = on;
  setLayoutVisibility();
  clearOverlay(); mPts = [];
  restyle(); updateInfo(); drawDims(); updateKin();
  if (on) fitLayout(); else look(0.6, -0.6, 0.5);
}
function buildCutList() {
  const host = $("cut");
  host.innerHTML = `<div class="cut h"><span>Part</span><span>Qty</span><span>L × W × T (mm)</span><span>cm³</span></div>`;
  layoutGroups.forEach((g) => {
    const d = document.createElement("div");
    d.className = "cut" + (g.fit && !g.fit.fits ? " bad" : "");
    d.innerHTML = `<span title="${g.names.join(", ")}${g.material ? " · " + g.material : ""}">${g.short}${g.material ? `<small> ${g.material}</small>` : ""}</span><span>${g.qty}</span><span>${g.dims.map(fmt).join(" × ")}</span><span>${(g.part.volume / 1000).toFixed(1)}</span>`;
    d.onclick = () => { if (inspectMode) { inspect(g); return; } setSelection(g.meshes); if (layoutMode) fitBox(boxOf([g.layoutMesh])); };
    g.layoutMesh.userData.row = d;
    host.appendChild(d);
  });
  const byMat = new Map();
  layoutGroups.forEach((g) => byMat.set(g.material || "unspecified", (byMat.get(g.material || "unspecified") ?? 0) + (g.qty * g.part.volume) / 1e6));
  const mats = [...byMat].map(([m, v]) => `${m} ${v < 1 ? (v * 1000).toFixed(0) + " cm³" : v.toFixed(1) + " L"}`).join(", ");
  const bad = layoutGroups.filter((g) => g.fit && !g.fit.fits).length;
  $("cutsum").textContent = `${layoutGroups.length} different parts, ${model.parts.length} pieces in total. Material: ${mats}. Sizes are the bounding box, i.e. the stock to cut from.` +
    (process === "print" ? (bad ? ` ${bad} part type(s) do not fit the bed.` : " Every part fits the bed.") : "");
  buildPlates();
}
let plateResult = null;
function buildPlates() {
  const host = $("plates");
  host.innerHTML = "";
  plateResult = null;
  if (process !== "print") return;
  const items = [], tooTall = [];
  layoutGroups.forEach((g) => g.names.forEach((n) => (g.dims[2] > bed.z ? tooTall.push(n) : items.push({ id: n, w: g.dims[0], h: g.dims[1], g }))));
  const r = packPlates(items, { x: bed.x, y: bed.y }, 5);
  plateResult = r;
  const byId = new Map(items.map((i) => [i.id, i]));
  const h = document.createElement("h4"); h.textContent = `Print plates (${bed.x} × ${bed.y} mm)`; host.appendChild(h);
  r.plates.forEach((p, i) => {
    const d = document.createElement("div");
    d.className = "con"; d.style.setProperty("--k", "#81c784");
    d.innerHTML = `Plate ${i + 1}: ${p.items.length} part${p.items.length > 1 ? "s" : ""}<small>${[...new Set(p.items.map((x) => x.id))].slice(0, 6).join(", ")}${p.items.length > 6 ? "…" : ""}</small>`;
    const b = document.createElement("span"); b.className = "btn"; b.textContent = "STL"; b.style.float = "right";
    b.onclick = (e) => { e.stopPropagation(); downloadPlate(i, byId); };
    d.prepend(b);
    host.appendChild(d);
  });
  const lost = [...r.unplaced, ...tooTall];
  if (lost.length) { const d = document.createElement("div"); d.className = "con"; d.style.setProperty("--k", "#e06666"); d.innerHTML = `Does not fit: ${lost.join(", ")}<small>bigger than the bed or taller than ${bed.z} mm</small>`; host.appendChild(d); }
}
function download(name, data, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([data], { type }));
  a.download = name; a.click();
}
const meshOf = (g, matrix) => ({ positions: g.meshes[0].geometry.attributes.position.array, index: g.meshes[0].geometry.index.array, matrix: matrix.elements });
function downloadPlate(i, byId) {
  const meshes = plateResult.plates[i].items.map((it) => {
    const g = byId.get(it.id).g;
    const place = new THREE.Matrix4().makeTranslation(it.x, it.y, 0);
    if (it.turned) place.multiply(new THREE.Matrix4().makeTranslation(g.dims[1], 0, 0)).multiply(new THREE.Matrix4().makeRotationZ(Math.PI / 2));
    return meshOf(g, place.multiply(g.base));
  });
  download(`${model.name || curModel}_plate${i + 1}.stl`, toBinaryStl(meshes), "model/stl");
}
$("mFit").onclick = () => { if (inspectMode) setInspect(false); fitLayout(); };
$("stlPart").onclick = () => { if (inspG) download(`${inspG.label}.stl`, toBinaryStl([meshOf(inspG, inspG.base)]), "model/stl"); };
$("cutCsv").onclick = () => {
  const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const rows = [["part", "quantity", "length_mm", "width_mm", "thickness_mm", "volume_cm3_each", "material", "names"]];
  layoutGroups.forEach((g) => rows.push([q(g.label), g.qty, ...g.dims.map((v) => v.toFixed(1)), (g.part.volume / 1000).toFixed(1), q(g.material), q(g.names.join(" "))]));
  download(`${model.name || curModel}_cutlist.csv`, rows.map((r) => r.join(",")).join("\n"), "text/csv");
};
function setProcess(p) {
  process = p;
  try { localStorage.setItem("cad.process", p); } catch (e) { /* ignore */ }
  $("proc").value = p;
  $("bedBox").style.display = p === "print" ? "block" : "none";
  if (model) buildLayout();
}
$("proc").onchange = (e) => setProcess(e.target.value);
for (const k of ["X", "Y", "Z"]) $("bed" + k).oninput = (e) => { bed[k.toLowerCase()] = Math.max(1, +e.target.value || 1); try { localStorage.setItem("cad.bed", JSON.stringify(bed)); } catch (x) { /* ignore */ } if (model) buildLayout(); };
try {
  process = localStorage.getItem("cad.process") || "wood";
  Object.assign(bed, JSON.parse(localStorage.getItem("cad.bed") || "{}"));
} catch (e) { /* ignore */ }
for (const k of ["X", "Y", "Z"]) $("bed" + k).value = bed[k.toLowerCase()];
$("proc").value = process;
$("bedBox").style.display = process === "print" ? "block" : "none";
$("layPng").onclick = () => {
  renderNow();
  const a = document.createElement("a");
  a.href = renderer.domElement.toDataURL("image/png"); a.download = inspectMode ? `${inspG.label}.png` : "layout.png"; a.click();
};

// ---------------------------------------------------------------- static section planes in the assembly view
// A plane is {id, name, axis 0|1|2 (x|y|z), pos mm, flip, show, clip}. They are fixed in the world frame (the
// model moves through them when you change the pose). Saved in the browser (localStorage).
const PLANE_COL = [0xff6b6b, 0x6bd66b, 0x6ba8ff];
const AXN = ["x", "y", "z"];
let planes = [], selPlane = null, secCaps = true, secPicking = false, planeLbl = [];
const planeGroup = new THREE.Group();
const capAll = new THREE.Group();
scene.add(planeGroup, capAll);
let planesLoaded = false;
function loadPlanes() {
  planesLoaded = true;
  let raw = null;
  try { raw = localStorage.getItem(storageKey(curModel)); } catch (e) { /* private mode */ }
  try { planes = raw === null ? defaultPlanes() : JSON.parse(raw); } catch (e) { planes = defaultPlanes(); }
  selPlane = planes[0] ?? null;                       // an empty list is a valid, saved state
}
function defaultPlanes() { const b = modelBox(); return defaultPlanesFor({ min: b.min.toArray(), max: b.max.toArray() }); }
function savePlanes() { try { localStorage.setItem(storageKey(curModel), JSON.stringify(planes)); } catch (e) { /* private mode */ } }
const planeThree = (p) => { const c = clipPlane(p); return new THREE.Plane(new THREE.Vector3(...c.normal), c.constant); };
function modelBox() { return boxOf(meshes); }

function applySection() {
  const act = planes.filter((p) => p.clip), th = act.map(planeThree);
  meshes.forEach((m) => { m.material.clippingPlanes = th; m.material.side = act.length ? THREE.DoubleSide : THREE.FrontSide; m.material.needsUpdate = true; m.children.forEach((c) => (c.material.clippingPlanes = th)); });
  // plane quads
  planeGroup.clear(); planeLbl.forEach((l) => l.el.remove()); planeLbl = [];
  const b = modelBox(), sz = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
  planes.filter((p) => p.show).forEach((p) => {
    const dims = p.axis === 0 ? [sz.z, sz.y] : p.axis === 1 ? [sz.x, sz.z] : [sz.x, sz.y];
    const w = dims[0] + 240, h = dims[1] + 240, sel = p === selPlane;
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: PLANE_COL[p.axis], transparent: true, opacity: sel ? 0.2 : 0.1, side: THREE.DoubleSide, depthWrite: false }));
    const outline = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([[-.5, -.5, 0], [.5, -.5, 0], [.5, .5, 0], [-.5, .5, 0]].map((q) => new THREE.Vector3(...q))), new THREE.LineBasicMaterial({ color: PLANE_COL[p.axis], transparent: true, opacity: sel ? 1 : 0.6 }));
    const g = new THREE.Group();
    g.add(quad, outline);
    g.position.copy(c); g.position.setComponent(p.axis, p.pos);
    if (p.axis === 2) g.scale.set(w, h, 1);
    else if (p.axis === 0) { g.rotation.set(0, Math.PI / 2, 0); g.scale.set(w, h, 1); }
    else { g.rotation.set(Math.PI / 2, 0, 0); g.scale.set(w, h, 1); }
    quad.renderOrder = 3;
    planeGroup.add(g);
    const corner = c.clone(); corner.setComponent(p.axis, p.pos);
    const [u, v] = [[1, 2], [0, 2], [0, 1]][p.axis];
    corner.setComponent(u, c.getComponent(u) - w / 2); corner.setComponent(v, c.getComponent(v) + h / 2);
    planeLbl.push({ el: mkLabel(`${p.name} (${AXN[p.axis]} = ${Math.round(p.pos)})`, "g"), pos: corner, hidden: false });
  });
  planeGroup.visible = !layoutMode && disp.planes;
  $("tSec").classList.toggle("on", $("secBox").style.display === "block");
  renderPlaneUI();
  rebuildCaps();
}
let capTimer = null;
function rebuildCaps() {
  clearTimeout(capTimer);
  capTimer = setTimeout(() => {
    capAll.clear();
    const act = planes.filter((p) => p.clip);
    if (!act.length || !secCaps || layoutMode || !meshes.length) return;
    act.forEach((p) => {
      const others = act.filter((o) => o !== p).map(planeThree);
      meshes.filter((m) => m.visible).forEach((m) => {
        const loops = sliceLoops(m.geometry, m.matrixWorld, p.axis, p.pos);
        if (!loops.length) return;
        const g = capGroup(loops, p.axis, p.pos, partColor(m));
        g.traverse((o) => { if (o.material) o.material.clippingPlanes = others; });
        capAll.add(g);
      });
    });
    capAll.visible = !layoutMode;
  }, 60);
}
// closed loops -> filled shapes (even-odd: a loop nested inside an odd number of others is a hole)
function capGroup(loops, axis, pos, color) {
  const ab = [[1, 2], [0, 2], [0, 1]][axis];
  const pt = (p) => [p[ab[0]], p[ab[1]]];
  const area = (l) => l.reduce((a, p, i) => { const q = l[(i + 1) % l.length]; return a + (p[ab[0]] * q[ab[1]] - q[ab[0]] * p[ab[1]]) / 2; }, 0);
  const inside = (pnt, l) => { let c = false; for (let i = 0, j = l.length - 1; i < l.length; j = i++) { const [xi, yi] = pt(l[i]), [xj, yj] = pt(l[j]); if ((yi > pnt[1]) !== (yj > pnt[1]) && pnt[0] < ((xj - xi) * (pnt[1] - yi)) / (yj - yi) + xi) c = !c; } return c; };
  const info = loops.map((l) => ({ l, a: Math.abs(area(l)), parents: [] }));
  info.forEach((x) => info.forEach((y) => { if (x !== y && y.a > x.a && inside(pt(x.l[0]), y.l)) x.parents.push(y); }));
  const g = new THREE.Group();
  const to3 = (u, v) => { const p = [0, 0, 0]; p[axis] = pos; p[ab[0]] = u; p[ab[1]] = v; return p; };
  info.filter((x) => x.parents.length % 2 === 0).forEach((outer) => {
    const sh = new THREE.Shape();
    outer.l.forEach((p, i) => (i ? sh.lineTo(...pt(p)) : sh.moveTo(...pt(p))));
    info.filter((h) => h.parents.length % 2 === 1 && h.parents.sort((p, q) => p.a - q.a)[0] === outer).forEach((h) => {
      const path = new THREE.Path();
      h.l.forEach((p, i) => (i ? path.lineTo(...pt(p)) : path.moveTo(...pt(p))));
      sh.holes.push(path);
    });
    const geo = new THREE.ShapeGeometry(sh), pa = geo.attributes.position;
    for (let i = 0; i < pa.count; i++) { const p = to3(pa.getX(i), pa.getY(i)); pa.setXYZ(i, ...p); }
    g.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: new THREE.Color(color).lerp(new THREE.Color(0xffffff), 0.35), side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 })));
  });
  loops.forEach((l) => g.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(l.map((p) => new THREE.Vector3(...to3(...pt(p))))), new THREE.LineBasicMaterial({ color: 0x15100a }))));
  return g;
}

function renderPlaneUI() {
  const host = $("planeList");
  host.innerHTML = "";
  planes.forEach((p) => {
    const d = document.createElement("div");
    d.className = "con" + (p === selPlane ? " sel" : "");
    d.style.setProperty("--k", css(PLANE_COL[p.axis]));
    d.innerHTML = `<div style="display:flex;gap:6px;align-items:center"><b style="flex:1;font-weight:500">${p.name} <span style="color:var(--dim)">${AXN[p.axis]} = ${Math.round(p.pos)}</span></b>
      <label title="show plane"><input type="checkbox" data-k="show" ${p.show ? "checked" : ""}> show</label>
      <label title="cut the model here"><input type="checkbox" data-k="clip" ${p.clip ? "checked" : ""}> cut</label>
      <span class="btn" data-k="look" title="look at the cut face">View</span></div>`;
    d.onclick = (e) => {
      const k = e.target.dataset?.k;
      if (k === "show" || k === "clip") { p[k] = e.target.checked; savePlanes(); applySection(); return; }
      if (k === "look") { lookAtPlane(p); return; }
      selPlane = p; syncPlaneEditor(); applySection();
    };
    host.appendChild(d);
  });
}
function syncPlaneEditor() {
  $("planeEd").style.display = selPlane ? "block" : "none";
  $("planeNone").style.display = planes.length ? "none" : "block";
  if (!selPlane || !meshes.length) return;
  document.querySelectorAll("#secAx .btn").forEach((b) => b.classList.toggle("on", +b.dataset.a === selPlane.axis));
  const b = modelBox(), lo = Math.floor(b.min.getComponent(selPlane.axis)), hi = Math.ceil(b.max.getComponent(selPlane.axis));
  $("secWorld").min = lo; $("secWorld").max = hi; $("secWorld").value = selPlane.pos;
  $("secWorldV").textContent = `${selPlane.name}: ${AXN[selPlane.axis]} = ${Math.round(selPlane.pos)} mm`;
  $("secFlip").classList.toggle("on", selPlane.flip);
  $("secName").value = selPlane.name;
}
function setSecPos(v) { if (!selPlane) return; selPlane.pos = v; savePlanes(); syncPlaneEditor(); applySection(); }
function lookAtPlane(p) {                      // camera on the removed side, looking straight at the cut face
  const b = modelBox(), c = b.getCenter(new THREE.Vector3()), r = b.getSize(new THREE.Vector3()).length();
  c.setComponent(p.axis, p.pos);
  const dir = new THREE.Vector3(); dir.setComponent(p.axis, p.flip ? -1 : 1);
  if (p.axis === 2) dir.y = -0.001;
  controls.target.copy(c);
  camera.position.copy(c).addScaledVector(dir, Math.max(r * 1.1, 600));
  controls.update();
}
$("tSec").onclick = () => { $("secBox").style.display = $("secBox").style.display === "block" ? "none" : "block"; applySection(); };
document.querySelectorAll("#secAx .btn").forEach((b) => (b.onclick = () => {
  if (!selPlane) return;
  selPlane.axis = +b.dataset.a;
  const r = modelBox(); selPlane.pos = Math.round((r.min.getComponent(selPlane.axis) + r.max.getComponent(selPlane.axis)) / 2);
  savePlanes(); syncPlaneEditor(); applySection();
}));
$("secWorld").oninput = (e) => setSecPos(+e.target.value);
$("secFlip").onclick = () => { if (!selPlane) return; selPlane.flip = !selPlane.flip; savePlanes(); syncPlaneEditor(); applySection(); };
$("secPick").onclick = () => { secPicking = !secPicking; $("secPick").classList.toggle("on", secPicking); };
$("secCaps").onchange = (e) => { secCaps = e.target.checked; applySection(); };
$("secName").onchange = (e) => { if (!selPlane) return; selPlane.name = e.target.value || selPlane.name; savePlanes(); applySection(); syncPlaneEditor(); };
$("planeAdd").onclick = () => {
  const id = Math.max(0, ...planes.map((p) => p.id)) + 1, b = modelBox();
  const axis = selPlane?.axis ?? 1;
  planes.push({ id, name: `Plane ${id}`, axis, pos: Math.round((b.min.getComponent(axis) + b.max.getComponent(axis)) / 2), flip: false, show: true, clip: true });
  selPlane = planes[planes.length - 1]; savePlanes(); syncPlaneEditor(); applySection();
};
$("planeDel").onclick = () => { if (!selPlane) return; planes = planes.filter((p) => p !== selPlane); selPlane = planes[0] ?? null; savePlanes(); syncPlaneEditor(); applySection(); };
$("planeOff").onclick = () => { planes.forEach((p) => { p.show = false; p.clip = false; }); savePlanes(); applySection(); };
$("planeDelAll").onclick = () => { planes = []; selPlane = null; savePlanes(); syncPlaneEditor(); applySection(); };
$("planeReset").onclick = () => { planes = defaultPlanes(); selPlane = planes[0]; savePlanes(); syncPlaneEditor(); applySection(); };

// ---------------------------------------------------------------- part inspector: 2D views, 3D and a cross section
const inspScene = new THREE.Scene();
inspScene.add(new THREE.HemisphereLight(0xffffff, 0x555566, 1.2));
const inspSun = new THREE.DirectionalLight(0xffffff, 1.3);
inspSun.position.set(1, -2, 3);
inspScene.add(inspSun);
const inspObj = new THREE.Group();
inspScene.add(inspObj);
const icam = new THREE.PerspectiveCamera(35, 1, 1, 100000);
icam.up.set(0, 0, 1);
icam.layers.enable(4);
const ictl = new OrbitControls(icam, renderer.domElement);
ictl.enabled = false;
renderer.localClippingEnabled = true;
const oc = [1, 2, 3, 5].map((k) => { const c = new THREE.OrthographicCamera(-1, 1, 1, -1, -5000, 5000); c.layers.enable(k); return c; });
// grid cells: 0 top, 1 front, 2 right (row 1) / 3 = 3D (wide), 4 = section (row 2)
const VIEWS = ["TOP", "FRONT", "RIGHT", "3D", "SECTION"];
let inspLabels = [], inspBox = new THREE.Box3(), inspExt = [1, 1, 1], inspMesh = null, secObj = null, secLabels = [];
let secAxis = 0, secFrac = 0.5, clip3d = true;
function viewRects() {
  const x0 = 345, y0 = 10, w = innerWidth - x0 - 10, h = innerHeight - y0 - 66, gap = 8;
  const cw = (w - 2 * gap) / 3, ch = (h - gap) / 2;
  return [
    { x: x0, y: y0, w: cw, h: ch }, { x: x0 + cw + gap, y: y0, w: cw, h: ch }, { x: x0 + 2 * (cw + gap), y: y0, w: cw, h: ch },
    { x: x0, y: y0 + ch + gap, w: 2 * cw + gap, h: ch }, { x: x0 + 2 * (cw + gap), y: y0 + ch + gap, w: cw, h: ch },
  ];
}
const inRect = (e, r) => e.clientX >= r.x && e.clientX <= r.x + r.w && e.clientY >= r.y && e.clientY <= r.y + r.h;
for (const t of ["pointerdown", "wheel"]) renderer.domElement.addEventListener(t, (e) => {
  ictl.enabled = inspectMode && inRect(e, viewRects()[3]);
  controls.enabled = !inspectMode;
}, true);

function dimLine(layer, a, b, ticks, color = 0xffd27a) {
  const pts = [a, b, a.clone().add(ticks), a.clone().sub(ticks), b.clone().add(ticks), b.clone().sub(ticks)];
  const l = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color, depthTest: false }));
  l.layers.set(layer); l.renderOrder = 5;
  inspObj.add(l);
}
function inspLabel(view, text, pos, cls = "") { const l = { el: mkLabel(text, cls), view, pos }; inspLabels.push(l); return l; }
function clearInsp() { inspObj.clear(); secObj = null; inspLabels.forEach((l) => l.el.remove()); inspLabels = []; secLabels = []; }

// slice the part mesh with an axis-aligned plane -> closed outline loops (2D) + filled shape
const sliceLoops = (geo, M, axis, pos) => sliceCore({ positions: geo.attributes.position.array, index: geo.index.array }, M.elements, axis, pos);
function buildSection() {
  if (secObj) { inspObj.remove(secObj); secObj = null; }
  secLabels.forEach((l) => { l.el.remove(); inspLabels.splice(inspLabels.indexOf(l), 1); });
  secLabels = [];
  if (!inspMesh) return;
  const { min, max } = inspBox, c = inspBox.getCenter(new THREE.Vector3());
  const axis = secAxis, pos = min.getComponent(axis) + (max.getComponent(axis) - min.getComponent(axis)) * secFrac;
  const ab = [[1, 2], [0, 2], [0, 1]][axis];                    // in-plane axes (u, v)
  const loops = sliceLoops(inspMesh.geometry, inspMesh.matrix, axis, pos);
  const to3 = (u, v) => { const p = [0, 0, 0]; p[axis] = pos; p[ab[0]] = u; p[ab[1]] = v; return new THREE.Vector3(...p); };
  const g = new THREE.Group();
  g.layers.set(5);
  const area = (l) => l.reduce((a, p, i) => { const q = l[(i + 1) % l.length]; return a + (p[ab[0]] * q[ab[1]] - q[ab[0]] * p[ab[1]]) / 2; }, 0);
  let bu = [1e9, -1e9], bv = [1e9, -1e9], areaTotal = 0;
  if (loops.length) {
    const sorted = loops.slice().sort((x, y) => Math.abs(area(y)) - Math.abs(area(x)));
    const mkShape = (l, S) => { const sh = S ?? new THREE.Shape(); l.forEach((p, i) => (i ? sh.lineTo(p[ab[0]], p[ab[1]]) : sh.moveTo(p[ab[0]], p[ab[1]]))); return sh; };
    const shape = mkShape(sorted[0]);
    sorted.slice(1).forEach((l) => shape.holes.push(mkShape(l, new THREE.Path())));
    areaTotal = Math.abs(area(sorted[0])) - sorted.slice(1).reduce((a, l) => a + Math.abs(area(l)), 0);
    const sg = new THREE.ShapeGeometry(shape), pa = sg.attributes.position;
    for (let i = 0; i < pa.count; i++) { const p = to3(pa.getX(i), pa.getY(i)); pa.setXYZ(i, p.x, p.y, p.z); }
    const fill = new THREE.Mesh(sg, new THREE.MeshBasicMaterial({ color: 0x4f8fd9, transparent: true, opacity: 0.55, side: THREE.DoubleSide, depthTest: false }));
    fill.layers.set(5); g.add(fill);
    loops.forEach((l) => {
      const ln = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(l.map((p) => to3(p[ab[0]], p[ab[1]]))), new THREE.LineBasicMaterial({ color: 0xffffff, depthTest: false }));
      ln.layers.set(5); g.add(ln);
      l.forEach((p) => { bu = [Math.min(bu[0], p[ab[0]]), Math.max(bu[1], p[ab[0]])]; bv = [Math.min(bv[0], p[ab[1]]), Math.max(bv[1], p[ab[1]])]; });
    });
    // dimension lines of the cut face
    const e = Math.max(...[[inspExt[1], inspExt[2]], [inspExt[0], inspExt[2]], [inspExt[0], inspExt[1]]][axis]), off = e * 0.09, tk = e * 0.015;
    const du = to3(0, 0).setComponent(ab[0], tk), dv = to3(0, 0).setComponent(ab[1], tk); du.setComponent(axis, 0); dv.setComponent(axis, 0);
    const mkd = (a, b, t) => { const pts = [a, b, a.clone().add(t), a.clone().sub(t), b.clone().add(t), b.clone().sub(t)]; const l = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xffd27a, depthTest: false })); l.layers.set(5); g.add(l); };
    mkd(to3(bu[0], bv[0] - off), to3(bu[1], bv[0] - off), dv);
    mkd(to3(bu[0] - off, bv[0]), to3(bu[0] - off, bv[1]), du);
    secLabels.push(inspLabel(4, fmt(bu[1] - bu[0]), to3((bu[0] + bu[1]) / 2, bv[0] - off * 1.8)));
    secLabels.push(inspLabel(4, fmt(bv[1] - bv[0]), to3(bu[0] - off * 1.8, (bv[0] + bv[1]) / 2)));
  }
  inspObj.add(g); secObj = g;
  // camera for the section view
  const cam = oc[3], ext = [[inspExt[1], inspExt[2]], [inspExt[0], inspExt[2]], [inspExt[0], inspExt[1]]][axis];
  const look = [[pos + 2000, c.y, c.z, 0, 0, 1], [c.x, pos - 2000, c.z, 0, 0, 1], [c.x, c.y, pos + 2000, 0, 1, 0]][axis];
  cam.position.set(look[0], look[1], look[2]); cam.up.set(look[3], look[4], look[5]); cam.lookAt(c.x, c.y, c.z);
  secExt = ext;
  const name = ["L (x)", "W (y)", "T (z)"][axis];
  $("secInfo").textContent = `cut at ${name} = ${(pos - min.getComponent(axis)).toFixed(1)} mm from the end` + (loops.length ? ` · area ${areaTotal.toFixed(0)} mm² · ${loops.length > 1 ? loops.length - 1 + " hole(s)" : "solid"}` : " · no material here");
  // clip the 3D view at the same plane
  const normal = new THREE.Vector3(); normal.setComponent(axis, -1);
  const plane = new THREE.Plane(normal, pos);
  inspMesh.material.clippingPlanes = clip3d ? [plane] : [];
  inspMesh.children.forEach((ch) => (ch.material.clippingPlanes = clip3d ? [plane] : []));
}
let secExt = [1, 1];

function inspect(g) {
  clearInsp();
  inspG = g;
  setSelection(g.meshes);
  const src = g.layoutMesh;
  const mat = new THREE.MeshStandardMaterial({ color: partColor(g.meshes[0]), roughness: 0.75, metalness: 0.05, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const m = new THREE.Mesh(src.geometry, mat);
  m.matrixAutoUpdate = false; m.matrix.copy(src.matrix);
  m.add(new THREE.LineSegments(new THREE.EdgesGeometry(src.geometry, 25), new THREE.LineBasicMaterial({ color: 0x111111 })));
  inspObj.add(m);
  inspMesh = m;
  inspObj.updateMatrixWorld(true);
  const bb = new THREE.Box3().setFromObject(m);
  inspBox = bb;
  const sz = bb.getSize(new THREE.Vector3()), c = bb.getCenter(new THREE.Vector3());
  inspExt = [sz.x, sz.y, sz.z];
  const { min, max } = bb, e = Math.max(sz.x, sz.y, sz.z), off = e * 0.09, tk = e * 0.015;
  const V = (x, y, z) => new THREE.Vector3(x, y, z);
  dimLine(1, V(min.x, min.y - off, max.z), V(max.x, min.y - off, max.z), V(0, tk, 0));            // top: L, W
  dimLine(1, V(min.x - off, min.y, max.z), V(min.x - off, max.y, max.z), V(tk, 0, 0));
  inspLabel(0, fmt(sz.x), V(c.x, min.y - off * 1.8, max.z));
  inspLabel(0, fmt(sz.y), V(min.x - off * 1.8, c.y, max.z));
  dimLine(2, V(min.x, min.y, min.z - off), V(max.x, min.y, min.z - off), V(0, 0, tk));            // front: L, T
  dimLine(2, V(min.x - off, min.y, min.z), V(min.x - off, min.y, max.z), V(tk, 0, 0));
  inspLabel(1, fmt(sz.x), V(c.x, min.y, min.z - off * 1.8));
  inspLabel(1, fmt(sz.z), V(min.x - off * 1.8, min.y, c.z));
  dimLine(3, V(max.x, min.y, min.z - off), V(max.x, max.y, min.z - off), V(0, 0, tk));            // right: W, T
  dimLine(3, V(max.x, min.y - off, min.z), V(max.x, min.y - off, max.z), V(0, tk, 0));
  inspLabel(2, fmt(sz.y), V(max.x, c.y, min.z - off * 1.8));
  inspLabel(2, fmt(sz.z), V(max.x, min.y - off * 1.8, c.z));
  const bh = new THREE.Box3Helper(bb, 0xffd27a); bh.layers.set(4); inspObj.add(bh);                // 3D: bbox sizes
  inspLabel(3, fmt(sz.x), V(c.x, min.y, min.z));
  inspLabel(3, fmt(sz.y), V(max.x, c.y, min.z));
  inspLabel(3, fmt(sz.z), V(max.x, max.y, c.z));
  VIEWS.forEach((t, i) => inspLabels.push({ el: mkLabel(t === "SECTION" ? "SECTION (cut face)" : t, "g"), view: i, title: true }));
  icam.position.set(c.x + e * 1.3, c.y - e * 1.5, c.z + e * 1.1);
  ictl.target.copy(c); ictl.update();
  oc[0].position.set(c.x, c.y, max.z + 2000); oc[0].up.set(0, 1, 0); oc[0].lookAt(c);
  oc[1].position.set(c.x, min.y - 2000, c.z); oc[1].up.set(0, 0, 1); oc[1].lookAt(c);
  oc[2].position.set(max.x + 2000, c.y, c.z); oc[2].up.set(0, 0, 1); oc[2].lookAt(c);
  buildSection();
  const j = g.meshes[0].userData.joint;
  $("insp").innerHTML = `<b>${g.label}</b> ×${g.qty}<br>${g.dims.map(fmt).join(" × ")} mm (L × W × T)<br>${(g.part.volume / 1000).toFixed(1)} cm³ each<br><span style="color:var(--dim)">${g.names.join(", ")}<br>${j ? "moves with " + jointsByName[j].label : "fixed to the frame"}</span>`;
  document.querySelectorAll("#cut .cut").forEach((d) => d.classList.remove("cur"));
  g.layoutMesh.userData.row?.classList.add("cur");
}
function setInspect(on) {
  if (!layoutGroups.length) return;
  if (on) {
    inspectMode = true;
    controls.enabled = false;
    $("mInsp").classList.add("on"); $("mOver").classList.remove("on"); $("inspBox").style.display = "block";
    [labels, layoutLabels, kinLabels, planeLbl].forEach((arr) => arr.forEach((l) => { l.hidden = true; l.el.style.display = "none"; }));   // the render loop is paused in inspect mode, so hide them by hand
    inspect(inspG ?? layoutGroups.find((g) => g.meshes.some((m) => selected.has(m))) ?? layoutGroups[0]);
    document.body.classList.add("insp");
  } else {
    inspectMode = false;
    controls.enabled = true; ictl.enabled = false;
    clearInsp(); inspMesh = null;
    $("mInsp").classList.remove("on"); $("mOver").classList.add("on"); $("inspBox").style.display = "none";
    layoutLabels.forEach((l) => (l.hidden = !layoutMode));
    document.body.classList.remove("insp");
    updateKin(); drawDims();
    resize();                                   // reset renderer viewport and scissor
    if (layoutMode) fitLayout();
  }
}
$("mOver").onclick = () => setInspect(false);
$("mInsp").onclick = () => setInspect(true);
document.querySelectorAll("#secAxis .btn").forEach((b) => (b.onclick = () => {
  secAxis = +b.dataset.a;
  document.querySelectorAll("#secAxis .btn").forEach((x) => x.classList.toggle("on", x === b));
  if (inspectMode) buildSection();
}));
$("secPos").oninput = (e) => { secFrac = +e.target.value / 100; if (inspectMode) buildSection(); };
$("secClip").onchange = (e) => { clip3d = e.target.checked; if (inspectMode) buildSection(); };
renderer.domElement.addEventListener("dblclick", (e) => {
  if (!layoutMode || inspectMode) return;
  const hit = pick(e);
  if (hit) { inspG = hit.object.userData.group; setInspect(true); }
});

function renderInspect() {
  const rects = viewRects();
  renderer.setScissorTest(true);
  renderer.setViewport(0, 0, innerWidth, innerHeight); renderer.setScissor(0, 0, innerWidth, innerHeight);
  renderer.setClearColor(0x2b2d31); renderer.clear();
  const cams = [oc[0], oc[1], oc[2], icam, oc[3]];
  const exts = [[inspExt[0], inspExt[1]], [inspExt[0], inspExt[2]], [inspExt[1], inspExt[2]], null, secExt];
  rects.forEach((r, i) => {
    const yb = innerHeight - r.y - r.h;
    renderer.setViewport(r.x, yb, r.w, r.h); renderer.setScissor(r.x, yb, r.w, r.h);
    renderer.setClearColor(0x1c1e22); renderer.clear();
    const cam = cams[i], asp = r.w / r.h;
    if (i === 3) { icam.aspect = asp; icam.updateProjectionMatrix(); }
    else {
      const [a, b] = exts[i];
      const hh = Math.max(b * 0.5 * 1.6, (a * 0.5 * 1.6) / asp);
      cam.left = -hh * asp; cam.right = hh * asp; cam.top = hh; cam.bottom = -hh; cam.updateProjectionMatrix();
    }
    cam.updateMatrixWorld();
    renderer.render(inspScene, cam);
  });
  renderer.setScissorTest(false);
  renderer.setViewport(0, 0, innerWidth, innerHeight);
  inspLabels.forEach((l) => {
    const r = rects[l.view];
    let x, y, vis = true;
    if (l.title) { x = r.x + (l.view === 4 ? 70 : 30); y = r.y + 14; }
    else {
      tmp.copy(l.pos).project(cams[l.view]);
      x = r.x + ((tmp.x + 1) / 2) * r.w; y = r.y + ((1 - tmp.y) / 2) * r.h;
      vis = tmp.x > -1 && tmp.x < 1 && tmp.y > -1 && tmp.y < 1;
    }
    l.el.style.display = vis ? "block" : "none";
    l.el.style.left = x + "px"; l.el.style.top = y + "px";
  });
}
function renderNow() { if (inspectMode) { renderInspect(); } else renderer.render(scene, camera); }

// ---------------------------------------------------------------- chat
const chat = $("chat");
function openChat(x, y) {
  chat.style.display = "flex";
  if (x != null) { chat.style.left = Math.min(Math.max(10, x), innerWidth - 360) + "px"; chat.style.top = Math.min(Math.max(10, y), innerHeight - 300) + "px"; }
  else if (!chat.style.left) { chat.style.left = innerWidth - 370 + "px"; chat.style.top = "70px"; }
  $("msg").focus();
}
function closeChat() { chat.style.display = "none"; autoOpenChat = false; }
$("fab").onclick = () => { if (chat.style.display === "flex") closeChat(); else { autoOpenChat = true; openChat(); } };
$("cclose").onclick = closeChat;
let drag = null;
$("chead").onpointerdown = (e) => { if (e.target.id === "cclose") return; drag = [e.clientX - chat.offsetLeft, e.clientY - chat.offsetTop]; $("chead").setPointerCapture(e.pointerId); };
$("chead").onpointermove = (e) => { if (drag) { chat.style.left = e.clientX - drag[0] + "px"; chat.style.top = e.clientY - drag[1] + "px"; } };
$("chead").onpointerup = () => (drag = null);
$("form").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("msg").value.trim();
  if (!text) return;
  $("msg").value = "";
  renderNow();
  const shot = $("shot").checked ? renderer.domElement.toDataURL("image/png") : "";
  const sel = [...selected];
  const measure = mPts.length === 2 ? { from: mPts[0].toArray().map(fmt), to: mPts[1].toArray().map(fmt), mm: +fmt(mPts[0].distanceTo(mPts[1])) } : null;
  await fetch("/api/message", {
    method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN },
    body: JSON.stringify({
      m: curModel, text, shot, measure, pose: { ...values }, constraint: activeCon?.id ?? null,
      part: sel.length === 1 ? sel[0].userData.part.name : null, parts: sel.map((m) => m.userData.part.name),
      point: sel.length === 1 ? selPoint : null, normal: sel.length === 1 ? selNormal : null,
    }),
  });
  poll();
};
let shown = 0;
let lastAssistant = null;
async function assistantPoll() {
  try { lastAssistant = await (await fetch("/api/assistant")).json(); } catch (e) { return; }
  const p = presence(lastAssistant, Date.now() / 1000);
  for (const id of ["adot", "pdot"]) $(id).className = "dot " + (lastAssistant.last_seen == null && !lastAssistant.listening ? "none" : p.level);
  $("atext").textContent = p.text;
  $("ptext").textContent = lastAssistant.listening ? "Assistant listening" : lastAssistant.last_seen == null ? "Assistant not connected" : "Assistant away";
  $("apill").style.color = lastAssistant.listening ? "var(--fg)" : "";
  $("astart").style.display = lastAssistant.listening ? "none" : "";
  const h = $("ahint");
  h.style.display = p.detail ? "block" : "none";
  h.textContent = p.detail;
}
$("apill").onclick = () => openChat();
$("astart").onclick = async () => {
  const b = $("astart");
  b.textContent = "Starting…";
  try {
    const r = await (await fetch("/api/assistant/start", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: "{}" })).json();
    b.textContent = r.ok ? (r.state === "started" ? "Opened a terminal…" : "Already starting…") : "Failed";
  } catch (e) { b.textContent = "Failed"; }
  setTimeout(() => { b.textContent = "Start assistant"; }, 15000);
};
setInterval(assistantPoll, 2000);
assistantPoll();
let connOk = true;
function setConn(ok) { if (ok !== connOk) { connOk = ok; $("conn").style.display = ok ? "none" : "block"; } }
async function poll() {
  try {
    const msgs = await (await fetch("/api/chat")).json();                 // the whole conversation of the project
    if (msgs.length !== shown) {
      const log = $("log");
      log.innerHTML = "";
      for (const m of msgs) {
        const d = document.createElement("div");
        d.className = "m " + m.role;
        d.textContent = m.text;
        const on = m.parts?.length > 1 ? m.parts.length + " parts" : m.part;
        if (m.role === "user") {
          const s = document.createElement("small");
          s.className = "st";
          s.textContent = [m.model ?? "", on ? "on " + on : "", stateLabel(m.state)].filter(Boolean).join(" · ");
          if (s.textContent) d.appendChild(s);
        }
        log.appendChild(d);
      }
      log.scrollTop = log.scrollHeight;
      if (msgs.length > shown && shown && msgs[msgs.length - 1].role !== "user" && autoOpenChat) openChat();
      shown = msgs.length;
    }
    const v = await (await fetch("/api/version")).json();
    if (v.name && $("projBar").textContent !== v.name) { $("projBar").textContent = v.name; document.title = `${v.name} · CAD chat`; }
    if (curModel === null) {
      const r = await refreshList();
      let stored = null; try { stored = localStorage.getItem("cad.model"); } catch (e) { /* ignore */ }
      stamps = v.models;
      const pick = chooseModel({ models: r.models, latest: r.latest, stored });
      if (pick) await switchModel(pick);
      return;
    }
    const changed = publishedSince(stamps, v.models);
    const listChanged = Object.keys(v.models).join() !== Object.keys(stamps).join();
    stamps = v.models;
    if (listChanged) await refreshList();
    if (changed && changed !== curModel) await switchModel(changed);          // a script just published a model: show it
    else if (v.models[curModel] !== undefined && v.models[curModel] !== modelStamp) await loadModel(curModel, false);
    setConn(true);
  } catch (e) { setConn(false); /* server restarting: keep polling, the page recovers by itself */ }
}
// ---------------------------------------------------------------- history (versions of the model script and parameters)
async function loadHistory() {
  if (!curModel) return;
  const host = $("hist");
  let items = [];
  try { items = await (await fetch(`/api/history?m=${encodeURIComponent(curModel)}`)).json(); } catch (e) { return; }
  host.innerHTML = "";
  if (!items.length) { host.innerHTML = '<div style="color:var(--dim);margin:6px 2px">No versions yet: they appear when the model is built.</div>'; return; }
  items.forEach((it, i) => {
    const d = document.createElement("div");
    d.className = "hist";
    const t = it.time.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/, "$1-$2-$3 $4:$5:$6");
    d.innerHTML = `<span class="t"><b>${t}${i === 0 ? " (current)" : ""}</b><small></small></span>`;
    d.querySelector("small").textContent = it.note || "(no request recorded)";
    if (i > 0) {
      const b = document.createElement("span");
      b.className = "btn"; b.textContent = "Restore";
      b.onclick = async () => {
        b.textContent = "…";
        const r = await (await fetch("/api/restore", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify({ m: curModel, id: it.id }) })).json();
        $("modelStat").textContent = r.ok ? "Restored " + t : "Restore failed: " + r.error;
        await loadHistory();
      };
      d.appendChild(b);
    }
    host.appendChild(d);
  });
}
async function refreshList() {
  const r = await (await fetch("/api/models")).json();
  modelList = r.models;
  const sel = $("modelSel");
  sel.innerHTML = "";
  modelList.forEach((m) => { const o = document.createElement("option"); o.value = m.id; o.textContent = m.built ? m.id : `${m.id} (not built)`; sel.appendChild(o); });
  if (curModel) sel.value = curModel;
  return r;
}
async function switchModel(id) {
  const info = modelList.find((m) => m.id === id);
  if (info && !info.built) {
    $("modelStat").textContent = `Building ${id}…`;
    const r = await (await fetch("/api/build", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify({ script: id }) })).json();
    if (!r.ok) { $("modelStat").textContent = "Build failed: " + r.error; $("modelSel").value = curModel ?? ""; return; }
    await refreshList();
    stamps = (await (await fetch("/api/version")).json()).models;
  }
  curModel = id;
  try { localStorage.setItem("cad.model", id); } catch (e) { /* ignore */ }
  planesLoaded = false; collisions = []; activeCon = null; mPts = [];
  Object.keys(values).forEach((k) => delete values[k]);
  if (inspectMode) setInspect(false);
  $("modelSel").value = id;
  await loadModel(id, true);
}
async function loadModel(id, fresh) {
  const tl = performance.now();
  const res = await fetch(`/api/model?m=${encodeURIComponent(id)}`);
  if (!res.ok) { $("modelStat").textContent = "Model not found"; return; }
  const m = await res.json();
  if (!m.parts) return;
  model = m; modelStamp = stamps?.[id] ?? 0;
  loadHistory();
  $("modelStat").textContent = `${m.parts.length} parts, ${m.joints.length} joints`;
  const prev = { ...values };
  model.joints.forEach((j) => (values[j.name] = prev[j.name] ?? model.presets[model.default]?.[j.name] ?? 0));
  kinLabels.forEach((l) => l.el.remove()); kinLabels = [];
  build(); rebuildGrid(); buildPoseUI(); buildConsUI(); buildParamsUI();
  scheduleCheck();
  if (fresh) { if (layoutMode) fitLayout(); else look(0.6, -0.6, 0.5); }
  perf.load = performance.now() - tl;
}
$("modelSel").onchange = (e) => switchModel(e.target.value);
async function importFile(f) {
  const ext = f.name.split(".").pop().toLowerCase();
  const name = f.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]/g, "_").replace(/^[_-]+/, "") || "import";
  $("modelStat").textContent = `Importing ${f.name}…`;
  const r = await (await fetch(`/api/import?name=${encodeURIComponent(name)}&ext=${ext}`, { method: "POST", headers: { "X-CAD-Token": window.CAD_TOKEN }, body: f })).json();
  if (!r.ok) { $("modelStat").textContent = "Import failed: " + r.error; return; }
  await refreshList();
  stamps = (await (await fetch("/api/version")).json()).models;
  await switchModel(name);
}
$("modelImport").onclick = () => $("importFile").click();
$("importFile").onchange = (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ""; };
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f && /\.(step|stp|stl)$/i.test(f.name)) importFile(f); });
$("modelRebuild").onclick = async () => {
  if (!curModel) return;
  $("modelStat").textContent = "Rebuilding…";
  const r = await (await fetch("/api/build", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify({ script: curModel }) })).json();
  $("modelStat").textContent = r.ok ? "Rebuilt." : "Build failed: " + r.error;
};
// ---------------------------------------------------------------- Creo link (experimental)
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
if (location.hash === "#creo") document.querySelector('#tabs [data-p="creo"]').click();

setInterval(poll, 1500);
poll();
rebuildGrid();
applyDisplay();

const tmp = new THREE.Vector3();
const tb = new THREE.Vector3();
function place(l) {
  tmp.copy(l.pos).project(camera);
  let vis = tmp.z < 1 && !l.hidden;
  if (vis && l.span) {          // hide labels that are wider than the feature they describe (zoom in to see them)
    tb.copy(l.span[0]).project(camera);
    const ax = tb.x, ay = tb.y;
    tb.copy(l.span[1]).project(camera);
    const px = Math.hypot((tb.x - ax) * innerWidth, (tb.y - ay) * innerHeight) / 2;
    vis = px > (l.w ?? l.el.offsetWidth) * 0.5 + 4;
  }
  l.el.style.display = vis ? "block" : "none";
  l.el.style.left = ((tmp.x + 1) / 2) * innerWidth + "px";
  l.el.style.top = ((1 - tmp.y) / 2) * innerHeight + "px";
}
const perf = { render: 0, frames: 0, t: performance.now(), fps: 0, pose: 0, load: 0, check: 0 };
setInterval(() => {
  const now = performance.now(), dt = (now - perf.t) / 1000;
  perf.fps = perf.frames / dt; perf.frames = 0; perf.t = now;
  const el = $("perf");
  el.style.display = disp.perf ? "" : "none";
  if (!disp.perf) return;
  const i = renderer.info.render;
  el.textContent = `${perf.fps.toFixed(0)} fps · render ${perf.render.toFixed(1)} ms · ${i.calls} draws · ${(i.triangles / 1000).toFixed(1)}k tris · pose ${perf.pose.toFixed(1)} ms · model load ${perf.load.toFixed(0)} ms · collision check ${perf.check.toFixed(0)} ms`;
}, 500);
(function loop() {
  requestAnimationFrame(loop);
  if (inspectMode) { ictl.update(); renderInspect(); return; }
  controls.update();
  const t0 = performance.now();
  renderer.render(scene, camera);
  perf.render = perf.render * 0.9 + (performance.now() - t0) * 0.1;
  perf.frames++;
  labels.forEach((l) => { const h = l.hidden; if (!overlayVisible(disp, measureMode)) l.hidden = true; place(l); l.hidden = h; });
  kinLabels.forEach(place);
  layoutLabels.forEach(place);
  planeLbl.forEach((l) => { l.hidden = layoutMode || !disp.planes; place(l); });
})();

// ---------------------------------------------------------------- menu bar: File, View, Tools, Assistant, Help
const api = async (path, body) => (await fetch(path, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify(body) })).json();
const menuCache = { projects: [], library: [], joints: [], exports: [] };
async function menuState(refresh) {
  if (refresh || !menuCache.library.length) {
    try {
      const [p, l, j, x] = await Promise.all([api("/api/projects"), api("/api/library"), api("/api/joints?t=18"), curModel ? api("/api/exports?m=" + encodeURIComponent(curModel)) : []]);
      Object.assign(menuCache, { projects: p.projects, library: l, joints: j, exports: x });
    } catch (e) { /* server restarting: show what we have */ }
  }
  return { ...menuCache, curModel, assistant: lastAssistant ?? {}, display: disp, displayItems: DISPLAY_ITEMS };
}
const say = (t) => { $("modelStat").textContent = t; };
const tabTo = (t) => document.querySelector(`#tabs div[data-p="${t}"]`)?.click();
async function newModel(body, label) {
  const r = await api("/api/model/new", body);
  if (!r.ok) { dialog("Could not create the model", `<p>${r.error}</p>`); return; }
  await refreshList(); await switchModel(r.id); say(`${label} ${r.id} created`);
}
async function openProjectResult(r) {
  if (!r.ok) { dialog("Could not open the project", `<p>${r.error}</p>`); return; }
  if (r.url) location.href = r.url;                                     // each project is served on its own port
}
function exportStl() {
  const parts = meshes.filter((m) => m.visible).map((m) => ({ positions: m.geometry.attributes.position.array, index: m.geometry.index.array, matrix: m.matrixWorld.elements }));
  download(`${model.name || curModel}_pose.stl`, toBinaryStl(parts), "model/stl");
}
function settingsDialog() {
  Promise.all([api("/api/settings"), api("/api/providers")]).then(([c, pr]) => {
    const f = (k, label, type = "text", hint = "") => `<label>${label}${hint ? ` <small style="color:var(--dim)">${hint}</small>` : ""}<input type="${type}" data-k="${k}" ${type === "checkbox" ? (c[k] ? "checked" : "") : `value="${String(c[k]).replace(/"/g, "&quot;")}"`}></label>`;
    const sel = (k, label, opts) => `<label>${label}<select data-k="${k}">${opts.map(([v, t]) => `<option value="${v}"${c[k] === v ? " selected" : ""}>${t}</option>`).join("")}</select></label>`;
    dialog("Settings", [sel("provider", "AI assistant", pr.providers.map((p) => [p.id, p.name])), sel("assistant_mode", "How it answers", [["message", "Once per message (cheapest, any agent)"], ["session", "Live session (keeps its context)"]]),
      f("assistant_cmd", "Command of your own agent", "text", "only for 'Another agent'; {prompt} is replaced by the message"), `<p><span class="btn" id="openWizard">Setup wizard…</span></p>`,
      f("terminal", "Terminal command", "text", "empty = first terminal found, e.g. gnome-terminal --"), f("projects_dir", "Folder for new projects"), f("clearance", "Default glue gap for joints (mm)", "number"),
      f("auto_open_chat", "Open the chat when I select a part or the assistant answers", "checkbox"), `<p style="color:var(--dim)">Saved for all projects in ~/.config/cadchat/settings.json.</p>`].join(""), [
      { label: "Cancel" },
      { label: "Save", primary: true, onClick: async (c2) => {
        const body = {};
        c2.querySelectorAll("[data-k]").forEach((i) => { body[i.dataset.k] = i.type === "checkbox" ? i.checked : i.type === "number" ? +i.value : i.value; });
        const r = await api("/api/settings", body);
        if (!r.ok) { c2.querySelector("p:last-child").textContent = r.error; c2.querySelector("p:last-child").style.color = "#ffb0a8"; return false; }
        autoOpenChat = !!r.settings.auto_open_chat; say("Settings saved");
      } }]).content.querySelector("#openWizard").onclick = () => { document.querySelectorAll(".modal").forEach((m) => m.remove()); wizard(); };
  });
}
async function jointsDialog(focus) {
  const mk = async (t) => {
    const list = await api("/api/joints?t=" + encodeURIComponent(t));
    return list.map((j) => `<tr${j.kind === focus ? ' style="background:#33363c"' : ""}><td><b>${j.label}</b><br><small style="color:var(--dim)">${j.description}</small></td><td>${Object.entries(j.defaults).map(([k, v]) => `${k.replace(/_/g, " ")} ${Math.round(v * 10) / 10}`).join("<br>")}</td></tr>`).join("");
  };
  const d = dialog("Joint library", `<label>Board thickness (mm)<input type="number" id="jt" value="18" min="3" max="100"></label><table id="jtab"><tr><th>Joint</th><th>Usual proportions</th></tr>${await mk(18)}</table>
    <p style="color:var(--dim)">In a model script: <code>import joints</code>, then <code>joints.dado(side, shelf)</code>. Demo with all five: library model <b>joinery_demo</b>.</p>`, [
    { label: "Add the demo to this project", onClick: async () => { await newModel({ library: "joinery_demo", name: "joinery_demo" }, "Demo"); } },
    { label: "Close", primary: true }]);
  d.content.querySelector("#jt").oninput = async (e) => { const t = +e.target.value; if (t > 0) d.content.querySelector("#jtab").innerHTML = `<tr><th>Joint</th><th>Usual proportions</th></tr>` + (await mk(t)); };
}
const HELP = {
  start: ["Quick start", `<p><b>Look:</b> drag to turn, wheel to zoom, click a part for its size. Pick a pose (open, closed...) or move the joint sliders.</p><p><b>Measure:</b> <kbd>M</kbd> then click two points. <kbd>S</kbd> adds a section plane. <kbd>I</kbd> isolates the selection.</p><p><b>Ask:</b> select a part, press <b>💬</b> and say what to change. The assistant answers in the chat and the model rebuilds.</p><p><b>Make:</b> the Make tab shows cut list and print plates. <b>History</b> restores any earlier build.</p><p><b>Phone:</b> File ▸ Export ▸ Workshop site builds pages with views, dimensions and tap-to-measure.</p>`],
  keys: ["Keyboard shortcuts", `<table><tr><td><kbd>M</kbd></td><td>Measure</td></tr><tr><td><kbd>S</kbd></td><td>Section</td></tr><tr><td><kbd>I</kbd></td><td>Isolate selection</td></tr><tr><td><kbd>D</kbd></td><td>Dimensions</td></tr><tr><td><kbd>A</kbd></td><td>Select all parts</td></tr><tr><td><kbd>H</kbd></td><td>Hide or show all overlays</td></tr><tr><td><kbd>←</kbd> <kbd>→</kbd></td><td>Previous or next part</td></tr><tr><td><kbd>Esc</kbd></td><td>Clear, close menus</td></tr></table>`],
  resume: ["Coming back after a break", `<p>Start the viewer with <code>./cadchat start</code> or the <b>CAD chat</b> icon. It opens the project you used last; <b>File ▸ Open recent</b> switches project.</p><p>The chat shows the whole conversation of the project. Replies only arrive while an assistant is listening: <b>Assistant ▸ Start listening</b> opens one in a terminal. Until then your messages wait.</p><p>Every build is kept in <b>History</b>; <b>File ▸ Save version</b> adds a named one.</p>`],
};
const ACTIONS = {
  "project:new": async () => { const n = await ask("New project", "Name", "", "Create"); if (n) openProjectResult(await api("/api/project/new", { name: n })); },
  "model:new:part": async () => { const n = await ask("New part", "Name (letters, digits, _ or -)", "", "Create"); if (n) newModel({ kind: "part", name: n }, "Part"); },
  "model:new:mechanism": async () => { const n = await ask("New mechanism", "Name (letters, digits, _ or -)", "", "Create"); if (n) newModel({ kind: "mechanism", name: n }, "Mechanism"); },
  "version:save": async () => { const n = await ask("Save version", "Note", "", "Save"); if (n && curModel) { const r = await api("/api/version/save", { m: curModel, note: n }); say(r.ok ? "Version saved" : "Could not save: " + r.error); loadHistory(); } },
  import: () => $("importFile").click(),
  "export:stl": exportStl,
  "export:plates": () => { tabTo("make"); say("Plates are in the Make tab: STL per plate"); },
  "export:cutlist": () => { tabTo("make"); setTimeout(() => { $("cutCsv").click(); tabTo("pose"); }, 60); },
  "export:shot": () => renderer.domElement.toBlob((b) => b && download(`${curModel || "view"}.png`, b, "image/png")),
  "export:site": async () => { const r = await api("/api/share/build", { m: curModel }); dialog("Workshop site", r.ok ? `<p>${r.files.length} files written to <code>${r.path}</code>.</p><p>On the phone: run <code>./cadchat share --serve</code> and open the address it prints (same wifi), or publish the page as an artifact.</p>` : `<p>${r.error}</p>`); },
  settings: settingsDialog,
  "view:iso": VIEW_FN.iso, "view:top": VIEW_FN.top, "view:front": VIEW_FN.front, "view:side": VIEW_FN.side, "view:fit": VIEW_FN.fit,
  "usage:open": () => usageDialog(),
  "display:all": () => setDisp(preset("all")), "display:clean": () => setDisp(preset("clean")),
  "tool:measure": () => $("tMeas").click(), "tool:section": () => $("tSec").click(), "tool:isolate": () => $("tIso").click(), "tool:check": () => scheduleCheck(),
  "joints:open": () => jointsDialog(),
  "assistant:start": () => $("astart").click(), "chat:open": () => openChat(),
  "chat:clear": () => clearChatDialog(),
  "help:tour": () => tourDialog(), "help:wizard": () => wizard(),
  "help:about": async () => { const v = await api("/api/version"); dialog("About cadchat", `<p>Code-CAD workbench: build123d models, a viewer with chat, measuring, sections, cut lists and a workshop site for the phone.</p><p>Project <b>${v.name}</b><br><code>${v.project}</code></p>`); },
};
async function runMenu(id) {
  if (ACTIONS[id]) return ACTIONS[id]();
  if (id.startsWith("project:open:")) return openProjectResult(await api("/api/project/open", { path: id.slice(13) }));
  if (id.startsWith("model:lib:")) { const lib = id.slice(10); const n = await ask("Add from library", "Name in this project", lib, "Add"); if (n) newModel({ library: lib, name: n }, "Model"); return; }
  if (id.startsWith("export:file:")) { location.href = "/api/export/file?name=" + encodeURIComponent(id.slice(12)); return; }
  if (id.startsWith("display:")) return setDisp(toggled(disp, id.slice(8)));
  if (id.startsWith("joint:")) return jointsDialog(id.slice(6));
  if (id.startsWith("help:") && HELP[id.slice(5)]) { const [t, b] = HELP[id.slice(5)]; dialog(t, b); }
}
mountMenubar($("menubar"), menuState, runMenu);
addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); ACTIONS["version:save"](); } });

// ---------------------------------------------------------------- token usage: small badge always, details in View > Token usage
let usageData = null;
function drawUsageMini() {
  if (!usageData) return;
  const days = lastDays(usageData.days, 7, new Date().toISOString().slice(0, 10)), h = scale(days.map((d) => d.output));
  $("usageSpark").innerHTML = days.map((d, i) => `<rect class="${d.output ? "" : "z"}" x="${i * 6}" y="${16 - Math.max(1.5, h[i] * 16)}" width="4" height="${Math.max(1.5, h[i] * 16)}" rx="1"/>`).join("");
  $("usageText").textContent = badgeText(usageData);
  const t = usageData.total;
  $("usageMini").title = `This project's assistant sessions (${usageData.sources}): written ${fmtTokens(t.output)}, new input ${fmtTokens(t.input + t.cache_creation)}, read from cache ${fmtTokens(t.cache_read)}, ${t.messages} replies. Click for details.`;
}
async function usagePoll() {
  try { usageData = await api("/api/usage"); drawUsageMini(); } catch (e) { /* server restarting */ }
}
function usageDialog() {
  const r = usageData; if (!r) return;
  const days = lastDays(r.days, 14, new Date().toISOString().slice(0, 10));
  const tot = (d) => d.output + d.input + d.cache_creation + d.cache_read, max = Math.max(1, ...days.map(tot)), H = 110, bw = 34;
  const bars = days.map((d, i) => { let y = H; return barSegments(d, max, H).map((sg) => { y -= sg.h; return `<rect class="${sg.kind[0]}" x="${i * bw + 4}" y="${y}" width="${bw - 8}" height="${sg.h}"/>`; }).join("") + `<text x="${i * bw + bw / 2}" y="${H + 12}" text-anchor="middle">${d.date.slice(8)}</text>`; }).join("");
  const week = days.slice(-7).reduce((a, d) => ({ output: a.output + d.output, new: a.new + d.input + d.cache_creation, cache: a.cache + d.cache_read }), { output: 0, new: 0, cache: 0 });
  const card = (t, v, sub) => `<div><small>${t}</small><b>${v}</b><small>${sub}</small></div>`;
  const row = (cells) => `<tr>${cells.map((c, i) => `<td${i ? ' style="text-align:right"' : ""}>${c}</td>`).join("")}</tr>`;
  const html = `<div class="ucards">${card("Today written", fmtTokens(r.today.output), r.today.messages + " replies")}${card("7 days written", fmtTokens(week.output), fmtTokens(week.new) + " new input")}
    ${card("All time written", fmtTokens(r.total.output), r.total.messages + " replies")}${card("From cache", Math.floor(r.cache_share * 100) + "%", fmtTokens(r.total.cache_read) + " read")}</div>
    <svg class="uchart" width="${days.length * bw}" height="${H + 18}" viewBox="0 0 ${days.length * bw} ${H + 18}" style="max-width:100%">${bars}</svg>
    <div style="color:var(--dim);font-size:11px;margin:2px 0 8px"><span style="color:var(--acc)">■</span> written &nbsp;<span style="color:#6cb2ff">■</span> new input &nbsp;<span style="color:#7a8194">■</span> cached input · last 14 days (UTC)</div>
    <h4>Models</h4><table>${row(["model", "written", "new input", "cached"])}${Object.entries(r.models).map(([m, v]) => row([m, fmtTokens(v.output), fmtTokens(v.input + v.cache_creation), fmtTokens(v.cache_read)])).join("")}</table>
    <h4>Sessions</h4><table>${row(["session", "last active", "replies", "written"])}${r.sessions.slice(0, 8).map((x) => row([x.id.slice(0, 8), (x.last || "").replace("T", " ").slice(0, 16), x.messages, fmtTokens(x.output)])).join("")}</table>
    <p style="color:var(--dim);font-size:11px">Read from the Claude Code transcripts of sessions that mention this project (${r.sources} found). Folders can be set in Settings.</p>`;
  dialog("Token usage", html);
}
$("usageMini").onclick = () => usageDialog();
usagePoll(); setInterval(usagePoll, 30000);

// ---------------------------------------------------------------- clear the chat (archived, so the conversation does not just grow)
function clearChatDialog() {
  dialog("Clear the chat and the assistant session", `<p>The conversation of this project is moved to <code>.cad/chat-archive/</code> (nothing is deleted) and the chat starts empty.</p>
    <p>An assistant that was started from here (button, menu or launcher icon) is closed and a fresh one is opened with an empty context, so old screenshots and errors are not sent again.</p>
    <p style="color:var(--dim)">An assistant you started by hand cannot be reset from here: it is told that everything earlier is closed, and you can end that session yourself.</p>`, [
    { label: "Cancel" },
    { label: "Clear and restart assistant", primary: true, onClick: async () => {
      const r = await api("/api/chat/clear", {});
      const a = { restarted: " · a fresh assistant session was opened", none: " · no assistant started from here (a manual one only got a note)" }[r.assistant] ?? "";
      say(r.ok ? (r.archived ? `Chat cleared (${r.archived} messages archived)` : "The chat was already empty") + a : "Could not clear: " + r.error);
      shown = -1; poll();
    } }]);
}
$("cclear").onclick = (e) => { e.stopPropagation(); clearChatDialog(); };

// ---------------------------------------------------------------- first-start wizard: tour + connect an AI agent
function tourHtml() { return TOUR.map((t, i) => `<p><b>${i + 1}. ${t.title}</b><br><span style="color:var(--dim)">${t.text}</span></p>`).join(""); }
function tourDialog() { dialog("What can cadchat do?", tourHtml()); }
async function wizard() {
  const pr = await api("/api/providers");
  const st = { step: 0, provider: pr.current.provider, mode: pr.current.assistant_mode, command: "", det: {} };
  const get = (id) => pr.providers.find((p) => p.id === id);
  const d = dialog("Set up cadchat", "<div id='wz'></div>", []);
  const box = d.content.querySelector("#wz");
  pr.providers.filter((p) => p.id !== "custom").forEach((p) => api("/api/providers/test", { id: p.id }).then((r) => { st.det[p.id] = r; if (st.step === 1 || st.step === 2) render(); }));
  const nav = (back, next, nextLabel = "Next") => `<div class="mbtns"><span class="btn" id="wz-skip" style="float:left">Skip for now</span>${back ? '<span class="btn" id="wz-back">Back</span>' : ""}<span class="btn on" id="wz-next">${nextLabel}</span></div>`;
  const badge = (id) => { const r = st.det[id]; return !r ? '<small style="color:var(--dim)">checking…</small>' : r.installed ? `<small style="color:#9be3a8">✓ installed ${r.version || ""}</small>` : '<small style="color:#ffb0a8">not installed</small>'; };
  async function finish(start) {
    const body = { provider: st.provider, assistant_mode: st.mode, setup_done: true };
    if (st.provider === "custom") body.assistant_cmd = st.command;
    const r = await api("/api/settings", body);
    if (!r.ok) { box.insertAdjacentHTML("afterbegin", `<p style="color:#ffb0a8">${r.error}</p>`); return; }
    d.close();
    if (start) { await api("/api/assistant/start", {}); say("Starting the assistant…"); }
  }
  function render() {
    const p = get(st.provider);
    if (st.step === 0) {
      box.innerHTML = `<h3 style="margin:0 0 6px">Welcome</h3>${tourHtml()}${nav(false, true, "Connect an AI assistant ▸")}`;
    } else if (st.step === 1) {
      box.innerHTML = `<h3 style="margin:0 0 6px">Which AI do you use?</h3><p style="color:var(--dim)">The assistant edits the models when you ask in the chat. Pick the subscription you already have.</p>` +
        pr.providers.map((q) => `<label style="display:block;padding:6px 8px;border:1px solid var(--line);border-radius:6px;margin:4px 0;cursor:pointer"><input type="radio" name="wzp" value="${q.id}" ${q.id === st.provider ? "checked" : ""}> <b>${q.name}</b> ${q.id === "custom" ? "" : badge(q.id)}<br><small style="color:var(--dim)">${q.subscription}</small></label>`).join("") + nav(true, true);
      box.querySelectorAll("input[name=wzp]").forEach((i) => (i.onchange = () => { st.provider = i.value; st.mode = recommendedMode(get(i.value)); }));
    } else if (st.step === 2) {
      const r = st.det[p.id];
      box.innerHTML = `<h3 style="margin:0 0 6px">Sign in: ${p.name}</h3>` + (p.id === "custom" ? `<label>Command <small style="color:var(--dim)">{prompt} is replaced by the message, otherwise it is added at the end</small><input type="text" id="wz-cmd" value="${st.command.replace(/"/g, "&quot;")}" placeholder="myagent --yes"></label>` :
        `<p>${r?.installed ? `<span style="color:#9be3a8">✓ Found ${r.path} ${r.version || ""}</span>` : `<span style="color:#ffb0a8">Not found on this computer.</span> Install it first:<br><code>${p.install}</code>`}</p>`) +
        `<p><b>Sign in</b></p><ol style="margin:4px 0 8px 18px;padding:0">${p.login.map((l) => `<li>${l}</li>`).join("")}</ol><p style="color:var(--dim)">Needs: ${p.subscription}.</p>` + (p.id === "custom" ? "" : '<p><span class="btn" id="wz-recheck">Check again</span></p>') + nav(true, true);
      const c = box.querySelector("#wz-cmd"); if (c) c.oninput = () => { st.command = c.value; };
      const rc = box.querySelector("#wz-recheck"); if (rc) rc.onclick = () => api("/api/providers/test", { id: p.id }).then((x) => { st.det[p.id] = x; render(); });
    } else if (st.step === 3) {
      box.innerHTML = `<h3 style="margin:0 0 6px">How should it answer?</h3>
        <label style="display:block;padding:6px 8px;border:1px solid var(--line);border-radius:6px;margin:4px 0;cursor:pointer"><input type="radio" name="wzm" value="message" ${st.mode === "message" ? "checked" : ""}> <b>Once per message</b> ${p.listens ? "" : "(recommended)"}<br><small style="color:var(--dim)">Every chat message runs the agent once. Works with any agent and costs the same however long the project is: nothing from earlier messages is resent.</small></label>
        <label style="display:block;padding:6px 8px;border:1px solid var(--line);border-radius:6px;margin:4px 0;cursor:pointer"><input type="radio" name="wzm" value="session" ${st.mode === "session" ? "checked" : ""}> <b>Live session</b> ${p.listens ? "(recommended)" : ""}<br><small style="color:var(--dim)">An interactive agent in a terminal listens to the chat and remembers the conversation. Richer for long work, but its context grows (Clear chat resets it).</small></label>` + nav(true, true);
      box.querySelectorAll("input[name=wzm]").forEach((i) => (i.onchange = () => { st.mode = i.value; }));
    } else {
      box.innerHTML = `<h3 style="margin:0 0 6px">Ready</h3><p>${summary(p, st.mode, { command: st.command })}</p><p style="color:var(--dim)">Change this any time in Settings, or run the wizard again from Help ▸ Set up the AI assistant. Help ▸ What can cadchat do? shows the tour again.</p>
        <div class="mbtns"><span class="btn" id="wz-back">Back</span><span class="btn" id="wz-save">Save</span><span class="btn on" id="wz-start">Save and start the assistant</span></div>`;
      box.querySelector("#wz-save").onclick = () => finish(false);
      box.querySelector("#wz-start").onclick = () => finish(true);
    }
    box.querySelector("#wz-back")?.addEventListener("click", () => { st.step--; render(); });
    box.querySelector("#wz-skip")?.addEventListener("click", async () => { await api("/api/settings", { setup_done: true }); d.close(); });
    box.querySelector("#wz-next")?.addEventListener("click", () => {
      if (st.step === 2 && !canContinue(p, st.command)) { box.insertAdjacentHTML("afterbegin", '<p style="color:#ffb0a8">Enter the command of your agent first.</p>'); return; }
      st.step++; render();
    });
  }
  render();
}
async function firstStart() {
  try {
    const [c, a] = await Promise.all([api("/api/settings"), api("/api/assistant")]);
    if (needsWizard(c, a)) wizard();
    else if (!c.setup_done) api("/api/settings", { setup_done: true });             // an assistant is already listening: nothing to set up
  } catch (e) { /* server restarting */ }
}
setTimeout(firstStart, 1500);
