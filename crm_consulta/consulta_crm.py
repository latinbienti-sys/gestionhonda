# -*- coding: utf-8 -*-
"""
CONSULTA CRM HONDA MÉRIDA (latinbienmotors.com) - MODO SOLO LECTURA / CONSULTA.

Genera la relacion de clientes/oportunidades que poseen etiquetas financieras
(ARCA, PIVCA, CREDITO BANESCO, CREDITO BANCO PROVINCIAL) y exporta:

  - relacion_clientes_crm.csv  (export plano)
  - relacion_clientes_crm.html (reporte visual agrupado por etiqueta)

Campos mostrados:
  - Etiqueta financiera (varias por cliente si aplica)
  - Nombre del cliente
  - Oportunidad (nombre en CRM) con modelo del vehiculo
  - Etapa del pipeline
  - Notas internas (description, texto limpio)
  - Info adicional: Monto Total, Monto Aprobado, Plazo, Fecha de Aprobacion
"""
import csv
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

LEAD_FIELDS = [
    "id", "name", "partner_id", "contact_name", "email_from", "x_phone2",
    "stage_id", "tag_ids", "user_id", "team_id",
    "description",
    "x_montototal", "x_monto_aprobado", "x_plazo", "x_fecha_aprobacion",
    "x_product_interes", "x_bancos_cuenta", "x_contenido_rif",
    "date_open", "date_last_stage_update", "expected_revenue",
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
        v = float(v or 0)
        return "${:,.2f}".format(v)
    except (TypeError, ValueError):
        return ""


def fmt_date(d):
    if not d:
        return ""
    return str(d)[:10]


def main():
    if not USER or not PWD:
        sys.exit("ERROR: Faltan ODOO_USER / ODOO_PASSWORD")

    auth = rpc(BASE + "/web/session/authenticate", "call",
               {"db": DB, "login": USER, "password": PWD})
    r = auth.get("result", {})
    if not r.get("uid"):
        sys.exit("Fallo de autenticacion en Odoo")
    print("Autenticado como:", r.get("name"))

    # ---- Referencias: tags y stages ----
    tags = call_kw("crm.tag", "search_read", [[]], {"fields": ["id", "name"]})
    tag_by_id = {t["id"]: t["name"] for t in tags}

    stages = call_kw("crm.stage", "search_read", [[]], {"fields": ["id", "name", "sequence"]})
    stage_by_id = {s["id"]: s["name"] for s in stages}

    # Etiquetas financieras objetivo
    fin_tag_ids = []
    for _, tag_name, _color in FIN_TAGS_PRIORITY:
        tid = None
        for t in tags:
            if t["name"].strip().upper() == tag_name.strip().upper():
                tid = t["id"]
                break
        if tid:
            fin_tag_ids.append(tid)
        else:
            print("AVISO: no se encontro etiqueta", tag_name)

    # ---- Buscar leads con cualquier etiqueta financiera ----
    lead_ids = call_kw("crm.lead", "search", [[["tag_ids", "in", fin_tag_ids]]])
    print("Leads con etiquetas financieras:", len(lead_ids))

    leads = []
    for i in range(0, len(lead_ids), 100):
        batch = lead_ids[i:i + 100]
        recs = call_kw("crm.lead", "read", [batch, LEAD_FIELDS])
        leads.extend(recs)

    rows = []
    for l in leads:
        lid_tags = l.get("tag_ids") or []
        # Determinar etiqueta financiera prioritaria para agrupar
        matched = []
        # buscar el id de la etiqueta en la lista
        for label, tag_name, color in FIN_TAGS_PRIORITY:
            tid = None
            for t in tags:
                if t["name"].strip().upper() == tag_name.strip().upper():
                    tid = t["id"]
                    break
            if tid and (tid in [x[0] if isinstance(x, (list, tuple)) else x for x in lid_tags]):
                matched.append((label, tag_name, color))
        if not matched:
            continue
        # etiqueta prioritaria (por orden de la lista)
        matched.sort(key=lambda m: [m[1] for m in FIN_TAGS_PRIORITY].index(m[1]))
        primario = matched[0]
        cliente = ""
        if l.get("partner_id") and isinstance(l.get("partner_id"), (list, tuple)):
            cliente = l["partner_id"][1]
        elif l.get("contact_name"):
            cliente = l["contact_name"]
        elif l.get("name"):
            cliente = l["name"]
        stage = ""
        if l.get("stage_id") and isinstance(l.get("stage_id"), (list, tuple)):
            stage = l["stage_id"][1]
        asesor = ""
        if l.get("user_id") and isinstance(l.get("user_id"), (list, tuple)):
            asesor = l["user_id"][1]
        tags_nombres = [tag_by_id.get(x[0] if isinstance(x, (list, tuple)) else x, "") for x in lid_tags]
        tags_nombres = [t for t in tags_nombres if t]
        rows.append({
            "fin_etiqueta": primario[0],
            "fin_tag_name": primario[1],
            "fin_color": primario[2],
            "fin_otras": ", ".join(f"{m[0]}" for m in matched[1:]),
            "cliente": cliente,
            "oportunidad": l.get("name") or "",
            "etapa": stage,
            "asesor": asesor,
            "modelo_interes": l.get("x_product_interes") or "",
            "bancos_cuenta": l.get("x_bancos_cuenta") or "",
            "ci_rif": l.get("x_contenido_rif") or "",
            "email": l.get("email_from") or "",
            "telefono": l.get("x_phone2") or "",
            "notas": clean_html(l.get("description")),
            "monto_total": fmt_money(l.get("x_montototal")),
            "monto_aprobado": fmt_money(l.get("x_monto_aprobado")),
            "monto_total_raw": l.get("x_montototal") or 0,
            "monto_aprobado_raw": l.get("x_monto_aprobado") or 0,
            "plazo": str(l.get("x_plazo") or ""),
            "fecha_aprobacion": fmt_date(l.get("x_fecha_aprobacion")),
            "tags": ", ".join(tags_nombres),
            "lead_id": l.get("id"),
            "fecha_apertura": fmt_date(l.get("date_open")),
        })

    # Ordenar: por etiqueta (orden), luego por cliente
    rows.sort(key=lambda x: ([m[1] for m in FIN_TAGS_PRIORITY].index(x["fin_tag_name"]), x["cliente"].upper()))

    # ---- Exportar CSV ----
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relacion_clientes_crm.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fc:
        w = csv.DictWriter(fc, fieldnames=[
            "fin_etiqueta", "cliente", "oportunidad", "etapa", "modelo_interes",
            "notas", "monto_total", "monto_aprobado", "plazo", "fecha_aprobacion",
            "asesor", "bancos_cuenta", "ci_rif", "email", "telefono", "tags",
            "fecha_apertura", "lead_id"
        ])
        w.writeheader()
        for rr in rows:
            w.writerow({k: (rr.get(k) or "") for k in w.fieldnames})
    print("CSV guardado:", csv_path, "| filas:", len(rows))

    # ---- Generar HTML ----
    grupos = {}
    for rr in rows:
        grupos.setdefault(rr["fin_etiqueta"], []).append(rr)

    def nota_html(notas):
        if not notas:
            return '<span style="color:#bbb;">—</span>'
        n = html.escape(notas)
        n = n.replace("\n", "<br>")
        return f'<div class="nota">{n}</div>'

    cards = []
    for fin_label, rr_list in grupos.items():
        tag_name = rr_list[0]["fin_tag_name"]
        color = rr_list[0]["fin_color"]
        n = len(rr_list)
        tot_total = sum(x["monto_total_raw"] for x in rr_list)
        tot_apro = sum(x["monto_aprobado_raw"] for x in rr_list)
        thead = ("<tr>"
                 "<th>Cliente</th><th>Oportunidad / Modelo</th><th>Etapa</th>"
                 "<th>Notas internas</th><th>Monto Total</th><th>Monto Aprobado</th>"
                 "<th>Plazo</th><th>Fecha Aprobación</th><th>Asesor</th>"
                 "</tr>")
        body = []
        for x in rr_list:
            extra = f'<div class="mini tags">{html.escape(x["fin_otras"])}</div>' if x.get("fin_otras") else ""
            detail = f'<div class="mini">📧 {html.escape(x["email"])}</div>' if x.get("email") else ""
            if x.get("telefono"):
                detail += f'<div class="mini">📞 {html.escape(x["telefono"])}</div>'
            if x.get("modelo_interes"):
                opp = f'{html.escape(x["oportunidad"])}<div class="mini model">{html.escape(x["modelo_interes"])}</div>'
            else:
                opp = html.escape(x["oportunidad"])
            body.append(
                "<tr>"
                f'<td><strong>{html.escape(x["cliente"])}</strong>{extra}{detail}</td>'
                f'<td class="opp">{opp}</td>'
                f'<td>{html.escape(x["etapa"])}</td>'
                f'<td>{nota_html(x["notas"])}</td>'
                f'<td class="num">{html.escape(x["monto_total"])}</td>'
                f'<td class="num"><strong>{html.escape(x["monto_aprobado"])}</strong></td>'
                f'<td>{html.escape(x["plazo"])}</td>'
                f'<td>{html.escape(x["fecha_aprobacion"])}</td>'
                f'<td>{html.escape(x["asesor"])}</td>'
                "</tr>"
            )
        cards.append(f'''
        <div class="card" style="border-left:6px solid {color};">
          <div class="card-title">
            <h2>{fin_label}</h2>
            <span class="badge">{n} cliente(s)</span>
          </div>
          <div class="sumario">
            <span><b>Monto Total:</b> ${tot_total:,.2f}</span>
            <span><b>Monto Aprobado:</b> ${tot_apro:,.2f}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>{thead}</thead>
              <tbody>{''.join(body)}</tbody>
            </table>
          </div>
        </div>''')

    fecha_generacion = datetime.now().strftime("%d/%m/%Y %H:%M")
    html_doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Relación de Clientes CRM - Honda Mérida</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; background:#f4f6fa; color:#1a1a1a; }}
  .topbar {{ background:#213C83; color:#fff; padding:16px 22px; }}
  .topbar h1 {{ margin:0; font-size:20px; }}
  .topbar p {{ margin:4px 0 0; color:#cbd5e8; font-size:13px; }}
  .wrap {{ max-width:1200px; margin:20px auto; padding:0 16px; }}
  .stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:18px; }}
  .stat {{ flex:1; min-width:150px; background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,.06); }}
  .stat b {{ font-size:26px; display:block; }}
  .stat span {{ color:#666; font-size:13px; }}
  .card {{ background:#fff; border-radius:12px; padding:18px; margin-bottom:18px; box-shadow:0 3px 12px rgba(0,0,0,.06); }}
  .card-title {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }}
  .card-title h2 {{ margin:0; font-size:18px; }}
  .badge {{ background:#eef1f8; color:#213C83; border-radius:20px; padding:4px 12px; font-weight:700; font-size:13px; }}
  .sumario {{ display:flex; gap:20px; font-size:14px; color:#444; margin-bottom:12px; }}
  .table-wrap {{ overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#f0f3fa; text-align:left; padding:9px 10px; font-size:12px; text-transform:uppercase; letter-spacing:.4px; color:#213C83; }}
  td {{ padding:9px 10px; border-bottom:1px solid #eef1f8; vertical-align:top; }}
  tr:hover td {{ background:#fafcff; }}
  .num {{ text-align:right; white-space:nowrap; }}
  .opp {{ min-width:200px; }}
  .mini {{ color:#888; font-size:11px; margin-top:3px; }}
  .mini.model {{ color:#0a7d2c; font-weight:600; }}
  .nota {{ max-width:340px; max-height:120px; overflow:auto; font-size:12px; color:#555; background:#fbfcff; border:1px solid #eef1f8; border-radius:6px; padding:6px 8px; }}
  .tags {{ color:#213C83; }}
  .foot {{ text-align:center; color:#999; font-size:12px; padding:16px; }}
  @media (max-width:700px) {{ .stats {{ flex-direction:column; }} }}
</style>
</head>
<body>
<div class="topbar">
  <h1>🚗 Relación de Clientes por Etiqueta Financiera — Honda Mérida</h1>
  <p>Origen del financiamiento: ARCA · PIVCA · Banesco · Provincial · Generado {fecha_generacion}</p>
</div>
<div class="wrap">
  <div class="stats">
    <div class="stat"><b>{len(rows)}</b><span>Clientes con etiqueta financiera</span></div>
    <div class="stat"><b>{len(grupos)}</b><span>Entidades financieras</span></div>
    <div class="stat"><b>${sum(x['monto_total_raw'] for x in rows):,.2f}</b><span>Suma Montos Totales</span></div>
    <div class="stat"><b>${sum(x['monto_aprobado_raw'] for x in rows):,.2f}</b><span>Suma Montos Aprobados</span></div>
  </div>
  {''.join(cards)}
  <div class="foot">Consulta solo-lectura al CRM de Odoo · latinbienmotors.com · Generado el {fecha_generacion}</div>
</div>
</body>
</html>
"""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relacion_clientes_crm.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    print("HTML generado:", html_path)


if __name__ == "__main__":
    main()