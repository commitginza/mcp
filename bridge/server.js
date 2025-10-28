// server.js 先頭付近
import { createRequire } from "module";
const require = createRequire(import.meta.url);
// バージョン表示は不要。どうしても出すならモジュール解決のみ（失敗しても無視）
try {
  const r = require.resolve("@modelcontextprotocol/sdk/server/mcp.js");
  console.log("MCP SDK module =", r);
} catch {}

import express from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const PORT = Number(process.env.PORT || 8080);
const UI_API = process.env.UI_API || "http://127.0.0.1:5000";

const app = express();
app.use(express.json());
app.use((req,res,next)=>{ console.log(req.method, req.url); next(); });

const server = new McpServer({ name: "mcp-bridge-shopify", version: "0.2.7" });

// 最小JSON Schema（説明・$schemaは付けない）
const searchInputSchema = Object.freeze({
  type: "object",
  properties: { query: { type: "string" } },
  required: ["query"],
  additionalProperties: false
});
console.log("SCHEMA:", JSON.stringify(searchInputSchema));

const asText = (data) => ({ content: [{ type: "text", text: JSON.stringify(data, null, 2) }] });

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// 在庫>0のみ検索。空や失敗時はTOP10フォールバック。
server.registerTool(
  "shopify.search_in_stock",
  {
    title: "在庫あり検索",
    description: "例: 「デイトナ」や「Ref.126500」。空なら販売中在庫TOP10。",
    inputSchema: JSON.parse('{"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":false}')
  },
  async (args) => {
    const q = (args?.query ?? "").toString().trim();
    try {
      if (q) {
        const data = await fetchJson(`${UI_API}/api/search?q=${encodeURIComponent(q)}`);
        if (Array.isArray(data) && data.length > 0) return asText(data);
      }
    } catch (e) { console.error("primary search failed:", e); }
    try {
      const data = await fetchJson(`${UI_API}/api/search?fallback=1&limit=10`);
      return asText(data);
    } catch (e) { console.error("fallback failed:", e); return asText({ error:"search_failed", reason:String(e) }); }
  }
);

app.post("/mcp", async (req, res) => {
  const transport = new StreamableHTTPServerTransport({ enableJsonResponse: true });
  res.on("close", () => transport.close());
  await server.connect(transport);
  await transport.handleRequest(req, res, req.body);
});

app.get("/healthz", (_, res) => res.status(200).send("ok"));
app.listen(PORT, "0.0.0.0", () => console.log(`MCP bridge on :${PORT}/mcp`));
process.on("unhandledRejection", e => console.error("UnhandledRejection", e));
