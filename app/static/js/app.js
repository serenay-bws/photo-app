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
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
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
  document.body.innerHTML = `<div style="padding:40px;text-align:center">Deze browser ondersteunt geen WebGL.<br>Probeer Chrome, Edge, Firefox of Safari.<br><br><small>${escapeHtml(e.message)}</small></div>`;
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
  scheduleRender();
  syncControls();
  persistState();
}

function layoutFrame() {
  const p = current();
  const frame = $("#frame");
  if (!p || !app.previewImg) return;
  const stage = $("#stage");
  const cs = getComputedStyle(stage);
  const availW = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const availH = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  const ar = app.previewImg.naturalWidth / app.previewImg.naturalHeight;
  let w = availW, h = w / ar;
  if (h > availH) { h = availH; w = h * ar; }
  frame.style.width = `${Math.max(1, Math.floor(w))}px`;
  frame.style.height = `${Math.max(1, Math.floor(h))}px`;
}
new ResizeObserver(layoutFrame).observe($("#stage"));

async function showPhoto(id) {
  if (pendingSave) await flushSave();
  app.currentId = id;
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
    $("#before").src = p.preview_url;
    renderer.setImage(prev, p.width, p.height);
    thumbRenderer.setImage(thumb, p.width, p.height);
    $("#frame").hidden = false;
    layoutFrame();
    renderer.render(effective(curState()));
    renderPresetTiles();
    syncControls();
  } catch (e) {
    toast(e.message, { error: true });
  } finally {
    clearTimeout(busy);
    setBusy(null);
  }
}

function setBusy(text) {
  $("#stage-busy").hidden = !text;
  if (text) $("#stage-busy-text").textContent = text;
}

// ------------------------------------------------------------------ presets

function renderPresetStrip() {
  const strip = $("#preset-strip");
  strip.innerHTML = "";
  const none = { id: null, name: "Geen" };
  for (const pr of [none, ...app.presets]) {
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

function buildSliders() {
  const box = $("#sliders");
  box.innerHTML = "";
  for (const s of SLIDERS) {
    if (s.group) {
      const g = document.createElement("div");
      g.className = "group-title";
      g.textContent = s.group;
      box.append(g);
      continue;
    }
    const row = document.createElement("div");
    row.className = "slider";
    row.dataset.key = s.key;
    row.innerHTML = `<div class="slider-head"><span>${s.label}</span><span class="val">0</span></div>
      <input type="range" min="${s.min}" max="${s.max}" step="1" value="0" aria-label="${s.label}">`;
    const input = row.querySelector("input");
    input.addEventListener("input", () => {
      const st = curState();
      st.adjust[s.key] = Number(input.value) - presetBase(st, s.key);
      changed();
    });
    // dubbelklik / dubbeltik = terug naar de waarde van de preset
    row.querySelector(".slider-head").addEventListener("dblclick", () => {
      const st = curState();
      delete st.adjust[s.key];
      changed();
    });
    input.addEventListener("dblclick", () => {
      const st = curState();
      delete st.adjust[s.key];
      changed();
    });
    box.append(row);
  }
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

  for (const row of $$("#sliders .slider")) {
    const k = row.dataset.key;
    const input = row.querySelector("input");
    const v = Math.round(eff[k]);
    if (document.activeElement !== input || Number(input.value) !== v) input.value = v;
    row.querySelector(".val").textContent = v > 0 && RANGES[k][0] < 0 ? `+${v}` : `${v}`;
    row.classList.toggle("changed", v !== 0);
    paintRange(input);
  }

  for (const el of $$("#preset-strip .preset")) {
    if (el.dataset.id === undefined) continue;
    el.classList.toggle("active", p != null && (el.dataset.id || null) === (st.preset || null) && !!el.querySelector("canvas"));
  }
  const pr = st.preset ? app.byId[st.preset] : null;
  $("#strength-row").hidden = !pr;
  if (pr) {
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
  changed();
  toast("Alle bewerkingen gewist");
};

$("#btn-apply-all").onclick = async () => {
  const st = curState();
  const others = app.photos.filter((p) => p.id !== app.currentId);
  if (!others.length) return toast("Er is maar één foto");
  for (const p of others) {
    p.state = JSON.parse(JSON.stringify(st));
    api("PUT", `/api/photos/${p.id}/state`, { state: p.state }).catch(() => {});
  }
  toast(`Instellingen toegepast op ${others.length + 1} foto's`);
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

let dragging = false, holdTimer = null;
frame.addEventListener("pointerdown", (e) => {
  if (app.compare) {
    dragging = true;
    frame.setPointerCapture(e.pointerId);
    moveSplit(e);
  } else {
    // ingedrukt houden = origineel tonen
    holdTimer = setTimeout(() => { view.style.opacity = "0"; $("#hold-badge").hidden = false; }, 160);
  }
});
frame.addEventListener("pointermove", (e) => { if (dragging) moveSplit(e); });
const endPointer = () => {
  dragging = false;
  clearTimeout(holdTimer);
  view.style.opacity = "";
  $("#hold-badge").hidden = true;
};
frame.addEventListener("pointerup", endPointer);
frame.addEventListener("pointercancel", endPointer);
frame.addEventListener("pointerleave", () => { if (!dragging) endPointer(); });
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
    if (p.upscaled) el.insertAdjacentHTML("beforeend", `<span class="tag">${p.upscaled}×</span>`);
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
  $("#up-size").innerHTML = p.upscaled
    ? `Nu: <b>${fmtSize(p.width, p.height)}</b> <span class="muted">(${p.upscaled}× van ${fmtSize(p.orig_width, p.orig_height)})</span>`
    : `Nu: <b>${fmtSize(p.width, p.height)}</b> <span class="muted">(origineel)</span>`;
  for (const f of ["2", "4"]) {
    const [w, h] = p.targets[f];
    const capped = w < p.orig_width * Number(f) - 1;
    $(`#up-t${f}`).textContent = `${fmtSize(w, h)}${capped ? " (max)" : ""}`;
  }
  const job = p.job;
  const busy = job && (job.status === "running" || job.status === "queued");
  btns.forEach((b) => {
    b.disabled = !!busy;
    b.classList.toggle("done", String(p.upscaled) === b.dataset.factor);
  });
  $("#btn-up-reset").hidden = !p.upscaled || busy;
  $("#up-progress").hidden = !busy;
  if (busy) {
    $("#up-bar").style.width = `${Math.round(job.progress * 100)}%`;
    const pct = Math.round(job.progress * 100);
    $("#up-text").textContent = job.status === "queued"
      ? job.message || "In de wachtrij..."
      : `${job.factor}× upscalen — ${pct}% ${job.eta ? "· " + fmtTime(job.eta) : ""}`;
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

$$(".up-btn").forEach((b) => (b.onclick = () => current() && startUpscale(current(), Number(b.dataset.factor))));
$$("[data-batch-factor]").forEach((b) => (b.onclick = async () => {
  const f = Number(b.dataset.batchFactor);
  if (!app.photos.length) return;
  for (const p of app.photos) await startUpscale(p, f);
  toast(`${app.photos.length} foto's staan in de wachtrij voor ${f}×`);
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
        toast(`${p.name}: ${fresh.job.factor}× upscalen klaar`);
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
    if (app.status?.is_local) {
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

// ------------------------------------------------------------------ telefoon

$("#btn-phone").onclick = async () => {
  const st = app.status || (await api("GET", "/api/status"));
  const url = st.lan_url;
  await modal({
    html: url
      ? `<h2>Openen op je telefoon</h2><p>Zorg dat je telefoon op hetzelfde wifi-netwerk zit en scan deze code met de camera:</p>
         <img class="qr" src="/api/qr" alt="QR-code"><p class="url">${escapeHtml(url)}</p>
         <p>Werkt het niet? Sta de app toe in de firewall van je computer (privé-netwerk).</p>`
      : `<h2>Openen op je telefoon</h2><p>Deze computer lijkt niet met een netwerk verbonden.</p>`,
    buttons: [{ label: "Sluiten", cls: "primary", value: true }],
  });
};

// ------------------------------------------------------------------ tabs

function setTab(tab) {
  document.body.dataset.tab = tab;
  if (tab === "edit" || tab === "upscale") document.body.dataset.side = tab;
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

// ------------------------------------------------------------------ start

async function init() {
  document.body.dataset.side = "edit";
  buildSliders();
  syncTabs();
  try {
    const [photos, status] = await Promise.all([api("GET", "/api/photos"), api("GET", "/api/status")]);
    app.photos = photos;
    app.status = status;
    await loadPresets();
    renderFilm();
    if (photos.length) await showPhoto(photos[photos.length - 1].id);
    syncControls();
    poll();
  } catch (e) {
    toast(`Kan geen verbinding maken met de app: ${e.message}`, { error: true, ms: 10000 });
  }
}
init();
