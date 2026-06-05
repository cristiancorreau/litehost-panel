from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from ..auth import require_admin
from ..services import metrics_service as ms

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "metrics.html", {"request": request}
    )


@router.get("/api/metrics")
async def metrics_api():
    return JSONResponse(ms.current())
