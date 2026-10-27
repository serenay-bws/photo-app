// Bijsnijden, draaien en rechtzetten. Dezelfde rekenregels staan in app/geometry.py
// (export op de computer), zodat preview en export precies gelijk zijn.
//
// crop = { rot: 0-3 (kwartslagen met de klok mee), angle: -45..45 graden (rechtzetten),
//          aspect: null (zoals de foto) of breedte/hoogte, zoom: 0.2..1, cx, cy: 0..1 }

export const ASPECTS = [
  { label: "Origineel", value: null },
  { label: "1:1", value: 1 },
  { label: "4:5", value: 4 / 5 },
  { label: "9:16", value: 9 / 16 },
  { label: "3:2", value: 3 / 2 },
  { label: "2:3", value: 2 / 3 },
  { label: "16:9", value: 16 / 9 },
];

export const defaultCrop = () => ({ rot: 0, angle: 0, aspect: null, zoom: 1, cx: 0.5, cy: 0.5 });

export function isIdentity(g) {
  return !g || (!(g.rot % 4) && !g.angle && !g.aspect && (g.zoom ?? 1) >= 1);
}

// formaat na de kwartslagen
export function frameSize(w, h, g) {
  return (g?.rot ?? 0) % 2 ? [h, w] : [w, h];
}

// vergroting zodat er na het rechtzetten geen lege hoeken zijn
export function fillScale(fw, fh, angle) {
  const a = Math.abs((angle || 0) * Math.PI / 180);
  const c = Math.cos(a), s = Math.sin(a);
  return Math.max((fw * c + fh * s) / fw, (fw * s + fh * c) / fh);
}

// het uitsnijkader binnen het (gedraaide) beeld, in pixels
export function cropRect(w, h, g) {
  const [fw, fh] = frameSize(w, h, g);
  const A = g?.aspect || fw / fh;
  const maxW = Math.min(fw, fh * A);
  const z = Math.min(1, Math.max(0.2, g?.zoom ?? 1));
  const cw = maxW * z, ch = (maxW / A) * z;
  const x = Math.min(Math.max((g?.cx ?? 0.5) * fw - cw / 2, 0), fw - cw);
  const y = Math.min(Math.max((g?.cy ?? 0.5) * fh - ch / 2, 0), fh - ch);
  return { x, y, w: cw, h: ch, fw, fh };
}

/**
 * Teken `src` (w x h) met draaien/rechtzetten/bijsnijden op een nieuw canvas.
 * withCrop=false geeft het hele gedraaide beeld (voor het bijsnijscherm).
 * maxLong begrenst de lange zijde van het resultaat.
 */
export function renderGeometry(src, w, h, g, { withCrop = true, maxLong = Infinity } = {}) {
  const r = withCrop ? cropRect(w, h, g) : { x: 0, y: 0, w: frameSize(w, h, g)[0], h: frameSize(w, h, g)[1] };
  const [fw, fh] = frameSize(w, h, g);
  const s = Math.min(1, maxLong / Math.max(r.w, r.h));
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(r.w * s));
  out.height = Math.max(1, Math.round(r.h * s));
  const ctx = out.getContext("2d");
  if (!ctx) throw new Error("te weinig geheugen in de browser");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.scale(out.width / r.w, out.height / r.h);
  ctx.translate(-r.x, -r.y);
  const k = fillScale(fw, fh, g?.angle);
  ctx.translate(fw / 2, fh / 2);
  ctx.rotate(((g?.angle || 0) * Math.PI) / 180);
  ctx.scale(k, k);
  ctx.translate(-fw / 2, -fh / 2);
  const rot = ((g?.rot ?? 0) % 4 + 4) % 4;
  if (rot === 1) { ctx.translate(h, 0); ctx.rotate(Math.PI / 2); }
  else if (rot === 2) { ctx.translate(w, h); ctx.rotate(Math.PI); }
  else if (rot === 3) { ctx.translate(0, w); ctx.rotate(-Math.PI / 2); }
  ctx.drawImage(src, 0, 0, w, h);
  return out;
}
