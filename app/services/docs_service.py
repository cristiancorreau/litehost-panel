"""Helpers para la mini-wiki en /docs:
- slugify de títulos
- render markdown → HTML (con bloques mermaid intactos)
- almacenamiento de assets subidos (imágenes, pdfs, etc.) por slug
"""
import re
import secrets
from pathlib import Path
import markdown as md
from .. import config


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, max_len: int = 80) -> str:
    s = (value or "").strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    return (s or "doc")[:max_len]


def render_markdown(text: str) -> str:
    extensions = [
        "fenced_code",
        "tables",
        "sane_lists",
        "toc",
        "admonition",
        "codehilite",
        "attr_list",
    ]
    html = md.markdown(
        text or "",
        extensions=extensions,
        extension_configs={"codehilite": {"guess_lang": False, "css_class": "codehilite"}},
        output_format="html5",
    )
    return html


# ---------------- assets (uploads dentro de un doc) ----------------

ALLOWED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".txt", ".md", ".csv", ".log",
    ".zip", ".tar", ".gz",
}
MAX_BYTES = 25 * 1024 * 1024  # 25 MB por archivo


def assets_dir(slug: str) -> Path:
    d = config.DOCS_ASSETS_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_filename(original: str) -> str:
    """Devuelve un nombre seguro: prefijo aleatorio + nombre saneado."""
    base = Path(original or "file").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "file"
    if "." not in base:
        base = base + ".bin"
    name, ext = base.rsplit(".", 1)
    ext = ext.lower()
    if ("." + ext) not in ALLOWED_EXTS:
        raise ValueError(f"Tipo de archivo no permitido: .{ext}")
    rnd = secrets.token_hex(4)
    return f"{rnd}-{name[:60]}.{ext}"


async def save_upload(slug: str, upload, original_name: str) -> dict:
    """Guarda un UploadFile en disco. Retorna {filename, url, size, content_type}."""
    target_dir = assets_dir(slug)
    fname = safe_filename(original_name)
    target = target_dir / fname
    written = 0
    with target.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_BYTES:
                f.close()
                target.unlink(missing_ok=True)
                raise ValueError(f"Archivo > {MAX_BYTES // (1024 * 1024)} MB")
            f.write(chunk)
    return {
        "filename": fname,
        "url": f"/docs/{slug}/asset/{fname}",
        "size": written,
        "content_type": getattr(upload, "content_type", None),
    }


def list_assets(slug: str) -> list[dict]:
    d = config.DOCS_ASSETS_DIR / slug
    if not d.exists():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if p.is_file():
            out.append({
                "filename": p.name,
                "url": f"/docs/{slug}/asset/{p.name}",
                "size": p.stat().st_size,
            })
    return out


def delete_asset(slug: str, filename: str) -> bool:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    p = config.DOCS_ASSETS_DIR / slug / safe
    if p.is_file() and p.parent == config.DOCS_ASSETS_DIR / slug:
        p.unlink()
        return True
    return False


def asset_path(slug: str, filename: str) -> Path | None:
    """Retorna el path absoluto del asset si existe y está dentro del docs root."""
    safe_slug = slugify(slug)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    p = (config.DOCS_ASSETS_DIR / safe_slug / safe_name).resolve()
    root = config.DOCS_ASSETS_DIR.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    return p if p.is_file() else None
