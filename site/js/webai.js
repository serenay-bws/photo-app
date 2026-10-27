// Real-ESRGAN in de browser (ONNX Runtime Web).
// Gebruikt de videochip van je telefoon (WebGPU) als dat kan, anders de processor (WASM).

const VENDOR = new URL("../vendor/ort/", import.meta.url).href;
const MODEL_URL = new URL("../models/realesr-general-x4v3.onnx", import.meta.url).href;
const WASM_PARTS = ["ort-wasm-simd-threaded.jsep.wasm.part0", "ort-wasm-simd-threaded.jsep.wasm.part1"];
export const SCALE = 4;

let sessionPromise = null;
export const engine = { name: null, label: "AI wordt geladen bij het eerste gebruik" };

async function fetchBuffer(url, onBytes) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download mislukt (${res.status})`);
  const total = Number(res.headers.get("content-length")) || 0;
  if (!res.body || !onBytes) return new Uint8Array(await res.arrayBuffer());
  const reader = res.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onBytes(value.length, total);
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

export function hasWebGPU() {
  let forced = null;
  try { forced = localStorage.getItem("fotostudio-ai"); } catch {}
  return !!navigator.gpu && forced !== "wasm";
}

export function load(onStatus) {
  if (!sessionPromise) {
    sessionPromise = (async () => {
      onStatus?.("AI-model downloaden (eenmalig ±35 MB)...");
      const ort = await import(VENDOR + "ort.min.mjs");
      const parts = await Promise.all(WASM_PARTS.map((p) => fetchBuffer(VENDOR + p)));
      const wasm = new Uint8Array(parts.reduce((s, p) => s + p.length, 0));
      let o = 0;
      for (const p of parts) { wasm.set(p, o); o += p.length; }
      ort.env.wasm.wasmBinary = wasm.buffer;
      ort.env.wasm.wasmPaths = VENDOR;
      ort.env.wasm.numThreads = self.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 2) : 1;
      const model = await fetchBuffer(MODEL_URL);
      onStatus?.("AI starten...");
      let session = null;
      if (hasWebGPU()) {
        try {
          session = await ort.InferenceSession.create(model, { executionProviders: ["webgpu"] });
          // proefrit: sommige toestellen falen pas bij het rekenen
          const probe = new ort.Tensor("float32", new Float32Array(3 * 16 * 16).fill(0.5), [1, 3, 16, 16]);
          (await session.run({ input: probe })).output.dispose?.();
          engine.name = "webgpu";
          engine.label = "Videochip (WebGPU) · Real-ESRGAN general-x4v3";
        } catch (e) {
          console.warn("WebGPU niet bruikbaar, val terug op WASM", e);
          session = null;
        }
      }
      if (!session) {
        session = await ort.InferenceSession.create(model, { executionProviders: ["wasm"] });
        engine.name = "wasm";
        engine.label = `Processor (${ort.env.wasm.numThreads} kernen) · Real-ESRGAN general-x4v3`;
      }
      return { ort, session };
    })();
    sessionPromise.catch(() => (sessionPromise = null));
  }
  return sessionPromise;
}

// Hoeveel pixels het model in één keer mag verwerken (snelheid en geheugen op een telefoon)
export function modelBudget() {
  return engine.name === "webgpu" || (engine.name === null && hasWebGPU()) ? 4_000_000 : 2_000_000;
}

/**
 * Upscale `src` (canvas, invoer-formaat) naar een canvas van outW x outH.
 * De 4x-uitvoer wordt per tegel direct naar het doelformaat geschaald, zodat er nooit
 * een gigantische tussenafbeelding in het geheugen hoeft.
 */
export async function upscale(src, outW, outH, onProgress, { tile = 192, pad = 12 } = {}) {
  const { ort, session } = await load();
  const w = src.width, h = src.height;
  const input = src.getContext("2d").getImageData(0, 0, w, h).data;
  const out = document.createElement("canvas");
  out.width = outW;
  out.height = outH;
  const octx = out.getContext("2d");
  octx.imageSmoothingEnabled = true;
  octx.imageSmoothingQuality = "high";
  const tmp = document.createElement("canvas");
  const tctx = tmp.getContext("2d");
  const sx = outW / w, sy = outH / h;
  const tiles = [];
  for (let y = 0; y < h; y += tile) for (let x = 0; x < w; x += tile) tiles.push([x, y]);
  for (let i = 0; i < tiles.length; i++) {
    const [x, y] = tiles[i];
    const x0 = Math.max(0, x - pad), y0 = Math.max(0, y - pad);
    const x1 = Math.min(w, x + tile + pad), y1 = Math.min(h, y + tile + pad);
    const tw = x1 - x0, th = y1 - y0;
    const data = new Float32Array(3 * tw * th);
    for (let yy = 0; yy < th; yy++) {
      for (let xx = 0; xx < tw; xx++) {
        const s = 4 * ((y0 + yy) * w + (x0 + xx));
        const d = yy * tw + xx;
        data[d] = input[s] / 255;
        data[tw * th + d] = input[s + 1] / 255;
        data[2 * tw * th + d] = input[s + 2] / 255;
      }
    }
    const feeds = { input: new ort.Tensor("float32", data, [1, 3, th, tw]) };
    const result = (await session.run(feeds)).output;
    const o = result.data;
    const OW = tw * SCALE, OH = th * SCALE;
    // alleen de kern van de tegel (zonder de overlap-rand)
    const cx0 = (x - x0) * SCALE, cy0 = (y - y0) * SCALE;
    const cw = (Math.min(w, x + tile) - x) * SCALE, ch = (Math.min(h, y + tile) - y) * SCALE;
    const img = new ImageData(cw, ch);
    const plane = OW * OH;
    for (let yy = 0; yy < ch; yy++) {
      for (let xx = 0; xx < cw; xx++) {
        const s = (cy0 + yy) * OW + (cx0 + xx);
        const d = 4 * (yy * cw + xx);
        img.data[d] = o[s] * 255;
        img.data[d + 1] = o[plane + s] * 255;
        img.data[d + 2] = o[2 * plane + s] * 255;
        img.data[d + 3] = 255;
      }
    }
    result.dispose?.();
    tmp.width = cw;
    tmp.height = ch;
    tctx.putImageData(img, 0, 0);
    const dx0 = Math.round(x * sx), dy0 = Math.round(y * sy);
    const dx1 = Math.round(Math.min(w, x + tile) * sx), dy1 = Math.round(Math.min(h, y + tile) * sy);
    octx.drawImage(tmp, 0, 0, cw, ch, dx0, dy0, dx1 - dx0, dy1 - dy0);
    onProgress?.((i + 1) / tiles.length);
    await new Promise((r) => setTimeout(r, 0));
  }
  return out;
}
