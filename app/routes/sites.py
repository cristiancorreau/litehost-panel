"""Rutas: listar, crear subdominio + WordPress fresh, ver detalle, eliminar."""
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, desc
from datetime import datetime
import secrets
import string
from pathlib import Path
from .. import config, db as dbm
from ..auth import require_admin
from ..services import (
    nginx_service as ng,
    nginx_inventory as ngi,
    mysql_service as my,
    filesystem_service as fs,
    wordpress_service as wp,
    duplicator_service as dup,
    coolify_service as cool,
    backup_service as bk,
    landing_service as land,
    services_service as svc,
)

router = APIRouter(dependencies=[Depends(require_admin)])


def gen_admin_password() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))


def _all_sites(s):
    return s.execute(select(dbm.Site).order_by(desc(dbm.Site.created_at))).scalars().all()


def _new_op(s, site_id: int | None, action: str) -> dbm.Operation:
    op = dbm.Operation(site_id=site_id, action=action, status="running", log="")
    s.add(op); s.flush()
    return op


def _finish_op(s, op: dbm.Operation, ok: bool, log_lines: list):
    op.status = "ok" if ok else "error"
    op.finished_at = datetime.utcnow()
    op.log = "\n".join(log_lines)
    s.add(op)


# ---------------- LISTADO / DASHBOARD ----------------

def _merge_with_nginx(db_sites: list) -> list[dict]:
    """Combina sitios de la DB con vhosts en sites-enabled.
    Retorna una lista de dicts con: fqdn, type, status, source, db_id (si aplica),
    php, root, created_at."""
    by_fqdn: dict[str, dict] = {}

    # 1. Sitios desde la DB
    for s in db_sites:
        if s.status == "deleted":
            continue
        by_fqdn[s.fqdn.lower()] = {
            "fqdn": s.fqdn,
            "subdomain": s.subdomain,
            "type": s.type,
            "status": s.status,
            "source": "panel",
            "db_id": s.id,
            "php_version": s.php_version,
            "docroot": s.docroot,
            "created_at": s.created_at,
        }

    # 2. Vhosts de nginx no registrados en la DB → fuente "nginx"
    try:
        for v in ngi.list_vhosts():
            for name in v.server_names:
                key = name.lower().rstrip(".")
                if not key or key == "_":
                    continue
                if key in by_fqdn:
                    # Ya está en la DB; solo marcamos que también tiene vhost
                    by_fqdn[key]["has_vhost"] = True
                    continue
                # Solo nos interesan sitios bajo lab.example.com o pre-existentes
                # del servidor (los .sw legacy también los listamos para visibilidad)
                by_fqdn[key] = {
                    "fqdn": name,
                    "subdomain": key.split(".")[0] if "." in key else key,
                    "type": v.type,
                    "status": "external",
                    "source": "nginx",
                    "db_id": None,
                    "php_version": v.php_version,
                    "docroot": v.root,
                    "created_at": None,
                    "has_vhost": True,
                }
    except Exception:
        pass

    rows = sorted(by_fqdn.values(), key=lambda x: (x["source"] != "panel", x["fqdn"]))
    # Adjuntar tamaño en disco (con cache 5 min)
    paths = [r["docroot"] for r in rows if r.get("docroot")]
    sizes = svc.disk_usage(paths) if paths else {}
    for r in rows:
        if r.get("docroot") and r["docroot"] in sizes:
            r["size_bytes"] = sizes[r["docroot"]]
    return rows


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    with dbm.session_scope() as s:
        sites = _all_sites(s)
    merged = _merge_with_nginx(sites)
    return request.app.state.templates.TemplateResponse(
        "dashboard.html", {"request": request, "rows": merged}
    )


@router.post("/api/regenerate-landing")
async def regenerate_landing_now():
    log: list = []
    with dbm.session_scope() as s:
        sites = _all_sites(s)
    try:
        land.regenerate_landing(sites, log)
        return {"ok": True, "log": log}
    except Exception as e:
        return {"ok": False, "error": str(e), "log": log}


@router.get("/api/check-subdomain")
async def check_subdomain(name: str):
    """Endpoint para validación en vivo desde el form."""
    try:
        sub = ng.validate_subdomain(name)
        return {"available": True, "fqdn": ng.fqdn_for(sub)}
    except ValueError as e:
        return {"available": False, "reason": str(e)}


# ---------------- NUEVO SITIO (WIZARD) ----------------

@router.get("/sites/new", response_class=HTMLResponse)
async def new_site_picker(request: Request):
    return request.app.state.templates.TemplateResponse(
        "new_site.html", {"request": request}
    )


@router.get("/sites/new/wp", response_class=HTMLResponse)
async def new_wp_form(request: Request, error: str = ""):
    return request.app.state.templates.TemplateResponse(
        "new_wordpress.html",
        {"request": request, "php_versions": list(config.PHP_VERSIONS.keys()),
         "default_php": config.DEFAULT_PHP, "error": error or None}
    )


@router.get("/sites/new/static", response_class=HTMLResponse)
async def new_static_form(request: Request, error: str = ""):
    return request.app.state.templates.TemplateResponse(
        "new_static.html", {"request": request, "error": error or None}
    )


@router.post("/sites/new/wp", response_class=HTMLResponse)
@router.post("/sites/wordpress", response_class=HTMLResponse, include_in_schema=False)
async def create_wordpress(
    request: Request,
    subdomain: str = Form(...),
    php_version: str = Form(config.DEFAULT_PHP),
    site_title: str = Form(...),
    admin_user: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(""),
):
    log: list = []
    try:
        sub = ng.validate_subdomain(subdomain)
        fqdn = ng.fqdn_for(sub)
        docroot = str(config.WWW_ROOT / fqdn)
        if not admin_password:
            admin_password = gen_admin_password()
    except Exception as e:
        return RedirectResponse(f"/sites/new/wp?error={e}", status_code=303)

    with dbm.session_scope() as s:
        existing = s.execute(select(dbm.Site).where(dbm.Site.subdomain == sub)).scalar_one_or_none()
        if existing:
            return request.app.state.templates.TemplateResponse(
                "new_site.html", {"request": request, "error": f"Ya existe '{sub}'",
                                  "php_versions": list(config.PHP_VERSIONS.keys())}, status_code=400
            )
        site = dbm.Site(subdomain=sub, fqdn=fqdn, type="wordpress", status="creating",
                        php_version=php_version, docroot=docroot)
        s.add(site); s.flush()
        op = _new_op(s, site.id, "create_wordpress")
        site_id = site.id

    success = False
    db_name = db_user = None
    try:
        # 1. Docroot
        fs.make_docroot(docroot, log=log)
        # 2. Descarga + extracción
        wp.download_and_extract(docroot, log)
        # 3. Crear BD
        db_name, db_user, db_pass = my.create_db_and_user(sub, log)
        # 4. wp-config
        wp.write_wp_config(docroot, db_name, db_user, db_pass, fqdn, log)
        # 5. Vhost nginx
        vhost = ng.render_vhost_php(fqdn, docroot, php_version)
        ng.write_vhost(fqdn, vhost, log)
        ng.reload_nginx(log)
        # 6. wp-cli core install
        wp.core_install(docroot, fqdn, site_title, admin_user, admin_password,
                        admin_email, log)
        success = True
    except Exception as e:
        log.append(f"ERROR: {e}")

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        site.status = "ready" if success else "failed"
        if db_name:
            site.db_name = db_name
            site.db_user = db_user
            site.extra = {"admin_user": admin_user, "admin_email": admin_email,
                          "admin_password": admin_password if success else ""}
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
        sites_for_landing = _all_sites(s)

    if success:
        try:
            land.regenerate_landing(sites_for_landing, log)
        except Exception as e:
            log.append(f"landing regen failed: {e}")

    return RedirectResponse(f"/sites/{site_id}", status_code=303)


@router.post("/sites/new/static", response_class=HTMLResponse)
@router.post("/sites/static", response_class=HTMLResponse, include_in_schema=False)
async def create_static(
    request: Request,
    subdomain: str = Form(...),
    archive: UploadFile = File(None),
):
    log: list = []
    try:
        sub = ng.validate_subdomain(subdomain)
    except Exception as e:
        return RedirectResponse(f"/sites/new/static?error={e}", status_code=303)
    fqdn = ng.fqdn_for(sub)
    docroot = str(config.WWW_ROOT / fqdn)
    with dbm.session_scope() as s:
        site = dbm.Site(subdomain=sub, fqdn=fqdn, type="static", status="creating",
                        docroot=docroot)
        s.add(site); s.flush()
        op = _new_op(s, site.id, "create_static")
        site_id = site.id

    success = False
    try:
        fs.make_docroot(docroot, log=log)
        # ¿El usuario subió un ZIP?
        has_zip = archive is not None and archive.filename and archive.filename != ""
        zip_inspection = None
        if has_zip:
            staging = config.UPLOADS_DIR / f"site-{site_id}"
            staging.mkdir(parents=True, exist_ok=True)
            zip_dst = staging / "upload.zip"
            await dup.save_upload(archive, zip_dst, log)
            ok, msg, n = fs.validate_zip(str(zip_dst))
            log.append(f"validate_zip: ok={ok} msg={msg} files={n}")
            if not ok:
                zip_dst.unlink(missing_ok=True)
                raise RuntimeError(f"ZIP inválido: {msg}")
            zip_inspection = fs.inspect_zip(str(zip_dst))
            log.append(
                f"zip contiene {zip_inspection['total']} entries, "
                f"top-level={zip_inspection['top_level']}, "
                f"wrapped_in={zip_inspection['wrapped_in']}, "
                f"index_root={zip_inspection['has_index_root']}"
            )
            fs.extract_zip_into_docroot(str(zip_dst), docroot, log)
        else:
            fs.write_file(f"{docroot}/index.html",
                          f"<h1>{fqdn}</h1><p>Sitio estático recién creado.</p>", log)
        vhost = ng.render_vhost_static(fqdn, docroot)
        ng.write_vhost(fqdn, vhost, log)
        ng.reload_nginx(log)
        success = True
    except Exception as e:
        log.append(f"ERROR: {e}")

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        site.status = "ready" if success else "failed"
        if zip_inspection is not None:
            extra = dict(site.extra or {})
            extra["zip"] = {
                "total": zip_inspection["total"],
                "top_level": list(zip_inspection["top_level"]),
                "wrapped_in": zip_inspection["wrapped_in"],
                "has_index_root": zip_inspection["has_index_root"],
                "size_uncompressed": zip_inspection["size_uncompressed"],
                "entries": zip_inspection["entries"],
            }
            if zip_inspection.get("wrapped_in"):
                extra["effective_url"] = f"https://{fqdn}/{zip_inspection['wrapped_in']}/"
            site.extra = extra
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
        sites_for_landing = _all_sites(s)
    if success:
        try:
            land.regenerate_landing(sites_for_landing, log)
        except Exception:
            pass
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


# ---------------- DUPLICATOR ----------------

DEFAULT_UPLOAD_DIR = str(config.HOME_DIR / "uploads/duplicator")
_HOME = str(config.HOME_DIR)


def _is_allowed_upload_dir(path: str) -> bool:
    if not path or path.strip() == "":
        return False
    p = path.rstrip("/")
    return (
        p == "/tmp"
        or p.startswith("/tmp/")
        or p == _HOME
        or p.startswith(_HOME + "/")
    )


def _scan_dir_for_files(dirp: str) -> tuple[list[dict], list[dict], bool]:
    """Retorna (installers, archives, exists). Usa helper sudo porque el panel
    user no tiene permiso para leer el home del usuario del sistema."""
    import os
    from ..services.runner import run_sudo
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "list-upload-dir", dirp])
    if rc != 0:
        return [], [], False
    if out.strip() == "MISSING":
        return [], [], False
    installers, archives = [], []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, sz = line.rsplit("|", 1)
        try:
            size = int(sz)
        except ValueError:
            continue
        full = os.path.join(dirp, name)
        low = name.lower()
        if low == "installer.php" or (low.endswith(".php") and "installer" in low):
            installers.append({"name": name, "size": size, "path": full})
        elif low.endswith((".daf", ".zip", ".archive")):
            archives.append({"name": name, "size": size, "path": full})
    return installers, archives, True


@router.get("/sites/new/duplicator-from-disk", response_class=HTMLResponse)
async def duplicator_from_disk_form(request: Request, error: str = "",
                                      dir: str = DEFAULT_UPLOAD_DIR):
    if not _is_allowed_upload_dir(dir):
        dir = DEFAULT_UPLOAD_DIR
    installers, archives, _exists = _scan_dir_for_files(dir)
    return request.app.state.templates.TemplateResponse(
        "install_duplicator_from_disk.html",
        {
            "request": request,
            "php_versions": list(config.PHP_VERSIONS.keys()),
            "default_php": config.DEFAULT_PHP,
            "installers": installers,
            "archives": archives,
            "error": error or None,
            "current_dir": dir,
            "default_dir": DEFAULT_UPLOAD_DIR,
        },
    )


@router.get("/api/list-upload-dir")
async def list_upload_dir(dir: str = DEFAULT_UPLOAD_DIR):
    if not _is_allowed_upload_dir(dir):
        return {"ok": False, "reason": f"directorio no permitido (solo /tmp o {_HOME})"}
    installers, archives, exists = _scan_dir_for_files(dir)
    return {
        "ok": True,
        "dir": dir,
        "exists": exists,
        "installers": installers,
        "archives": archives,
    }


@router.post("/sites/new/duplicator-from-disk", response_class=HTMLResponse)
async def duplicator_from_disk_create(
    request: Request,
    subdomain: str = Form(...),
    php_version: str = Form(config.DEFAULT_PHP),
    installer_path: str = Form(...),
    archive_path: str = Form(...),
):
    log: list = []
    # Validaciones básicas
    try:
        sub = ng.validate_subdomain(subdomain)
    except Exception as e:
        return RedirectResponse(f"/sites/new/duplicator-from-disk?error={e}", status_code=303)

    if not (installer_path.startswith("/tmp/") or installer_path.startswith(_HOME + "/")):
        return RedirectResponse(f"/sites/new/duplicator-from-disk?error=installer-path-invalido",
                                  status_code=303)
    if not (archive_path.startswith("/tmp/") or archive_path.startswith(_HOME + "/")):
        return RedirectResponse(f"/sites/new/duplicator-from-disk?error=archive-path-invalido",
                                  status_code=303)

    fqdn = ng.fqdn_for(sub)
    docroot = str(config.WWW_ROOT / fqdn)

    with dbm.session_scope() as s:
        existing = s.execute(select(dbm.Site).where(dbm.Site.subdomain == sub)).scalar_one_or_none()
        if existing:
            return RedirectResponse(
                f"/sites/new/duplicator-from-disk?error=ya-existe-{sub}", status_code=303)
        site = dbm.Site(subdomain=sub, fqdn=fqdn, type="duplicator", status="creating",
                        php_version=php_version, docroot=docroot)
        s.add(site); s.flush()
        op = _new_op(s, site.id, "create_duplicator_from_disk")
        site_id = site.id

    success = False
    db_name = db_user = db_pass = None
    try:
        # 1. Crear docroot
        fs.make_docroot(docroot, log=log)
        # 2. Mover archivos desde /tmp al docroot
        from .sites import _all_sites  # noqa
        from ..services.runner import run_sudo
        import os
        installer_dst = f"{docroot}/installer.php"
        archive_name = os.path.basename(archive_path)
        archive_dst = f"{docroot}/{archive_name}"
        rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper",
                                  "mv-from-tmp-into-www", installer_path, installer_dst])
        log.append(f"mv installer {installer_path} → {installer_dst}: rc={rc} {err}")
        if rc != 0:
            raise RuntimeError(f"no pude mover installer: {err}")
        rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper",
                                  "mv-from-tmp-into-www", archive_path, archive_dst])
        log.append(f"mv archive {archive_path} → {archive_dst}: rc={rc} {err}")
        if rc != 0:
            raise RuntimeError(f"no pude mover archive: {err}")
        # 3. Crear BD vacía
        db_name, db_user, db_pass = my.create_db_and_user(sub, log)
        # 4. Vhost PHP
        vhost = ng.render_vhost_php(fqdn, docroot, php_version)
        ng.write_vhost(fqdn, vhost, log)
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
            site.extra = {"db_pass_for_wizard": db_pass,
                          "wizard_url": f"https://{fqdn}/installer.php"}
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


@router.get("/sites/new/duplicator", response_class=HTMLResponse)
@router.get("/sites/duplicator", response_class=HTMLResponse, include_in_schema=False)
async def duplicator_form(request: Request):
    return request.app.state.templates.TemplateResponse(
        "install_duplicator.html",
        {"request": request, "php_versions": list(config.PHP_VERSIONS.keys())}
    )


@router.post("/sites/new/duplicator", response_class=HTMLResponse)
@router.post("/sites/duplicator", response_class=HTMLResponse, include_in_schema=False)
async def duplicator_create(
    request: Request,
    subdomain: str = Form(...),
    php_version: str = Form(config.DEFAULT_PHP),
    installer: UploadFile = File(...),
    archive: UploadFile = File(...),
):
    log: list = []
    try:
        sub = ng.validate_subdomain(subdomain)
    except Exception as e:
        return request.app.state.templates.TemplateResponse(
            "install_duplicator.html",
            {"request": request, "error": str(e), "php_versions": list(config.PHP_VERSIONS.keys())},
            status_code=400)

    fqdn = ng.fqdn_for(sub)
    docroot = str(config.WWW_ROOT / fqdn)

    with dbm.session_scope() as s:
        existing = s.execute(select(dbm.Site).where(dbm.Site.subdomain == sub)).scalar_one_or_none()
        if existing:
            return request.app.state.templates.TemplateResponse(
                "install_duplicator.html",
                {"request": request, "error": f"Ya existe '{sub}'",
                 "php_versions": list(config.PHP_VERSIONS.keys())}, status_code=400
            )
        site = dbm.Site(subdomain=sub, fqdn=fqdn, type="duplicator", status="creating",
                        php_version=php_version, docroot=docroot)
        s.add(site); s.flush()
        op = _new_op(s, site.id, "create_duplicator")
        site_id = site.id

    success = False
    db_name = db_user = db_pass = None
    try:
        # Save uploads to staging
        staging = config.UPLOADS_DIR / f"site-{site_id}"
        staging.mkdir(parents=True, exist_ok=True)
        installer_dst = staging / "installer.php"
        archive_dst = staging / archive.filename  # .daf preserva nombre original
        await dup.save_upload(installer, installer_dst, log)
        await dup.save_upload(archive, archive_dst, log)
        # Crear docroot
        fs.make_docroot(docroot, log=log)
        # Mover
        dup.move_to_docroot([installer_dst, archive_dst], docroot, log)
        # Crear BD
        db_name, db_user, db_pass = my.create_db_and_user(sub, log)
        # Vhost PHP
        vhost = ng.render_vhost_php(fqdn, docroot, php_version)
        ng.write_vhost(fqdn, vhost, log)
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
            site.extra = {"db_pass_for_wizard": db_pass,
                          "wizard_url": f"https://{fqdn}/installer.php"}
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


# ---------------- COOLIFY ----------------

@router.get("/sites/new/coolify", response_class=HTMLResponse)
@router.get("/sites/coolify", response_class=HTMLResponse, include_in_schema=False)
async def coolify_form(request: Request):
    error = None
    projects = servers = []
    try:
        projects = cool.list_projects()
        servers = cool.list_servers()
    except Exception as e:
        error = f"No se pudo listar Coolify: {e}"
    return request.app.state.templates.TemplateResponse(
        "install_coolify.html",
        {"request": request, "projects": projects, "servers": servers, "error": error}
    )


def _next_coolify_port(s) -> int:
    used = set(r[0] for r in s.execute(
        select(dbm.Site.coolify_port).where(dbm.Site.coolify_port.isnot(None))
    ).all())
    for p in range(config.COOLIFY_PORT_START, config.COOLIFY_PORT_END + 1):
        if p not in used:
            return p
    raise RuntimeError("Sin puertos libres en el rango Coolify")


@router.post("/sites/new/coolify", response_class=HTMLResponse)
@router.post("/sites/coolify", response_class=HTMLResponse, include_in_schema=False)
async def coolify_create(
    request: Request,
    subdomain: str = Form(...),
    project_uuid: str = Form(...),
    server_uuid: str = Form(...),
    git_repository: str = Form(...),
    git_branch: str = Form("master"),
    build_pack: str = Form("dockerfile"),
    container_port: int = Form(3000),
):
    log: list = []
    try:
        sub = ng.validate_subdomain(subdomain)
    except Exception as e:
        return RedirectResponse(f"/sites/coolify?error={e}", status_code=303)
    fqdn = ng.fqdn_for(sub)

    with dbm.session_scope() as s:
        existing = s.execute(select(dbm.Site).where(dbm.Site.subdomain == sub)).scalar_one_or_none()
        if existing:
            return RedirectResponse(f"/sites/coolify?error=already-exists", status_code=303)
        host_port = _next_coolify_port(s)
        site = dbm.Site(subdomain=sub, fqdn=fqdn, type="coolify", status="creating",
                        repo_url=git_repository, coolify_port=host_port)
        s.add(site); s.flush()
        op = _new_op(s, site.id, "create_coolify")
        site_id = site.id

    success = False
    coolify_uuid = None
    try:
        # 1. Crear app en Coolify
        app = cool.create_application_from_public_repo(
            project_uuid=project_uuid,
            server_uuid=server_uuid,
            environment_name="production",
            git_repository=git_repository,
            git_branch=git_branch,
            build_pack=build_pack,
            name=sub,
            ports_exposes=str(container_port),
            instant_deploy=True,
        )
        coolify_uuid = app.get("uuid") or app.get("data", {}).get("uuid")
        log.append(f"Coolify app creada uuid={coolify_uuid}: {app}")
        # 2. nginx vhost
        vhost = ng.render_vhost_proxy(fqdn, host_port)
        ng.write_vhost(fqdn, vhost, log)
        ng.reload_nginx(log)
        success = True
    except Exception as e:
        log.append(f"ERROR: {e}")

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        site.status = "ready" if success else "failed"
        if coolify_uuid:
            site.coolify_uuid = coolify_uuid
        site.extra = {"git_branch": git_branch, "build_pack": build_pack,
                      "container_port": container_port, "host_port": site.coolify_port}
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


# ---------------- COOLIFY SERVICE (Supabase, etc — sin repo) ----------------

@router.get("/sites/new/coolify-service", response_class=HTMLResponse)
async def coolify_service_form(request: Request, error: str = ""):
    services = []
    err = error or None
    try:
        services = cool.list_services()
    except Exception as e:
        err = f"No se pudo listar services de Coolify: {e}"
    # Para cada service, intentamos enriquecerlo con sus sub-applications
    enriched = []
    for s in services:
        uuid = s.get("uuid")
        item = {
            "uuid": uuid,
            "name": s.get("name", uuid),
            "type": s.get("service_type") or s.get("type") or "compose",
            "status": s.get("status", "?"),
            "apps": [],
        }
        try:
            detail = cool.get_service(uuid)
            for a in cool.service_applications(detail):
                item["apps"].append({
                    "name": a.get("name") or a.get("human_name"),
                    "image": a.get("image", ""),
                    "fqdn": a.get("fqdn", ""),
                    "ports": a.get("ports", ""),
                })
        except Exception:
            pass
        enriched.append(item)
    return request.app.state.templates.TemplateResponse(
        "install_coolify_service.html",
        {"request": request, "services": enriched, "error": err,
         "default_host_port": config.COOLIFY_PORT_START}
    )


@router.post("/sites/new/coolify-service", response_class=HTMLResponse)
async def coolify_service_create(
    request: Request,
    subdomain: str = Form(...),
    service_uuid: str = Form(...),
    service_app_name: str = Form(""),
    host_port: int = Form(...),
    container_port: int = Form(...),
    display_name: str = Form(""),
):
    log: list = []
    try:
        sub = ng.validate_subdomain(subdomain)
    except Exception as e:
        return RedirectResponse(f"/sites/new/coolify-service?error={e}", status_code=303)
    fqdn = ng.fqdn_for(sub)

    if host_port < 1024 or host_port > 65535:
        return RedirectResponse(
            "/sites/new/coolify-service?error=host_port-fuera-de-rango",
            status_code=303,
        )

    with dbm.session_scope() as s:
        existing = s.execute(select(dbm.Site).where(dbm.Site.subdomain == sub)).scalar_one_or_none()
        if existing:
            return RedirectResponse(
                f"/sites/new/coolify-service?error=ya-existe-{sub}", status_code=303
            )
        site = dbm.Site(
            subdomain=sub, fqdn=fqdn, type="coolify_service", status="creating",
            coolify_uuid=service_uuid, coolify_port=host_port,
        )
        s.add(site); s.flush()
        op = _new_op(s, site.id, "create_coolify_service")
        site_id = site.id

    success = False
    service_info = {}
    try:
        # 1. Validar que el service existe en Coolify (best effort)
        try:
            service_info = cool.get_service(service_uuid)
            log.append(
                f"Service Coolify: {service_info.get('name')} "
                f"(status={service_info.get('status')})"
            )
        except Exception as e:
            log.append(f"WARN: no pude leer detalle del service: {e}")
        # 2. Vhost nginx (proxy 127.0.0.1:host_port)
        vhost = ng.render_vhost_proxy(fqdn, host_port)
        ng.write_vhost(fqdn, vhost, log)
        ng.reload_nginx(log)
        success = True
    except Exception as e:
        log.append(f"ERROR: {e}")

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        site.status = "ready" if success else "failed"
        site.extra = {
            "service_uuid": service_uuid,
            "service_name": service_info.get("name") if service_info else None,
            "service_type": service_info.get("service_type") if service_info else None,
            "service_app_name": service_app_name or None,
            "container_port": container_port,
            "host_port": host_port,
            "display_name": display_name or None,
        }
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
        sites_for_landing = _all_sites(s)
    if success:
        try:
            land.regenerate_landing(sites_for_landing, log)
        except Exception:
            pass
    return RedirectResponse(f"/sites/{site_id}", status_code=303)


# ---------------- DETALLE ----------------

@router.get("/sites/{site_id}", response_class=HTMLResponse)
async def site_detail(request: Request, site_id: int):
    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        if not site:
            raise HTTPException(404)
        ops = s.execute(
            select(dbm.Operation).where(dbm.Operation.site_id == site_id)
            .order_by(desc(dbm.Operation.id))
        ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        "site_detail.html",
        {
            "request": request,
            "site": site,
            "operations": ops,
            "php_versions": list(config.PHP_VERSIONS.keys()),
            "php_change_msg": request.query_params.get("php_msg"),
            "php_change_ok": request.query_params.get("php_ok") == "1",
        },
    )


@router.post("/sites/{site_id}/set-php")
async def site_set_php(request: Request, site_id: int, php_version: str = Form(...)):
    if php_version not in config.PHP_VERSIONS:
        return RedirectResponse(
            f"/sites/{site_id}?php_msg=versi%C3%B3n+inv%C3%A1lida&php_ok=0",
            status_code=303,
        )
    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        if not site:
            raise HTTPException(404)
        if not site.php_version:
            return RedirectResponse(
                f"/sites/{site_id}?php_msg=el+sitio+no+es+PHP&php_ok=0",
                status_code=303,
            )
        if site.php_version == php_version:
            return RedirectResponse(
                f"/sites/{site_id}?php_msg=ya+est%C3%A1+en+esa+versi%C3%B3n&php_ok=1",
                status_code=303,
            )
        fqdn = site.fqdn
        prev = site.php_version

    op_log: list[str] = [f"Cambio PHP {prev} -> {php_version} en {fqdn}"]
    ok, msg = svc.set_php_version_for_vhost(fqdn, php_version)
    op_log.append(msg or ("OK" if ok else "fallo"))

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        op = _new_op(s, site_id, "set_php_version")
        _finish_op(s, op, ok, op_log)
        if ok:
            site.php_version = php_version
            s.add(site)

    if ok:
        url = f"/sites/{site_id}?php_msg=PHP+actualizado+a+{php_version}&php_ok=1"
    else:
        from urllib.parse import quote
        url = f"/sites/{site_id}?php_msg={quote(msg or 'error')}&php_ok=0"
    return RedirectResponse(url, status_code=303)


# ---------------- ELIMINAR ----------------

@router.post("/sites/{site_id}/delete", response_class=HTMLResponse)
async def site_delete(request: Request, site_id: int, confirm: str = Form(...)):
    log: list = []
    if confirm.strip().lower() != "borrar":
        return RedirectResponse(f"/sites/{site_id}?delete_error=confirmacion-invalida",
                                 status_code=303)
    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        if not site:
            raise HTTPException(404)
        op = _new_op(s, site_id, "delete_with_backup")
        site_dict = {"subdomain": site.subdomain, "fqdn": site.fqdn,
                     "type": site.type, "db_name": site.db_name, "db_user": site.db_user,
                     "docroot": site.docroot, "coolify_uuid": site.coolify_uuid}

    success = False
    try:
        # 1. Backup
        class _S: pass
        st = _S()
        for k, v in site_dict.items(): setattr(st, k, v)
        bk.backup_site(st, log)
        # 2. Coolify cleanup si aplica (solo apps tipo 'coolify' con repo;
        #    para 'coolify_service' el service vive más allá del vhost
        #    y se gestiona desde la UI de Coolify)
        if site_dict.get("type") == "coolify" and site_dict.get("coolify_uuid"):
            try:
                cool.delete_application(site_dict["coolify_uuid"])
                log.append("coolify app deleted")
            except Exception as e:
                log.append(f"coolify delete failed: {e}")
        elif site_dict.get("type") == "coolify_service":
            log.append("coolify_service: solo se quita el vhost; el service en Coolify se conserva")
        # 3. nginx
        ng.remove_vhost(site_dict["fqdn"], log)
        ng.reload_nginx(log)
        # 4. BD
        my.drop_db_and_user(site_dict.get("db_name"), site_dict.get("db_user"), log)
        # 5. Filesystem
        if site_dict.get("docroot"):
            fs.remove_docroot(site_dict["docroot"], log)
        success = True
    except Exception as e:
        log.append(f"ERROR borrado: {e}")

    with dbm.session_scope() as s:
        site = s.get(dbm.Site, site_id)
        site.status = "deleted" if success else "failed"
        op = s.execute(select(dbm.Operation).where(dbm.Operation.site_id == site_id)
                       .order_by(desc(dbm.Operation.id))).scalars().first()
        _finish_op(s, op, success, log)
        s.add(site)
        sites_for_landing = _all_sites(s)
    if success:
        try:
            land.regenerate_landing(sites_for_landing, log)
        except Exception:
            pass
    return RedirectResponse("/", status_code=303)
