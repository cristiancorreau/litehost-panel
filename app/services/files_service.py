"""Operaciones del file manager bajo /var/www. Todo pasa por el helper sudo."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from .runner import run_sudo
from .. import config


@dataclass
class Entry:
    name: str
    kind: str       # dir | file | link | other
    size: int
    mtime: int      # epoch
    mode: str       # octal '755'

    @property
    def is_text(self) -> bool:
        if self.kind != "file":
            return False
        # heurística por extensión
        text_exts = {".html", ".htm", ".css", ".js", ".mjs", ".ts", ".tsx", ".jsx",
                     ".php", ".py", ".rb", ".go", ".rs", ".sh", ".md", ".txt", ".json",
                     ".xml", ".yml", ".yaml", ".toml", ".ini", ".env", ".conf", ".log",
                     ".sql", ".csv", ".tsv", ".vue", ".svg", ".htaccess"}
        return Path(self.name).suffix.lower() in text_exts or self.name.lower() in {
            "dockerfile", "makefile", ".env", ".gitignore", ".htaccess"
        }

    @property
    def is_image(self) -> bool:
        return self.kind == "file" and Path(self.name).suffix.lower() in {
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"
        }


def _is_safe_under_www(p: str) -> bool:
    try:
        rp = Path(p).resolve()
    except (RuntimeError, ValueError):
        return False
    return str(rp).startswith(str(config.WWW_ROOT) + "/") or str(rp) == str(config.WWW_ROOT)


def list_dir(path: str) -> list[Entry]:
    if not _is_safe_under_www(path):
        raise PermissionError(f"path fuera de /var/www: {path}")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "list-dir", path])
    if rc != 0:
        raise RuntimeError(err.strip() or "list-dir failed")
    entries: list[Entry] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        try:
            entries.append(Entry(
                name=parts[0], kind=parts[1],
                size=int(parts[2] or 0), mtime=int(parts[3] or 0), mode=parts[4],
            ))
        except ValueError:
            continue
    # Carpetas primero, luego archivos, ambos alfabético case-insensitive
    entries.sort(key=lambda e: (0 if e.kind == "dir" else 1, e.name.lower()))
    return entries


def read_file(path: str) -> str:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "read-www-file", path])
    if rc != 0:
        raise RuntimeError(err.strip() or "read failed")
    return out


def write_file(path: str, content: str) -> None:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "write-www-file", path],
                             input_text=content)
    if rc != 0:
        raise RuntimeError(err.strip() or "write failed")


def mkdir(path: str) -> None:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "mkdir-www", path])
    if rc != 0:
        raise RuntimeError(err.strip() or "mkdir failed")


def remove(path: str) -> None:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "rm-www", path])
    if rc != 0:
        raise RuntimeError(err.strip() or "rm failed")


def rename(src: str, dst: str) -> None:
    if not _is_safe_under_www(src) or not _is_safe_under_www(dst):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "rename-www", src, dst])
    if rc != 0:
        raise RuntimeError(err.strip() or "rename failed")


def chmod(path: str, mode: str, recursive: bool = False) -> None:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo([
        "/usr/local/bin/sw-panel-helper", "chmod-www", path, mode,
        "yes" if recursive else "no",
    ])
    if rc != 0:
        raise RuntimeError(err.strip() or "chmod failed")


def chown(path: str, owner: str, recursive: bool = False) -> None:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo([
        "/usr/local/bin/sw-panel-helper", "chown-www", path, owner,
        "yes" if recursive else "no",
    ])
    if rc != 0:
        raise RuntimeError(err.strip() or "chown failed")


def stat_path(path: str) -> dict:
    """Retorna {mode, user, group, owner_str}."""
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "stat-www", path])
    if rc != 0:
        raise RuntimeError(err.strip() or "stat failed")
    parts = out.strip().split("|")
    if len(parts) != 4:
        raise RuntimeError("stat unexpected output")
    return {"mode": parts[0], "user": parts[1], "group": parts[2], "owner": parts[3]}


def put_file(path: str, content: bytes) -> None:
    if not _is_safe_under_www(path):
        raise PermissionError("path fuera de /var/www")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "put-www-file", path],
                             input_text=content.decode("latin1"))
    if rc != 0:
        raise RuntimeError(err.strip() or "put failed")
