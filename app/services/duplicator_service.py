"""Restauración desde Duplicator: recibe installer.php + archive.daf, prepara BD vacía
y deja todo en el docroot. El usuario completa el wizard del propio Duplicator."""
from pathlib import Path
from fastapi import UploadFile
from .runner import run_sudo
from .. import config


async def save_upload(upload: UploadFile, dest: Path, log: list) -> int:
    """Guarda un upload a un path temporal. Retorna bytes escritos."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await upload.read(config.UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    log.append(f"upload {upload.filename} → {dest}: {total} bytes")
    return total


def move_to_docroot(temp_paths: list[Path], docroot: str, log: list) -> None:
    """Mueve los archivos del staging temporal al docroot vía helper sudo."""
    for src in temp_paths:
        dst = f"{docroot}/{src.name}"
        rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "mv-into-www", str(src), dst])
        log.append(f"mv {src} → {dst}: rc={rc} {err}")
        if rc != 0:
            raise RuntimeError(f"mv falló: {err}")
