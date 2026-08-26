import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { registerAppResource, registerAppTool, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const WIDGET_URI = "ui://sku-decision/v1.html";
const readParts = (dir,prefix,ext,count) => Array.from({length:count},(_,i)=>readFileSync(new URL(`./${dir}/${prefix}${i+1}.${ext}`,import.meta.url),"utf8")).join("");
const widgetHtml = readParts("widget","part","html",3);
const skus = JSON.parse(gunzipSync(Buffer.from(readParts("data","part","b64",3),"base64")).toString("utf8"));

function createSkuServer(){
  const server=new McpServer({name:"sku-decision-widget",version:"0.1.0"});
  registerAppResource(server,"sku-decision-widget",WIDGET_URI,{},async()=>({contents:[{uri:WIDGET_URI,mimeType:RESOURCE_MIME_TYPE,text:widgetHtml,_meta:{ui:{prefersBorder:true},"openai/widgetDescription":"31 SKU interactive decision dashboard with dropdown and sorting."}}]}));
  registerAppTool(server,"render_sku_decision_dashboard",{title:"Render SKU decision dashboard",description:"Use this when the user wants the 31-SKU interactive selection decision dashboard.",inputSchema:{},annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:false},_meta:{ui:{resourceUri:WIDGET_URI},"openai/toolInvocation/invoking":"正在载入SKU决策卡…","openai/toolInvocation/invoked":"SKU决策卡已载入"}},async()=>({structuredContent:{version:"31-sku-golden-v1",total:skus.length,skus},content:[{type:"text",text:`已载入 ${skus.length} 个SKU的交互式决策卡。`}]}));
  return server;
}

const port=Number(process.env.PORT??8787);
const httpServer=createServer(async(req,res)=>{
  if(!req.url){res.writeHead(400).end("Missing URL");return;}
  const url=new URL(req.url,`http://${req.headers.host??"localhost"}`);
  if(req.method==="GET"&&url.pathname==="/"){res.writeHead(200,{"content-type":"application/json; charset=utf-8"}).end(JSON.stringify({ok:true,name:"SKU Decision MCP",skuCount:skus.length,mcp:"/mcp"}));return;}
  if(req.method==="OPTIONS"&&url.pathname==="/mcp"){res.writeHead(204,{"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"POST, GET, DELETE, OPTIONS","Access-Control-Allow-Headers":"content-type, mcp-session-id","Access-Control-Expose-Headers":"Mcp-Session-Id"});res.end();return;}
  if(url.pathname==="/mcp"&&["POST","GET","DELETE"].includes(req.method??"")){
    res.setHeader("Access-Control-Allow-Origin","*");res.setHeader("Access-Control-Expose-Headers","Mcp-Session-Id");
    const server=createSkuServer(); const transport=new StreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true});
    res.on("close",()=>{transport.close();server.close();});
    try{await server.connect(transport);await transport.handleRequest(req,res);}catch(e){console.error(e);if(!res.headersSent)res.writeHead(500).end("Internal server error");}
    return;
  }
  res.writeHead(404).end("Not Found");
});
httpServer.listen(port,()=>console.log(`SKU MCP server listening on http://localhost:${port}/mcp; ${skus.length} SKUs loaded`));
