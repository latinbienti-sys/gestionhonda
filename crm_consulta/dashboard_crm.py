# -*- coding: utf-8 -*-
"""
DASHBOARD INTERACTIVO CRM HONDA MÉRIDA (latinbienmotors.com) - SOLO LECTURA / CONSULTA.

Genera crm_dashboard.html: un panel interactivo con graficas (Chart.js CDN) que muestra
cuantos clientes hay por entidad financiera (ARCA, PIVCA, BANESCO, PROVINCIAL) y
cuantos han sido FACTURADOS y APROBADOS, con tabla filtrable en vivo.
"""
import html
import json
import os
import re
import sys
import urllib.request
import http.cookiejar
from datetime import datetime

BASE = os.environ.get("ODOO_BASE", "https://latinbienmotors.com")
DB = os.environ.get("ODOO_DB", "latinbien")
USER = os.environ.get("ODOO_USER", "")
PWD = os.environ.get("ODOO_PASSWORD", "")

FIN_TAGS_PRIORITY = [
    ("ARCA", "ARCA", "#213C83"),
    ("PIVCA", "PIVCA", "#7c3aed"),
    ("BANESCO", "CREDITO BANESCO", "#0a7d2c"),
    ("PROVINCIAL", "CREDITO BANCO PROVINCIAL", "#b45309"),
]

# Etiquetas de "liquidado" (credito totalmente pagado) por entidad
LIQUID_TAGS = [
    ("ARCA", "liquidado arca", "#213C83"),
    ("PIVCA", "liquidado pivca", "#7c3aed"),
    ("BANESCO", "liquidado banesco", "#0a7d2c"),
    ("PROVINCIAL", "liquidado provincial", "#b45309"),
]

STAGE_STATUS = {
    "Facturado Credito": "FACTURADO",
    "Facturado Contado": "FACTURADO",
    "Credito Aprobado": "APROBADO",
    "Gestion de Credito": "GESTION",
    "Asesoria": "GESTION",
    "Seguimiento": "GESTION",
    "Contacto": "GESTION",
    "Prospecto": "GESTION",
    "Test Drive Agendado": "GESTION",
    "Test Drive Realizado": "GESTION",
}

LEAD_FIELDS = [
    "id", "name", "partner_id", "contact_name", "email_from", "x_phone2",
    "stage_id", "tag_ids", "user_id", "team_id",
    "description",
    "x_montototal", "x_monto_aprobado", "x_plazo", "x_fecha_aprobacion",
    "x_product_interes", "x_bancos_cuenta", "x_contenido_rif",
    "date_open", "date_last_stage_update",
]

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def rpc(url, method, params):
    payload = {"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    resp = opener.open(req, timeout=90)
    return json.loads(resp.read().decode())


def call_kw(model, method, args=None, kwargs=None):
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}
    res = rpc(BASE + "/web/dataset/call_kw", model,
              {"model": model, "method": method, "args": args, "kwargs": kwargs})
    if "error" in res:
        raise RuntimeError(json.dumps(res["error"], ensure_ascii=False)[:2000])
    return res["result"]


def clean_html(s):
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    lines = [l.strip() for l in s.splitlines()]
    return "\n".join(l for l in lines if l)


def fmt_money(v):
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def main():
    if not USER or not PWD:
        sys.exit("ERROR: Faltan ODOO_USER / ODOO_PASSWORD")

    auth = rpc(BASE + "/web/session/authenticate", "call",
               {"db": DB, "login": USER, "password": PWD})
    r = auth.get("result", {})
    if not r.get("uid"):
        sys.exit("Fallo de autenticacion en Odoo")

    tags = call_kw("crm.tag", "search_read", [[]], {"fields": ["id", "name"]})
    tag_by_id = {t["id"]: t["name"] for t in tags}
    stages = call_kw("crm.stage", "search_read", [[]], {"fields": ["id", "name", "sequence"]})
    stage_by_id = {s["id"]: s["name"] for s in stages}

    # Ids de etiquetas financieras (incluye las de "LIQUIDADO")
    fin_tag_ids = []
    for label, tag_name, color in FIN_TAGS_PRIORITY:
        tid = next((t["id"] for t in tags if t["name"].strip().upper() == tag_name.strip().upper()), None)
        if tid:
            fin_tag_ids.append(tid)
    for label, tag_name, color in LIQUID_TAGS:
        tid = next((t["id"] for t in tags if t["name"].strip().upper() == tag_name.strip().upper()), None)
        if tid:
            fin_tag_ids.append(tid)

    lead_ids = call_kw("crm.lead", "search", [[["tag_ids", "in", fin_tag_ids]]])
    leads = []
    for i in range(0, len(lead_ids), 100):
        batch = lead_ids[i:i + 100]
        leads.extend(call_kw("crm.lead", "read", [batch, LEAD_FIELDS]))

    # ---- Modelo del vehiculo desde sale.order.line (ordenes vinculadas a las oportunidades) ----
    # 1) Ordenes de venta asociadas a las oportunidades
    orders = call_kw("sale.order", "search_read",
                     [[["opportunity_id", "in", lead_ids]]],
                     {"fields": ["id", "opportunity_id"], "limit": 2000})
    opp_to_order = {}   # lead_id -> list(order_id)
    for o in orders:
        opp_id = o.get("opportunity_id")
        if isinstance(opp_id, (list, tuple)) and opp_id:
            opp_to_order.setdefault(opp_id[0], []).append(o["id"])
    # 2) Lineas de esas ordenes -> nombre de producto vehiculo
    order_ids = [oid for lst in opp_to_order.values() for oid in lst]
    modelo_by_opp = {}
    modelo_by_opp_exact = {}
    if order_ids:
        for i in range(0, len(order_ids), 100):
            blines = call_kw("sale.order.line", "search_read",
                             [[["order_id", "in", order_ids[i:i + 100]]]],
                             {"fields": ["order_id", "name"], "limit": 4000})
            for ln in blines:
                oid = ln["order_id"][0] if isinstance(ln.get("order_id"), (list, tuple)) else None
                if not oid:
                    continue
                nm = ln.get("name") or ""
                # Parece vehiculo el producto cuyo nombre contiene "[SKU] HONDA ... 2026"
                if re.search(r"\[[^\]]+\]\s*HONDA", nm, re.IGNORECASE):
                    opp_for = next((opp for opp, olst in opp_to_order.items() if oid in olst), None)
                    if opp_for:
                        modelo_by_opp_exact.setdefault(opp_for, set()).add(nm.strip())

    # Normalizar etapas sin acentos
    stage_by_id_clean = {}
    for sid, sname in stage_by_id.items():
        norm = sname.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        stage_by_id_clean[sid] = norm

    # ---- HISTORICO: todas las solicitudes del CRM (sin filtrar por etiqueta) ----
    all_ids = call_kw("crm.lead", "search", [[]])
    hist_fields = ["id", "create_date", "date_open", "stage_id", "tag_ids", "x_montototal", "x_monto_aprobado", "x_plazo", "x_fecha_aprobacion"]
    all_leads = []
    for i in range(0, len(all_ids), 200):
        batch = all_ids[i:i + 200]
        all_leads.extend(call_kw("crm.lead", "read", [batch, hist_fields]))
    hist_data = []
    for l in all_leads:
        sid = l["stage_id"][0] if isinstance(l.get("stage_id"), (list, tuple)) else None
        etapa = stage_by_id_clean.get(sid, "")
        estado = "OTROS"
        for k, v in STAGE_STATUS.items():
            if etapa == k:
                estado = v
                break
        if "facturado" in etapa.lower():
            estado = "FACTURADO"
        elif "aprobado" in etapa.lower():
            estado = "APROBADO"
        lid_tags2 = l.get("tag_ids") or []
        tids2 = [x[0] if isinstance(x, (list, tuple)) else x for x in lid_tags2]
        entidades_hist = []
        liquidado_hist = False
        for label, tag_name, color in FIN_TAGS_PRIORITY:
            tid = next((t["id"] for t in tags if t["name"].strip().upper() == tag_name.strip().upper()), None)
            if tid and tid in tids2:
                entidades_hist.append(label)
        for label, tag_name, color in LIQUID_TAGS:
            tid = next((t["id"] for t in tags if t["name"].strip().upper() == tag_name.strip().upper()), None)
            if tid and tid in tids2:
                liquidado_hist = True
                if label not in entidades_hist:
                    entidades_hist.append(label)
        if liquidado_hist or "liquid" in etapa.lower():
            estado = "LIQUIDADO"
        # Montos (pueden venir como False/None -> 0)
        montot = l.get("x_montototal") or 0
        montoap = l.get("x_monto_aprobado") or 0
        hist_data.append({
            "id": l["id"],
            "create": (l.get("create_date") or "")[:10],
            "open": (l.get("date_open") or "")[:10],
            "mes": (l.get("create_date") or "")[:7],
            "etapa": etapa,
            "estado": estado,
            "entidades": entidades_hist,
            "montototal": float(montot),
            "montoaprobado": float(montoap),
            "plazo": l.get("x_plazo") or "",
            "fechaaprob": (l.get("x_fecha_aprobacion") or "")[:10],
        })

    data = []
    for l in leads:
        lid_tags = l.get("tag_ids") or []
        tids = [x[0] if isinstance(x, (list, tuple)) else x for x in lid_tags]

        # Que entidades financieras tiene este lead (puede tener varias)
        entidades = []
        for label, tag_name, color in FIN_TAGS_PRIORITY:
            tid = next((t["id"] for t in tags if t["name"].strip().upper() == tag_name.strip().upper()), None)
            if tid and tid in tids:
                entidades.append({"label": label, "color": color, "tag": tag_name})

        # Detectar etiquetas de "LIQUIDADO" (credito totalmente pagado)
        liquidado = False
        for label, tag_name, color in LIQUID_TAGS:
            tid = next((t["id"] for t in tags if t["name"].strip().upper() == tag_name.strip().upper()), None)
            if tid and tid in tids:
                liquidado = True
                if not any(e["label"] == label for e in entidades):
                    entidades.append({"label": label, "color": color, "tag": tag_name})
        if not entidades:
            continue

        # Etapa y estado (FACTURADO / APROBADO / GESTION / LIQUIDADO)
        sid = l["stage_id"][0] if isinstance(l.get("stage_id"), (list, tuple)) else None
        etapa = stage_by_id_clean.get(sid, "")
        if liquidado or "liquid" in etapa.lower():
            estado = "LIQUIDADO"
        else:
            estado = "OTROS"
            for k, v in STAGE_STATUS.items():
                if etapa == k:
                    estado = v
                    break
            if "facturado" in etapa.lower():
                estado = "FACTURADO"
            elif "aprobado" in etapa.lower():
                estado = "APROBADO"

        cliente = l["partner_id"][1] if isinstance(l.get("partner_id"), (list, tuple)) else (l.get("contact_name") or l.get("name") or "")
        if cliente.startswith("Oportunidad de "):
            cliente = cliente[len("Oportunidad de "):]
        if isinstance(cliente, str):
            cliente = cliente.strip()

        oportunidad = l.get("name") or ""
        modelo = (l.get("x_product_interes") or "").strip()
        # Extraer modelo del nombre de la oportunidad si no hay campo manual
        if not modelo and isinstance(oportunidad, str):
            m = re.search(r"\b(HR[- ]?V|CR[- ]?V|CIVIC|CITY|BR[- ]?V|WR[- ]?V|ACCORD|FIT|PILOT|ODYSSEY|CROSSTOUR|CRF|XRE|CB\s?\d+|CG\s?\d+)[^,]*", oportunidad, re.IGNORECASE)
            if m:
                modelo = m.group(0).strip()
        # Modelo exacto desde las lineas de la orden de venta (nombre de producto "[SKU] HONDA ...")
        if not modelo:
            names = modelo_by_opp_exact.get(l["id"], set())
            if names:
                raw = sorted(names)[0]
                # Remover prefijo [SKU] y color final "(...)":  "[HRV...] HONDA HR-V 1.5L A/T LX 2026 (Blanco)" -> "HONDA HR-V 1.5L A/T LX 2026"
                raw_clean = re.sub(r"^\[[^\]]*\]\s*", "", raw)
                modelo = re.sub(r"\s*\([^)]*\)\s*$", "", raw_clean).strip()

        asesor = l["user_id"][1] if isinstance(l.get("user_id"), (list, tuple)) else ""
        otras_tags = [tag_by_id.get(t, "") for t in tids]
        otras_tags = [t for t in otras_tags if t and t not in [e["tag"] for e in entidades]]

        data.append({
            "id": l["id"],
            "nombre": cliente,
            "oportunidad": oportunidad,
            "modelo": modelo,
            "etapa": etapa,
            "etapa_original": l["stage_id"][1] if isinstance(l.get("stage_id"), (list, tuple)) else etapa,
            "estado": estado,
            "entidades": [e["label"] for e in entidades],
            "entidad_principal": entidades[0]["label"],
            "entidad_colores": {e["label"]: e["color"] for e in entidades},
            "fecha_aprobacion": (l.get("x_fecha_aprobacion") or ""),
            "plazo": str(l.get("x_plazo") or ""),
            "monto_total": fmt_money(l.get("x_montototal")),
            "monto_aprobado": fmt_money(l.get("x_monto_aprobado")),
            "asesor": asesor,
            "telefono": l.get("x_phone2") or "",
            "email": l.get("email_from") or "",
            "bancos": l.get("x_bancos_cuenta") or "",
            "ci_rif": l.get("x_contenido_rif") or "",
            "notas": clean_html(l.get("description"))[:1200],
            "tags_extra": ", ".join(otras_tags),
        })

    # ---- Build HTML ----
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    json_data = json.dumps(data, ensure_ascii=False)
    json_hist = json.dumps(hist_data, ensure_ascii=False)

    html_doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard CRM Financiamiento - Honda Mérida</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; background:#eef1f6; color:#1a1a1a; }}
  .topbar {{ background:linear-gradient(135deg,#213C83,#15295e); color:#fff; padding:18px 24px; }}
  .topbar h1 {{ margin:0; font-size:22px; }}
  .topbar p {{ margin:4px 0 0; color:#cbd5e8; font-size:13px; }}
  .wrap {{ max-width:1280px; margin:20px auto; padding:0 18px; }}

  .kpis {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:20px; }}
  .kpi {{ flex:1; min-width:150px; background:#fff; border-radius:12px; padding:16px 18px; box-shadow:0 2px 10px rgba(0,0,0,.06); position:relative; overflow:hidden; }}
  .kpi .bar {{ position:absolute; left:0; top:0; bottom:0; width:5px; }}
  .kpi b {{ font-size:28px; display:block; letter-spacing:-.5px; }}
  .kpi span {{ color:#666; font-size:12.5px; }}
  .kpi small {{ color:#999; font-size:11px; display:block; margin-top:4px; }}

  .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:18px; margin-bottom:20px; }}
  .grid .full {{ grid-column: 1 / -1; }}
  @media (max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}

  .card {{ background:#fff; border-radius:12px; padding:16px 18px; box-shadow:0 3px 12px rgba(0,0,0,.06); }}
  .card h3 {{ margin:0 0 10px; font-size:15px; color:#213C83; }}
  .chart-box {{ position:relative; height:300px; }}

  .filters {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:14px; }}
  .chip {{ border:2px solid #d7deee; background:#fff; color:#213C83; border-radius:30px; padding:8px 16px; font-weight:700; font-size:13.5px; cursor:pointer; transition:all .15s; }}
  .chip.active {{ background:#213C83; color:#fff; border-color:#213C83; }}
  .chip.ent {{ background:#fff; }}
  .chip.ent.active {{ color:#fff; }}
  select, input[type=text] {{ padding:9px 12px; border:1px solid #ccd2e0; border-radius:8px; font-size:14px; font-family:inherit; }}
  .search {{ flex:1; min-width:200px; }}

  .table-wrap {{ overflow-x:auto; border-radius:10px; border:1px solid #e5e9f2; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#f0f3fa; text-align:left; padding:9px 10px; font-size:11.5px; text-transform:uppercase; letter-spacing:.4px; color:#213C83; position:sticky; top:0; }}
  td {{ padding:9px 10px; border-bottom:1px solid #eef1f8; vertical-align:top; }}
  tr:hover td {{ background:#fafcff; }}
  .num {{ text-align:right; white-space:nowrap; }}
  .tag-pill {{ display:inline-block; border-radius:20px; padding:2px 10px; font-size:11px; font-weight:700; color:#fff; margin-right:4px; }}
  .estado {{ display:inline-block; border-radius:20px; padding:3px 10px; font-size:11px; font-weight:700; }}
  .est.FACTURADO {{ background:#d1fae5; color:#065f46; }}
  .est.APROBADO {{ background:#ede9fe; color:#5b21b6; }}
  .est.GESTION {{ background:#fef9c3; color:#854d0e; }}
  .est.OTROS {{ background:#f3f4f6; color:#374151; }}
  .est.LIQUIDADO {{ background:#cffafe; color:#0e7490; }}
  .foot {{ text-align:center; color:#999; font-size:12px; padding:18px; }}
  .count-line {{ font-size:13px; color:#666; margin-bottom:8px; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>🚗 Dashboard Financiamiento — Honda Mérida</h1>
</div>

<div class="wrap">
  <div class="kpis" id="kpis"></div>

  <div class="grid">
    <div class="card">
      <h3>📊 Clientes por Entidad Financiera</h3>
      <div class="chart-box"><canvas id="chartEntidades"></canvas></div>
    </div>
    <div class="card">
      <h3>🥧 Distribución de Entidades</h3>
      <div class="chart-box"><canvas id="chartDonut"></canvas></div>
    </div>
    <div class="card">
      <h3>💰 Montos Aprobados por Entidad</h3>
      <div class="chart-box"><canvas id="chartMontos"></canvas></div>
    </div>
    <div class="card">
      <h3>✔️ Estado del Proceso por Entidad (Facturado · Aprobado · En Gestión · Liquidado)</h3>
      <div class="chart-box"><canvas id="chartEstado"></canvas></div>
    </div>
  </div>

  <div class="card full">
    <h3>📈 Histórico de Solicitudes</h3>
    <div class="filters" style="margin-top:4px;">
      <span class="chip hist-chip active" data-vista="solicitadas">Solicitadas</span>
      <span class="chip hist-chip" data-vista="nuevas">Nuevas (mes actual)</span>
      <span class="chip hist-chip" data-vista="procesadas">Procesadas</span>
      <span class="chip hist-chip" data-vista="montos">Montos (Sol. vs Aprob.)</span>
      <span class="chip hist-chip" data-vista="tendencia">Tendencia</span>
    </div>
    <div class="filters" style="margin-top:4px;">
      <button type="button" class="chip" id="btnHistOrder" title="Alternar orden ascendente/descendente">
        Orden: <span id="histOrderLabel">Asc</span>
      </button>
    </div>
    <div class="chart-box" style="height:320px;"><canvas id="chartHist"></canvas></div>
    <div class="count-line" id="histCountLine" style="margin-top:8px;"></div>
  </div>

  <div class="card full">
    <h3>👥 Relación de Clientes</h3>
    <div class="filters">
      <span class="chip ent active" data-ent="ALL" style="border-color:#213C83;">Todas</span>
      <span class="chip ent" data-ent="ARCA" style="border-color:#213C83;">ARCA</span>
      <span class="chip ent" data-ent="PIVCA" style="border-color:#7c3aed;">PIVCA</span>
      <span class="chip ent" data-ent="BANESCO" style="border-color:#0a7d2c;">BANESCO</span>
      <span class="chip ent" data-ent="PROVINCIAL" style="border-color:#b45309;">PROVINCIAL</span>
      <select id="fEstado">
        <option value="ALL">Estado: Todos</option>
        <option value="FACTURADO">Facturados</option>
        <option value="APROBADO">Aprobados</option>
        <option value="GESTION">En Gestión / Crédito</option>
        <option value="LIQUIDADO">Liquidados</option>
      </select>
      <input type="text" id="fBuscar" class="search" placeholder="🔍 Buscar por nombre, modelo, asesor...">
      <span class="chip" id="fmtCsv">⬇️ CSV</span>
    </div>
    <div class="count-line" id="countLine"></div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Entidad</th><th>Cliente</th><th>Oportunidad / Modelo</th><th>Etapa</th>
          <th>Estado</th><th>Monto Total</th><th>Monto Aprobado</th><th>Plazo</th>
          <th>Fecha Aprob.</th><th>Asesor</th><th>Notas internas</th>
        </tr></thead>
        <tbody id="tabla"></tbody>
      </table>
    </div>
  </div>

  <div class="foot">Consulta solo-lectura al CRM de Odoo · latinbienmotors.com · Generado el {now}</div>
</div>

<script>
const DATA = {json_data};
const HIST = {json_hist};
const ENTIDADES = ['ARCA','PIVCA','BANESCO','PROVINCIAL'];
const COLOR_ENT = {{ 'ARCA':'#213C83', 'PIVCA':'#7c3aed', 'BANESCO':'#0a7d2c', 'PROVINCIAL':'#b45309' }};

let fEnt = 'ALL', fEstado = 'ALL', fBuscar = '';
let chartEnt, chartDonut, chartEstado, chartMontos, chartHist;
let histVista = 'solicitadas';

function fmtMoney(v) {{
  return '$' + Number(v||0).toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}});
}}

function filtrado() {{
  const q = fBuscar.toLowerCase();
  return DATA.filter(d => {{
    if (fEnt !== 'ALL' && d.entidad_principal !== fEnt) return false;
    if (fEstado !== 'ALL' && d.estado !== fEstado) return false;
    if (q) {{
      const hay = [d.nombre, d.modelo, d.oportunidad, d.asesor, d.etapa, (d.entidades||[]).join(' ')]
        .join(' ').toLowerCase().includes(q);
      if (!hay) return false;
    }}
    return true;
  }});
}}

function renderKpis() {{
  const all = filtrado();
  const entCounts = {{}};
  ENTIDADES.forEach(e => entCounts[e] = 0);
  all.forEach(d => entCounts[d.entidad_principal]++);
  // ordenar ARCA, PIVCA, BANESCO, PROVINCIAL
  let kpiHtml = '';
  const totalMonto = all.reduce((s,d)=>s+(d.monto_total||0),0);
  const totalAprob = all.reduce((s,d)=>s+(d.monto_aprobado||0),0);
  const aprobadosCount = all.filter(d => ['APROBADO','FACTURADO','LIQUIDADO'].includes(d.estado)).length;
  kpiHtml += `<div class="kpi"><div class="bar" style="background:#213C83"></div><b>${{all.length}}</b><span>Clientes filtrados</span><small>Suma monto total: ${{fmtMoney(totalMonto)}}</small><small>Suma aprobado: ${{fmtMoney(totalAprob)}}</small></div>`;
  kpiHtml += `<div class="kpi"><div class="bar" style="background:#0a7d2c"></div><b>${{aprobadosCount}}</b><span>Clientes Aprobados/Facturados/Liquidados</span><small>Suma monto aprobado: ${{fmtMoney(totalAprob)}}</small><small>Promedio por cliente: ${{fmtMoney(aprobadosCount ? totalAprob/aprobadosCount : 0)}}</small></div>`;
  ENTIDADES.forEach(e => {{
    kpiHtml += `<div class="kpi"><div class="bar" style="background:${{COLOR_ENT[e]}}"></div><b>${{entCounts[e]}}</b><span>${{e}}</span></div>`;
  }});
  document.getElementById('kpis').innerHTML = kpiHtml;
}}

function renderCharts() {{
  const all = filtrado();
  const entCounts = {{}};
  ENTIDADES.forEach(e => entCounts[e] = 0);
  all.forEach(d => entCounts[d.entidad_principal]++);

  const labels = ENTIDADES;
  const vals = ENTIDADES.map(e => entCounts[e] || 0);
  const colors = ENTIDADES.map(e => COLOR_ENT[e]);

  if (chartEnt) chartEnt.destroy();
  chartEnt = new Chart(document.getElementById('chartEntidades'), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ label: 'Clientes', data: vals, backgroundColor: colors, borderRadius: 8 }}] }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }} }} }}
  }});

  if (chartDonut) chartDonut.destroy();
  chartDonut = new Chart(document.getElementById('chartDonut'), {{
    type: 'doughnut',
    data: {{ labels, datasets: [{{ data: vals, backgroundColor: colors, borderWidth: 3, borderColor: '#fff' }}] }},
    options: {{ plugins: {{ legend: {{ position: 'bottom' }} }} }}
  }});

  // Montos aprobados por entidad
  const montosAprob = {{}};
  ENTIDADES.forEach(e => montosAprob[e] = 0);
  all.forEach(d => montosAprob[d.entidad_principal] += (d.monto_aprobado || 0));
  if (chartMontos) chartMontos.destroy();
  chartMontos = new Chart(document.getElementById('chartMontos'), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ label: 'Monto aprobado (USD)', data: ENTIDADES.map(e => Math.round(montosAprob[e])), backgroundColor: colors, borderRadius: 8 }}] }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: (v) => '$' + Number(v).toLocaleString() }} }} }} }}
  }});

  // Estado por entidad
  const estadosPorEnt = {{}};
  all.forEach(d => {{
    const e = d.entidad_principal;
    if (!estadosPorEnt[e]) estadosPorEnt[e] = {{ FACTURADO:0, APROBADO:0, GESTION:0, OTROS:0, LIQUIDADO:0 }};
    estadosPorEnt[e][d.estado]++;
  }});
  const dF = labels.map(e => (estadosPorEnt[e]||{{}}).FACTURADO||0);
  const dA = labels.map(e => (estadosPorEnt[e]||{{}}).APROBADO||0);
  const dG = labels.map(e => (estadosPorEnt[e]||{{}}).GESTION||0);
  const dO = labels.map(e => (estadosPorEnt[e]||{{}}).OTROS||0);
  const dL = labels.map(e => (estadosPorEnt[e]||{{}}).LIQUIDADO||0);
  if (chartEstado) chartEstado.destroy();
  chartEstado = new Chart(document.getElementById('chartEstado'), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{ label: 'Facturados', data: dF, backgroundColor: '#0a7d2c' }},
        {{ label: 'Aprobados', data: dA, backgroundColor: '#7c3aed' }},
        {{ label: 'En Gestión', data: dG, backgroundColor: '#d9b300' }},
        {{ label: 'Liquidados', data: dL, backgroundColor: '#0891b2' }},
        {{ label: 'Otros', data: dO, backgroundColor: '#9ca3af' }},
      ]
    }},
    options: {{ scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, beginAtZero: true, ticks: {{ precision: 0 }} }} }} }}
  }});
}}

// ---- HISTORICO ----
let histOrder = 'asc'; // 'asc' o 'desc'

function renderHist() {{
  // Agrupar por mes (create_date) - contadores y montos
  const porMes = {{}};
  HIST.forEach(h => {{
    if (!h.mes) return;
    if (!porMes[h.mes]) porMes[h.mes] = {{ total: 0, facturado: 0, aprobado: 0, gestion: 0, otros: 0, liquidado: 0, montototal: 0, montoaprobado: 0 }};
    const m = porMes[h.mes];
    m.total++;
    m.montototal += (h.montototal || 0);
    m.montoaprobado += (h.montoaprobado || 0);
    if (h.estado === 'FACTURADO') m.facturado++;
    else if (h.estado === 'APROBADO') m.aprobado++;
    else if (h.estado === 'GESTION') m.gestion++;
    else if (h.estado === 'LIQUIDADO') m.liquidado++;
    else m.otros++;
  }});
  
  // Orden de meses según toggle
  let meses = Object.keys(porMes);
  meses.sort((a, b) => histOrder === 'asc' ? a.localeCompare(b) : b.localeCompare(a));
  
  const nombresMes = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
  const labels = meses.map(m => {{
    const [y, mo] = m.split('-');
    return nombresMes[parseInt(mo,10)-1] + ' ' + y;
  }});
  
  const dTotal = meses.map(m => porMes[m].total);
  const dNuevas = meses.map(m => (m === getCurrentMonth() ? porMes[m].total : 0));
  const dFact = meses.map(m => porMes[m].facturado);
  const dAprob = meses.map(m => porMes[m].aprobado);
  const dGestion = meses.map(m => porMes[m].gestion);
  const dOtros = meses.map(m => porMes[m].otros);
  const dLiquid = meses.map(m => porMes[m].liquidado);
  const dMontoSol = meses.map(m => porMes[m].montototal);
  const dMontoApr = meses.map(m => porMes[m].montoaprobado);
  
  let chartType = 'bar';
  let chartData;
  let yTickCallback = (val) => val;
  let yBeginAtZero = true;
  
  if (histVista === 'montos') {{
    chartType = 'bar';
    chartData = {{
      labels,
      datasets: [
        {{ label: 'Monto Solicitado', data: dMontoSol, backgroundColor: '#213C83', borderRadius: 6 }},
        {{ label: 'Monto Aprobado', data: dMontoApr, backgroundColor: '#0a7d2c', borderRadius: 6 }}
      ]
    }};
    yTickCallback = (val) => '$' + val.toLocaleString('es-VE', {{maximumFractionDigits: 0}});
  }} else if (histVista === 'tendencia') {{
    chartType = 'line';
    chartData = {{
      labels,
      datasets: [
        {{ label: 'Solicitadas', data: dTotal, borderColor: '#213C83', backgroundColor: 'rgba(33,60,131,0.1)', fill: true, tension: 0.3, pointRadius: 4 }},
        {{ label: 'Aprobadas', data: dAprob, borderColor: '#0a7d2c', backgroundColor: 'rgba(10,125,44,0.1)', fill: true, tension: 0.3, pointRadius: 4 }},
        {{ label: 'Facturadas', data: dFact, borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.1)', fill: true, tension: 0.3, pointRadius: 4 }},
        {{ label: 'Liquidadas', data: dLiquid, borderColor: '#0891b2', backgroundColor: 'rgba(8,145,178,0.1)', fill: true, tension: 0.3, pointRadius: 4 }},
      ]
    }};
    yBeginAtZero = true;
  }} else {{
    // Vistas de conteo existentes
    chartData = {{
      labels,
      datasets: {{
        solicitadas: [{{ label: 'Solicitadas', data: dTotal, backgroundColor: '#213C83', borderRadius: 6 }}],
        nuevas: [{{ label: 'Nuevas (mes actual)', data: dNuevas, backgroundColor: '#e11d48', borderRadius: 6 }}],
        procesadas: [
          {{ label: 'Facturadas', data: dFact, backgroundColor: '#0a7d2c' }},
          {{ label: 'Aprobadas', data: dAprob, backgroundColor: '#7c3aed' }},
          {{ label: 'En Gestión', data: dGestion, backgroundColor: '#d9b300' }},
          {{ label: 'Liquidados', data: dLiquid, backgroundColor: '#0891b2' }},
          {{ label: 'Otros', data: dOtros, backgroundColor: '#9ca3af' }},
        ]
      }}[histVista]
    }};
    // stacked for procesadas
    if (histVista === 'procesadas') {{
      chartData.datasets.forEach(ds => ds.borderRadius = 6);
    }}
  }}
  
  if (chartHist) chartHist.destroy();
  
  const isStacked = histVista === 'procesadas';
  chartHist = new Chart(document.getElementById('chartHist'), {{
    type: chartType,
    data: chartData,
    options: {{
      plugins: {{
        legend: {{ position: 'bottom' }},
        tooltip: {{
          callbacks: {{
            label: (ctx) => {{
              if (histVista === 'montos') {{
                return ctx.dataset.label + ': $' + ctx.parsed.y.toLocaleString('es-VE', {{maximumFractionDigits: 2}});
              }}
              return ctx.dataset.label + ': ' + ctx.parsed.y + (histVista === 'tendencia' ? ' solicitudes' : '');
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ stacked: isStacked }},
        y: {{ 
          beginAtZero: yBeginAtZero, 
          stacked: isStacked, 
          ticks: {{ precision: 0, callback: yTickCallback }} 
        }}
      }},
      interaction: histVista === 'tendencia' ? {{ mode: 'index', intersect: false }} : undefined
    }}
  }});
  
  // Resumen financiero
  const totalSolic = HIST.length;
  const totalMontoSol = HIST.reduce((s, h) => s + (h.montototal || 0), 0);
  const totalMontoApr = HIST.reduce((s, h) => s + (h.montoaprobado || 0), 0);
  const totalFact = HIST.filter(h => h.estado === 'FACTURADO').length;
  const totalAprob = HIST.filter(h => h.estado === 'APROBADO').length;
  const totalGestion = HIST.filter(h => h.estado === 'GESTION').length;
  const totalLiquid = HIST.filter(h => h.estado === 'LIQUIDADO').length;
  const mesActual = getCurrentMonth();
  const nuevasMes = totalSolic ? (porMes[mesActual] ? porMes[mesActual].total : 0) : 0;
  const montoSolMes = totalSolic ? (porMes[mesActual] ? porMes[mesActual].montototal : 0) : 0;
  const montoAprMes = totalSolic ? (porMes[mesActual] ? porMes[mesActual].montoaprobado : 0) : 0;
  
  document.getElementById('histCountLine').textContent =
    `📌 Solicitudes: ${{totalSolic}} total · ${{nuevasMes}} este mes · ${{totalAprob + totalFact + totalLiquid}} procesadas · ${{totalFact}} facturadas · ${{totalAprob}} aprobadas · ${{totalLiquid}} liquidadas · ${{totalGestion}} en gestión | ` +
    `💰 Montos: Solicitado total $${{totalMontoSol.toLocaleString('es-VE')}} · Aprobado total $${{totalMontoApr.toLocaleString('es-VE')}} · ` +
    `Este mes: Solicitado $${{montoSolMes.toLocaleString('es-VE')}} · Aprobado $${{montoAprMes.toLocaleString('es-VE')}}`;
}}

function getCurrentMonth() {{
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0');
}}

// Toggle orden ascendente/descendente
document.getElementById('btnHistOrder').addEventListener('click', () => {{
  histOrder = histOrder === 'asc' ? 'desc' : 'asc';
  document.getElementById('histOrderLabel').textContent = histOrder === 'asc' ? 'Asc' : 'Desc';
  renderHist();
}});

function renderTabla() {{
  const rows = filtrado();
  const tb = document.getElementById('tabla');
  document.getElementById('countLine').textContent = `Mostrando ${{rows.length}} de ${{DATA.length}} clientes con etiqueta financiera.`;
  if (rows.length === 0) {{
    tb.innerHTML = '<tr><td colspan="11" style="text-align:center;color:#999;">Sin resultados</td></tr>';
    return;
  }}
  tb.innerHTML = rows.map(d => {{
    const pils = d.entidades.map(e => `<span class="tag-pill" style="background:${{COLOR_ENT[e]}}">${{e}}</span>`).join('');
    const notas = d.notas ? `<div style="max-width:320px;max-height:110px;overflow:auto;font-size:11.5px;color:#555;background:#fbfcff;border:1px solid #eef1f8;border-radius:6px;padding:5px 8px;">${{d.notas.replace(/\\n/g,'<br>')}}</div>` : '<span style="color:#bdbdbd;">—</span>';
    return `<tr>
      <td>${{pils}}</td>
      <td><strong>${{d.nombre}}</strong><div style="color:#888;font-size:11px;">${{d.email || ''}}</div><div style="color:#888;font-size:11px;">${{d.telefono || ''}}</div></td>
      <td><div>${{d.oportunidad || ''}}</div>${{d.modelo ? '<div style="color:#0a7d2c;font-weight:600;font-size:12px;">🚗 '+d.modelo+'</div>':''}}</td>
      <td>${{d.etapa_original || ''}}</td>
      <td><span class="estado est ${{d.estado}}">${{d.estado}}</span></td>
      <td class="num">${{fmtMoney(d.monto_total)}}</td>
      <td class="num"><strong>${{fmtMoney(d.monto_aprobado)}}</strong></td>
      <td>${{d.plazo || ''}}</td>
      <td>${{d.fecha_aprobacion || ''}}</td>
      <td>${{d.asesor || ''}}</td>
      <td>${{notas}}</td>
    </tr>`;
  }}).join('');
}}

function aplicarFiltro() {{
  renderKpis(); renderCharts(); renderHist(); renderTabla();
}}

// Eventos
document.querySelectorAll('.chip.ent').forEach(ch => {{
  ch.addEventListener('click', () => {{
    document.querySelectorAll('.chip.ent').forEach(x => x.classList.remove('active'));
    ch.classList.add('active');
    fEnt = ch.getAttribute('data-ent');
    aplicarFiltro();
  }});
}});
document.querySelectorAll('.chip.hist-chip').forEach(ch => {{
  ch.addEventListener('click', () => {{
    document.querySelectorAll('.chip.hist-chip').forEach(x => x.classList.remove('active'));
    ch.classList.add('active');
    histVista = ch.getAttribute('data-vista');
    renderHist();
  }});
}});
document.getElementById('fEstado').addEventListener('change', e => {{
  fEstado = e.target.value; aplicarFiltro();
}});
document.getElementById('fBuscar').addEventListener('input', e => {{
  fBuscar = e.target.value; aplicarFiltro();
}});

// Exportar CSV filtrado
document.getElementById('fmtCsv').addEventListener('click', () => {{
  const rows = filtrado();
  const enc = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
  const cols = ['Entidad','Cliente','Oportunidad','Modelo','Etapa','Estado','MontoTotal','MontoAprobado','Plazo','FechaAprobacion','Asesor','Email','Telefono','Notas'];
  let csv = cols.join(',') + '\\n';
  rows.forEach(d => {{
    csv += [d.entidades.join(' '), d.nombre, d.oportunidad, d.modelo, d.etapa_original, d.estado,
      d.monto_total, d.monto_aprobado, d.plazo, d.fecha_aprobacion, d.asesor, d.email, d.telefono, d.notas]
      .map(enc).join(',') + '\\n';
  }});
  const blob = new Blob(['\\ufeff'+csv], {{type:'text/csv;charset=utf-8;'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'clientes_financiamiento.csv';
  a.click();
}});

aplicarFiltro();
</script>
</body>
</html>
"""

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm_dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print("Dashboard generado:", out)
    print("Registros:", len(data))


if __name__ == "__main__":
    main()