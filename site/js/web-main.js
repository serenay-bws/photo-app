// Start van de Cloudflare-versie: alles draait in de browser.
import { localApi } from "./local-api.js";

window.FOTOSTUDIO_LOCAL = localApi;
await import("./app.js");
