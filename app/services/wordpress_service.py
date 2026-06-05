"""Instalación WordPress fresh: descarga core + crea BD + wp-config + install."""
import secrets
import string
import urllib.request
import shutil
import tempfile
from pathlib import Path
from .runner import run_sudo
from .. import config

WP_TARBALL_URL = "https://wordpress.org/latest.tar.gz"


def _wp_secret() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}<>?"
    return "".join(secrets.choice(alphabet) for _ in range(64))


def download_and_extract(docroot: str, log: list) -> None:
    """Descarga WordPress latest.tar.gz y lo extrae en docroot (vía helper sudo)."""
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
        tarball = tf.name
    try:
        log.append(f"Descargando {WP_TARBALL_URL}")
        urllib.request.urlretrieve(WP_TARBALL_URL, tarball)
        log.append(f"Tarball descargado en {tarball}")
        tmpdir = tempfile.mkdtemp(prefix="wp-extract-")
        shutil.unpack_archive(tarball, tmpdir)
        # tmpdir/wordpress/* → docroot (el contenido, no la carpeta)
        src = Path(tmpdir) / "wordpress"
        rc, out, err = run_sudo([
            "/usr/local/bin/sw-panel-helper", "mv-contents-into-www", str(src), docroot
        ])
        log.append(f"mv WP contents → {docroot}: rc={rc} {err}")
        if rc != 0:
            raise RuntimeError(f"No se pudo mover WordPress a {docroot}: {err}")
    finally:
        Path(tarball).unlink(missing_ok=True)


def write_wp_config(docroot: str, db_name: str, db_user: str, db_pass: str,
                    fqdn: str, log: list) -> None:
    keys = "\n".join(
        f"define( '{k}', {repr(_wp_secret())} );"
        for k in [
            "AUTH_KEY", "SECURE_AUTH_KEY", "LOGGED_IN_KEY", "NONCE_KEY",
            "AUTH_SALT", "SECURE_AUTH_SALT", "LOGGED_IN_SALT", "NONCE_SALT",
        ]
    )
    content = f"""<?php
define( 'WP_HOME', 'https://{fqdn}' );
define( 'WP_SITEURL', 'https://{fqdn}' );
define( 'DB_NAME', {db_name!r} );
define( 'DB_USER', {db_user!r} );
define( 'DB_PASSWORD', {db_pass!r} );
define( 'DB_HOST', 'localhost' );
define( 'DB_CHARSET', 'utf8mb4' );
define( 'DB_COLLATE', '' );

{keys}

$table_prefix = 'wp_';

define( 'WP_DEBUG', false );

if ( ! empty( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https' ) {{
    $_SERVER['HTTPS'] = 'on';
}}

if ( ! defined( 'ABSPATH' ) ) {{
    define( 'ABSPATH', __DIR__ . '/' );
}}
require_once ABSPATH . 'wp-settings.php';
"""
    target = f"{docroot}/wp-config.php"
    rc, out, err = run_sudo([
        "/usr/local/bin/sw-panel-helper", "write-file", target, "www-data:www-data"
    ], input_text=content)
    log.append(f"wp-config.php → {target}: rc={rc} {err}")
    if rc != 0:
        raise RuntimeError(f"No se pudo escribir wp-config.php: {err}")


def core_install(docroot: str, fqdn: str, site_title: str,
                 admin_user: str, admin_pass: str, admin_email: str, log: list) -> None:
    """wp-cli core install."""
    rc, out, err = run_sudo([
        "/usr/local/bin/sw-panel-helper", "wp-cli", docroot,
        "core", "install",
        f"--url=https://{fqdn}",
        f"--title={site_title}",
        f"--admin_user={admin_user}",
        f"--admin_password={admin_pass}",
        f"--admin_email={admin_email}",
        "--skip-email",
    ])
    log.append(f"wp core install: rc={rc} stdout={out[:500]} err={err[:500]}")
    if rc != 0:
        raise RuntimeError(f"wp core install falló: {err}")
