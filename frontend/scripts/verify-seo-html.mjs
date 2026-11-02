#!/usr/bin/env node
/**
 * Verify production SSR HTML via next start (dynamic route — no static index.html).
 */
import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 18711;

function fetchText(urlPath) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: "127.0.0.1", port: PORT, path: urlPath }, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () =>
          resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString("utf8") }),
        );
      })
      .on("error", reject);
  });
}

function assertIncludes(html, needle, label) {
  if (!html.includes(needle)) {
    throw new Error(`SEO HTML missing ${label}: ${JSON.stringify(needle)}`);
  }
}

function assertNotIncludes(html, needle, label) {
  if (html.includes(needle)) {
    throw new Error(`SEO HTML must not contain ${label}: ${JSON.stringify(needle)}`);
  }
}

async function main() {
  const server = spawn(
    "npx",
    ["next", "start", "-H", "127.0.0.1", "-p", String(PORT)],
    {
      cwd: root,
      env: {
        ...process.env,
        DESINFO_API_HOST: process.env.DESINFO_API_HOST || "127.0.0.1",
        DESINFO_API_PORT: process.env.DESINFO_API_PORT || "8700",
      },
      stdio: "ignore",
    },
  );
  try {
    for (let i = 0; i < 40; i++) {
      try {
        await fetchText("/");
        break;
      } catch {
        await new Promise((r) => setTimeout(r, 250));
      }
    }
    const home = await fetchText("/");
    assertIncludes(home.body, "Observatoire de la désinformation", "brand");
    assertIncludes(
      home.body,
      'rel="canonical" href="https://desinfo.electronlibre.info/"',
      "canonical",
    );
    assertIncludes(home.body, 'name="description"', "description");
    assertNotIncludes(home.body, "BAILOUT_TO_CLIENT_SIDE_RENDERING", "bailout");
    assertNotIncludes(home.body, 'class="empty">Chargement…</p>', "loading shell");
    assertIncludes(home.body, "Méthodologie", "methodology");

    const robots = await fetchText("/robots.txt");
    assertIncludes(robots.body, "Disallow: /api/", "robots api");
    const sitemap = await fetchText("/sitemap.xml");
    assertIncludes(sitemap.body, "https://desinfo.electronlibre.info/", "sitemap");
    console.log("OK SSR SEO HTML bytes=", home.body.length);
  } finally {
    server.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
