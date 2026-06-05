"""Cliente API de Coolify para crear apps Docker desde el panel."""
import httpx
from typing import Any, Optional
from .. import config


def _client() -> httpx.Client:
    if not config.COOLIFY_API_TOKEN:
        raise RuntimeError("COOLIFY_API_TOKEN no configurado en /etc/sw-panel/panel.env")
    return httpx.Client(
        base_url=config.COOLIFY_API_URL,
        headers={"Authorization": f"Bearer {config.COOLIFY_API_TOKEN}",
                 "Accept": "application/json"},
        timeout=60.0,
        verify=False,  # cert wildcard interno
    )


def list_servers() -> list[dict]:
    with _client() as c:
        r = c.get("/servers")
        r.raise_for_status()
        return r.json()


def list_projects() -> list[dict]:
    with _client() as c:
        r = c.get("/projects")
        r.raise_for_status()
        return r.json()


def list_private_keys() -> list[dict]:
    with _client() as c:
        r = c.get("/security/keys")
        r.raise_for_status()
        return r.json()


def create_application_from_public_repo(
    project_uuid: str, server_uuid: str, environment_name: str,
    git_repository: str, git_branch: str, build_pack: str,
    name: str, ports_exposes: str, instant_deploy: bool = True,
) -> dict:
    payload = {
        "project_uuid": project_uuid,
        "server_uuid": server_uuid,
        "environment_name": environment_name,
        "git_repository": git_repository,
        "git_branch": git_branch,
        "build_pack": build_pack,
        "name": name,
        "ports_exposes": ports_exposes,
        "instant_deploy": instant_deploy,
    }
    with _client() as c:
        r = c.post("/applications/public", json=payload)
        r.raise_for_status()
        return r.json()


def get_application(uuid: str) -> dict:
    with _client() as c:
        r = c.get(f"/applications/{uuid}")
        r.raise_for_status()
        return r.json()


def deploy_application(uuid: str) -> dict:
    with _client() as c:
        r = c.post(f"/deploy", params={"uuid": uuid})
        r.raise_for_status()
        return r.json()


def delete_application(uuid: str) -> None:
    with _client() as c:
        r = c.delete(f"/applications/{uuid}")
        r.raise_for_status()


# ---------------- SERVICES (Docker Compose templates: Supabase, etc.) ----------------

def list_services() -> list[dict]:
    """Lista todos los services (resources tipo Docker Compose) de Coolify."""
    with _client() as c:
        r = c.get("/services")
        r.raise_for_status()
        return r.json()


def get_service(uuid: str) -> dict:
    """Detalle de un service. Incluye sub-applications con sus FQDN/ports."""
    with _client() as c:
        r = c.get(f"/services/{uuid}")
        r.raise_for_status()
        return r.json()


def restart_service(uuid: str) -> dict:
    """Reinicia un service en Coolify (recrea sus containers)."""
    with _client() as c:
        r = c.post(f"/services/{uuid}/restart")
        r.raise_for_status()
        return r.json()


def start_service(uuid: str) -> dict:
    with _client() as c:
        r = c.get(f"/services/{uuid}/start")
        r.raise_for_status()
        return r.json()


def stop_service(uuid: str) -> dict:
    with _client() as c:
        r = c.get(f"/services/{uuid}/stop")
        r.raise_for_status()
        return r.json()


def service_applications(service: dict) -> list[dict]:
    """Devuelve la lista de sub-aplicaciones de un service. Coolify a veces las
    retorna en 'applications' (objeto raíz) o como 'service_applications'."""
    apps = service.get("applications") or service.get("service_applications") or []
    if isinstance(apps, dict):
        apps = list(apps.values())
    return apps
