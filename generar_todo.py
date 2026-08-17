# -*- coding: utf-8 -*-
"""
Generador de la consulta CRM Honda (latinbienmotors.com) - SOLO LECTURA / CONSULTA.

Ejecuta ambos scripts y produce:
  - relacion_clientes_crm.csv  + relacion_clientes_crm.html  (tabla por entidad financiera)
  - crm_dashboard.html                                       (panel interactivo con graficas)

Credenciales via variables de entorno: ODOO_USER y ODOO_PASSWORD.
Este script NO contiene credenciales en texto plano.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    scripts_dir = os.path.join(HERE, "crm_consulta")
    scripts = ["consulta_crm.py", "dashboard_crm.py"]
    for s in scripts:
        path = os.path.join(scripts_dir, s)
        print("== Ejecutando", s, "==")
        code = subprocess.call([sys.executable, path], cwd=scripts_dir)
        if code != 0:
            print("ERROR en", s, "exit:", code)
            sys.exit(code)

    # Publicar el dashboard como index.html en la raiz (GitHub Pages)
    src = os.path.join(scripts_dir, "crm_dashboard.html")
    dst = os.path.join(HERE, "index.html")
    if os.path.exists(src):
        shutil.copyfile(src, dst)
        print("Dashboard publicado como index.html")
    else:
        print("AVISO: no se encontro crm_dashboard.html")

    print("OK: reportes generados.")


if __name__ == "__main__":
    main()