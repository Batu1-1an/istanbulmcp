"""MCP Apps (io.modelcontextprotocol/ui, SEP-1865 2026-01-26) sandboxed interactive views.

All views are self-contained HTML/CSS/JS with zero external network calls
(strict CSP: no connect/resource domains). Each view implements the full
SEP-1865 lifecycle: ui/initialize -> ui/notifications/initialized,
ui/notifications/tool-result, ui/notifications/host-context-changed,
ui/notifications/size-changed, ui/open-link, and ui/resource-teardown.
Hosts without MCP Apps support ignore `_meta.ui` and render standard text/structuredContent.
"""
from __future__ import annotations

from mcp.server.apps import Apps, ResourceCsp

NEARBY_MAP_URI = "ui://istanbul/nearby-map"
WATER_DASHBOARD_URI = "ui://istanbul/water-dashboard"
EVENTS_PLAN_URI = "ui://istanbul/events-plan"

TOOL_APP_URIS: dict[str, str] = {
    "istanbul_nearby": NEARBY_MAP_URI,
    "istanbul_water_status": WATER_DASHBOARD_URI,
    "istanbul_events_plan": EVENTS_PLAN_URI,
}

_STRICT_CSP = ResourceCsp(connect_domains=[], resource_domains=[])

_BASE_CSS = """
*{box-sizing:border-box}
:root{--bg:#0f172a;--surface:#1e293b;--border:#334155;--text:#e2e8f0;--title:#f8fafc;--muted:#94a3b8;--accent:#38bdf8;--warn-bg:#451a03;--warn-border:#f59e0b;--warn-text:#fde68a;--canvas:#0b1220}
:root[data-theme="light"]{--bg:#f8fafc;--surface:#ffffff;--border:#cbd5e1;--text:#1e293b;--title:#0f172a;--muted:#475569;--accent:#0284c7;--warn-bg:#fffbeb;--warn-border:#d97706;--warn-text:#92400e;--canvas:#f1f5f9}
body{margin:0;padding:14px;font-family:var(--font-sans,system-ui,-apple-system,Segoe UI,Roboto,sans-serif);background:var(--color-background-primary,var(--bg));color:var(--color-text-primary,var(--text));font-size:13px;line-height:1.45}
h1{font-size:15px;margin:0 0 8px;display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--title)}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;background:var(--surface);color:var(--accent);border:1px solid var(--border)}
.badge.warn{color:var(--warn-text);border-color:var(--warn-border);background:var(--warn-bg)}
.banner{padding:8px 10px;border-radius:8px;background:var(--warn-bg);border-left:3px solid var(--warn-border);margin:8px 0;font-size:12px;color:var(--warn-text)}
.grid{display:grid;gap:8px;margin-top:10px}
.card{background:var(--color-background-secondary,var(--surface));border:1px solid var(--color-border-primary,var(--border));border-radius:10px;padding:10px 12px}
.card-title{font-weight:600;color:var(--title);margin:0 0 4px}
.meta{color:var(--color-text-secondary,var(--muted));font-size:12px}
.bar-track{height:8px;border-radius:999px;background:var(--canvas);overflow:hidden;margin-top:6px}
.bar-fill{height:100%;background:linear-gradient(90deg,#0ea5e9,#22d3ee);border-radius:999px}
a{color:var(--accent);text-decoration:none;cursor:pointer}
a:hover{text-decoration:underline}
svg{width:100%;height:220px;background:var(--canvas);border:1px solid var(--border);border-radius:10px;display:block;margin-bottom:10px}
.empty{color:var(--muted);padding:16px;text-align:center}
"""

_BRIDGE_JS = """
const APP_PROTOCOL="2026-01-26";
let rpcSeq=1;
const initId=rpcSeq++;
function postRpc(payload){try{window.parent.postMessage(payload,"*");}catch(_){}}
function applyHostContext(ctx){
  if(!ctx||typeof ctx!=="object")return;
  if(ctx.theme==="light"||ctx.theme==="dark"){document.documentElement.dataset.theme=ctx.theme;}
  const vars=ctx.styles&&ctx.styles.variables;
  if(vars&&typeof vars==="object"){
    for(const [k,v] of Object.entries(vars)){
      if(typeof k==="string"&&k.startsWith("--")&&typeof v==="string"){
        document.documentElement.style.setProperty(k,v);
      }
    }
  }
}
function notifySize(){
  const h=Math.ceil(document.documentElement.scrollHeight||document.body.scrollHeight||0);
  const w=Math.ceil(document.documentElement.scrollWidth||document.body.scrollWidth||0);
  if(h>0){postRpc({jsonrpc:"2.0",method:"ui/notifications/size-changed",params:{width:w,height:h}});}
}
function extractEnvelope(msg){
  if(!msg||typeof msg!=="object")return null;
  if(msg.method==="ui/notifications/tool-result"&&msg.params){
    const p=msg.params;
    if(p.structuredContent)return p.structuredContent;
    if(Array.isArray(p.content)&&p.content[0]&&p.content[0].text){try{return JSON.parse(p.content[0].text);}catch(_){}}
  }
  const p=msg.params||msg.result||msg;
  if(p&&p.structuredContent)return p.structuredContent;
  if(p&&p.result&&p.result.structuredContent)return p.result.structuredContent;
  const c=(p&&p.content)||(p&&p.result&&p.result.content);
  if(Array.isArray(c)&&c[0]&&c[0].text){try{return JSON.parse(c[0].text);}catch(_){}}
  if(msg.summary&&Array.isArray(msg.data))return msg;
  return null;
}
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,s=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[s]));}
function safeHref(u){return typeof u==="string"&&/^https:\\/\\//i.test(u)?u:null;}
function renderMeta(env){
  const st=(env.freshness&&env.freshness.status)||"unknown";
  const w=Array.isArray(env.warnings)&&env.warnings.length?`<div class="banner">${env.warnings.map(esc).join(" · ")}</div>`:"";
  return `<div class="meta">Freshness: <span class="badge ${st==="fresh"?"":"warn"}">${esc(st)}</span></div>${w}`;
}
document.addEventListener("click",ev=>{
  const a=ev.target&&ev.target.closest?ev.target.closest("a[data-external-url]"):null;
  if(!a)return;
  const url=safeHref(a.getAttribute("data-external-url"));
  if(!url)return;
  ev.preventDefault();
  postRpc({jsonrpc:"2.0",id:rpcSeq++,method:"ui/open-link",params:{url}});
});
window.addEventListener("message",ev=>{
  const msg=ev.data;
  if(!msg||typeof msg!=="object")return;
  if(msg.id===initId&&msg.result){
    applyHostContext(msg.result.hostContext);
    postRpc({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}});
    notifySize();
    return;
  }
  if(msg.method==="ui/notifications/host-context-changed"){applyHostContext(msg.params);return;}
  if((msg.method==="ui/resource-teardown"||msg.method==="ping")&&msg.id!=null){
    postRpc({jsonrpc:"2.0",id:msg.id,result:{}});return;
  }
  if(msg.method==="ui/notifications/tool-cancelled"){
    document.getElementById("app").innerHTML=`<div class="empty">İşlem iptal edildi.</div>`;
    notifySize();return;
  }
  const env=extractEnvelope(msg);
  if(env){render(env);notifySize();}
});
if(typeof ResizeObserver!=="undefined"){
  new ResizeObserver(()=>notifySize()).observe(document.body);
}
postRpc({
  jsonrpc:"2.0",
  id:initId,
  method:"ui/initialize",
  params:{
    protocolVersion:APP_PROTOCOL,
    appInfo:{name:"istanbul-mcp-ui",version:"0.10.0"},
    appCapabilities:{availableDisplayModes:["inline"]}
  }
});
"""


def _html_shell(title: str, script: str) -> str:
    return (
        f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>{_BASE_CSS}</style></head>"
        f"<body><div id='app'><div class='empty'>Veri bekleniyor…</div></div>"
        f"<script>{_BRIDGE_JS}\n{script}</script></body></html>"
    )


NEARBY_MAP_HTML = _html_shell(
    "İstanbul Yakın Sonuçlar",
    """
function render(env){
  const rows=Array.isArray(env.data)?env.data:[];
  const pts=rows.filter(r=>typeof r.lat==="number"&&typeof r.lon==="number");
  let svg="";
  if(pts.length){
    const lats=pts.map(p=>p.lat),lons=pts.map(p=>p.lon);
    const minLat=Math.min(...lats)-0.002,maxLat=Math.max(...lats)+0.002;
    const minLon=Math.min(...lons)-0.002,maxLon=Math.max(...lons)+0.002;
    const w=480,h=220,pad=24;
    const sx=lon=>pad+((lon-minLon)/Math.max(maxLon-minLon,0.0001))*(w-2*pad);
    const sy=lat=>h-pad-((lat-minLat)/Math.max(maxLat-minLat,0.0001))*(h-2*pad);
    const circles=pts.map((p,i)=>`<g><circle cx="${sx(p.lon).toFixed(1)}" cy="${sy(p.lat).toFixed(1)}" r="7" fill="#0ea5e9" stroke="#f8fafc" stroke-width="1.5"><title>${esc(p.name||p.title||"#"+(i+1))}</title></circle><text x="${(sx(p.lon)+10).toFixed(1)}" y="${(sy(p.lat)+4).toFixed(1)}" fill="currentColor" font-size="11">${esc(String(p.name||"").slice(0,22))}</text></g>`).join("");
    svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Konum haritası">${circles}</svg>`;
  }
  const cards=rows.map(r=>{
    const link=safeHref(r.maps_url||r.maps_search_url);
    const dist=r.distance_m!=null?` · ${esc(r.distance_m)} m`:"";
    const sub=[r.district,r.address,r.phone].filter(Boolean).map(esc).join(" · ");
    return `<div class="card"><div class="card-title">${esc(r.name||r.title||"Kayıt")}${dist}</div>`
      +`${sub?`<div class="meta">${sub}</div>`:""}`
      +`${link?`<div class="meta"><a href="${esc(link)}" data-external-url="${esc(link)}" target="_blank" rel="noopener noreferrer">Haritada aç ↗</a></div>`:""}</div>`;
  }).join("");
  document.getElementById("app").innerHTML=`<h1><span>${esc(env.summary||"Yakındaki Sonuçlar")}</span><span class="badge">${rows.length}</span></h1>${renderMeta(env)}${svg}<div class="grid">${cards||"<div class='empty'>Kayıt bulunamadı.</div>"}</div>`;
}
""",
)

WATER_DASHBOARD_HTML = _html_shell(
    "İSKİ Su & Baraj Durumu",
    """
function render(env){
  const rows=Array.isArray(env.data)?env.data:[];
  const cards=rows.map(r=>{
    const pct=typeof r.occupancy_percent==="number"?r.occupancy_percent:(typeof r.doluluk_orani==="number"?r.doluluk_orani:null);
    if(pct!=null){
      const clamped=Math.max(0,Math.min(100,pct));
      return `<div class="card"><div class="card-title">${esc(r.dam_name||r.name||"Baraj")} — %${clamped.toFixed(1)}</div><div class="bar-track"><div class="bar-fill" style="width:${clamped.toFixed(1)}%"></div></div></div>`;
    }
    return `<div class="card"><div class="card-title">${esc(r.district||r.neighborhood||"İSKİ Arıza")}</div><div class="meta">${esc(r.description||r.reason||r.status||"")}</div></div>`;
  }).join("");
  document.getElementById("app").innerHTML=`<h1><span>${esc(env.summary||"İSKİ Durumu")}</span><span class="badge">${rows.length}</span></h1>${renderMeta(env)}<div class="grid">${cards||"<div class='empty'>Kayıt yok.</div>"}</div>`;
}
""",
)

EVENTS_PLAN_HTML = _html_shell(
    "İstanbul Günlük Etkinlik Planı",
    """
function render(env){
  const root=(Array.isArray(env.data)&&env.data[0])||{};
  const options=Array.isArray(root.options)?root.options:[];
  const flex=Array.isArray(root.flexible_entries)?root.flexible_entries:[];
  const optHtml=options.map((opt,idx)=>{
    const stops=(opt.performances||opt.events||[]).map(ev=>{
      const url=safeHref(ev.ticket_url||(Array.isArray(ev.ticket_links)&&ev.ticket_links[0]&&ev.ticket_links[0].url));
      const about=ev.about&&ev.about.text?`<div class="meta">${esc(ev.about.text)}</div>`:"";
      return `<div class="card"><div class="card-title">${esc(ev.start_at||ev.event_date||"")} · ${esc(ev.title||"Etkinlik")}</div>`
        +`<div class="meta">${esc((ev.venue&&ev.venue.name)||"")}${url?` · <a href="${esc(url)}" data-external-url="${esc(url)}" target="_blank" rel="noopener noreferrer">Bilet ↗</a>`:""}</div>${about}</div>`;
    }).join("");
    const tot=opt.known_minimum_total_try!=null?` · <span class="badge">${esc(opt.known_minimum_total_try)} ₺</span>`:"";
    return `<div class="card"><div class="card-title">Seçenek ${idx+1}${tot}</div><div class="grid">${stops}</div></div>`;
  }).join("");
  const flexHtml=flex.length?`<div class="card"><div class="card-title">Esnek Giriş Biletleri (saatli plana dahil değil)</div><div class="meta">${flex.map(f=>esc(f.title||"")).join(" · ")}</div></div>`:"";
  document.getElementById("app").innerHTML=`<h1><span>${esc(env.summary||"Etkinlik Planı")}</span><span class="badge">${options.length} seçenek</span></h1>${renderMeta(env)}<div class="grid">${optHtml||"<div class='empty'>Tam plan seçeneği bulunamadı.</div>"}${flexHtml}</div>`;
}
""",
)


def create_istanbul_apps() -> Apps:
    apps = Apps()
    apps.add_html_resource(
        NEARBY_MAP_URI,
        NEARBY_MAP_HTML,
        name="istanbul_nearby_map_ui",
        title="İstanbul Yakın Konum Haritası",
        description="Interactive sandboxed map and list view for istanbul_nearby results.",
        csp=_STRICT_CSP,
        prefers_border=True,
    )
    apps.add_html_resource(
        WATER_DASHBOARD_URI,
        WATER_DASHBOARD_HTML,
        name="istanbul_water_dashboard_ui",
        title="İSKİ Su ve Baraj Paneli",
        description="Interactive sandboxed dashboard for ISKI dam occupancy and active water faults.",
        csp=_STRICT_CSP,
        prefers_border=True,
    )
    apps.add_html_resource(
        EVENTS_PLAN_URI,
        EVENTS_PLAN_HTML,
        name="istanbul_events_plan_ui",
        title="İstanbul Günlük Etkinlik Planı Görünümü",
        description="Interactive sandboxed itinerary view for istanbul_events_plan options.",
        csp=_STRICT_CSP,
        prefers_border=True,
    )
    return apps
