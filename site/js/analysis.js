// Auto-knop en Kopieer look, voor de browserversie.
// Zelfde logica als app/auto.py en app/match.py.

const LUMA = [0.2126, 0.7152, 0.0722];
const HSL_RANGES = { orange: [30, 35], green: [110, 50], blue: [215, 50] };
const QUANTILES = [0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98];
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function quantiles(arr, qs) {
  const s = Float32Array.from(arr).sort();
  return qs.map((q) => {
    const pos = q * (s.length - 1);
    const i = Math.floor(pos);
    const f = pos - i;
    return i + 1 < s.length ? s[i] + (s[i + 1] - s[i]) * f : s[i];
  });
}

const smooth = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};

function hueOf(r, g, b) {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  const c = mx - mn, safe = Math.max(c, 1e-6);
  let h;
  if (mx === r) h = (((g - b) / safe) % 6 + 6) % 6;
  else if (mx === g) h = (b - r) / safe + 2;
  else h = (r - g) / safe + 4;
  return [h * 60, c];
}

function rangeWeight(h, center, half) {
  const d = Math.abs(((h - center + 180) % 360 + 360) % 360 - 180);
  return clamp(1 - d / half, 0, 1);
}

// ------------------------------------------------------------------ Auto

export function suggest(rgba) {
  const n = rgba.length / 4;
  const lum = new Float32Array(n);
  let satSum = 0, rS = 0, gS = 0, bS = 0, cnt = 0, low = 0, high = 0, sum = 0;
  for (let i = 0; i < n; i++) {
    const r = rgba[4 * i] / 255, g = rgba[4 * i + 1] / 255, b = rgba[4 * i + 2] / 255;
    const L = r * LUMA[0] + g * LUMA[1] + b * LUMA[2];
    lum[i] = L;
    sum += L;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    satSum += mx > 1e-3 ? (mx - mn) / Math.max(mx, 1e-3) : 0;
    if (L > 0.15 && L < 0.85) { rS += r; gS += g; bS += b; cnt++; }
    if (L < 0.02) low++;
    if (L > 0.98) high++;
  }
  if (cnt <= 100) {
    rS = gS = bS = 0;
    for (let i = 0; i < n; i++) { rS += rgba[4 * i] / 255; gS += rgba[4 * i + 1] / 255; bS += rgba[4 * i + 2] / 255; }
    cnt = n;
  }
  const r = rS / cnt, g = gS / cnt, b = bS / cnt, avg = Math.max((r + g + b) / 3, 1e-3);
  const mean = sum / n;
  let varSum = 0;
  for (let i = 0; i < n; i++) varSum += (lum[i] - mean) ** 2;
  const std = Math.sqrt(varSum / n);
  const [p2, median] = quantiles(lum, [0.02, 0.5]);
  const sat = satSum / n, warmth = (r - b) / avg, gm = (g - (r + b) / 2) / avg;
  const clipLow = low / n, clipHigh = high / n;

  let preset, why;
  if (sat < 0.08) [preset, why] = ["bw-contrast", "weinig kleur in de foto"];
  else if (mean < 0.32) [preset, why] = ["moody-dark", "donkere, low-key foto"];
  else if (mean > 0.58 && std < 0.26) [preset, why] = ["clean-bright", "lichte, luchtige foto"];
  else if (warmth > 0.12) [preset, why] = ["film-warm", "warme tinten"];
  else if (warmth < -0.08) [preset, why] = ["cool-grey", "koele tinten"];
  else if (sat > 0.35) [preset, why] = ["film-warm", "veel kleur, past goed bij film"];
  else if (std < 0.17) [preset, why] = ["clean-bright", "zacht licht met weinig contrast"];
  else [preset, why] = ["moody-dark", "uitgebalanceerde foto, geschikt voor een moody look"];

  const adjust = {}, notes = [];
  const target = { "moody-dark": 0.36, "clean-bright": 0.52, "bw-contrast": 0.45 }[preset] ?? 0.46;
  const stops = 2.2 * Math.log2(target / Math.max(median, 0.02)) * 0.6;
  const exposure = clamp(stops * 50, -45, 45);
  if (Math.abs(exposure) >= 4) {
    adjust.exposure = Math.round(exposure);
    notes.push(exposure > 0 ? "lichter gemaakt" : "donkerder gemaakt");
  }
  if (std < 0.16) { adjust.contrast = Math.round(Math.min(30, (0.2 - std) * 250)); notes.push("meer contrast"); }
  else if (std > 0.3) { adjust.contrast = -Math.round(Math.min(25, (std - 0.28) * 200)); notes.push("minder contrast"); }
  if (clipHigh > 0.02) { adjust.highlights = -Math.round(Math.min(40, clipHigh * 400)); notes.push("hoge lichten hersteld"); }
  if (clipLow > 0.05 && preset !== "moody-dark" && preset !== "bw-contrast") {
    adjust.shadows = Math.round(Math.min(35, clipLow * 200)); notes.push("schaduwen opgehaald");
  }
  if (p2 > 0.1) { adjust.blacks = -Math.round(Math.min(30, (p2 - 0.05) * 150)); notes.push("diepere zwarten"); }
  if (preset !== "bw-contrast") {
    if (Math.abs(warmth) > 0.06 && preset !== "film-warm" && preset !== "cool-grey") {
      adjust.temperature = Math.round(clamp(-warmth * 120, -30, 30)); notes.push("witbalans gecorrigeerd");
    }
    if (gm > 0.06) adjust.tint = Math.round(Math.min(gm * 120, 20));
  }
  const names = { "moody-dark": "Moody Dark", "clean-bright": "Clean Bright", "film-warm": "Film Warm", "cool-grey": "Cool Grey", "bw-contrast": "B&W Contrast" };
  let summary = `${names[preset]} — ${why}`;
  if (notes.length) summary += "; " + notes.join(", ");
  const strength = preset === "moody-dark" || preset === "film-warm" ? 80 : 75;
  return { state: { preset, strength, adjust }, summary };
}

// ------------------------------------------------------------------ Kopieer look

export function fingerprint(rgba) {
  const n = rgba.length / 4;
  const lum = new Float32Array(n);
  let chromaSum = 0;
  const chroma = new Float32Array(n);
  const tone = [0, 0, 0, 0, 0, 0], wsum = [0, 0, 0];
  const hsl = {};
  for (const k in HSL_RANGES) hsl[k] = { w: 0, L: 0, c: 0 };
  for (let i = 0; i < n; i++) {
    const r = rgba[4 * i] / 255, g = rgba[4 * i + 1] / 255, b = rgba[4 * i + 2] / 255;
    const L = r * LUMA[0] + g * LUMA[1] + b * LUMA[2];
    lum[i] = L;
    const [h, c] = hueOf(r, g, b);
    chroma[i] = c;
    chromaSum += c;
    const a = r - g, yb = (r + g) / 2 - b;
    const bands = [(1 - L) ** 2, 1 - Math.abs(2 * L - 1), L * L];
    for (let k = 0; k < 3; k++) {
      tone[2 * k] += a * bands[k];
      tone[2 * k + 1] += yb * bands[k];
      wsum[k] += bands[k];
    }
    const cw = smooth(0.02, 0.15, c);
    for (const k in HSL_RANGES) {
      const w = rangeWeight(h, ...HSL_RANGES[k]) * cw;
      if (w > 0) { hsl[k].w += w; hsl[k].L += L * w; hsl[k].c += c * w; }
    }
  }
  const fp = {
    lum: quantiles(lum, QUANTILES),
    chroma: [chromaSum / n, quantiles(chroma, [0.8])[0]],
    tone: tone.map((v, i) => v / Math.max(wsum[i >> 1], 1e-9)),
  };
  for (const k in HSL_RANGES) {
    const share = hsl[k].w / n;
    if (share > 0.01) fp[k] = { share, v: [hsl[k].L / hsl[k].w, hsl[k].c / hsl[k].w] };
  }
  return fp;
}

const W = { lum: 2.0, chroma: 3.0, tone: 6.0, reg: 1e-3 };

function distance(fp, ref) {
  const sq = (a, b) => a.reduce((s, v, i) => s + (v - b[i]) ** 2, 0);
  let d = W.lum * sq(fp.lum, ref.lum) + W.chroma * sq(fp.chroma, ref.chroma) + W.tone * sq(fp.tone, ref.tone);
  for (const k in HSL_RANGES) {
    if (fp[k] && ref[k]) {
      const weight = 2 * Math.min(1, 10 * Math.min(fp[k].share, ref[k].share));
      const a = k === "orange" ? fp[k].v : fp[k].v.slice(1);
      const b = k === "orange" ? ref[k].v : ref[k].v.slice(1);
      d += weight * sq(a, b);
    }
  }
  return d;
}

const KEYS = ["exposure", "contrast", "highlights", "shadows", "blacks", "fade", "saturation",
  "temperature", "tint", "orange_sat", "orange_lum", "green_sat", "blue_sat"];

export function vectorToParams(x) {
  const p = {};
  KEYS.forEach((k, i) => (p[k] = x[i] * 100));
  ["split_shadow", "split_highlight"].forEach((name, j) => {
    const sx = x[KEYS.length + 2 * j], sy = x[KEYS.length + 2 * j + 1];
    p[name] = Math.min(100, Math.hypot(sx, sy) * 100);
    p[name + "_hue"] = ((Math.atan2(sy, sx) * 180) / Math.PI + 360) % 360;
  });
  for (const k of ["fade", "split_shadow", "split_highlight"]) p[k] = clamp(p[k], 0, 100);
  for (const k of KEYS) if (k !== "fade") p[k] = clamp(p[k], -100, 100);
  return p;
}

// render(params) -> RGBA-pixels van de bewerkte (kleine) foto
export async function matchLook(render, refRGBA, { maxEvals = 900, onProgress } = {}) {
  const ref = fingerprint(refRGBA);
  const cost = (x) => distance(fingerprint(render(vectorToParams(x))), ref) + W.reg * x.reduce((s, v) => s + v * v, 0);
  let x = new Array(KEYS.length + 4).fill(0);
  let best = cost(x);
  let evals = 0;
  const steps = [0.4, 0.2, 0.1, 0.05, 0.02];
  for (let si = 0; si < steps.length; si++) {
    const step = steps[si];
    let improved = true;
    while (improved && evals < maxEvals) {
      improved = false;
      for (let i = 0; i < x.length; i++) {
        for (const sign of [1, -1]) {
          const trial = x.slice();
          trial[i] = clamp(trial[i] + sign * step, -1, 1);
          const c = cost(trial);
          evals++;
          if (c < best - 1e-7) { x = trial; best = c; improved = true; break; }
        }
      }
      onProgress?.(Math.min(0.99, (si + evals / maxEvals) / steps.length));
      await new Promise((r) => setTimeout(r, 0)); // scherm laten bijwerken
    }
  }
  return vectorToParams(x);
}

export function describe(p) {
  const w = [];
  if (p.exposure <= -15) w.push("donkerder"); else if (p.exposure >= 15) w.push("lichter");
  if (p.contrast >= 15) w.push("meer contrast"); else if (p.contrast <= -15) w.push("zachter contrast");
  if (p.saturation <= -20) w.push("gedempte kleuren"); else if (p.saturation >= 20) w.push("kleurrijker");
  if (p.temperature >= 12) w.push("warmer"); else if (p.temperature <= -12) w.push("koeler");
  if (p.fade >= 15) w.push("matte zwarten");
  if (Math.abs(p.orange_lum) >= 15 || Math.abs(p.orange_sat) >= 15) w.push("huidtinten aangepast");
  return w.join(", ") || "subtiele aanpassing";
}
