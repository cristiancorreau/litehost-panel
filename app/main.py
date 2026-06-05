from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from . import db as dbm, config
from .auth import require_admin
from .routes import sites as sites_routes
from .routes import services as services_routes
from .routes import restore as restore_routes
from .routes import metrics as metrics_routes
from .routes import files as files_routes
from .routes import docs as docs_routes

app = FastAPI(title="Server Panel", version="1.0",
              docs_url=None, redoc_url=None, openapi_url=None)
app.state.templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
def _startup():
    dbm.init_db()
    config.DOCS_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    from .seed_docs import seed_initial_docs
    seed_initial_docs()


# /architecture viejo → /docs/architecture (redirect permanente)
from fastapi.responses import RedirectResponse as _Redirect
@app.get("/architecture", include_in_schema=False)
def _legacy_architecture():
    return _Redirect("/docs/architecture", status_code=301)


# health check público (no requiere auth)
@app.get("/healthz")
def healthz():
    return {"ok": True}


# todo lo demás detrás de auth
app.include_router(sites_routes.router)
app.include_router(services_routes.router)
app.include_router(restore_routes.router)
app.include_router(metrics_routes.router)
app.include_router(files_routes.router)
app.include_router(docs_routes.router)


# Filtro datetimeformat para epoch → string
def _datetimeformat(value):
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""

app.state.templates.env.filters["datetimeformat"] = _datetimeformat
