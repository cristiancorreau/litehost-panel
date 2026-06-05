"""Sincroniza la landing (index.html del dominio base) con la lista de sitios activos."""
import re
from .runner import run_sudo
from .. import config
from . import nginx_inventory

LAB = config.LAB_DOMAIN

CARD_TEMPLATE = """    <a class="card" href="https://{fqdn}/" target="_blank" rel="noopener"{style}>
      <div><div class="name">{name}</div><div class="host">{fqdn}</div></div>
      <div class="row"><span class="pill"{pill_style}>{pill}</span><span class="open">abrir →</span></div>
    </a>
"""

# Servicios "infra" que siempre van arriba de la landing
INFRA_CARDS = [
    {"name": "Panel admin", "fqdn": f"panel.{LAB}",
     "pill": "panel",
     "style": ' style="border-color: rgba(74,222,128,0.40);"',
     "pill_style": ' style="background: rgba(74,222,128,0.12); color: #4ade80; border-color: rgba(74,222,128,0.30);"'},
    {"name": "Coolify", "fqdn": f"coolify.{LAB}",
     "pill": "deploys",
     "style": ' style="border-color: rgba(157,140,255,0.45);"',
     "pill_style": ' style="background: rgba(157,140,255,0.12); color: #c4b5fd; border-color: rgba(157,140,255,0.3);"'},
    {"name": "Archivos", "fqdn": f"panel.{LAB}/files",
     "pill": "files",
     "style": ' style="border-color: rgba(251,191,36,0.40);"',
     "pill_style": ' style="background: rgba(251,191,36,0.12); color: #fbbf24; border-color: rgba(251,191,36,0.30);"'},
    {"name": "VSCode", "fqdn": f"vscode.{LAB}",
     "pill": "editor",
     "style": ' style="border-color: rgba(6,182,212,0.40);"',
     "pill_style": ' style="background: rgba(6,182,212,0.12); color: #67e8f9; border-color: rgba(6,182,212,0.30);"'},
]


def _site_card(name: str, fqdn: str, pill: str) -> str:
    return CARD_TEMPLATE.format(fqdn=fqdn, name=name, pill=pill, style="", pill_style="")


def regenerate_landing(sites: list, log: list) -> None:
    """Combina sitios del panel (DB) + inventario nginx + servicios de infra."""
    rc, current_html, err = run_sudo(["/usr/local/bin/sw-panel-helper", "read-file",
                                       str(config.LANDING_HTML)])
    if rc != 0:
        log.append(f"read landing failed: {err}")
        return

    cards = []
    seen: set[str] = set()

    # 1. Tarjetas de infra (siempre primero)
    for c in INFRA_CARDS:
        cards.append(CARD_TEMPLATE.format(**c))
        seen.add(c["fqdn"].lower())

    # 2. Sitios del panel (status='ready')
    for s in sites:
        if s.status != "ready":
            continue
        if s.fqdn.lower() in seen:
            continue
        pill = {
            "wordpress": "wordpress",
            "duplicator": "wordpress",
            "coolify": "coolify",
            "static": "estático",
        }.get(s.type, "activo")
        name = s.subdomain.replace("-", " ").title()
        cards.append(_site_card(name, s.fqdn, pill))
        seen.add(s.fqdn.lower())

    # 3. Vhosts externos en nginx (no manejados por panel)
    try:
        for v in nginx_inventory.list_vhosts():
            for n in v.server_names:
                fqdn = n.lower().rstrip(".")
                if not fqdn.endswith("." + LAB):
                    continue
                if fqdn in seen or fqdn == LAB:
                    continue
                sub = fqdn.split(".")[0]
                pill = {"php": "wordpress", "proxy": "proxy", "static": "estático"}.get(v.type, "activo")
                cards.append(_site_card(sub.replace("-", " ").title(), fqdn, pill))
                seen.add(fqdn)
    except Exception as e:
        log.append(f"landing inventory failed: {e}")

    new_grid = '  <div class="grid">\n\n' + "".join(cards) + "  </div>"

    new_html = re.sub(
        r'  <div class="grid">.*?  </div>',
        new_grid,
        current_html,
        count=1,
        flags=re.DOTALL,
    )
    count = len(seen)
    new_html = re.sub(
        r'<span class="badge">[^<]*</span>',
        f'<span class="badge">{count} sitios</span>',
        new_html,
        count=1,
    )

    rc, _, err = run_sudo(["/usr/local/bin/sw-panel-helper", "write-file",
                            str(config.LANDING_HTML), "www-data:www-data"],
                          input_text=new_html)
    log.append(f"landing regenerated ({count} cards): rc={rc} {err}")
