import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { after, before, describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 18710;

async function fileExists(p) {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

function run(cmd, args, env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd: root,
      stdio: "inherit",
      env: { ...process.env, ...env },
    });
    child.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`${cmd} failed: ${code}`)),
    );
  });
}

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

describe("desinfo SSR SEO HTML", () => {
  /** @type {import('node:child_process').ChildProcess | null} */
  let server = null;

  before(async () => {
    if (!(await fileExists(path.join(root, ".next", "BUILD_ID")))) {
      await run("npm", ["run", "build"], {
        DESINFO_API_HOST: process.env.DESINFO_API_HOST || "127.0.0.1",
        DESINFO_API_PORT: process.env.DESINFO_API_PORT || "8700",
      });
    }
    server = spawn(
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
    // wait for listen
    for (let i = 0; i < 40; i++) {
      try {
        await fetchText("/");
        break;
      } catch {
        await new Promise((r) => setTimeout(r, 250));
      }
    }
  });

  after(() => {
    if (server && !server.killed) {
      server.kill("SIGTERM");
    }
  });

  it("serves ranking content with canonical and no CSR bailout", async () => {
    const { status, body } = await fetchText("/");
    assert.equal(status, 200);
    assert.match(body, /Observatoire de la désinformation/);
    assert.match(body, /<meta name="description"/);
    assert.match(
      body,
      /rel="canonical" href="https:\/\/desinfo\.electronlibre\.info\/"/,
    );
    assert.doesNotMatch(body, /BAILOUT_TO_CLIENT_SIDE_RENDERING/);
    assert.doesNotMatch(body, /class="empty">Chargement…<\/p>/);
    assert.match(body, /Méthodologie/);
    // At least one ranking row from live/API snapshot
    assert.match(body, /media-name|Ranking|AFP|Média/);
  });

  it("serves robots.txt and sitemap.xml", async () => {
    const robots = await fetchText("/robots.txt");
    assert.equal(robots.status, 200);
    assert.match(robots.body, /Disallow: \/api\//);
    assert.match(robots.body, /Sitemap: https:\/\/desinfo\.electronlibre\.info\/sitemap\.xml/);

    const sitemap = await fetchText("/sitemap.xml");
    assert.equal(sitemap.status, 200);
    assert.match(sitemap.body, /https:\/\/desinfo\.electronlibre\.info\//);
  });
});

describe("site SEO helpers", () => {
  it("allowlists only public paths", async () => {
    const site = await import("../src/lib/site.ts");
    assert.equal(site.absoluteUrl("/"), "https://desinfo.electronlibre.info/");
    assert.ok(site.DISALLOW_PATH_PREFIXES.includes("/api/"));
    assert.ok(site.PUBLIC_INDEXABLE_PATHS.includes("/"));
  });
});
