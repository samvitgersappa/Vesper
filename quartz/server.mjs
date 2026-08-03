// Quartz trigger + static server for the Vesper Second Brain container.
//
// Serves the built site from OUTPUT_DIR with Quartz's extension-less URL
// convention ({path} -> {path}.html -> {path}/), and exposes:
//   POST /rebuild  — re-sync the vault and rebuild (blocking, streams result)
//   GET  /health   — liveness + last build time
//   GET  /         — the garden itself (dev convenience; Caddy serves prod)

import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { createReadStream, existsSync, statSync, readdirSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";

const OUT = process.env.OUTPUT_DIR || "/out";
const PORT = Number(process.env.TRIGGER_PORT || 8081);

let lastBuild = 0;
let building = false;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".pdf": "application/pdf",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
  ".map": "application/json",
};

function resolveFile(urlPath) {
  let p = normalize(urlPath).replace(/^(\.\.(\/|\\|$))+/, "");
  p = p.replace(/^[/\\]+/, "");
  const base = resolve(OUT);
  let file = resolve(base, p);
  if (!file.startsWith(base)) return null;
  if (!existsSync(file) || statSync(file).isDirectory()) {
    if (existsSync(file + ".html")) return file + ".html";
    const idx = join(file, "index.html");
    if (existsSync(idx)) return idx;
    return null;
  }
  return file;
}

function serve(res, file) {
  const type = MIME[extname(file).toLowerCase()] || "application/octet-stream";
  res.writeHead(200, { "content-type": type, "cache-control": "no-cache" });
  createReadStream(file).pipe(res);
}

function runBuild() {
  return new Promise((resolvePromise) => {
    if (building) return resolvePromise({ ok: false, message: "already building" });
    building = true;
    const t = Date.now();
    const child = spawn("./rebuild.sh", [], { cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    child.stdout.on("data", (d) => (out += d.toString()));
    child.stderr.on("data", (d) => (out += d.toString()));
    child.on("close", (code) => {
      building = false;
      if (code === 0) lastBuild = Date.now();
      resolvePromise({ ok: code === 0, exitCode: code, durationMs: Date.now() - t, output: out.slice(-8000) });
    });
  });
}

const server = createServer(async (req, res) => {
  const url = (req.url || "/").split("?")[0];

  if (req.method === "POST" && url === "/rebuild") {
    const result = await runBuild();
    res.writeHead(result.ok ? 200 : 500, { "content-type": "application/json" });
    res.end(JSON.stringify(result));
    return;
  }

  if (req.method === "GET" && url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "ok", lastBuild, building }));
    return;
  }

  if (req.method === "GET") {
    const file = resolveFile(url === "/" ? "/index.html" : url);
    if (file) return serve(res, file);
    const notFound = resolve(OUT, "404.html");
    if (existsSync(notFound)) {
      res.writeHead(404, { "content-type": "text/html; charset=utf-8" });
      return createReadStream(notFound).pipe(res);
    }
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("not found");
    return;
  }

  res.writeHead(405, { "content-type": "text/plain" });
  res.end("method not allowed");
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[quartz] server listening on http://0.0.0.0:${PORT}`);
});
