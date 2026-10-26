// Fails the build when `dist/index.html` points anywhere but `./web/`: under Ingress the site lives at a changing
// prefix, so every asset URL must be relative, and the add-on serves the assets at `web/` only.
import { existsSync, readFileSync } from "node:fs";
import { URL, fileURLToPath } from "node:url";

const index = fileURLToPath(new URL("../dist/index.html", import.meta.url));
if (!existsSync(index)) throw new Error(`${index} is missing; did the build run?`);

const html = readFileSync(index, "utf-8");
const urls = [...html.matchAll(/\s(?:src|href)\s*=\s*["']([^"']*)["']/g)].map((match) => match[1]);
if (urls.length === 0) throw new Error(`${index} has no src or href; the build looks broken`);

const wrong = urls.filter((url) => !url.startsWith("./web/"));
if (wrong.length > 0) throw new Error(`${index} has URLs outside ./web/: ${wrong.join(", ")}`);
