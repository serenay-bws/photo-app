// "Server" die volledig in de browser draait (Cloudflare-versie).
// Beantwoordt dezelfde /api/...-verzoeken als de Python-server, maar alles gebeurt
// op het toestel zelf: foto's worden in de browser bewaard en nergens heen gestuurd.

import { matchLook, suggest, describe } from "./analysis.js";
import { db } from "./db.js";
import { Renderer } from "./renderer.js";
import * as ai from "./webai.js";
import { makeZip } from "./zip.js";

const PREVIEW_LONG = 1600;
const THUMB_LONG = 360;
const MAX_OUT_PIXELS = 16_777_216; // grens van canvas-geheugen op iPhones
const JPEG_QUALITY = 0.95;

const RANGES = {
  exposure: [-100, 100], contrast: [-100, 100], highlights: [-100, 100], shadows: [-100, 100],
  blacks: [-100, 100], saturation: [-100, 100], temperature: [-100, 100], tint: [-100, 100],
  grain: [0, 100], vignette: [0, 100], sharpness: [0, 100], fade: [0, 100],
  orange_sat: [-100, 100], orange_lum: [-100, 100], green_sat: [-100, 100], blue_sat: [-100, 100],
  split_shadow: [0, 100], split_highlight: [0, 100],
};
const HUES = { split_shadow_hue: 210, split_highlight_hue: 40 };
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

let builtin = null;
const jobs = new Map();
const urls = new Map(); // id -> {version, preview, thumb}
const queue = [];
let working = false;

// ------------------------------------------------------------------ hulpjes

function cleanParams(raw = {}) {
  const p = {};
  for (const [k, [lo, hi]] of Object.entries(RANGES)) p[k] = clamp(Number(raw[k]) || 0, lo, hi);
  for (const [k, d] of Object.entries(HUES)) p[k] = ((Number(raw[k] ?? d) % 360) + 360) % 360;
  return p;
}

async function presetsById() {
  if (!builtin) {
    builtin = await (await fetch(new URL("../presets.json", import.meta.url))).json();
  }
  const custom = await db.all("presets");
  const all = [...builtin, ...custom.map((p) => ({ ...p, builtin: false }))];
  return Object.fromEntries(all.map((p) => [p.id, p]));
}

function effective(state, byId) {
  state = state || {};
  const adj = state.adjust || {};
  const preset = state.preset ? byId[state.preset] : null;
  const s = clamp(state.strength ?? 100, 0, 100) / 100;
  const out = {};
  for (const [k, [lo, hi]] of Object.entries(RANGES)) {
    out[k] = clamp((preset ? (preset.params[k] || 0) * s : 0) + (Number(adj[k]) || 0), lo, hi);
  }
  for (const [k, d] of Object.entries(HUES)) {
    const amount = k.replace("_hue", "");
    if (preset && preset.params[amount] > 0) out[k] = preset.params[k];
    else out[k] = adj[k] ?? (preset ? preset.params[k] : d);
  }
  return out;
}

function loadImage(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Deze foto kan de browser niet openen")); };
    img.src = url;
  });
}

// iPhones geven een webpagina weinig canvas-geheugen; canvassen die we niet meer
// nodig hebben geven we daarom meteen terug (breedte/hoogte 0).
function newCanvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d");
  if (!ctx) {
    release(c);
    throw new Error("te weinig geheugen in de browser; sluit andere tabbladen en probeer opnieuw");
  }
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  return [c, ctx];
}

export function release(...canvases) {
  for (const c of canvases) if (c && c.getContext) { c.width = 0; c.height = 0; }
}

// Netjes verkleinen in stappen (voorkomt kartelige randen)
function resized(img, w, h) {
  let src = img, sw = img.naturalWidth || img.width, sh = img.naturalHeight || img.height;
  while (sw / 2 >= w && sh / 2 >= h) {
    const [c, ctx] = newCanvas(Math.round(sw / 2), Math.round(sh / 2));
    ctx.drawImage(src, 0, 0, c.width, c.height);
    if (src !== img) release(src);
    src = c; sw = c.width; sh = c.height;
  }
  const [c, ctx] = newCanvas(w, h);
  ctx.drawImage(src, 0, 0, w, h);
  if (src !== img) release(src);
  return c;
}

function fit(w, h, long) {
  const s = Math.min(1, long / Math.max(w, h));
  return [Math.max(1, Math.round(w * s)), Math.max(1, Math.round(h * s))];
}

const toBlob = (canvas, type, q) =>
  new Promise((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error("Opslaan mislukt (te weinig geheugen?)"))), type, q));

async function makePreviews(id, img) {
  const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
  const preview = resized(img, ...fit(w, h, PREVIEW_LONG));
  const thumb = resized(preview, ...fit(preview.width, preview.height, THUMB_LONG));
  try {
    await db.put("blobs", await toBlob(preview, "image/jpeg", 0.9), `${id}:preview`);
    await db.put("blobs", await toBlob(thumb, "image/jpeg", 0.85), `${id}:thumb`);
  } finally {
    release(preview, thumb);
  }
}

let gl = null;
function renderers() {
  if (!gl) {
    gl = {
      export: new Renderer(document.createElement("canvas")),
      match: new Renderer(document.createElement("canvas")),
    };
  }
  return gl;
}

function targetSize(w, h, f) {
  const s = Math.max(1, Math.min(f, Math.sqrt(MAX_OUT_PIXELS / (w * h))));
  return [Math.round(w * s), Math.round(h * s)];
}

async function photoJson(meta) {
  let u = urls.get(meta.id);
  if (!u || u.version !== meta.version) {
    if (u) { URL.revokeObjectURL(u.preview); URL.revokeObjectURL(u.thumb); }
    const [p, t] = await Promise.all([db.get("blobs", `${meta.id}:preview`), db.get("blobs", `${meta.id}:thumb`)]);
    u = { version: meta.version, preview: URL.createObjectURL(p), thumb: URL.createObjectURL(t) };
    urls.set(meta.id, u);
  }
  const job = jobs.get(meta.id) || null;
  const pixels = meta.orig_width * meta.orig_height;
  const budget = ai.modelBudget();
  return {
    ...meta,
    preview_url: u.preview,
    thumb_url: u.thumb,
    targets: Object.fromEntries([1, 2, 4].map((f) => [String(f), targetSize(meta.orig_width, meta.orig_height, f)])),
    upscale_note: pixels > budget
      ? `Deze foto is al groot (${(pixels / 1e6).toFixed(1)} MP). AI-upscalen op de telefoon werkt tot ${(budget / 1e6).toFixed(0)} MP en is bedoeld voor kleinere of oudere foto's.`
      : null,
    job: job && { ...job },
  };
}

class HttpError extends Error {}
const fail = (msg) => { throw new HttpError(msg); };

// ------------------------------------------------------------------ upscalen

async function runQueue() {
  if (working) return;
  working = true;
  while (queue.length) {
    const job = queue.shift();
    try {
      await runJob(job);
    } catch (e) {
      console.error(e);
      Object.assign(job, { status: "error", message: `Upscalen mislukt: ${e.message}` });
    }
  }
  working = false;
}

async function runJob(job) {
  const meta = await db.get("photos", job.photo_id);
  if (!meta) return Object.assign(job, { status: "error", message: "Foto is verwijderd" });
  job.status = "running";
  job.message = "AI laden...";
  await ai.load((m) => (job.message = m));
  const img = await loadImage(await db.get("blobs", `${meta.id}:original`));
  const w = img.naturalWidth, h = img.naturalHeight;
  if (w * h > ai.modelBudget()) fail("foto is te groot voor upscalen op dit toestel");
  const [tw, th] = targetSize(w, h, job.factor);
  const src = resized(img, w, h);
  const started = performance.now();
  job.message = "Bezig...";
  const out = await ai.upscale(src, tw, th, (f) => {
    job.progress = f * 0.95;
    const el = (performance.now() - started) / 1000;
    if (f > 0.03) job.eta = Math.round((el / f) * (1 - f));
  });
  release(src);
  job.message = "Opslaan...";
  try {
    await db.put("blobs", await toBlob(out, "image/png"), `${meta.id}:working`);
    await makePreviews(meta.id, out);
  } finally {
    release(out);
  }
  Object.assign(meta, { width: tw, height: th, upscaled: job.factor, version: meta.version + 1 });
  await db.put("photos", meta);
  Object.assign(job, { status: "done", progress: 1, message: "Klaar", eta: 0 });
}

// ------------------------------------------------------------------ routes

async function addPhotos(form) {
  const photos = [], errors = [];
  for (const file of form.getAll("files")) {
    try {
      const img = await loadImage(file);
      const id = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
      const meta = {
        id, name: (file.name || "foto").slice(0, 80),
        width: img.naturalWidth, height: img.naturalHeight,
        orig_width: img.naturalWidth, orig_height: img.naturalHeight,
        upscaled: 0, version: 1, state: null, created: Date.now(),
      };
      await db.put("blobs", file, `${id}:original`);
      await makePreviews(id, img);
      await db.put("photos", meta);
      photos.push(await photoJson(meta));
    } catch (e) {
      errors.push(`${file.name}: ${e.message}`);
    }
  }
  return { photos, errors };
}

async function exportPhotos({ photo_ids, state }) {
  if (!photo_ids?.length) fail("Geen foto's gekozen");
  const byId = await presetsById();
  const r = renderers().export;
  const max = r.maxSize();
  const files = [];
  const used = new Set();
  for (const id of photo_ids) {
    const meta = await db.get("photos", id);
    if (!meta) continue;
    const blob = (await db.get("blobs", `${id}:working`)) || (await db.get("blobs", `${id}:original`));
    let img = await loadImage(blob);
    let w = img.naturalWidth, h = img.naturalHeight;
    // binnen de grenzen van het toestel blijven
    const s = Math.min(1, max / Math.max(w, h), Math.sqrt(MAX_OUT_PIXELS / (w * h)));
    if (s < 1) { [w, h] = [Math.round(w * s), Math.round(h * s)]; img = resized(img, w, h); }
    r.setImage(img, w, h);
    release(img);
    r.render(effective(state ?? meta.state, byId));
    const out = await toBlob(r.canvas, "image/jpeg", JPEG_QUALITY);
    let base = meta.name.replace(/\.[^.]+$/, "").replace(/[^\w-]+/g, "_") || "foto";
    if (meta.upscaled === 1) base += "_ai"; else if (meta.upscaled) base += `_${meta.upscaled}x`;
    let name = `${base}_edit.jpg`, i = 2;
    while (used.has(name)) name = `${base}_edit_${i++}.jpg`;
    used.add(name);
    files.push(new File([out], name, { type: "image/jpeg", lastModified: Date.now() }));
  }
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return { files, count: files.length, filename: files.length === 1 ? files[0].name : `fotostudio_${stamp}.zip`,
    zip: files.length > 1 ? () => makeZip(files) : null };
}

async function autoAdjust(id) {
  const img = await loadImage(await db.get("blobs", `${id}:preview`));
  const c = resized(img, ...fit(img.naturalWidth, img.naturalHeight, 512));
  const px = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
  release(c);
  return suggest(px);
}

async function copyLook(id, form) {
  const refFile = form.get("reference");
  let ref;
  try { ref = await loadImage(refFile); } catch { fail("Dat voorbeeld is geen geldige foto"); }
  const rc = resized(ref, ...fit(ref.naturalWidth, ref.naturalHeight, 300));
  const refPixels = rc.getContext("2d").getImageData(0, 0, rc.width, rc.height).data;
  release(rc);
  const img = await loadImage(await db.get("blobs", `${id}:preview`));
  const small = resized(img, ...fit(img.naturalWidth, img.naturalHeight, 200));
  const r = renderers().match;
  r.setImage(small, small.width, small.height);
  release(small);
  const params = await matchLook((p) => { r.render(p); return r.pixels(); }, refPixels);
  const customs = await db.all("presets");
  const n = customs.filter((p) => p.name.startsWith("Look ")).length + 1;
  const preset = { id: "custom-" + crypto.randomUUID().slice(0, 8), name: `Look ${n}`, short: "L" + n, params: cleanParams(params) };
  await db.put("presets", preset);
  return { preset: { ...preset, builtin: false }, summary: describe(params) };
}

const routes = [
  ["GET", /^\/api\/auth\/status$/, () => ({ authenticated: true, is_local: false, password_set: true })],
  ["GET", /^\/api\/status$/, () => ({
    upscaler: { state: "ready", message: ai.engine.label, engine: ai.engine.name },
    lan_url: null, is_local: false, password_set: true, tunnel: { state: "off" },
  })],
  ["GET", /^\/api\/photos$/, async () => {
    const all = (await db.all("photos")).sort((a, b) => a.created - b.created);
    return Promise.all(all.map(photoJson));
  }],
  ["POST", /^\/api\/photos$/, (m, body) => addPhotos(body)],
  ["PUT", /^\/api\/photos\/(\w+)\/state$/, async (m, body) => {
    const meta = await db.get("photos", m[1]);
    if (!meta) fail("Foto niet gevonden");
    meta.state = body.state;
    await db.put("photos", meta);
    return photoJson(meta);
  }],
  ["DELETE", /^\/api\/photos\/(\w+)$/, async (m) => {
    for (const k of ["original", "working", "preview", "thumb"]) await db.del("blobs", `${m[1]}:${k}`);
    await db.del("photos", m[1]);
    jobs.delete(m[1]);
    return { ok: true };
  }],
  ["POST", /^\/api\/photos\/(\w+)\/upscale$/, async (m, body) => {
    const meta = await db.get("photos", m[1]);
    if (!meta) fail("Foto niet gevonden");
    if (meta.orig_width * meta.orig_height > ai.modelBudget()) fail((await photoJson(meta)).upscale_note);
    const existing = jobs.get(m[1]);
    if (existing && (existing.status === "queued" || existing.status === "running")) return existing;
    const job = { id: crypto.randomUUID().slice(0, 10), photo_id: m[1], factor: body.factor, status: "queued",
      progress: 0, message: "In de wachtrij", eta: null };
    jobs.set(m[1], job);
    queue.push(job);
    runQueue();
    return job;
  }],
  ["POST", /^\/api\/photos\/(\w+)\/reset-upscale$/, async (m) => {
    const meta = await db.get("photos", m[1]);
    await db.del("blobs", `${m[1]}:working`);
    await makePreviews(m[1], await loadImage(await db.get("blobs", `${m[1]}:original`)));
    Object.assign(meta, { width: meta.orig_width, height: meta.orig_height, upscaled: 0, version: meta.version + 1 });
    await db.put("photos", meta);
    jobs.delete(m[1]);
    return photoJson(meta);
  }],
  ["POST", /^\/api\/photos\/(\w+)\/auto$/, (m) => autoAdjust(m[1])],
  ["POST", /^\/api\/photos\/(\w+)\/match$/, (m, body) => copyLook(m[1], body)],
  ["GET", /^\/api\/presets$/, async () => Object.values(await presetsById())],
  ["POST", /^\/api\/presets$/, async (m, body) => {
    const name = (body.name || "").trim().slice(0, 40) || "Mijn preset";
    const short = (name.match(/\w+/g) || ["P"]).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
    const preset = { id: "custom-" + crypto.randomUUID().slice(0, 8), name, short, params: cleanParams(body.params) };
    await db.put("presets", preset);
    return { ...preset, builtin: false };
  }],
  ["DELETE", /^\/api\/presets\/([\w-]+)$/, async (m) => {
    if (!m[1].startsWith("custom-")) fail("Preset niet gevonden");
    await db.del("presets", m[1]);
    return { ok: true };
  }],
  ["POST", /^\/api\/export$/, (m, body) => exportPhotos(body)],
];

export async function localApi(method, url, body) {
  const path = url.split("?")[0];
  for (const [verb, re, handler] of routes) {
    const m = verb === method && path.match(re);
    if (m) {
      try {
        return await handler(m, body);
      } catch (e) {
        throw new Error(e.message || "Er ging iets mis");
      }
    }
  }
  throw new Error(`Onbekend verzoek: ${method} ${path}`);
}
