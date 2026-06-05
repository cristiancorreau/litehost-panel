"""Operaciones de filesystem que requieren sudo se delegan al helper."""
from pathlib import Path
from .runner import run_sudo


def make_docroot(path: str, owner: str = "www-data:www-data", log: list = None) -> None:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "make-docroot", path, owner])
    if log is not None:
        log.append(f"make-docroot {path}: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"No se pudo crear docroot {path}: {err}")


def remove_docroot(path: str, log: list) -> None:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "remove-docroot", path])
    log.append(f"remove-docroot {path}: rc={rc} {err}")


def chown_recursive(path: str, owner: str, log: list) -> None:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "chown-r", owner, path])
    log.append(f"chown -R {owner} {path}: rc={rc} {err}")


def write_file(path: str, content: str, log: list, owner: str = "www-data:www-data") -> None:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "write-file", path, owner], input_text=content)
    log.append(f"write-file {path}: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"No se pudo escribir {path}: {err}")


def validate_zip(zip_path: str) -> tuple[bool, str, int]:
    """Verifica que el ZIP no tenga paths peligrosos. Retorna (ok, msg, num_files)."""
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as zf:
            count = 0
            for info in zf.infolist():
                name = info.filename
                if name.startswith("/") or name.startswith("\\"):
                    return False, f"ruta absoluta no permitida: {name}", 0
                if ".." in name.replace("\\", "/").split("/"):
                    return False, f"path traversal detectado: {name}", 0
                count += 1
            return True, "ok", count
    except zipfile.BadZipFile:
        return False, "archivo no es un ZIP válido", 0
    except Exception as e:
        return False, f"error leyendo zip: {e}", 0


def inspect_zip(zip_path: str, max_entries: int = 500) -> dict:
    """Lee el contenido del ZIP y devuelve estructura útil para mostrar al usuario:
       - entries: lista de nombres (archivos y carpetas), ordenada
       - total: cantidad total de entries
       - top_level: set de directorios/archivos en el primer nivel
       - wrapped_in: nombre del dir único top-level si aplica, sino None
       - has_index_root: True si index.html está en la raíz del ZIP
       - size_uncompressed: bytes
    """
    import zipfile
    res = {
        "entries": [],
        "total": 0,
        "top_level": set(),
        "wrapped_in": None,
        "has_index_root": False,
        "size_uncompressed": 0,
    }
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            res["total"] = len(infos)
            for info in infos:
                name = info.filename.rstrip("/")
                if not name:
                    continue
                if any(name.startswith(p) for p in ("__MACOSX/", ".DS_Store")) or name.endswith(".DS_Store"):
                    continue
                # primer segmento
                first = name.split("/", 1)[0]
                res["top_level"].add(first)
                res["size_uncompressed"] += info.file_size
                if name.lower() == "index.html":
                    res["has_index_root"] = True
            entries = sorted(set(
                e.filename for e in infos
                if e.filename and not e.filename.startswith("__MACOSX/")
                and not e.filename.endswith(".DS_Store")
            ))
            res["entries"] = entries[:max_entries]
            # Wrapping: si solo hay un top-level Y es directorio (todos los otros entries lo tienen como prefijo)
            tl = list(res["top_level"])
            if len(tl) == 1:
                only = tl[0]
                # Verificar que es un directorio (existen archivos bajo él)
                if any(e.startswith(only + "/") for e in entries):
                    res["wrapped_in"] = only
            res["top_level"] = sorted(res["top_level"])
        return res
    except Exception as e:
        res["error"] = str(e)
        return res


def extract_zip_into_docroot(zip_path: str, docroot: str, log: list) -> None:
    """Extrae el ZIP en el docroot vía helper sudo. El zip se borra al terminar."""
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "unzip-into-www",
                              zip_path, docroot])
    log.append(f"unzip {zip_path} → {docroot}: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"unzip falló: {err}")
