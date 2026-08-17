# 🚗 Gestión Honda — Consulta CRM (LatinBien Motors)

Panel de gestión comercial de **Honda Mérida** que consulta el CRM de **Odoo**
(`latinbienmotors.com`) en **modo solo lectura** y genera:

| Archivo | Descripción |
|---|---|
| `crm_consulta/crm_dashboard.html` | 📊 **Dashboard interactivo** con gráficas (Chart.js): clientes por entidad financiera, montos aprobados, clientes facturados/aprobados y tabla filtrable en vivo |
| `crm_consulta/relacion_clientes_crm.html` | 📋 Relación estática de clientes por etiqueta financiera |
| `crm_consulta/relacion_clientes_crm.csv` | 📁 Exportación a Excel (UTF-8) |

## 🏦 Entidades financieras rastreadas

- **ARCA**
- **PIVCA**
- **BANESCO** (etiqueta: Crédito Banesco)
- **PROVINCIAL** (etiqueta: Crédito Banco Provincial)

Para cada cliente se muestra: nombre, oportunidad/modelo del vehículo, etapa del pipeline,
notas internas, **monto total**, **monto aprobado**, **plazo** y **fecha de aprobación**.

## ⚙️ Cómo usarlo

### Opción A — GitHub Actions (automático)

El workflow `.github/workflows/actualizar_crm.yml` regenera los reportes **cada hora**
(o manualmente desde la pestaña *Actions*) usando credenciales almacenadas como secretos.

Configura los secretos del repositorio en **Settings → Secrets and variables → Actions**:

- `ODOO_USER` — usuario de Odoo (ej: `yarley@hondamerida.com`)
- `ODOO_PASSWORD` — contraseña de Odoo

> Por seguridad las credenciales **nunca** se guardan en el repositorio.

### Opción B — Local

```bash
# En Windows PowerShell
$env:ODOO_USER    = "usuario@correo.com"
$env:ODOO_PASSWORD = "tu-contrasena"
$env:ODOO_DB      = "latinbien"

python generar_todo.py
```

Luego abre `crm_consulta/crm_dashboard.html` en el navegador.

## 🔒 Seguridad

- Todos los scripts son de **solo lectura**: no modifican, crean ni eliminan datos en Odoo.
- Las credenciales se leen exclusivamente de variables de entorno (`ODOO_USER`, `ODOO_PASSWORD`).
- El reporte incluye datos reales de clientes; **no subir capturas ni datos a repositorios públicos** más allá de lo necesario.