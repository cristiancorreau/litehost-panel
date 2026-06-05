"""Operaciones sobre servicios systemd: nginx + cada php-fpm."""
from .runner import run_sudo
from .. import config


PHP_FPM_SERVICES = [f"php{v}-fpm" for v in config.PHP_VERSIONS.keys()]
ALLOWED_SERVICES = ["nginx"] + PHP_FPM_SERVICES


def status(svc: str) -> dict:
    if svc not in ALLOWED_SERVICES:
        return {"name": svc, "active": "unknown", "ok": False, "error": "service no permitido"}
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "service-is-active", svc])
    return {"name": svc, "active": (out.strip() or "unknown"), "ok": rc == 0}


def all_status() -> list[dict]:
    return [status(s) for s in ALLOWED_SERVICES]


def action(svc: str, act: str) -> tuple[bool, str]:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "service-action", svc, act])
    msg = (out + err).strip()
    return rc == 0, msg


def get_fpm_config(ver: str) -> dict:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "fpm-config-get", ver])
    cfg = {}
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith(";"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def set_fpm_config(ver: str, key: str, value: str) -> tuple[bool, str]:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "fpm-config-set",
                              ver, key, value])
    msg = (out + err).strip()
    return rc == 0, msg


def tail_log(kind: str, fqdn: str = "", lines: int = 200) -> str:
    args = ["/usr/local/bin/sw-panel-helper", "tail-log", kind]
    if fqdn:
        args.append(fqdn)
    args.append(str(lines))
    rc, out, err = run_sudo(args)
    return out if rc == 0 else (err or "")


def phpinfo(ver: str) -> str:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "phpinfo", ver])
    return out if rc == 0 else (err or "")


def set_php_version_for_vhost(fqdn: str, version: str) -> tuple[bool, str]:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "set-php-version",
                              fqdn, version])
    msg = (out + err).strip()
    return rc == 0, msg


_disk_cache: dict[str, tuple[float, int]] = {}
_DISK_CACHE_TTL = 300  # 5 min


def disk_usage(paths: list[str], use_cache: bool = True) -> dict[str, int]:
    if not paths:
        return {}
    import time as _t
    now = _t.time()
    res: dict[str, int] = {}
    pending: list[str] = []
    if use_cache:
        for p in paths:
            cached = _disk_cache.get(p)
            if cached and now - cached[0] < _DISK_CACHE_TTL:
                res[p] = cached[1]
            else:
                pending.append(p)
    else:
        pending = list(paths)
    if pending:
        rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "disk-usage", *pending])
        if rc == 0:
            for line in out.splitlines():
                if "|" in line:
                    p, b = line.split("|", 1)
                    try:
                        n = int(b)
                        res[p] = n
                        _disk_cache[p] = (now, n)
                    except ValueError:
                        pass
    return res


def invalidate_disk_cache(path: str | None = None):
    if path is None:
        _disk_cache.clear()
    else:
        _disk_cache.pop(path, None)
