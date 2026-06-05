import re
from pathlib import Path
from .. import config
from .runner import run_sudo

VHOST_TEMPLATE = """server {{
    listen 80;
    server_name {fqdn};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {fqdn};

    ssl_certificate     {cert};
    ssl_certificate_key {key};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 2g;

{body}
}}
"""

PHP_LOCATION = """    root {docroot};
    index index.php index.html;

    location / {{
        try_files $uri $uri/ /index.php?$args;
    }}

    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{php_sock};
        fastcgi_read_timeout 300s;
    }}
"""

PROXY_LOCATION = """    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }}
"""

STATIC_LOCATION = """    root {docroot};
    index index.html;

    location / {{
        try_files $uri $uri/ =404;
    }}
"""


SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


def validate_subdomain(sub: str) -> str:
    sub = sub.strip().lower()
    if not SUBDOMAIN_RE.match(sub):
        raise ValueError("Subdominio inválido (a-z, 0-9, guiones, 1-32 caracteres)")
    if sub in {"coolify", "lab", "www", "panel", "mail"}:
        raise ValueError(f"Subdominio reservado: {sub}")
    # Chequeo contra inventario en vivo de nginx
    from . import nginx_inventory
    fqdn = fqdn_for(sub)
    if fqdn in nginx_inventory.existing_fqdns():
        raise ValueError(f"El subdominio '{sub}' ya está en uso (vhost activo en nginx)")
    return sub


def fqdn_for(sub: str) -> str:
    return f"{sub}.{config.LAB_DOMAIN}"


def render_vhost_php(fqdn: str, docroot: str, php_version: str) -> str:
    sock = config.PHP_VERSIONS[php_version]
    body = PHP_LOCATION.format(docroot=docroot, php_sock=sock)
    return VHOST_TEMPLATE.format(fqdn=fqdn, cert=config.SSL_CERT, key=config.SSL_KEY, body=body)


def render_vhost_proxy(fqdn: str, port: int) -> str:
    body = PROXY_LOCATION.format(port=port)
    return VHOST_TEMPLATE.format(fqdn=fqdn, cert=config.SSL_CERT, key=config.SSL_KEY, body=body)


def render_vhost_static(fqdn: str, docroot: str) -> str:
    body = STATIC_LOCATION.format(docroot=docroot)
    return VHOST_TEMPLATE.format(fqdn=fqdn, cert=config.SSL_CERT, key=config.SSL_KEY, body=body)


def write_vhost(fqdn: str, content: str, log: list) -> None:
    """Escribe el vhost en sites-available + symlink en sites-enabled. Requiere helper sudo."""
    avail = config.NGINX_AVAILABLE / fqdn
    enabled = config.NGINX_ENABLED / fqdn
    # Escribir vía helper sudo (panel-helper write-file)
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "write-vhost", str(avail)], input_text=content)
    log.append(f"write-vhost {avail}: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"No se pudo escribir vhost: {err}")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "enable-vhost", str(avail), str(enabled)])
    log.append(f"enable-vhost: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"No se pudo activar vhost: {err}")


def reload_nginx(log: list) -> None:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "nginx-test"])
    log.append(f"nginx -t: rc={rc} {out}{err}")
    if rc != 0:
        raise RuntimeError(f"nginx -t falló: {err}")
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "nginx-reload"])
    log.append(f"nginx reload: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"nginx reload falló: {err}")


def remove_vhost(fqdn: str, log: list) -> None:
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "remove-vhost", fqdn])
    log.append(f"remove-vhost {fqdn}: rc={rc} {err}")
