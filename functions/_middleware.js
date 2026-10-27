// Inloggen voor de Cloudflare-versie (Cloudflare Pages Functions).
//
// Alleen wie de gebruikersnaam en het wachtwoord kent komt erin. Na het inloggen
// blijf je een jaar ingelogd (cookie). Instellingen staan als geheime variabelen
// in het Pages-project:
//   AUTH_USER       gebruikersnaam
//   AUTH_PASS_HASH  "salt:hash" (PBKDF2-SHA256, hex)
//   SESSION_SECRET  willekeurige sleutel om sessies te ondertekenen

const COOKIE = "fs_session";
const SESSION_DAYS = 365;
const ITERATIONS = 20000;
const PUBLIC = new Set(["/manifest.webmanifest", "/icon.svg", "/icon-180.png", "/icon-192.png", "/icon-512.png"]);

const enc = new TextEncoder();
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const unhex = (s) => new Uint8Array(s.match(/../g).map((h) => parseInt(h, 16)));

async function pbkdf2(password, saltHex) {
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: unhex(saltHex), iterations: ITERATIONS }, key, 256);
  return hex(bits);
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function makeSession(env) {
  const expires = Date.now() + SESSION_DAYS * 86400e3;
  return `${expires}.${await hmac(env.SESSION_SECRET, `${env.AUTH_USER}|${expires}`)}`;
}

async function validSession(env, value) {
  if (!value) return false;
  const [expires, sig] = value.split(".");
  if (!expires || !sig || Number(expires) < Date.now()) return false;
  return safeEqual(sig, await hmac(env.SESSION_SECRET, `${env.AUTH_USER}|${expires}`));
}

function getCookie(request, name) {
  const m = (request.headers.get("cookie") || "").match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return m ? decodeURIComponent(m[1]) : null;
}

export async function checkPassword(env, user, password) {
  const [salt, hash] = (env.AUTH_PASS_HASH || "").split(":");
  if (!salt || !hash || !env.AUTH_USER) return false;
  const userOk = safeEqual((user || "").trim().toLowerCase(), env.AUTH_USER.toLowerCase());
  const passOk = safeEqual(await pbkdf2(password || "", salt), hash);
  return userOk && passOk;
}

const SECURITY_HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "cache-control": "no-store",
  "x-frame-options": "DENY",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

function loginPage(error = "") {
  const html = `<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0b0c"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/icon-180.png"><link rel="manifest" href="/manifest.webmanifest">
<title>Fotostudio</title>
<style>
  html,body{height:100%;margin:0;background:#0b0b0c;color:#ededee;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  body{display:flex;align-items:center;justify-content:center;padding:20px;box-sizing:border-box}
  form{width:100%;max-width:320px;display:flex;flex-direction:column;gap:12px;text-align:center}
  .brand{font-weight:700;letter-spacing:.32em;font-size:12px;margin-bottom:10px}
  input{height:46px;border-radius:10px;border:1px solid #26262a;background:#131315;color:#ededee;padding:0 14px;font-size:16px;outline:none}
  input:focus{border-color:#666}
  button{height:46px;border-radius:999px;border:0;background:#fff;color:#000;font-weight:600;font-size:15px}
  .err{color:#ff5f57;min-height:18px;font-size:13px}
</style></head><body>
<form method="post" action="/login">
  <div class="brand">FOTOSTUDIO</div>
  <input name="username" placeholder="Gebruikersnaam" autocomplete="username" autocapitalize="none" required>
  <input name="password" type="password" placeholder="Wachtwoord" autocomplete="current-password" required>
  <button type="submit">Inloggen</button>
  <div class="err">${error}</div>
</form></body></html>`;
  return new Response(html, { status: error ? 401 : 200, headers: SECURITY_HEADERS });
}

export async function onRequest({ request, env, next }) {
  const url = new URL(request.url);
  if (PUBLIC.has(url.pathname)) return next();
  if (!env.AUTH_USER || !env.AUTH_PASS_HASH || !env.SESSION_SECRET) {
    // niet ingesteld = dicht, nooit open
    return new Response("Nog niet ingesteld", { status: 503, headers: { "cache-control": "no-store" } });
  }

  if (url.pathname === "/logout") {
    return new Response(null, { status: 303, headers: {
      location: "/", "set-cookie": `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`,
    } });
  }

  if (url.pathname === "/login" && request.method === "POST") {
    const form = await request.formData();
    if (await checkPassword(env, form.get("username"), form.get("password"))) {
      return new Response(null, { status: 303, headers: {
        location: "/",
        "set-cookie": `${COOKIE}=${await makeSession(env)}; Path=/; Max-Age=${SESSION_DAYS * 86400}; HttpOnly; Secure; SameSite=Lax`,
      } });
    }
    await new Promise((r) => setTimeout(r, 1000)); // raden vertragen
    return loginPage("Gebruikersnaam of wachtwoord klopt niet");
  }

  if (await validSession(env, getCookie(request, COOKIE))) return next();
  if (request.method === "GET" && (request.headers.get("accept") || "").includes("text/html")) return loginPage();
  return new Response("Log eerst in", { status: 401, headers: { "cache-control": "no-store" } });
}
