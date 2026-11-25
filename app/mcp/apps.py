"""MCP Apps (io.modelcontextprotocol/ui) sandboxed interactive views.

All views are self-contained HTML/CSS/JS with zero external network calls
(strict CSP: no connect/resource domains). Hosts that do not implement MCP Apps
ignore `_meta.ui` and render standard text/structuredContent responses.
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
body{margin:0;padding:14px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;font-size:13px;line-height:1.45}
h1{font-size:15px;margin:0 0 8px;display:flex;align-items:center;justify-content:space-between;gap:8px}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;background:#1e293b;color:#38bdf8;border:1px solid #334155}
.badge.warn{color:#fbbf24;border-color:#78350f;background:#451a03}
.banner{padding:8px 10px;border-radius:8px;background:#1e293b;border-left:3px solid #f59e0b;margin:8px 0;font-size:12px;color:#fde68a}
.grid{display:grid;gap:8px;margin-top:10px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:10px 12px}
.card-title{font-weight:600;color:#f8fafc;margin:0 0 4px}
.meta{color:#94a3b8;font-size:12px}
.bar-track{height:8px;border-radius:999px;background:#0f172a;overflow:hidden;margin-top:6px}
.bar-fill{height:100%;background:linear-gradient(90deg,#0ea5e9,#22d3ee);border-radius:999px}
a{color:#38bdf8;text-decoration:none}
a:hover{text-decoration:underline}
svg{width:100%;height:220px;background:#0b1220;border:1px solid #334155;border-radius:10px;display:block;margin-bottom:10px}
.empty{color:#94a3b8;padding:16px;text-align:center}
"""

_BRIDGE_JS = """
function extractEnvelope(msg){
  if(!msg||typeof msg!=="object")return null;
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
window.addEventListener("message",ev=>{const env=extractEnvelope(ev.data);if(env)render(env);});
try{window.parent.postMessage({jsonrpc:"2.0",method:"ui/notifications/initialized",params:{}},"*");}catch(_){}
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
    const circles=pts.map((p,i)=>`<g><circle cx="${sx(p.lon).toFixed(1)}" cy="${sy(p.lat).toFixed(1)}" r="7" fill="#0ea5e9" stroke="#f8fafc" stroke-width="1.5"><title>${esc(p.name||p.title||"#"+(i+1))}</title></circle><text x="${(sx(p.lon)+10).toFixed(1)}" y="${(sy(p.lat)+4).toFixed(1)}" fill="#cbd5e1" font-size="11">${esc(String(p.name||"").slice(0,22))}</text></g>`).join("");
    svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Konum haritası">${circles}</svg>`;
  }
  const cards=rows.map(r=>{
    const link=safeHref(r.maps_url||r.maps_search_url);
    const dist=r.distance_m!=null?` · ${esc(r.distance_m)} m`:"";
    const sub=[r.district,r.address,r.phone].filter(Boolean).map(esc).join(" · ");
    return `<div class="card"><div class="card-title">${esc(r.name||r.title||"Kayıt")}${dist}</div>`
      +`${sub?`<div class="meta">${sub}</div>`:""}`
      +`${link?`<div class="meta"><a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Haritada aç ↗</a></div>`:""}</div>`;
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
    const stops=(opt.events||[]).map(ev=>{
      const url=safeHref(ev.ticket_url||(Array.isArray(ev.ticket_links)&&ev.ticket_links[0]&&ev.ticket_links[0].url));
      const about=ev.about&&ev.about.text?`<div class="meta">${esc(ev.about.text)}</div>`:"";
      return `<div class="card"><div class="card-title">${esc(ev.start_at||ev.event_date||"")} · ${esc(ev.title||"Etkinlik")}</div>`
        +`<div class="meta">${esc((ev.venue&&ev.venue.name)||"")}${url?` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Bilet ↗</a>`:""}</div>${about}</div>`;
    }).join("");
    return `<div class="card"><div class="card-title">Seçenek ${idx+1}</div><div class="grid">${stops}</div></div>`;
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
