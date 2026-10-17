// Run the app locally with plain Node — no Vercel CLI needed.
//   node server.js
// Serves index.html as a static file and routes /api/chat to the same
// function Vercel uses. Reads the key from a local .env file.

const http = require("http");
const fs = require("fs");
const path = require("path");

// --- tiny .env loader (no dependencies) ---
try {
  fs.readFileSync(path.join(__dirname, ".env"), "utf8").split("\n").forEach((line) => {
    const m = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  });
} catch { /* no .env — fine, turn 1 still works */ }

const chat = require("./api/chat.js");
const PORT = process.env.PORT || 3000;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };

http.createServer((req, res) => {
  const urlPath = req.url.split("?")[0];

  if (urlPath === "/api/chat") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try { req.body = body ? JSON.parse(body) : {}; } catch { req.body = {}; }
      // give the function the same res helpers Vercel provides
      res.status = (code) => { res.statusCode = code; return res; };
      res.json = (obj) => { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(obj)); return res; };
      chat(req, res);
    });
    return;
  }

  const file = path.join(__dirname, urlPath === "/" ? "index.html" : decodeURIComponent(urlPath));
  fs.readFile(file, (err, data) => {
    if (err) { res.statusCode = 404; res.end("Not found"); return; }
    res.setHeader("Content-Type", TYPES[path.extname(file)] || "application/octet-stream");
    res.end(data);
  });
}).listen(PORT, () => {
  console.log("\n  Bhasha Doubt Solver  ->  http://localhost:" + PORT);
  console.log("  key loaded: " + (process.env.SARVAM_API_KEY ? "yes" : "NO (add SARVAM_API_KEY to .env)") + "\n");
});
