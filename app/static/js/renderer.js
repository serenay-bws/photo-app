// Live preview van de bewerkingen met WebGL.
// De formules zijn een exacte kopie van app/edits.py (de export op de server).

const VERT = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `
precision highp float;
varying vec2 v_uv;
uniform sampler2D u_img;
uniform vec2 u_texel;
uniform float u_sharpOff;
uniform vec2 u_grid;
uniform vec2 u_aspect;
uniform float u_exposure, u_contrast, u_highlights, u_shadows, u_blacks, u_saturation;
uniform float u_temperature, u_tint, u_grain, u_vignette, u_sharpness, u_fade;
uniform float u_splitShadow, u_splitHighlight;
uniform vec3 u_shadowColor, u_highlightColor;

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

float hash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

float valueNoise(vec2 g) {
  vec2 i = floor(g);
  vec2 f = g - i;
  float a = hash(i), b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
  float top = a + (b - a) * f.x;
  float bot = c + (d - c) * f.x;
  return top + (bot - top) * f.y - 0.5;
}

void main() {
  vec3 c = texture2D(u_img, v_uv).rgb;

  // 1. verscherpen (3x3 unsharp mask)
  if (u_sharpness > 0.0) {
    vec2 o = u_texel * u_sharpOff;
    vec3 blur = (
      texture2D(u_img, v_uv + vec2(-o.x, -o.y)).rgb + texture2D(u_img, v_uv + vec2(o.x, -o.y)).rgb +
      texture2D(u_img, v_uv + vec2(-o.x, o.y)).rgb + texture2D(u_img, v_uv + vec2(o.x, o.y)).rgb +
      2.0 * (texture2D(u_img, v_uv + vec2(0.0, -o.y)).rgb + texture2D(u_img, v_uv + vec2(0.0, o.y)).rgb +
             texture2D(u_img, v_uv + vec2(-o.x, 0.0)).rgb + texture2D(u_img, v_uv + vec2(o.x, 0.0)).rgb) +
      4.0 * c) / 16.0;
    c = c + (c - blur) * (u_sharpness / 100.0 * 2.0);
  }

  // 2. witbalans + belichting in lineair licht
  float t = u_temperature / 100.0, g = u_tint / 100.0;
  vec3 lin = pow(max(c, 0.0), vec3(2.2));
  lin *= vec3(1.0 + 0.25 * t, 1.0 - 0.2 * g, 1.0 - 0.25 * t) * exp2(u_exposure / 100.0 * 2.0);
  c = pow(max(lin, 0.0), vec3(1.0 / 2.2));

  // 3. contrast
  c = 0.5 + (c - 0.5) * (1.0 + u_contrast / 100.0);

  // 4. hoge lichten / schaduwen
  float L = luma(c);
  c += (u_highlights / 100.0 * 0.35) * smoothstep(0.45, 1.0, L)
     + (u_shadows / 100.0 * 0.35) * (1.0 - smoothstep(0.0, 0.55, L));

  // 5. zwarten
  float bp = -u_blacks / 100.0 * 0.12;
  c = (c - bp) / (1.0 - bp);

  // 6. verzadiging
  L = luma(c);
  c = L + (c - L) * (1.0 + u_saturation / 100.0);

  // 7. split toning
  L = clamp(luma(c), 0.0, 1.0);
  c += (u_shadowColor - 0.5) * (u_splitShadow / 100.0 * 0.3) * (1.0 - L) * (1.0 - L)
     + (u_highlightColor - 0.5) * (u_splitHighlight / 100.0 * 0.3) * L * L;

  // 8. fade
  float f = u_fade / 100.0;
  float lo = 0.2 * f, hi = 1.0 - 0.05 * f;
  c = lo + c * (hi - lo);

  // 9. vignet
  vec2 n = (v_uv * 2.0 - 1.0) * u_aspect;
  float dist = length(n) / length(u_aspect);
  c *= 1.0 - u_vignette / 100.0 * 0.7 * smoothstep(0.3, 1.05, dist);

  // 10. filmkorrel
  if (u_grain > 0.0) {
    L = clamp(luma(c), 0.0, 1.0);
    float w = 1.0 - 0.6 * (2.0 * L - 1.0) * (2.0 * L - 1.0);
    c += valueNoise(v_uv * u_grid) * w * (u_grain / 100.0 * 0.25);
  }

  gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}`;

const GRID_LONG = 1600;

export function hueRGB(h) {
  h = (((h % 360) + 360) % 360) / 360;
  const cl = (v) => Math.min(1, Math.max(0, v));
  return [cl(Math.abs(h * 6 - 3) - 1), cl(2 - Math.abs(h * 6 - 2)), cl(2 - Math.abs(h * 6 - 4))];
}

export class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    const opts = { preserveDrawingBuffer: true, premultipliedAlpha: false, antialias: false };
    const gl = canvas.getContext("webgl", opts) || canvas.getContext("experimental-webgl", opts);
    if (!gl) throw new Error("WebGL wordt niet ondersteund door deze browser");
    this.gl = gl;
    const prog = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, VERT], [gl.FRAGMENT_SHADER, FRAG]]) {
      const sh = gl.createShader(type);
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
      gl.attachShader(prog, sh);
    }
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    this.prog = prog;
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    this.tex = gl.createTexture();
    this.u = {};
    const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) {
      const info = gl.getActiveUniform(prog, i);
      this.u[info.name] = gl.getUniformLocation(prog, info.name);
    }
    this.image = null;
  }

  // img: HTMLImageElement (preview/thumb); fullW/fullH: afmetingen van de echte foto
  setImage(img, fullW, fullH) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.image = { w: img.naturalWidth, h: img.naturalHeight, fullW: fullW || img.naturalWidth, fullH: fullH || img.naturalHeight };
  }

  render(p, width, height) {
    if (!this.image) return;
    const gl = this.gl, u = this.u, im = this.image;
    width = width || im.w;
    height = height || im.h;
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    gl.viewport(0, 0, width, height);
    const long = Math.max(im.fullW, im.fullH);
    const gridLong = Math.min(GRID_LONG, long);
    const radius = Math.max(1, Math.round(long / gridLong));
    gl.uniform1i(u.u_img, 0);
    gl.uniform2f(u.u_texel, 1 / im.w, 1 / im.h);
    gl.uniform1f(u.u_sharpOff, (radius * Math.max(im.w, im.h)) / long);
    gl.uniform2f(u.u_grid, (im.fullW * gridLong) / long, (im.fullH * gridLong) / long);
    gl.uniform2f(u.u_aspect, im.fullW / long, im.fullH / long);
    const set = (name, v) => u[name] && gl.uniform1f(u[name], v || 0);
    set("u_exposure", p.exposure); set("u_contrast", p.contrast);
    set("u_highlights", p.highlights); set("u_shadows", p.shadows);
    set("u_blacks", p.blacks); set("u_saturation", p.saturation);
    set("u_temperature", p.temperature); set("u_tint", p.tint);
    set("u_grain", p.grain); set("u_vignette", p.vignette);
    set("u_sharpness", p.sharpness); set("u_fade", p.fade);
    set("u_splitShadow", p.split_shadow); set("u_splitHighlight", p.split_highlight);
    gl.uniform3fv(u.u_shadowColor, hueRGB(p.split_shadow_hue || 0));
    gl.uniform3fv(u.u_highlightColor, hueRGB(p.split_highlight_hue || 0));
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}
