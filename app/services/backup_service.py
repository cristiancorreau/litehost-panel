"""Respaldo y restauración de sitios."""
import datetime
import re
from pathlib import Path
from .. import config
from .runner import run_sudo


def backup_site(site, log: list) -> dict:
    """Genera dump SQL + tar del docroot. Retorna {db_dump, files_tar}."""
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base = config.BACKUPS_DIR / site.subdomain
    db_dump = base / f"{site.db_name or site.subdomain}_{ts}.sql"
    files_tar = base / f"{site.subdomain}_files_{ts}.tar.gz"

    if site.db_name:
        rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "mysqldump",
                                 site.db_name, str(db_dump)])
        log.append(f"backup mysqldump {site.db_name}: rc={rc} {err}")

    if site.docroot:
        rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "tar-backup",
                                 site.docroot, str(files_tar)])
        log.append(f"backup tar {site.docroot}: rc={rc} {err}")

    return {"db_dump": str(db_dump), "files_tar": str(files_tar)}


_TS_RE = re.compile(r"_(\d{8}_\d{6})\.(sql|tar\.gz)$")


def list_backups() -> list[dict]:
    """Devuelve lista de backups agrupados por subdominio + timestamp.
    Cada entry: {subdomain, ts, dump, tar, dump_size, tar_size, mtime}.
    """
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "list-backups"])
    if rc != 0:
        return []

    by_pair: dict[tuple, dict] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 4:
            continue
        sub, fname, size, mtime = parts[0], parts[1], int(parts[2]), int(parts[3])
        m = _TS_RE.search(fname)
        if not m:
            continue
        ts, ext = m.group(1), m.group(2)
        key = (sub, ts)
        full = str(config.BACKUPS_DIR / sub / fname)
        entry = by_pair.setdefault(key, {
            "subdomain": sub, "ts": ts, "dump": None, "tar": None,
            "dump_size": 0, "tar_size": 0, "mtime": mtime,
        })
        if ext == "sql":
            entry["dump"] = full
            entry["dump_size"] = size
        else:
            entry["tar"] = full
            entry["tar_size"] = size
        entry["mtime"] = max(entry["mtime"], mtime)

    return sorted(by_pair.values(), key=lambda x: -x["mtime"])


def import_db_dump(db_name: str, dump_path: str, log: list) -> bool:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "mysql-import",
                              db_name, dump_path])
    log.append(f"mysql-import {db_name} ← {dump_path}: rc={rc} {err}")
    return rc == 0


def extract_tar_into_docroot(tar_path: str, docroot: str, log: list) -> bool:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "tar-extract-into-www",
                              tar_path, docroot])
    log.append(f"tar-extract {tar_path} → {docroot}: rc={rc} {err}")
    return rc == 0
