"""File manager: navegar, ver, editar, subir, crear/borrar/renombrar bajo /var/www."""
import os
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, PlainTextResponse, Response
from .. import config
from ..auth import require_admin
from ..services import files_service as fsvc
from ..services import filesystem_service as fs
from ..services.runner import run_sudo

router = APIRouter(dependencies=[Depends(require_admin)])

WWW = str(config.WWW_ROOT)


def _safe_path(rel: str) -> str:
    """Resuelve un path relativo bajo /var/www. Sin escape."""
    rel = (rel or "").lstrip("/").rstrip("/")
    full = os.path.normpath(os.path.join(WWW, rel)) if rel else WWW
    rp = os.path.realpath(full)
    if not (rp == WWW or rp.startswith(WWW + "/")):
        raise HTTPException(400, "path inválido")
    return rp


def _rel(full: str) -> str:
    if full == WWW:
        return ""
    if full.startswith(WWW + "/"):
        return full[len(WWW) + 1:]
    raise HTTPException(400, "path fuera de /var/www")


def _breadcrumbs(rel: str) -> list[dict]:
    parts = [{"name": "/var/www", "rel": ""}]
    if not rel:
        return parts
    cum = ""
    for piece in rel.split("/"):
        cum = cum + "/" + piece if cum else piece
        parts.append({"name": piece, "rel": cum})
    return parts


@router.get("/files", response_class=HTMLResponse)
async def files_index(request: Request, path: str = "", error: str = "", message: str = ""):
    full = _safe_path(path)
    rel = _rel(full)
    try:
        entries = fsvc.list_dir(full)
    except Exception as e:
        raise HTTPException(400, str(e))

    parent_rel = "/".join(rel.split("/")[:-1]) if rel and "/" in rel else ""

    return request.app.state.templates.TemplateResponse(
        "files.html",
        {
            "request": request,
            "rel": rel,
            "full": full,
            "entries": entries,
            "breadcrumbs": _breadcrumbs(rel),
            "parent_rel": parent_rel,
            "is_root": rel == "",
            "error": error or None,
            "message": message or None,
        },
    )


@router.get("/files/view", response_class=HTMLResponse)
async def files_view(request: Request, path: str):
    full = _safe_path(path)
    if not os.path.isfile(full):
        raise HTTPException(400, "no es archivo")
    rel = _rel(full)
    parent_rel = "/".join(rel.split("/")[:-1]) if "/" in rel else ""
    name = os.path.basename(full)
    ext = Path(full).suffix.lower()
    is_image = ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"}
    is_text = (ext in {".html", ".htm", ".css", ".js", ".mjs", ".ts", ".tsx", ".jsx",
                       ".php", ".py", ".rb", ".go", ".rs", ".sh", ".md", ".txt", ".json",
                       ".xml", ".yml", ".yaml", ".toml", ".ini", ".env", ".conf", ".log",
                       ".sql", ".csv", ".tsv", ".vue", ".svg"} or
               name.lower() in {"dockerfile", "makefile", ".env", ".gitignore", ".htaccess"})
    content = ""
    error = None
    if is_text:
        try:
            content = fsvc.read_file(full)
        except Exception as e:
            error = str(e)
    return request.app.state.templates.TemplateResponse(
        "files_view.html",
        {
            "request": request, "rel": rel, "full": full, "name": name,
            "parent_rel": parent_rel, "is_image": is_image, "is_text": is_text,
            "content": content, "size": os.path.getsize(full) if os.path.exists(full) else 0,
            "error": error, "ext": ext,
        },
    )


@router.post("/files/save")
async def files_save(request: Request, path: str = Form(...), content: str = Form(...)):
    full = _safe_path(path)
    try:
        fsvc.write_file(full, content)
    except Exception as e:
        return RedirectResponse(f"/files/view?path={quote(_rel(full))}&error={e}", status_code=303)
    return RedirectResponse(f"/files/view?path={quote(_rel(full))}", status_code=303)


@router.get("/files/download")
async def files_download(path: str):
    full = _safe_path(path)
    if not os.path.isfile(full):
        raise HTTPException(404)
    return FileResponse(full, filename=os.path.basename(full))


@router.get("/files/raw")
async def files_raw(path: str):
    """Sirve binarios pequeños inline (para preview de imágenes)."""
    full = _safe_path(path)
    if not os.path.isfile(full):
        raise HTTPException(404)
    if os.path.getsize(full) > 20 * 1024 * 1024:
        raise HTTPException(413)
    return FileResponse(full)


@router.post("/files/mkdir")
async def files_mkdir(path: str = Form(...), name: str = Form(...)):
    parent = _safe_path(path)
    name = name.strip().strip("/")
    if not name or "/" in name or name in (".", ".."):
        return RedirectResponse(f"/files?path={quote(_rel(parent))}&error=nombre-invalido", status_code=303)
    target = os.path.join(parent, name)
    try:
        fsvc.mkdir(target)
    except Exception as e:
        return RedirectResponse(f"/files?path={quote(_rel(parent))}&error={e}", status_code=303)
    return RedirectResponse(f"/files?path={quote(_rel(parent))}&message=carpeta-creada", status_code=303)


@router.post("/files/delete")
async def files_delete(path: str = Form(...), confirm: str = Form(...)):
    full = _safe_path(path)
    if confirm != "borrar":
        return RedirectResponse(f"/files?path={quote(_rel(os.path.dirname(full)))}&error=confirmacion", status_code=303)
    parent_rel = _rel(os.path.dirname(full))
    try:
        fsvc.remove(full)
    except Exception as e:
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error={e}", status_code=303)
    return RedirectResponse(f"/files?path={quote(parent_rel)}&message=eliminado", status_code=303)


@router.post("/files/rename")
async def files_rename(path: str = Form(...), new_name: str = Form(...)):
    full = _safe_path(path)
    new_name = new_name.strip().strip("/")
    if not new_name or "/" in new_name or new_name in (".", ".."):
        parent_rel = _rel(os.path.dirname(full))
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error=nombre-invalido", status_code=303)
    new_full = os.path.join(os.path.dirname(full), new_name)
    parent_rel = _rel(os.path.dirname(full))
    try:
        fsvc.rename(full, new_full)
    except Exception as e:
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error={e}", status_code=303)
    return RedirectResponse(f"/files?path={quote(parent_rel)}&message=renombrado", status_code=303)


@router.post("/files/chmod")
async def files_chmod(path: str = Form(...), mode: str = Form(...),
                       recursive: str = Form("")):
    full = _safe_path(path)
    parent_rel = _rel(os.path.dirname(full))
    try:
        fsvc.chmod(full, mode.strip(), recursive == "on")
    except Exception as e:
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error={e}", status_code=303)
    return RedirectResponse(f"/files?path={quote(parent_rel)}&message=permisos-actualizados",
                             status_code=303)


@router.post("/files/chown")
async def files_chown(path: str = Form(...), owner: str = Form(...),
                       recursive: str = Form("")):
    full = _safe_path(path)
    parent_rel = _rel(os.path.dirname(full))
    try:
        fsvc.chown(full, owner.strip(), recursive == "on")
    except Exception as e:
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error={e}", status_code=303)
    return RedirectResponse(f"/files?path={quote(parent_rel)}&message=propietario-actualizado",
                             status_code=303)


@router.get("/files/api/stat")
async def files_api_stat(path: str):
    full = _safe_path(path)
    try:
        return fsvc.stat_path(full)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/files/upload")
async def files_upload(path: str = Form(...), uploads: list[UploadFile] = File(...)):
    parent = _safe_path(path)
    parent_rel = _rel(parent)
    saved = 0
    last_err = None
    for f in uploads:
        if not f.filename:
            continue
        # guardar en staging luego mover
        staging_dir = config.UPLOADS_DIR / "fm"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging = staging_dir / f.filename
        try:
            with open(staging, "wb") as out:
                while True:
                    chunk = await f.read(config.UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
            dst = os.path.join(parent, f.filename)
            rc, _, err = run_sudo(["/usr/local/bin/sw-panel-helper", "mv-into-www",
                                    str(staging), dst])
            if rc != 0:
                staging.unlink(missing_ok=True)
                last_err = err
                continue
            saved += 1
        except Exception as e:
            last_err = str(e)
    qs = f"path={quote(parent_rel)}"
    if last_err:
        qs += f"&error=algunos-archivos-fallaron:{last_err[:80]}"
    else:
        qs += f"&message={saved}-archivo(s)-subido(s)"
    return RedirectResponse(f"/files?{qs}", status_code=303)


@router.post("/files/upload-zip")
async def files_upload_zip(path: str = Form(...), zipfile_: UploadFile = File(..., alias="zip")):
    parent = _safe_path(path)
    parent_rel = _rel(parent)
    if not zipfile_.filename:
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error=sin-archivo", status_code=303)
    staging = config.UPLOADS_DIR / "fm" / zipfile_.filename
    staging.parent.mkdir(parents=True, exist_ok=True)
    with open(staging, "wb") as out:
        while True:
            chunk = await zipfile_.read(config.UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
    ok, msg, n = fs.validate_zip(str(staging))
    if not ok:
        staging.unlink(missing_ok=True)
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error=zip-invalido:{msg}",
                                 status_code=303)
    try:
        fs.extract_zip_into_docroot(str(staging), parent, [])
    except Exception as e:
        return RedirectResponse(f"/files?path={quote(parent_rel)}&error={e}", status_code=303)
    return RedirectResponse(f"/files?path={quote(parent_rel)}&message={n}-archivos-extraidos",
                             status_code=303)
