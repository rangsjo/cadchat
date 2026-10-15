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
const grid = new THREE.GridHelper(6000, 60, 0x555a62, 0x3a3d43);
grid.rotation.x = Math.PI / 2;
scene.add(grid);
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
function applyPose() {
  meshes.forEach((m) => {
    m.matrix.copy(m.userData.joint ? chainMatrix(m.userData.joint) : new THREE.Matrix4());
    m.matrixWorldNeedsUpdate = true;
  });
  group.updateMatrixWorld(true);
  updateKin();
  updateInfo();
  drawDims();
  rebuildCaps();
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
    l.hidden = !showAxes || (activeTab !== "cons" && !activeCon) || (activeCon && activeCon.joint && activeCon.joint !== l.joint.name);
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
$("vIso").onclick = () => look(0.6, -0.6, 0.5);
$("vTop").onclick = () => look(0, -0.001, 1);
$("vFront").onclick = () => look(0, -1, 0.05);
$("vSide").onclick = () => look(1, 0, 0.05);
$("vFit").onclick = fitSelection;

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
  const r = Math.max(4, camera.position.distanceTo(controls.target) * 0.006);
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
    if (!hit) return;
    if (mPts.length >= 2) mPts = [];
    mPts.push(snap(hit)); drawDims();
    if (mPts.length === 2) $("infotxt").textContent = `Distance ${fmt(mPts[0].distanceTo(mPts[1]))} mm`;
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
function setMeasure(on) { measureMode = on; if (!on) mPts = []; renderer.domElement.style.cursor = on ? "crosshair" : ""; restyle(); drawDims(); }
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
  const seq = ++checkSeq;
  try {
    const res = await fetch("/api/check", { method: "POST", headers: { "Content-Type": "application/json", "X-CAD-Token": window.CAD_TOKEN }, body: JSON.stringify({ m: curModel, values }) });
    if (res.status === 403) { location.reload(); return; }          // the server was restarted and issued a new token
    const r = await res.json();
    if (seq !== checkSeq) return;
    if (!r.ok) { $("coll").textContent = "Collision check failed: " + r.error; $("coll").className = "bad"; return; }
    collisions = r.collisions;
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
  lk("sAxes", () => (showAxes = !showAxes));
  lk("sLinks", () => (showLinks = !showLinks));
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
  group.visible = !layoutMode; kinOverlay.visible = !layoutMode; planeGroup.visible = !layoutMode; capAll.visible = !layoutMode;
  grid.visible = !layoutMode;
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
  planeGroup.visible = !layoutMode;
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
  const h = $("ahint");
  h.style.display = p.detail ? "block" : "none";
  h.textContent = p.detail;
}
$("apill").onclick = () => openChat();
setInterval(assistantPoll, 2000);
assistantPoll();
let connOk = true;
function setConn(ok) { if (ok !== connOk) { connOk = ok; $("conn").style.display = ok ? "none" : "block"; } }
async function poll() {
  try {
    const msgs = await (await fetch("/api/chat")).json();
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
          s.textContent = [on ? "on " + on : "", stateLabel(m.state)].filter(Boolean).join(" · ");
          if (s.textContent) d.appendChild(s);
        }
        log.appendChild(d);
      }
      log.scrollTop = log.scrollHeight;
      if (msgs.length > shown && shown && msgs[msgs.length - 1].role !== "user" && autoOpenChat) openChat();
      shown = msgs.length;
    }
    const v = await (await fetch("/api/version")).json();
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
  const res = await fetch(`/api/model?m=${encodeURIComponent(id)}`);
  if (!res.ok) { $("modelStat").textContent = "Model not found"; return; }
  const m = await res.json();
  if (!m.parts) return;
  model = m; modelStamp = stamps?.[id] ?? 0;
  $("modelStat").textContent = `${m.parts.length} parts, ${m.joints.length} joints`;
  const prev = { ...values };
  model.joints.forEach((j) => (values[j.name] = prev[j.name] ?? model.presets[model.default]?.[j.name] ?? 0));
  kinLabels.forEach((l) => l.el.remove()); kinLabels = [];
  build(); buildPoseUI(); buildConsUI(); buildParamsUI();
  scheduleCheck();
  if (fresh) { if (layoutMode) fitLayout(); else look(0.6, -0.6, 0.5); }
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
setInterval(poll, 1500);
poll();

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
(function loop() {
  requestAnimationFrame(loop);
  if (inspectMode) { ictl.update(); renderInspect(); return; }
  controls.update();
  renderer.render(scene, camera);
  labels.forEach(place);
  kinLabels.forEach(place);
  layoutLabels.forEach(place);
  planeLbl.forEach((l) => { l.hidden = layoutMode; place(l); });
})();
