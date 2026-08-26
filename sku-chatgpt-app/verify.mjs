import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const endpoint = new URL(process.env.MCP_URL ?? "http://127.0.0.1:8787/mcp");
const client = new Client({ name: "sku-app-verifier", version: "1.0.0" });
const transport = new StreamableHTTPClientTransport(endpoint);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

try {
  await client.connect(transport);

  const tools = await client.listTools();
  const tool = tools.tools?.find((t) => t.name === "render_sku_decision_dashboard");
  assert(tool, "render_sku_decision_dashboard tool missing");
  assert(
    tool._meta?.ui?.resourceUri === "ui://sku-decision/v1.html" ||
      tool._meta?.["openai/outputTemplate"] === "ui://sku-decision/v1.html",
    "tool is not linked to the expected widget resource"
  );

  const resources = await client.listResources();
  const widget = resources.resources?.find((r) => r.uri === "ui://sku-decision/v1.html");
  assert(widget, "ui://sku-decision/v1.html resource missing");

  const resource = await client.readResource({ uri: "ui://sku-decision/v1.html" });
  const html = resource.contents?.[0]?.text ?? "";
  assert(html.includes("31 SKU 选品决策卡"), "widget title missing");
  assert(html.includes('id="skuSelect"'), "SKU dropdown missing");
  assert(html.includes('data-sort="profit"'), "profit sorting control missing");
  assert(html.includes("ui/notifications/tool-result"), "MCP Apps bridge listener missing");

  const result = await client.callTool({
    name: "render_sku_decision_dashboard",
    arguments: {},
  });
  const sc = result.structuredContent;
  assert(sc?.version === "31-sku-golden-v1", "golden dataset version mismatch");
  assert(sc?.total === 31, `expected 31 SKUs, got ${sc?.total}`);
  assert(Array.isArray(sc?.skus) && sc.skus.length === 31, "SKU payload is not 31 rows");
  assert(sc.skus.every((x) => typeof x.sku === "string" && x.sku.length > 0), "SKU identity missing");

  console.log(JSON.stringify({
    ok: true,
    endpoint: endpoint.toString(),
    tool: tool.name,
    resource: widget.uri,
    htmlBytes: Buffer.byteLength(html, "utf8"),
    skuCount: sc.skus.length,
    firstSku: sc.skus[0].sku,
  }));
} finally {
  await client.close().catch(() => {});
}
