"""Inventario en vivo de vhosts en /etc/nginx/sites-enabled/."""
from dataclasses import dataclass
from typing import Optional
from .runner import run_sudo


@dataclass
class VhostEntry:
    filename: str
    server_names: list[str]
    type: str          # php | proxy | static | other
    ssl: bool
    root: Optional[str]
    php_version: Optional[str] = None

    @property
    def primary_fqdn(self) -> Optional[str]:
        for n in self.server_names:
            if "." in n and not n.startswith("_"):
                return n.rstrip(".")
        return self.server_names[0] if self.server_names else None


def list_vhosts() -> list[VhostEntry]:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "list-vhosts"])
    if rc != 0:
        return []
    entries: list[VhostEntry] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        filename, names_str, type_, ssl_, root_ = parts[0], parts[1], parts[2], parts[3], parts[4]
        php_ver = parts[5] if len(parts) >= 6 and parts[5] else None
        names = [n for n in names_str.split() if n]
        entries.append(VhostEntry(
            filename=filename,
            server_names=names,
            type=type_,
            ssl=ssl_ == "yes",
            root=root_ or None,
            php_version=php_ver,
        ))
    return entries


def existing_fqdns() -> set[str]:
    """Set con TODOS los server_names que ya están en sites-enabled."""
    out: set[str] = set()
    for v in list_vhosts():
        for n in v.server_names:
            if n and n != "_":
                out.add(n.rstrip(".").lower())
    return out


def find_by_subdomain(subdomain: str, lab_domain: str) -> Optional[VhostEntry]:
    """Busca un vhost que sirva <subdomain>.<lab_domain>."""
    target = f"{subdomain}.{lab_domain}".lower()
    for v in list_vhosts():
        if any(n.lower().rstrip(".") == target for n in v.server_names):
            return v
    return None
