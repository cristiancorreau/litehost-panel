import os
from pathlib import Path
from dotenv import load_dotenv

# Carga las variables de entorno del panel. La ruta es configurable para que
# puedas ubicar el archivo .env donde prefieras (por defecto /etc/sw-panel/panel.env).
load_dotenv(os.getenv("PANEL_ENV_FILE", "/etc/sw-panel/panel.env"))

# --- Rutas base de la aplicación ---------------------------------------------
BASE_DIR = Path(os.getenv("PANEL_BASE_DIR", "/opt/sw-panel"))
DATA_DIR = Path(os.getenv("PANEL_DATA_DIR", "/var/lib/sw-panel"))
DB_PATH = DATA_DIR / "panel.sqlite"
UPLOADS_DIR = DATA_DIR / "uploads"
DOCS_ASSETS_DIR = DATA_DIR / "docs-assets"

# Usuario del sistema bajo el que viven los sitios/uploads/backups. Cámbialo por
# el usuario de tu servidor (el que es dueño de /home/<usuario>).
SYSTEM_USER = os.getenv("PANEL_SYSTEM_USER", "appuser")
HOME_DIR = Path(os.getenv("PANEL_HOME_DIR", f"/home/{SYSTEM_USER}"))
BACKUPS_DIR = Path(os.getenv("PANEL_BACKUPS_DIR", str(HOME_DIR / "sw-panel-backups")))

# --- Autenticación del panel -------------------------------------------------
ADMIN_USER = os.getenv("PANEL_ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = os.getenv("PANEL_ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("PANEL_SESSION_SECRET", "change-me")

# --- MySQL / MariaDB ---------------------------------------------------------
MYSQL_ROOT_USER = os.getenv("MYSQL_ROOT_USER", "root")
MYSQL_ROOT_PASS = os.getenv("MYSQL_ROOT_PASS", "")
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")

# --- Nginx / dominio / SSL ---------------------------------------------------
# Dominio base donde se publican los subdominios (wildcard *.LAB_DOMAIN).
LAB_DOMAIN = os.getenv("PANEL_LAB_DOMAIN", "lab.example.com")

WWW_ROOT = Path(os.getenv("PANEL_WWW_ROOT", "/var/www"))
NGINX_AVAILABLE = Path(os.getenv("PANEL_NGINX_AVAILABLE", "/etc/nginx/sites-available"))
NGINX_ENABLED = Path(os.getenv("PANEL_NGINX_ENABLED", "/etc/nginx/sites-enabled"))

# Certificado wildcard (Let's Encrypt) usado por los vhosts generados.
SSL_CERT = os.getenv("PANEL_SSL_CERT", f"/etc/letsencrypt/live/{LAB_DOMAIN}/fullchain.pem")
SSL_KEY = os.getenv("PANEL_SSL_KEY", f"/etc/letsencrypt/live/{LAB_DOMAIN}/privkey.pem")
LANDING_HTML = Path(os.getenv("PANEL_LANDING_HTML", str(WWW_ROOT / LAB_DOMAIN / "index.html")))

PHP_VERSIONS = {
    "7.4": "/var/run/php/php7.4-fpm.sock",
    "8.1": "/var/run/php/php8.1-fpm.sock",
    "8.2": "/var/run/php/php8.2-fpm.sock",
    "8.3": "/var/run/php/php8.3-fpm.sock",
    "8.4": "/var/run/php/php8.4-fpm.sock",
}
DEFAULT_PHP = os.getenv("PANEL_DEFAULT_PHP", "8.3")

# --- Coolify (opcional) ------------------------------------------------------
COOLIFY_API_URL = os.getenv("COOLIFY_API_URL", "https://coolify.example.com/api/v1")
COOLIFY_API_TOKEN = os.getenv("COOLIFY_API_TOKEN", "")

# Rango de puertos para apps Coolify (mapeados al host en 127.0.0.1)
COOLIFY_PORT_START = int(os.getenv("COOLIFY_PORT_START", "8101"))
COOLIFY_PORT_END = int(os.getenv("COOLIFY_PORT_END", "8200"))

UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB
