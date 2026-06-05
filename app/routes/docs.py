"""Mini-wiki en /docs: crear, editar y servir páginas markdown con assets."""
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy import select, desc, asc
from .. import db as dbm
from ..auth import require_admin
from ..services import docs_service as ds


router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/docs", response_class=HTMLResponse)
async def docs_index(request: Request):
    with dbm.session_scope() as s:
        rows = s.execute(
            select(dbm.Doc).order_by(desc(dbm.Doc.is_pinned), asc(dbm.Doc.title))
        ).scalars().all()
        docs = [{"id": d.id, "slug": d.slug, "title": d.title,
                 "is_pinned": d.is_pinned,
                 "updated_at": d.updated_at} for d in rows]
    return request.app.state.templates.TemplateResponse(
        "docs/index.html", {"request": request, "docs": docs}
    )


@router.get("/docs/new", response_class=HTMLResponse)
async def docs_new(request: Request, error: str = ""):
    return request.app.state.templates.TemplateResponse(
        "docs/edit.html",
        {"request": request, "doc": None, "assets": [],
         "title": "", "slug": "", "content": "", "is_pinned": 0,
         "is_new": True, "error": error or None},
    )


@router.post("/docs/new")
async def docs_new_save(
    request: Request,
    title: str = Form(...),
    slug: str = Form(""),
    content: str = Form(""),
    is_pinned: str = Form(""),
):
    title = title.strip()
    if not title:
        return RedirectResponse("/docs/new?error=titulo-vacio", status_code=303)
    target_slug = ds.slugify(slug or title)
    with dbm.session_scope() as s:
        existing = s.execute(select(dbm.Doc).where(dbm.Doc.slug == target_slug)).scalar_one_or_none()
        if existing:
            return RedirectResponse(
                f"/docs/new?error=slug-en-uso-{target_slug}", status_code=303
            )
        d = dbm.Doc(slug=target_slug, title=title, content=content,
                    is_pinned=1 if is_pinned else 0)
        s.add(d); s.flush()
    return RedirectResponse(f"/docs/{target_slug}", status_code=303)


@router.get("/docs/{slug}", response_class=HTMLResponse)
async def docs_view(request: Request, slug: str):
    with dbm.session_scope() as s:
        d = s.execute(select(dbm.Doc).where(dbm.Doc.slug == slug)).scalar_one_or_none()
        if not d:
            raise HTTPException(404, f"Doc '{slug}' no encontrado")
        ctx = {
            "id": d.id, "slug": d.slug, "title": d.title,
            "content": d.content, "html": ds.render_markdown(d.content),
            "updated_at": d.updated_at, "is_pinned": d.is_pinned,
        }
    return request.app.state.templates.TemplateResponse(
        "docs/view.html",
        {"request": request, "doc": ctx, "assets": ds.list_assets(slug)},
    )


@router.get("/docs/{slug}/edit", response_class=HTMLResponse)
async def docs_edit(request: Request, slug: str, error: str = ""):
    with dbm.session_scope() as s:
        d = s.execute(select(dbm.Doc).where(dbm.Doc.slug == slug)).scalar_one_or_none()
        if not d:
            raise HTTPException(404)
        ctx = {"id": d.id, "slug": d.slug, "title": d.title,
               "content": d.content, "is_pinned": d.is_pinned}
    return request.app.state.templates.TemplateResponse(
        "docs/edit.html",
        {"request": request, "doc": ctx, "assets": ds.list_assets(slug),
         "title": ctx["title"], "slug": ctx["slug"], "content": ctx["content"],
         "is_pinned": ctx["is_pinned"], "is_new": False,
         "error": error or None},
    )


@router.post("/docs/{slug}/edit")
async def docs_edit_save(
    request: Request, slug: str,
    title: str = Form(...),
    new_slug: str = Form(""),
    content: str = Form(""),
    is_pinned: str = Form(""),
):
    with dbm.session_scope() as s:
        d = s.execute(select(dbm.Doc).where(dbm.Doc.slug == slug)).scalar_one_or_none()
        if not d:
            raise HTTPException(404)
        d.title = title.strip() or d.title
        d.content = content
        d.is_pinned = 1 if is_pinned else 0
        target_slug = slug
        if new_slug and ds.slugify(new_slug) != slug:
            cand = ds.slugify(new_slug)
            clash = s.execute(select(dbm.Doc).where(dbm.Doc.slug == cand)).scalar_one_or_none()
            if clash and clash.id != d.id:
                return RedirectResponse(
                    f"/docs/{slug}/edit?error=slug-en-uso-{cand}", status_code=303
                )
            d.slug = cand
            target_slug = cand
        d.updated_at = datetime.utcnow()
        s.add(d)
    return RedirectResponse(f"/docs/{target_slug}", status_code=303)


@router.post("/docs/{slug}/upload")
async def docs_upload(slug: str, file: UploadFile = File(...)):
    with dbm.session_scope() as s:
        d = s.execute(select(dbm.Doc).where(dbm.Doc.slug == slug)).scalar_one_or_none()
        if not d:
            raise HTTPException(404)
    try:
        info = await ds.save_upload(slug, file, file.filename or "file")
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return JSONResponse({"ok": True, **info})


@router.post("/docs/{slug}/asset/{filename}/delete")
async def docs_asset_delete(slug: str, filename: str):
    ok = ds.delete_asset(slug, filename)
    return JSONResponse({"ok": ok})


@router.get("/docs/{slug}/asset/{filename}")
async def docs_serve_asset(slug: str, filename: str):
    p = ds.asset_path(slug, filename)
    if not p:
        raise HTTPException(404)
    return FileResponse(str(p))


@router.post("/docs/{slug}/delete")
async def docs_delete(slug: str, confirm: str = Form(...)):
    if confirm.strip().lower() != "borrar":
        return RedirectResponse(f"/docs/{slug}?delete_error=confirmacion-invalida", status_code=303)
    with dbm.session_scope() as s:
        d = s.execute(select(dbm.Doc).where(dbm.Doc.slug == slug)).scalar_one_or_none()
        if d:
            s.delete(d)
    # No borramos los assets del FS (por seguridad / recuperación). El admin puede limpiarlos a mano.
    return RedirectResponse("/docs", status_code=303)
