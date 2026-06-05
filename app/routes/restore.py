"""Restaurar un sitio desde el backup automático generado al borrarlo."""
import re
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from .. import config, db as dbm
from ..auth import require_admin
from ..services import (
    backup_service as bk,
    nginx_service as ng,
    nginx_inventory as ngi,
    mysql_service as my,
    filesystem_service as fs,
    landing_service as land,
)
from .sites import _new_op, _finish_op, _all_sites

router = APIRouter(dependencies=[Depends(require_admin)])


def _extract_old_fqdn_from_dump(dump_path: str) -> str | None:
    """Lee las primeras KB del dump SQL buscando https://<fqdn>/ del siteurl."""
    try:
        with open(dump_path, "rb") as f:
            head = f.read(2_000_000)  # 2MB suelen contener wp_options
        # busca patrones tipo "siteurl" o "home" cercanos a una URL
        m = re.search(rb"'(https?://[a-z0-9.-]+\.[a-z]{2,})'\s*,\s*'(?:siteurl|home)'", head, re.I)
        if m:
            return m.group(1).decode("utf-8")
        lab = re.escape(config.LAB_DOMAIN).encode()
        m = re.search(rb"https://([a-z0-9.-]+\." + lab + rb")", head)
        if m:
            return f"https://{m.group(1).decode('utf-8')}"
    except Exception:
        pass
    return None


@router.get("/restore", response_class=HTMLResponse)
async def restore_list(request: Request, error: str = "", message: str = ""):
    backups = bk.list_backups()
    # Filtrar pares completos (con dump y tar)
    pairs = [b for b in backups if b["dump"] and b["tar"]]
    return request.app.state.templates.TemplateResponse(
        "restore.html",
        {"request": request, "backups": pairs,
         "php_versions": list(config.PHP_VERSIONS.keys()),
         "default_php": config.DEFAULT_PHP,
         "error": error or None, "message": message or None}
    )


@router.post("/restore", response_class=HTMLResponse)
async def do_restore(
    request: Request,
    source_subdomain: str = Form(...),
    source_ts: str = Form(...),
    target_subdomain: str = Form(...),
    php_version: str = Form(config.DEFAULT_PHP),
    site_type: str = Form("wordpress"),
):
    log: list = []
    # Validar subdominio destino
    try:
        target = ng.validate_subdomain(target_subdomain)
    except ValueError as e:
        return RedirectResponse(f"/restore?error={e}", status_code=303)

    # Buscar el par dump+tar del backup
    backup = next(
        (b for b in bk.list_backups()
         if b["subdomain"] == source_subdomain and b["ts"] == source_ts),
        None,
    )
    if not backup or not backup["dump"] or not backup["tar"]:
        return RedirectResponse("/restore?error=backup-no-encontrado", status_code=303)

    target_fqdn = ng.fqdn_for(target)
    target_docroot = str(config.WWW_ROOT / target_fqdn)

    # Crear record de site (o reactivar uno borrado con mismo subdominio)
    with dbm.session_scope() as s:
        existing = s.execute(
            select(dbm.Site).where(dbm.Site.subdomain == target)
        ).scalar_one_or_none()
        if existing and existing.status != "deleted":
            return RedirectResponse(
                f"/restore?error=ya-existe-activo:{target}", status_code=303)
        if existing and existing.status == "deleted":
            site = existing
            site.fqdn = target_fqdn
            site.type = site_type
            site.status = "creating"
            site.php_version = php_version
            site.docroot = target_docroot
            site.db_name = None
            site.db_user = None
            site.coolify_uuid = None
            site.coolify_port = None
            site.extra = {}
        else:
            site = dbm.Site(
                subdomain=target, fqdn=target_fqdn, type=site_type,
                status="creating", php_version=php_version, docroot=target_docroot,
            )
            s.add(site)
        s.flush()
        op = _new_op(s, site.id, f"restore_from_{source_subdomain}_{source_ts}")
        site_id = site.id

    success = False
    db_name = db_user = db_pass = None
    try:
        # 1. Crear docroot
        fs.make_docroot(target_docroot, log=log)

        # 2. Extraer tar (con --strip-components=1 ya configurado en helper)
        if not bk.extract_tar_into_docroot(backup["tar"], target_docroot, log):
            raise RuntimeError("falló extracción del tar")

        # 3. Crear BD + user nuevos
        if site_type == "wordpress":
            db_name, db_user, db_pass = my.create_db_and_user(target, log)

            # 4. Importar dump
            if not bk.import_db_dump(db_name, backup["dump"], log):
                raise RuntimeError("falló import del dump")

            # 5. Re-escribir wp-config.php con las nuevas credenciales
            #    (las viejas ya no sirven, ese user fue dropeado al borrar)
            from ..services import wordpress_service as wp
            wp.write_wp_config(target_docroot, db_name, db_user, db_pass,
                               target_fqdn, log)

            # 6. Si el subdominio cambió, search-replace en BD
            old_url = _extract_old_fqdn_from_dump(backup["dump"])
            log.append(f"old url detectado en dump: {old_url}")
            if old_url:
                from urllib.parse import urlparse
                old_host = urlparse(old_url).netloc
                if old_host and old_host != target_fqdn:
                    new_url = f"https://{target_fqdn}"
                    rc, out, err = run_wp_cli_search_replace(
                        target_docroot, old_url, new_url, log)
                    log.append(f"search-replace: rc={rc} {out[:300]} {err[:200]}")

        # 7. Configurar vhost nginx
        if site_type == "wordpress":
            vhost = ng.render_vhost_php(target_fqdn, target_docroot, php_version)
        else:
            vhost = ng.render_vhost_static(target_fqdn, target_docroot)
        ng.write_vhost(target_fqdn, vhost, log)
        ng.reload_nginx(log)

        success = True
    except Exception as e:
        log.append(f"ERROR: {e}")

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        site.status = "ready" if success else "failed"
        if db_name:
            site.db_name = db_name
            site.db_user = db_user
            site.extra = {
                "restored_from": f"{source_subdomain}/{source_ts}",
                "backup_dump": backup["dump"],
                "backup_tar": backup["tar"],
            }
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(dbm.Operation.id.desc())).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
        sites_for_landing = _all_sites(s)

    if success:
        try:
            land.regenerate_landing(sites_for_landing, log)
        except Exception:
            pass
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


def run_wp_cli_search_replace(docroot: str, old: str, new: str, log: list):
    from ..services.runner import run_sudo
    rc, out, err = run_sudo([
        "/usr/local/bin/sw-panel-helper", "wp-cli", docroot,
        "search-replace", old, new,
        "--skip-columns=guid", "--report-changed-only", "--all-tables",
    ])
    return rc, out, err
