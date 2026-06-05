"""Rutas: estado de servicios, acciones reload/restart, configuración FPM, logs, phpinfo."""
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from .. import config
from ..auth import require_admin
from ..services import services_service as svc

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/services", response_class=HTMLResponse)
async def services_page(request: Request, message: str = "", error: str = ""):
    rows = svc.all_status()
    return request.app.state.templates.TemplateResponse(
        "services.html",
        {"request": request, "rows": rows, "message": message, "error": error,
         "php_versions": list(config.PHP_VERSIONS.keys())}
    )


@router.post("/services/{service_name}/{action}")
async def services_action(request: Request, service_name: str, action: str):
    ok, msg = svc.action(service_name, action)
    qs = ("message" if ok else "error") + "=" + msg.replace("\n", " ")[:200]
    return RedirectResponse(f"/services?{qs}", status_code=303)


@router.get("/services/fpm/{version}/config", response_class=HTMLResponse)
async def fpm_config_get(request: Request, version: str):
    cfg = svc.get_fpm_config(version)
    return request.app.state.templates.TemplateResponse(
        "fpm_config.html",
        {"request": request, "version": version, "cfg": cfg}
    )


@router.post("/services/fpm/{version}/config")
async def fpm_config_set(request: Request, version: str,
                          key: str = Form(...), value: str = Form(...)):
    ok, msg = svc.set_fpm_config(version, key, value)
    return RedirectResponse(f"/services/fpm/{version}/config", status_code=303)


@router.get("/services/phpinfo/{version}", response_class=PlainTextResponse)
async def phpinfo(version: str):
    return svc.phpinfo(version)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, kind: str = "nginx-error", fqdn: str = "", lines: int = 200):
    if kind not in ("nginx-access", "nginx-error"):
        kind = "nginx-error"
    content = svc.tail_log(kind, fqdn, lines) if (kind or fqdn) else ""
    return request.app.state.templates.TemplateResponse(
        "logs.html",
        {"request": request, "kind": kind, "fqdn": fqdn, "lines": lines, "content": content}
    )


@router.get("/vhost/{fqdn}", response_class=HTMLResponse)
async def vhost_detail(request: Request, fqdn: str):
    """Detalle de un vhost externo (sin record en DB) — permite cambiar PHP, ver logs."""
    from ..services import nginx_inventory as ngi
    entries = ngi.list_vhosts()
    found = None
    for v in entries:
        if any(n.lower().rstrip(".") == fqdn.lower() for n in v.server_names):
            found = v; break
    if not found:
        raise HTTPException(404, f"vhost no encontrado: {fqdn}")
    return request.app.state.templates.TemplateResponse(
        "vhost_detail.html",
        {"request": request, "fqdn": fqdn, "vhost": found,
         "php_versions": list(config.PHP_VERSIONS.keys())}
    )


@router.post("/vhost/{fqdn}/php")
async def vhost_change_php(request: Request, fqdn: str, version: str = Form(...)):
    ok, msg = svc.set_php_version_for_vhost(fqdn, version)
    return RedirectResponse(f"/vhost/{fqdn}", status_code=303)
