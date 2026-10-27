import { ASPECTS, cropRect, defaultCrop, frameSize, isIdentity, renderGeometry } from "./geometry.js";
import { Renderer } from "./renderer.js";

// ------------------------------------------------------------------ config

const SLIDERS = [
  { group: "Licht" },
  { key: "exposure", label: "Belichting", min: -100, max: 100 },
  { key: "contrast", label: "Contrast", min: -100, max: 100 },
  { key: "highlights", label: "Hoge lichten", min: -100, max: 100 },
  { key: "shadows", label: "Schaduwen", min: -100, max: 100 },
  { key: "blacks", label: "Zwarten", min: -100, max: 100 },
  { key: "fade", label: "Fade", min: 0, max: 100 },
  { group: "Kleur" },
  { key: "saturation", label: "Verzadiging", min: -100, max: 100 },
  { key: "temperature", label: "Temperatuur", min: -100, max: 100 },
  { key: "tint", label: "Tint", min: -100, max: 100 },
  { group: "Kleurtinten" },
  { key: "orange_sat", label: "Huid / oranje verzadiging", min: -100, max: 100 },
  { key: "orange_lum", label: "Huid / oranje helderheid", min: -100, max: 100 },
  { key: "orange_hue", label: "Huid / oranje tint", min: -100, max: 100 },
  { key: "yellow_sat", label: "Geel / beige verzadiging", min: -100, max: 100 },
  { key: "green_sat", label: "Groen verzadiging", min: -100, max: 100 },
  { key: "green_hue", label: "Groen tint", min: -100, max: 100 },
  { key: "blue_sat", label: "Blauw verzadiging", min: -100, max: 100 },
  { key: "blue_hue", label: "Blauw tint", min: -100, max: 100 },
  { group: "Effecten" },
  { key: "sharpness", label: "Scherpte", min: 0, max: 100 },
  { key: "grain", label: "Korrel", min: 0, max: 100 },
  { key: "vignette", label: "Vignet", min: 0, max: 100 },
];
const RANGES = {};
for (const s of SLIDERS) if (s.key) RANGES[s.key] = [s.min, s.max];
RANGES.split_shadow = [0, 100];
RANGES.split_highlight = [0, 100];
const HUES = ["split_shadow_hue", "split_highlight_hue"];
const DEFAULT_HUES = { split_shadow_hue: 210, split_highlight_hue: 40 };

// ------------------------------------------------------------------ helpers

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const isDesktop = () => window.matchMedia("(min-width: 900px)").matches;

async function api(method, url, body) {
  // Cloudflare-versie: de "server" draait in de browser zelf
  if (window.FOTOSTUDIO_LOCAL) return window.FOTOSTUDIO_LOCAL(method, url, body);
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (res.status === 401 && !url.startsWith("/api/auth/")) {
    showLogin();
    throw new Error("Log eerst in");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(text, { error = false, action = null, ms = 4000 } = {}) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  const span = document.createElement("span");
  span.textContent = text;
  el.append(span);
  if (action) {
    const b = document.createElement("button");
    b.textContent = action.label;
    b.onclick = () => { action.run(); el.remove(); };
    el.append(b);
  }
  $("#toasts").append(el);
  setTimeout(() => el.remove(), action ? ms + 4000 : ms);
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Afbeelding laden mislukt"));
    img.src = url;
  });
}

function fmtSize(w, h) { return `${w} × ${h}`; }
function fmtTime(sec) {
  if (sec == null) return "";
  if (sec < 60) return `nog ±${Math.max(1, Math.round(sec))} s`;
  return `nog ±${Math.round(sec / 60)} min`;
}

function modal({ html, buttons }) {
  return new Promise((resolve) => {
    $("#modal-body").innerHTML = html;
    const actions = $("#modal-actions");
    actions.innerHTML = "";
    const close = (v) => { $("#modal").hidden = true; resolve(v); };
    for (const b of buttons) {
      const el = document.createElement("button");
      el.className = "btn " + (b.cls || "");
      el.textContent = b.label;
      el.onclick = () => close(b.value === "input" ? $("#modal-body input")?.value : b.value);
      actions.append(el);
    }
    $("#modal").onclick = (e) => { if (e.target.id === "modal") close(null); };
    $("#modal").hidden = false;
    const input = $("#modal-body input");
    if (input) {
      input.focus();
      input.onkeydown = (e) => { if (e.key === "Enter") close(input.value); };
    }
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ------------------------------------------------------------------ status

const app = {
  photos: [],
  currentId: null,
  presets: [],
  byId: {},
  status: null,
  previewImg: null,
  thumbImg: null,
  compare: false,
  split: 0.5,
};

const freshState = () => ({ preset: null, strength: 100, adjust: {} });
const current = () => app.photos.find((p) => p.id === app.currentId) || null;
function curState() {
  const p = current();
  if (!p) return freshState();
  if (!p.state) p.state = freshState();
  p.state.adjust = p.state.adjust || {};
  return p.state;
}

function effective(st) {
  const preset = st.preset ? app.byId[st.preset] : null;
  const s = clamp(st.strength ?? 100, 0, 100) / 100;
  const adj = st.adjust || {};
  const out = {};
  for (const [k, [lo, hi]] of Object.entries(RANGES)) {
    const base = preset ? (preset.params[k] || 0) * s : 0;
    out[k] = clamp(base + (Number(adj[k]) || 0), lo, hi);
  }
  for (const k of HUES) {
    const amount = k.replace("_hue", "");
    if (preset && preset.params[amount] > 0) out[k] = preset.params[k];
    else out[k] = adj[k] ?? (preset ? preset.params[k] : DEFAULT_HUES[k]);
  }
  return out;
}

function presetBase(st, key) {
  const preset = st.preset ? app.byId[st.preset] : null;
  return preset ? (preset.params[key] || 0) * clamp(st.strength ?? 100, 0, 100) / 100 : 0;
}

// ------------------------------------------------------------------ renderen

const view = $("#view");
let renderer, thumbRenderer;
try {
  renderer = new Renderer(view);
  thumbRenderer = new Renderer(document.createElement("canvas"));
} catch (e) {
  document.body.innerHTML = `<div style="padding:40px;text-align:center">De foto-weergave kon niet starten in deze browser.<br>Probeer Chrome, Edge, Firefox of Safari.<br><br><small>${escapeHtml(e.message)}</small></div>`;
  throw e;
}

let rafPending = false;
function scheduleRender() {
  if (rafPending) return;
  rafPending = true;
  requestAnimationFrame(() => {
    rafPending = false;
    if (app.previewImg) renderer.render(effective(curState()));
  });
}

let saveTimer = null;
let pendingSave = null;
function persistState() {
  const p = current();
  if (!p) return;
  pendingSave = p.id;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSave, 500);
}
async function flushSave() {
  clearTimeout(saveTimer);
  const id = pendingSave;
  pendingSave = null;
  const p = app.photos.find((x) => x.id === id);
  if (p) await api("PUT", `/api/photos/${id}/state`, { state: p.state }).catch(() => {});
}

function changed() {
  if (app.showOriginal) {
    app.showOriginal = false;
    applyOriginal();
  }
  scheduleRender();
  syncControls();
  persistState();
  if (!app.restoring) scheduleCommit();
}

function layoutFrame() {
  const p = current();
  const frame = $("#frame");
  if (!p || !app.previewImg) return;
  const stage = $("#stage");
  const cs = getComputedStyle(stage);
  const availW = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const availH = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  const ar = (app.srcW || app.previewImg.naturalWidth) / (app.srcH || app.previewImg.naturalHeight);
  let w = availW, h = w / ar;
  if (h > availH) { h = availH; w = h * ar; }
  frame.style.width = `${Math.max(1, Math.floor(w))}px`;
  frame.style.height = `${Math.max(1, Math.floor(h))}px`;
  positionCropBox();
}
new ResizeObserver(layoutFrame).observe($("#stage"));

async function showPhoto(id) {
  if (pendingSave) await flushSave();
  app.currentId = id;
  app.upChoice = null;
  const p = current();
  renderFilm();
  if (!p) {
    app.previewImg = null;
    $("#frame").hidden = true;
    syncControls();
    return;
  }
  const busy = setTimeout(() => setBusy("Foto laden..."), 250);
  try {
    const [prev, thumb] = await Promise.all([loadImage(p.preview_url), loadImage(p.thumb_url)]);
    if (app.currentId !== id) return;
    app.previewImg = prev;
    app.thumbImg = thumb;
    app.loadedVersion = p.version;
    thumbRenderer.setImage(thumb, p.width, p.height);
    $("#frame").hidden = false;
    histFor(p.id);
    updateSource();
    syncCrop();
    renderer.render(effective(curState()));
    renderPresetTiles();
    syncControls();
  } catch (e) {
    toast(errorText(e), { error: true, ms: 9000 });
  } finally {
    clearTimeout(busy);
    setBusy(null);
  }
}

function setBusy(text) {
  $("#stage-busy").hidden = !text;
  if (text) $("#stage-busy-text").textContent = text;
}

// ------------------------------------------------------------------ bron (bijsnijden)

// Het beeld dat de preview bewerkt: de preview, eventueel gedraaid/rechtgezet/bijgesneden.
// In de bijsnij-modus tonen we het hele gedraaide beeld met een kader erover.
function updateSource() {
  const p = current();
  if (!p || !app.previewImg) return;
  const img = app.previewImg;
  const pw = img.naturalWidth, ph = img.naturalHeight;
  const g = curState().crop || null;
  let src = img, fullW = p.width, fullH = p.height;
  if (app.cropping || !isIdentity(g)) {
    const geo = g || defaultCrop();
    src = renderGeometry(img, pw, ph, geo, { withCrop: !app.cropping });
    if (app.cropping) [fullW, fullH] = frameSize(p.width, p.height, geo);
    else {
      const r = cropRect(p.width, p.height, geo);
      fullW = Math.max(1, Math.round(r.w));
      fullH = Math.max(1, Math.round(r.h));
    }
  }
  if (app.srcCanvas && app.srcCanvas !== src) app.srcCanvas.width = app.srcCanvas.height = 0;
  app.srcCanvas = src === img ? null : src;
  app.srcW = src.naturalWidth || src.width;
  app.srcH = src.naturalHeight || src.height;
  renderer.setImage(src, fullW, fullH);
  const before = $("#before");
  before.width = app.srcW;
  before.height = app.srcH;
  before.getContext("2d")?.drawImage(src, 0, 0);
  layoutFrame();
  scheduleRender();
}

function positionCropBox() {
  const box = $("#cropbox");
  const p = current();
  box.hidden = !app.cropping || !p;
  if (box.hidden) return;
  const r = cropRect(p.width, p.height, curState().crop || defaultCrop());
  box.style.left = `${(r.x / r.fw) * 100}%`;
  box.style.top = `${(r.y / r.fh) * 100}%`;
  box.style.width = `${(r.w / r.fw) * 100}%`;
  box.style.height = `${(r.h / r.fh) * 100}%`;
}

function setCropping(on) {
  if (!!app.cropping === on) return;
  app.cropping = on;
  document.body.dataset.cropping = on ? "true" : "false";
  if (on && app.compare) $("#btn-compare").click();
  updateSource();
  syncCrop();
}

function cropState() {
  const st = curState();
  if (!st.crop) st.crop = defaultCrop();
  return st.crop;
}

function cropChanged({ geometry = false } = {}) {
  const st = curState();
  if (st.crop && isIdentity(st.crop)) st.crop = null;
  if (geometry) updateSource();
  positionCropBox();
  syncCrop();
  changed();
}

function syncCrop() {
  const g = curState().crop || defaultCrop();
  $$("#aspect-chips .chip").forEach((c) => c.classList.toggle("active", String(g.aspect ?? "") === c.dataset.aspect));
  $("#crop-angle").value = g.angle || 0;
  $("#angle-val").textContent = `${Number(g.angle || 0).toFixed(1).replace(".0", "")}°`;
  const zoomVal = Math.round((1 - (g.zoom ?? 1)) * 100);
  $("#crop-zoom").value = zoomVal;
  $("#zoom-val").textContent = zoomVal;
  paintRange($("#crop-angle"));
  paintRange($("#crop-zoom"));
}

function buildCropControls() {
  const box = $("#aspect-chips");
  box.innerHTML = "";
  for (const a of ASPECTS) {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = a.label;
    b.dataset.aspect = a.value == null ? "" : String(a.value);
    b.onclick = () => {
      cropState().aspect = a.value;
      cropChanged();
    };
    box.append(b);
  }
  $("#crop-angle").addEventListener("input", (e) => {
    cropState().angle = Number(e.target.value);
    cropChanged({ geometry: true });
  });
  $("#crop-angle").addEventListener("dblclick", () => {
    cropState().angle = 0;
    cropChanged({ geometry: true });
  });
  $("#crop-zoom").addEventListener("input", (e) => {
    cropState().zoom = 1 - Number(e.target.value) / 100;
    cropChanged();
  });
  $("#crop-rot").onclick = () => {
    const g = cropState();
    g.rot = ((g.rot || 0) + 1) % 4;
    if (g.aspect) g.aspect = 1 / g.aspect;
    cropChanged({ geometry: true });
  };
  $("#crop-reset").onclick = () => {
    curState().crop = null;
    cropChanged({ geometry: true });
  };
}

// ------------------------------------------------------------------ ongedaan maken

const hist = new Map();
let histTimer = null;

function histFor(id) {
  if (!hist.has(id)) {
    const p = app.photos.find((x) => x.id === id);
    hist.set(id, { past: [], future: [], last: JSON.stringify(p?.state || freshState()) });
  }
  return hist.get(id);
}

function scheduleCommit() {
  clearTimeout(histTimer);
  histTimer = setTimeout(commitHistory, 450);
}

function commitHistory() {
  clearTimeout(histTimer);
  const p = current();
  if (!p) return;
  const h = histFor(p.id);
  const now = JSON.stringify(curState());
  if (now !== h.last) {
    h.past.push(h.last);
    if (h.past.length > 100) h.past.shift();
    h.last = now;
    h.future = [];
  }
  syncUndo();
}

function restore(json) {
  const p = current();
  p.state = JSON.parse(json);
  app.restoring = true;
  updateSource();
  changed();
  app.restoring = false;
  syncCrop();
  syncUndo();
}

function undo() {
  commitHistory();
  const p = current();
  if (!p) return;
  const h = histFor(p.id);
  if (!h.past.length) return;
  h.future.push(h.last);
  h.last = h.past.pop();
  restore(h.last);
}

function redo() {
  commitHistory();
  const p = current();
  if (!p) return;
  const h = histFor(p.id);
  if (!h.future.length) return;
  h.past.push(h.last);
  h.last = h.future.pop();
  restore(h.last);
}

function syncUndo() {
  const p = current();
  const h = p ? histFor(p.id) : null;
  $("#btn-undo").disabled = !h || !h.past.length;
  $("#btn-redo").disabled = !h || !h.future.length;
}
$("#btn-undo").onclick = undo;
$("#btn-redo").onclick = redo;
window.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.target.matches?.("input[type=text], input[type=password]")) return;
  const k = e.key.toLowerCase();
  if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
  else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); redo(); }
});

// ------------------------------------------------------------------ presets

// categorieën worden uit de instellingen van de preset afgeleid
const FILTERS = [
  { key: "all", label: "Alles" },
  { key: "fav", label: "♥ Favorieten" },
  { key: "dark", label: "Donker", test: (p) => p.exposure <= -25 || (p.blacks <= -20 && p.exposure <= 0) },
  { key: "light", label: "Licht", test: (p) => p.exposure >= 10 || (p.fade >= 20 && p.exposure >= 0) },
  { key: "warm", label: "Warm", test: (p) => p.temperature >= 10 || p.orange_sat >= 20 || (p.split_highlight >= 10 && p.split_highlight_hue < 70) },
  { key: "cool", label: "Koel", test: (p) => p.temperature <= -8 || (p.split_shadow >= 15 && p.split_shadow_hue > 150 && p.split_shadow_hue < 260) },
  { key: "film", label: "Film", test: (p) => p.grain >= 15 || p.fade >= 15 },
  { key: "bw", label: "Zwart-wit", test: (p) => p.saturation <= -90 },
  { key: "mine", label: "Mijn presets" },
];

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return null;
  }
}
app.favs = new Set(store("fotostudio-favs") || []);
app.filter = store("fotostudio-filter") || "all";

function presetMatches(pr) {
  if (pr.id == null) return true;
  const f = FILTERS.find((x) => x.key === app.filter) || FILTERS[0];
  if (f.key === "all") return true;
  if (f.key === "fav") return app.favs.has(pr.id);
  if (f.key === "mine") return !pr.builtin;
  return f.test({ ...Object.fromEntries(Object.keys(RANGES).map((k) => [k, 0])), ...pr.params });
}

function renderPresetChips() {
  const box = $("#preset-chips");
  box.innerHTML = "";
  for (const f of FILTERS) {
    const b = document.createElement("button");
    b.className = "chip" + (f.key === app.filter ? " active" : "");
    b.textContent = f.label;
    b.onclick = () => {
      app.filter = f.key;
      store("fotostudio-filter", f.key);
      renderPresetChips();
      renderPresetStrip();
      $("#preset-strip").scrollLeft = 0;
    };
    box.append(b);
  }
}

$("#fav-btn").onclick = () => {
  const id = curState().preset;
  if (!id) return;
  if (app.favs.has(id)) app.favs.delete(id);
  else {
    app.favs.add(id);
    toast("Toegevoegd aan je favorieten ♥");
  }
  store("fotostudio-favs", [...app.favs]);
  renderPresetStrip();
};

function renderPresetStrip() {
  const strip = $("#preset-strip");
  // oude tegels meteen vrijgeven (iPhone: beperkt canvas-geheugen)
  strip.querySelectorAll("canvas").forEach((c) => { c.width = c.height = 0; });
  strip.innerHTML = "";
  const none = { id: null, name: "Geen" };
  const groupOf = (pr) => (pr.id == null ? null : pr.builtin ? pr.group || "Basis" : "Mijn presets");
  // eigen presets vooraan na "Geen", dan Basis, dan de Collectie
  const order = { "Mijn presets": 0, Basis: 1, Collectie: 2 };
  const sorted = [...app.presets]
    .filter(presetMatches)
    .sort((a, b) => (order[groupOf(a)] ?? 3) - (order[groupOf(b)] ?? 3));
  if (!sorted.length) {
    const empty = document.createElement("div");
    empty.className = "preset-empty muted tiny";
    empty.textContent = app.filter === "fav"
      ? "Nog geen favorieten. Kies een preset en tik op het hartje."
      : "Geen presets in deze categorie.";
    strip.append(empty);
  }
  let lastGroup = null;
  for (const pr of [none, ...sorted]) {
    const g = groupOf(pr);
    if (g && g !== lastGroup && app.filter === "all") {
      const sep = document.createElement("div");
      sep.className = "preset-group";
      sep.textContent = g;
      strip.append(sep);
      lastGroup = g;
    }
    const el = document.createElement("button");
    el.className = "preset";
    el.dataset.id = pr.id ?? "";
    const c = document.createElement("canvas");
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = c.height = Math.round(76 * dpr);
    el.append(c);
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = pr.name;
    el.append(name);
    if (pr.id && app.favs.has(pr.id)) el.insertAdjacentHTML("beforeend", '<span class="heart">♥</span>');
    if (pr.id && !pr.builtin) {
      const del = document.createElement("span");
      del.className = "del";
      del.textContent = "×";
      del.title = "Preset verwijderen";
      del.onclick = (e) => { e.stopPropagation(); deletePreset(pr); };
      el.append(del);
      let t;
      el.addEventListener("touchstart", () => { t = setTimeout(() => el.classList.add("show-del"), 500); }, { passive: true });
      el.addEventListener("touchend", () => clearTimeout(t));
    }
    el.onclick = () => selectPreset(pr.id);
    strip.append(el);
  }
  const copy = document.createElement("button");
  copy.className = "preset";
  copy.innerHTML = `<div class="tile"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="11" height="13" rx="2"/><path d="M8 3h11a2 2 0 0 1 2 2v11"/><path d="M7 15l2.5-3 2 2.2L13 12"/></svg></div><span class="name">Kopieer</span>`;
  copy.title = "Kies een voorbeeldfoto en neem de look over";
  copy.onclick = () => current() && $("#ref-input").click();
  strip.append(copy);
  const add = document.createElement("button");
  add.className = "preset";
  add.innerHTML = `<div class="tile"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></div><span class="name">Opslaan</span>`;
  add.title = "Huidige instellingen opslaan als preset";
  add.onclick = savePreset;
  strip.append(add);
  renderPresetTiles();
  syncControls();
}

function renderPresetTiles() {
  if (!app.thumbImg) return;
  const tw = app.thumbImg.naturalWidth, th = app.thumbImg.naturalHeight;
  const side = Math.min(tw, th);
  const sx = (tw - side) / 2, sy = (th - side) / 2;
  for (const el of $$("#preset-strip .preset")) {
    const c = el.querySelector("canvas");
    if (!c) continue;
    const pr = el.dataset.id ? app.byId[el.dataset.id] : null;
    thumbRenderer.render(effective({ preset: pr ? pr.id : null, strength: 100, adjust: {} }));
    const ctx = c.getContext("2d");
    if (!ctx) continue;
    ctx.drawImage(thumbRenderer.canvas, sx, sy, side, side, 0, 0, c.width, c.height);
  }
}

function selectPreset(id) {
  const st = curState();
  st.preset = id || null;
  st.strength = 100;
  changed();
}

async function loadPresets() {
  app.presets = await api("GET", "/api/presets");
  app.byId = Object.fromEntries(app.presets.map((p) => [p.id, p]));
  renderPresetStrip();
}

async function savePreset() {
  if (!current()) return;
  const name = await modal({
    html: `<h2>Preset opslaan</h2><p>Bewaar je huidige instellingen als eigen preset.</p><input type="text" maxlength="40" placeholder="Naam, bv. Zomeravond">`,
    buttons: [{ label: "Annuleren", cls: "ghost", value: null }, { label: "Opslaan", cls: "primary", value: "input" }],
  });
  if (name == null) return;
  try {
    const st = curState();
    const pr = await api("POST", "/api/presets", { name: name.trim() || "Mijn preset", params: effective(st) });
    await loadPresets();
    st.preset = pr.id;
    st.strength = 100;
    st.adjust = {};
    changed();
    toast(`Preset “${pr.name}” opgeslagen`);
    const tile = $(`#preset-strip .preset[data-id="${pr.id}"]`);
    tile?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  } catch (e) {
    toast(e.message, { error: true });
  }
}

$("#ref-input").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  const p = current();
  if (!file || !p) return;
  setBusy("Look van het voorbeeld overnemen...");
  try {
    const fd = new FormData();
    fd.append("reference", file, file.name);
    const res = await api("POST", `/api/photos/${p.id}/match`, fd);
    await loadPresets();
    const st = curState();
    st.preset = res.preset.id;
    st.strength = 100;
    st.adjust = {};
    changed();
    toast(`Look overgenomen als “${res.preset.name}”: ${res.summary}. Met de sterkte-balk stel je hem bij.`, { ms: 7000 });
    $(`#preset-strip .preset[data-id="${res.preset.id}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  } catch (err) {
    toast(`Look kopiëren mislukt: ${err.message}`, { error: true });
  } finally {
    setBusy(null);
  }
};

async function deletePreset(pr) {
  const ok = await modal({
    html: `<h2>Preset verwijderen?</h2><p>“${escapeHtml(pr.name)}” wordt verwijderd.</p>`,
    buttons: [{ label: "Annuleren", cls: "ghost", value: false }, { label: "Verwijderen", cls: "primary", value: true }],
  });
  if (!ok) return;
  await api("DELETE", `/api/presets/${pr.id}`).catch((e) => toast(e.message, { error: true }));
  for (const p of app.photos) {
    if (p.state?.preset === pr.id) {
      // look behouden: zet de presetwaarden om naar eigen aanpassingen
      const eff = effective(p.state);
      p.state = { preset: null, strength: 100, adjust: eff };
    }
  }
  await loadPresets();
  changed();
}

// ------------------------------------------------------------------ sliders

// Bewerken zoals in VSCO: een rij gereedschappen, en één grote regelaar voor het gekozen gereedschap.
app.tool = "exposure";

function buildSliders() {
  const box = $("#tools");
  box.innerHTML = "";
  for (const s of SLIDERS) {
    if (s.group) {
      const g = document.createElement("span");
      g.className = "tool-group";
      g.textContent = s.group;
      box.append(g);
      continue;
    }
    const b = document.createElement("button");
    b.className = "tool";
    b.dataset.key = s.key;
    b.innerHTML = `${s.label}<b>0</b>`;
    b.onclick = () => {
      app.tool = s.key;
      syncControls();
    };
    box.append(b);
  }
  const input = $("#tool-range");
  input.addEventListener("input", () => {
    const st = curState();
    st.adjust[app.tool] = Number(input.value) - presetBase(st, app.tool);
    changed();
  });
  const resetTool = () => {
    const st = curState();
    delete st.adjust[app.tool];
    changed();
  };
  // dubbeltik op de regelaar of het pijltje = terug naar de waarde van de preset
  input.addEventListener("dblclick", resetTool);
  $("#tool-reset").onclick = resetTool;
}

function paintRange(input) {
  const min = Number(input.min), max = Number(input.max), v = Number(input.value);
  const zero = clamp(0, min, max);
  const pz = ((zero - min) / (max - min)) * 100;
  const pv = ((v - min) / (max - min)) * 100;
  input.style.setProperty("--a", `${Math.min(pz, pv)}%`);
  input.style.setProperty("--b", `${Math.max(pz, pv)}%`);
}

function syncControls() {
  const p = current();
  const st = curState();
  const eff = effective(st);
  document.body.dataset.empty = app.photos.length ? "false" : "true";
  $("#photo-count").textContent = app.photos.length ? `(${app.photos.length})` : "";
  $("#export-count").textContent = `(${app.photos.length})`;

  const fmt = (k, v) => (v > 0 && RANGES[k][0] < 0 ? `+${v}` : `${v}`);
  for (const b of $$("#tools .tool")) {
    const k = b.dataset.key;
    const v = Math.round(eff[k]);
    b.querySelector("b").textContent = fmt(k, v);
    b.classList.toggle("changed", v !== 0);
    b.classList.toggle("active", k === app.tool);
  }
  const tool = SLIDERS.find((x) => x.key === app.tool);
  if (tool) {
    const input = $("#tool-range");
    const v = Math.round(eff[tool.key]);
    input.min = tool.min;
    input.max = tool.max;
    if (document.activeElement !== input || Number(input.value) !== v) input.value = v;
    $("#tool-name").textContent = tool.label;
    $("#tool-val").textContent = fmt(tool.key, v);
    paintRange(input);
  }
  $("#btn-paste").disabled = !app.clipboard;
  syncUndo();

  for (const el of $$("#preset-strip .preset")) {
    if (el.dataset.id === undefined) continue;
    el.classList.toggle("active", p != null && (el.dataset.id || null) === (st.preset || null) && !!el.querySelector("canvas"));
  }
  const pr = st.preset ? app.byId[st.preset] : null;
  $("#strength-row").hidden = !pr;
  if (pr) {
    const fav = app.favs.has(pr.id);
    $("#fav-btn").textContent = fav ? "♥" : "♡";
    $("#fav-btn").classList.toggle("on", fav);
    $("#strength-name").textContent = pr.name;
    $("#strength").value = st.strength ?? 100;
    $("#strength-val").textContent = Math.round(st.strength ?? 100);
    paintRange($("#strength"));
  }
  syncUpscale();
}

$("#strength").addEventListener("input", (e) => {
  curState().strength = Number(e.target.value);
  changed();
});

$("#btn-reset").onclick = () => {
  const p = current();
  if (!p) return;
  p.state = freshState();
  updateSource();
  changed();
  syncCrop();
  toast("Alle bewerkingen gewist");
};

// bewerking zonder uitsnede (die hoort bij één foto)
function lookOf(st) {
  const { crop, ...look } = JSON.parse(JSON.stringify(st || freshState()));
  return look;
}

$("#btn-apply-all").onclick = async () => {
  const look = lookOf(curState());
  const others = app.photos.filter((p) => p.id !== app.currentId);
  if (!others.length) return toast("Er is maar één foto");
  for (const p of others) {
    p.state = { ...JSON.parse(JSON.stringify(look)), crop: p.state?.crop || null };
    api("PUT", `/api/photos/${p.id}/state`, { state: p.state }).catch(() => {});
  }
  toast(`Bewerking toegepast op ${others.length + 1} foto's (bijsnijden niet)`);
};

app.clipboard = store("fotostudio-clipboard");
$("#btn-copy").onclick = () => {
  app.clipboard = lookOf(curState());
  store("fotostudio-clipboard", app.clipboard);
  syncControls();
  toast("Bewerking gekopieerd — kies een andere foto en tik op Plak");
};
$("#btn-paste").onclick = () => {
  const p = current();
  if (!p || !app.clipboard) return;
  p.state = { ...JSON.parse(JSON.stringify(app.clipboard)), crop: p.state?.crop || null };
  changed();
  toast("Bewerking geplakt");
};
$("#btn-save-preset").onclick = savePreset;

// ------------------------------------------------------------------ auto

$("#btn-auto").onclick = async () => {
  const p = current();
  if (!p) return;
  const btn = $("#btn-auto");
  btn.disabled = true;
  try {
    const res = await api("POST", `/api/photos/${p.id}/auto`);
    p.state = res.state;
    changed();
    toast(`Auto: ${res.summary}`, { ms: 6000 });
    if (!isDesktop()) setTab("presets");
    $(`#preset-strip .preset[data-id="${res.state.preset}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  } catch (e) {
    toast(e.message, { error: true });
  } finally {
    btn.disabled = false;
  }
};

// ------------------------------------------------------------------ voor/na

const frame = $("#frame");
function applySplit() {
  const pct = app.split * 100;
  $("#split").style.left = `${pct}%`;
  view.style.clipPath = app.compare ? `inset(0 0 0 ${pct}%)` : "";
}
$("#btn-compare").onclick = () => {
  app.compare = !app.compare;
  app.split = 0.5;
  $("#split").hidden = !app.compare;
  $("#btn-compare").classList.toggle("active", app.compare);
  applySplit();
};

let dragging = false, holdTimer = null, holding = false, downAt = null;
function applyOriginal() {
  const show = app.showOriginal || holding;
  view.style.opacity = show ? "0" : "";
  $("#hold-badge").hidden = !show;
}
let cropDrag = null, swipeStart = null;
frame.addEventListener("pointerdown", (e) => {
  if (app.cropping) {
    // kader verslepen
    const p = current();
    const r = cropRect(p.width, p.height, cropState());
    cropDrag = { x: e.clientX, y: e.clientY, cx: (r.x + r.w / 2) / r.fw, cy: (r.y + r.h / 2) / r.fh };
    frame.setPointerCapture(e.pointerId);
    return;
  }
  if (app.compare) {
    dragging = true;
    frame.setPointerCapture(e.pointerId);
    moveSplit(e);
    return;
  }
  // tikken = origineel aan/uit; ingedrukt houden = origineel zolang je vasthoudt; vegen = andere foto
  downAt = { x: e.clientX, y: e.clientY, t: performance.now() };
  swipeStart = { ...downAt };
  holdTimer = setTimeout(() => { holding = true; applyOriginal(); }, 300);
});
frame.addEventListener("pointermove", (e) => {
  if (cropDrag) {
    const rect = frame.getBoundingClientRect();
    const g = cropState();
    g.cx = clamp(cropDrag.cx + (e.clientX - cropDrag.x) / rect.width, 0, 1);
    g.cy = clamp(cropDrag.cy + (e.clientY - cropDrag.y) / rect.height, 0, 1);
    positionCropBox();
    return;
  }
  if (dragging) moveSplit(e);
  else if (downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 12) {
    clearTimeout(holdTimer);
    downAt = null;
  }
});
frame.addEventListener("pointerup", (e) => {
  clearTimeout(holdTimer);
  if (cropDrag) {
    // middelpunt vastleggen zoals het kader echt staat (binnen de foto)
    const p = current();
    const g = cropState();
    const r = cropRect(p.width, p.height, g);
    g.cx = (r.x + r.w / 2) / r.fw;
    g.cy = (r.y + r.h / 2) / r.fh;
    cropDrag = null;
    cropChanged();
    return;
  }
  if (dragging) dragging = false;
  else if (holding) holding = false;
  else if (downAt) app.showOriginal = !app.showOriginal;
  else if (swipeStart) {
    const dx = e.clientX - swipeStart.x, dy = e.clientY - swipeStart.y;
    if (Math.abs(dx) > 60 && Math.abs(dy) < Math.abs(dx) * 0.6 && performance.now() - swipeStart.t < 700) {
      const i = app.photos.findIndex((x) => x.id === app.currentId);
      const next = app.photos[i + (dx < 0 ? 1 : -1)];
      if (next) showPhoto(next.id);
    }
  }
  downAt = swipeStart = null;
  applyOriginal();
});
const cancelPointer = () => {
  dragging = holding = false;
  downAt = swipeStart = null;
  if (cropDrag) { cropDrag = null; cropChanged(); }
  clearTimeout(holdTimer);
  applyOriginal();
};
frame.addEventListener("pointercancel", cancelPointer);
frame.addEventListener("pointerleave", () => { if (!dragging) cancelPointer(); });
frame.addEventListener("contextmenu", (e) => e.preventDefault());
function moveSplit(e) {
  const r = frame.getBoundingClientRect();
  app.split = clamp((e.clientX - r.left) / r.width, 0, 1);
  applySplit();
}

// ------------------------------------------------------------------ foto's

function renderFilm() {
  const film = $("#film");
  film.innerHTML = "";
  for (const p of app.photos) {
    const el = document.createElement("button");
    el.className = "thumb" + (p.id === app.currentId ? " active" : "");
    el.title = p.name;
    el.innerHTML = `<img src="${p.thumb_url}" alt="" draggable="false">`;
    if (p.upscaled) el.insertAdjacentHTML("beforeend", `<span class="tag">${p.upscaled === 1 ? "AI" : p.upscaled + "×"}</span>`);
    if (p.job && (p.job.status === "running" || p.job.status === "queued")) {
      const txt = p.job.status === "queued" ? "wacht" : `${Math.round(p.job.progress * 100)}%`;
      el.insertAdjacentHTML("beforeend", `<span class="ring">${txt}</span>`);
    }
    const x = document.createElement("span");
    x.className = "x";
    x.textContent = "×";
    x.title = "Verwijderen";
    x.onclick = (e) => { e.stopPropagation(); removePhoto(p); };
    el.append(x);
    el.onclick = () => { if (p.id !== app.currentId) showPhoto(p.id); };
    film.append(el);
  }
  const add = document.createElement("button");
  add.className = "thumb add";
  add.title = "Foto's toevoegen";
  add.innerHTML = `<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>`;
  add.onclick = pickFiles;
  film.append(add);
}

async function removePhoto(p) {
  const ok = await modal({
    html: `<h2>Foto verwijderen?</h2><p>“${escapeHtml(p.name)}” wordt uit de app verwijderd. Je originele bestand blijft gewoon staan.</p>`,
    buttons: [{ label: "Annuleren", cls: "ghost", value: false }, { label: "Verwijderen", cls: "primary", value: true }],
  });
  if (!ok) return;
  await api("DELETE", `/api/photos/${p.id}`).catch(() => {});
  const idx = app.photos.indexOf(p);
  app.photos.splice(idx, 1);
  if (app.currentId === p.id) {
    const next = app.photos[Math.min(idx, app.photos.length - 1)];
    await showPhoto(next ? next.id : null);
  } else renderFilm();
  syncControls();
}

function pickFiles() { $("#file-input").click(); }
$("#btn-add").onclick = pickFiles;
$("#btn-pick").onclick = pickFiles;
$("#empty").onclick = (e) => { if (e.target.id !== "btn-pick") pickFiles(); };
$("#file-input").onchange = (e) => {
  uploadFiles([...e.target.files]);
  e.target.value = "";
};

async function uploadFiles(files) {
  files = files.filter((f) => f.type.startsWith("image/") || /\.(heic|heif|jpe?g|png|webp|tiff?|bmp)$/i.test(f.name));
  if (!files.length) return toast("Geen foto's gevonden", { error: true });
  let first = null, done = 0;
  const errors = [];
  for (const f of files) {
    setBusy(files.length > 1 ? `Uploaden ${done + 1} van ${files.length}...` : "Uploaden...");
    const fd = new FormData();
    fd.append("files", f, f.name);
    try {
      const res = await api("POST", "/api/photos", fd);
      for (const p of res.photos) {
        app.photos.push(p);
        first = first || p;
      }
      errors.push(...res.errors);
    } catch (e) {
      errors.push(`${f.name}: ${e.message}`);
    }
    done++;
    renderFilm();
  }
  setBusy(null);
  if (errors.length) toast(errors.join(" · "), { error: true, ms: 6000 });
  else if (files.length > 1) toast(`${files.length} foto's toegevoegd`);
  if (first) await showPhoto(first.id);
  syncControls();
}

// slepen & neerzetten
let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (!e.dataTransfer?.types.includes("Files")) return;
  e.preventDefault();
  dragDepth++;
  $("#drop-overlay").hidden = false;
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("#drop-overlay").hidden = true;
});
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("#drop-overlay").hidden = true;
  const files = [...(e.dataTransfer?.files || [])];
  if (files.length) uploadFiles(files);
});

// ------------------------------------------------------------------ upscalen

function syncUpscale() {
  const p = current();
  const info = app.status?.upscaler;
  if (info) {
    $("#up-engine").textContent = info.state === "ready" ? `Motor: ${info.message}` : info.message;
  }
  const btns = $$(".up-btn");
  if (!p) {
    $("#up-size").textContent = "";
    btns.forEach((b) => (b.disabled = true));
    $("#up-progress").hidden = true;
    $("#btn-up-reset").hidden = true;
    return;
  }
  $("#up-size").innerHTML = p.upscaled === 1
    ? `Nu: <b>${fmtSize(p.width, p.height)}</b> <span class="muted">(AI-verbeterd)</span>`
    : p.upscaled
    ? `Nu: <b>${fmtSize(p.width, p.height)}</b> <span class="muted">(${p.upscaled}× van ${fmtSize(p.orig_width, p.orig_height)})</span>`
    : `Nu: <b>${fmtSize(p.width, p.height)}</b> <span class="muted">(origineel)</span>`;
  for (const f of ["2", "4"]) {
    const [w, h] = p.targets[f];
    const capped = w < p.orig_width * Number(f) - 1;
    $(`#up-t${f}`).textContent = `${fmtSize(w, h)}${capped ? " (max)" : ""}`;
  }
  const job = p.job;
  const busy = job && (job.status === "running" || job.status === "queued");
  if (busy || p.upscale_note) app.upChoice = null;
  btns.forEach((b) => {
    b.disabled = !!busy || !!p.upscale_note;
    b.classList.toggle("done", String(p.upscaled) === b.dataset.factor);
    b.classList.toggle("selected", String(app.upChoice) === b.dataset.factor);
  });
  const start = $("#up-start");
  start.hidden = !app.upChoice;
  if (app.upChoice) {
    const [w, h] = p.targets[String(app.upChoice)];
    start.textContent = app.upChoice === 1
      ? "Start AI verbeteren"
      : `Start ${app.upChoice}× upscalen (${fmtSize(w, h)})`;
  }
  $("#up-note").hidden = !p.upscale_note;
  $("#up-note").textContent = p.upscale_note || "";
  $("#btn-up-reset").hidden = !p.upscaled || busy;
  $("#up-progress").hidden = !busy;
  $("#stage-job").hidden = !busy;
  if (busy) {
    const pct = Math.round(job.progress * 100);
    const text = job.status === "queued" || (job.progress === 0 && job.message)
      ? job.message || "In de wachtrij..."
      : `${job.factor === 1 ? "AI verbeteren" : job.factor + "× upscalen"} — ${pct}% ${job.eta ? "· " + fmtTime(job.eta) : ""}`;
    $("#up-bar").style.width = $("#stage-job-bar").style.width = `${pct}%`;
    $("#up-text").textContent = $("#stage-job-text").textContent = text;
  }
}

async function startUpscale(photo, factor) {
  try {
    photo.job = await api("POST", `/api/photos/${photo.id}/upscale`, { factor });
    syncControls();
    renderFilm();
    poll();
  } catch (e) {
    toast(e.message, { error: true });
  }
}

// eerst kiezen (AI / 2× / 4×), dan op Start tikken
$$(".up-btn").forEach((b) => (b.onclick = () => {
  const f = Number(b.dataset.factor);
  app.upChoice = app.upChoice === f ? null : f;
  syncUpscale();
}));
$("#up-start").onclick = () => {
  const p = current();
  if (!p || !app.upChoice) return;
  const f = app.upChoice;
  app.upChoice = null;
  toast(f === 1 ? "AI verbeteren gestart" : `${f}× upscalen gestart — je ziet de voortgang op de foto`);
  startUpscale(p, f);
};
$$("[data-batch-factor]").forEach((b) => (b.onclick = async () => {
  const f = Number(b.dataset.batchFactor);
  const todo = app.photos.filter((p) => !p.upscale_note);
  if (!todo.length) return toast("Deze foto's zijn al groot genoeg", { error: true });
  for (const p of todo) await startUpscale(p, f);
  toast(`${todo.length} foto's staan in de wachtrij voor ${f === 1 ? "AI verbeteren" : f + "×"}`);
}));
$("#btn-up-reset").onclick = async () => {
  const p = current();
  if (!p) return;
  try {
    Object.assign(p, await api("POST", `/api/photos/${p.id}/reset-upscale`));
    await showPhoto(p.id);
  } catch (e) {
    toast(e.message, { error: true });
  }
};

let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  try {
    const [list, status] = await Promise.all([api("GET", "/api/photos"), api("GET", "/api/status")]);
    app.status = status;
    let active = status.upscaler.state !== "ready";
    for (const fresh of list) {
      const p = app.photos.find((x) => x.id === fresh.id);
      if (!p) continue;
      const prevJob = p.job;
      Object.assign(p, { ...fresh, state: p.state });
      if (fresh.job && (fresh.job.status === "running" || fresh.job.status === "queued")) active = true;
      if (prevJob && prevJob.status !== fresh.job?.status && fresh.job?.status === "done") {
        toast(`${p.name}: ${fresh.job.factor === 1 ? "AI verbeteren" : fresh.job.factor + "× upscalen"} klaar`);
      }
      if (fresh.job?.status === "error" && prevJob?.status !== "error") toast(fresh.job.message, { error: true, ms: 7000 });
      if (p.id === app.currentId && fresh.version !== app.loadedVersion) showPhoto(p.id);
    }
    renderFilm();
    syncControls();
    if (active) pollTimer = setTimeout(poll, 1000);
  } catch {
    pollTimer = setTimeout(poll, 3000);
  }
}

// ------------------------------------------------------------------ exporteren

const menu = $("#export-menu");
$("#btn-export").onclick = (e) => {
  e.stopPropagation();
  if (app.photos.length <= 1) return doExport("one");
  const r = e.currentTarget.getBoundingClientRect();
  menu.style.top = `${r.bottom + 8}px`;
  menu.style.left = `${Math.max(8, r.right - 260)}px`;
  menu.hidden = !menu.hidden;
};
document.addEventListener("click", (e) => { if (!menu.contains(e.target)) menu.hidden = true; });
$$("#export-menu [data-export]").forEach((b) => (b.onclick = () => { menu.hidden = true; doExport(b.dataset.export); }));

async function doExport(mode) {
  const p = current();
  if (!p) return;
  if (pendingSave) await flushSave();
  const ids = mode === "one" ? [p.id] : app.photos.map((x) => x.id);
  const body = { photo_ids: ids, state: mode === "each" ? null : curState() };
  setBusy(ids.length > 1 ? `${ids.length} foto's exporteren...` : "Exporteren in hoge kwaliteit...");
  try {
    const res = await api("POST", "/api/export", body);
    if (res.files) {
      offerFiles(res);
    } else if (app.status?.is_local) {
      toast(ids.length > 1 ? `${res.count} foto's opgeslagen in de map Fotostudio` : `Opgeslagen: ${res.filename}`, {
        action: { label: "Open map", run: () => api("POST", "/api/open-export-folder").catch(() => {}) },
      });
    } else {
      const a = document.createElement("a");
      a.href = res.url;
      a.download = res.filename;
      document.body.append(a);
      a.click();
      a.remove();
      toast(ids.length > 1 ? `${res.count} foto's klaar (zip)` : "Foto klaar om op te slaan");
    }
  } catch (e) {
    toast(`Exporteren mislukt: ${e.message}`, { error: true });
  } finally {
    setBusy(null);
  }
}

// Cloudflare-versie: bestanden staan klaar in de browser
const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
let saveURLs = [];

function offerFiles(res) {
  const box = $("#saveview");
  saveURLs.forEach((u) => URL.revokeObjectURL(u));
  saveURLs = res.files.map((f) => URL.createObjectURL(f));
  $("#save-title").textContent = res.count > 1 ? `${res.count} foto's klaar` : "Je foto is klaar";
  $("#save-imgs").innerHTML = saveURLs.map((u, i) => `<img src="${u}" alt="${escapeHtml(res.files[i].name)}">`).join("");
  const canShare = !!(navigator.canShare && navigator.canShare({ files: res.files }));
  $("#save-btn").textContent = canShare ? (isIOS ? "Bewaar in Foto's" : "Bewaar / deel") : "Download";
  $("#save-hint").textContent = !isIOS ? ""
    : canShare ? "Tik op “Bewaar in Foto's” en kies “Bewaar afbeelding”. Of houd een foto ingedrukt en kies “Voeg toe aan Foto's”."
    : "Houd een foto ingedrukt en kies “Voeg toe aan Foto's”.";
  $("#save-btn").onclick = async () => {
    if (canShare) {
      try {
        await navigator.share({ files: res.files });
        return;
      } catch (e) {
        if (e.name === "AbortError") return;
        if (isIOS) return toast("Houd de foto ingedrukt en kies “Voeg toe aan Foto's”", { ms: 7000 });
      }
    }
    const blob = res.files.length === 1 ? res.files[0] : await res.zip();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = res.filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };
  box.hidden = false;
}
$("#saveview").addEventListener("click", (e) => {
  if (e.target.id === "saveview" || e.target.closest("[data-close]")) $("#saveview").hidden = true;
});

// ------------------------------------------------------------------ telefoon

let shareTimer = null;
$("#btn-phone").onclick = () => {
  $("#share").hidden = false;
  renderShare();
};
$("#share").addEventListener("click", (e) => {
  if (e.target.id === "share" || e.target.closest("[data-close]")) {
    $("#share").hidden = true;
    clearTimeout(shareTimer);
  }
});

async function renderShare() {
  clearTimeout(shareTimer);
  let st;
  try {
    st = app.status = await api("GET", "/api/status");
  } catch {
    return;
  }
  const t = st.tunnel;
  const local = st.is_local;
  const body = $("#share-body");
  const lan = st.lan_url
    ? `<img class="qr" src="/api/qr?target=lan" alt="QR-code"><p class="url">${escapeHtml(st.lan_url)}</p>`
    : `<p>Deze computer lijkt niet met een netwerk verbonden.</p>`;
  let pub;
  if (t.state === "on" && t.url) {
    pub = `<p class="ok">● Actief — overal bereikbaar, met wachtwoord</p>
      <img class="qr" src="/api/qr?target=public&u=${encodeURIComponent(t.url)}" alt="QR-code"><p class="url">${escapeHtml(t.url)}</p>
      ${t.mode === "quick" ? `<p>Dit adres verandert als je de app opnieuw start.${local ? " Wil je een vast adres? Zie <i>Vast adres</i> hieronder." : ""}</p>` : ""}`;
  } else if (t.state === "starting") {
    pub = `<p class="muted">Verbinden met Cloudflare… (de eerste keer wordt er ook iets gedownload)</p>`;
  } else if (t.state === "error") {
    pub = `<p class="err">${escapeHtml(t.message)}</p>`;
  } else {
    pub = `<p class="muted">Uit. Alleen bereikbaar op je eigen wifi.</p>`;
  }
  let controls = "";
  if (local) {
    controls = `
      <div class="share-row">
        <label>Wachtwoord ${st.password_set ? "(ingesteld)" : "(nog niet ingesteld)"}</label>
        <div class="inline">
          <input type="password" id="pw-new" placeholder="${st.password_set ? "Nieuw wachtwoord" : "Minstens 8 tekens"}" autocomplete="new-password">
          <button class="btn small" id="pw-save">${st.password_set ? "Wijzigen" : "Instellen"}</button>
        </div>
      </div>
      <div class="share-row">
        <button class="btn ${t.enabled ? "" : "primary"}" id="tunnel-toggle" ${st.password_set ? "" : "disabled"}>
          ${t.enabled ? "Overal bereikbaar uitzetten" : "Overal bereikbaar maken"}</button>
        ${st.password_set ? "" : "<p class='tiny'>Stel eerst een wachtwoord in.</p>"}
      </div>
      <details class="share-row">
        <summary>Vast adres (eigen Cloudflare-account)</summary>
        <p>Maak in Cloudflare (Zero Trust → Networks → Tunnels) een tunnel aan, laat hem wijzen naar
        <b>http://localhost:${location.port || 80}</b> en plak hier de tunnel-token en je adres.</p>
        <input type="password" id="tunnel-token" placeholder="Tunnel-token" value="" autocomplete="off">
        <input type="text" id="tunnel-host" placeholder="bv. foto.jouwdomein.nl" value="${escapeHtml(t.hostname || "")}">
        <div class="inline"><button class="btn small" id="tunnel-token-save">Opslaan</button>
        <button class="btn ghost small" id="tunnel-token-clear">Terug naar snel (willekeurig adres)</button></div>
      </details>`;
  } else {
    controls = `<div class="share-row"><button class="btn small" id="logout">Uitloggen op dit apparaat</button></div>`;
  }
  body.innerHTML = `
    <h2>Openen op je telefoon</h2>
    <h3>Thuis (zelfde wifi)</h3>${lan}
    <h3>Overal (via Cloudflare)</h3>${pub}${controls}`;

  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on("pw-save", async () => {
    try {
      await api("POST", "/api/auth/password", { password: $("#pw-new").value });
      toast("Wachtwoord opgeslagen. Andere apparaten moeten opnieuw inloggen.");
      renderShare();
    } catch (e) { toast(e.message, { error: true }); }
  });
  on("tunnel-toggle", async () => {
    try { await api("POST", "/api/tunnel", { enabled: !t.enabled }); renderShare(); }
    catch (e) { toast(e.message, { error: true }); }
  });
  on("tunnel-token-save", async () => {
    try {
      await api("POST", "/api/tunnel", { enabled: true, token: $("#tunnel-token").value, hostname: $("#tunnel-host").value });
      toast("Vaste tunnel opgeslagen");
      renderShare();
    } catch (e) { toast(e.message, { error: true }); }
  });
  on("tunnel-token-clear", async () => {
    try { await api("POST", "/api/tunnel", { enabled: t.enabled, token: "", hostname: "" }); renderShare(); }
    catch (e) { toast(e.message, { error: true }); }
  });
  on("logout", async () => {
    await api("POST", "/api/auth/logout").catch(() => {});
    location.reload();
  });
  if (t.state === "starting" && !$("#share").hidden) shareTimer = setTimeout(renderShare, 1500);
}

// ------------------------------------------------------------------ inloggen

function showLogin(message) {
  const box = $("#login");
  if (!box.hidden && !message) return;
  box.hidden = false;
  $("#login-msg").textContent = message || "";
  setTimeout(() => $("#login-pw").focus(), 50);
}

$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  const btn = $("#login-form button");
  btn.disabled = true;
  try {
    await api("POST", "/api/auth/login", { password: $("#login-pw").value });
    $("#login").hidden = true;
    $("#login-pw").value = "";
    init();
  } catch (err) {
    $("#login-msg").textContent = err.message;
  } finally {
    btn.disabled = false;
  }
};

// ------------------------------------------------------------------ tabs

function setTab(tab) {
  document.body.dataset.tab = tab;
  if (tab === "edit" || tab === "upscale" || tab === "crop") document.body.dataset.side = tab;
  setCropping(tab === "crop");
  syncTabs();
}
function syncTabs() {
  const desk = isDesktop();
  for (const b of $$(".tabs button")) {
    const t = b.dataset.tab;
    b.classList.toggle("active", desk ? document.body.dataset.side === t : document.body.dataset.tab === t);
  }
}
$$(".tabs button").forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));
window.matchMedia("(min-width: 900px)").addEventListener("change", () => { syncTabs(); layoutFrame(); });

// onverwachte fouten tonen, met de plek waar het misging
function errorText(e) {
  const line = (e?.stack || "").split("\n").find((l) => /\.js:\d+/.test(l)) || "";
  const m = line.match(/([\w.-]+\.js):(\d+)/);
  return `${e?.message || e}${m ? ` [${m[1]}:${m[2]}]` : ""}`;
}
window.addEventListener("error", (ev) => toast(`Fout: ${errorText(ev.error || ev.message)}`, { error: true, ms: 9000 }));
window.addEventListener("unhandledrejection", (ev) => toast(`Fout: ${errorText(ev.reason)}`, { error: true, ms: 9000 }));

// ------------------------------------------------------------------ start

let started = false;
async function init() {
  if (!started) {
    document.body.dataset.side = "edit";
    buildSliders();
    buildCropControls();
    renderPresetChips();
    syncTabs();
    started = true;
  }
  try {
    const who = await api("GET", "/api/auth/status");
    if (!who.authenticated) {
      return showLogin(who.password_set ? "" : "Er is nog geen wachtwoord. Stel dat eerst in op je computer (knop Telefoon).");
    }
    const [photos, status] = await Promise.all([api("GET", "/api/photos"), api("GET", "/api/status")]);
    app.photos = photos;
    app.status = status;
    await loadPresets();
    renderFilm();
    if (photos.length) await showPhoto(photos[photos.length - 1].id);
    syncControls();
    poll();
  } catch (e) {
    if (!$("#login").hidden) return;
    toast(`Kan geen verbinding maken met de app: ${e.message}`, { error: true, ms: 10000 });
  }
}
init();
