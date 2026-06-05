"""Métricas en vivo del servidor: CPU, memoria, disco, red, procesos."""
import time
import threading
import psutil

_lock = threading.Lock()
_last_disk_io = None      # (timestamp, read_bytes, write_bytes)
_last_net_io = None       # (timestamp, sent_bytes, recv_bytes)


def _delta_rate(prev, current_bytes_a, current_bytes_b, now):
    if prev is None:
        return 0.0, 0.0
    pt, pa, pb = prev
    dt = max(now - pt, 0.001)
    return max(0.0, (current_bytes_a - pa) / dt), max(0.0, (current_bytes_b - pb) / dt)


def current() -> dict:
    """Captura instantánea del sistema. Calcula deltas para I/O."""
    global _last_disk_io, _last_net_io
    now = time.time()

    cpu_percent = psutil.cpu_percent(interval=None)
    per_cpu = psutil.cpu_percent(interval=None, percpu=True)
    load = list(psutil.getloadavg())  # (1m, 5m, 15m)

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    disks = []
    for part in psutil.disk_partitions(all=False):
        if not part.mountpoint or part.fstype in {"squashfs", "tmpfs", "devtmpfs", "overlay"}:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({
                "mount": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total": u.total,
                "used": u.used,
                "free": u.free,
                "percent": u.percent,
            })
        except (OSError, PermissionError):
            continue

    with _lock:
        dio = psutil.disk_io_counters()
        read_rate, write_rate = _delta_rate(_last_disk_io,
                                             dio.read_bytes, dio.write_bytes, now)
        _last_disk_io = (now, dio.read_bytes, dio.write_bytes)

        nio = psutil.net_io_counters()
        sent_rate, recv_rate = _delta_rate(_last_net_io,
                                            nio.bytes_sent, nio.bytes_recv, now)
        _last_net_io = (now, nio.bytes_sent, nio.bytes_recv)

    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        info = p.info
        if info["cpu_percent"] is None and info["memory_percent"] is None:
            continue
        procs.append({
            "pid": info["pid"],
            "name": info["name"] or "?",
            "user": info["username"] or "?",
            "cpu": round(info["cpu_percent"] or 0.0, 1),
            "mem": round(info["memory_percent"] or 0.0, 1),
        })
    procs.sort(key=lambda p: p["cpu"], reverse=True)

    boot = psutil.boot_time()

    return {
        "ts": now,
        "uptime_seconds": int(now - boot),
        "cpu": {
            "percent": cpu_percent,
            "per_cpu": per_cpu,
            "count": psutil.cpu_count(),
            "load": load,
        },
        "mem": {
            "total": mem.total,
            "used": mem.used,
            "available": mem.available,
            "percent": mem.percent,
        },
        "swap": {
            "total": swap.total,
            "used": swap.used,
            "percent": swap.percent,
        },
        "disks": disks,
        "io": {
            "disk_read_bps": read_rate,
            "disk_write_bps": write_rate,
            "net_sent_bps": sent_rate,
            "net_recv_bps": recv_rate,
        },
        "top_procs": procs[:15],
    }
