#!/usr/bin/env bash
#
# LiteHost Panel — instalador interactivo.
# ---------------------------------------------------------------------------
# Asistente paso a paso que:
#   1. (opcional) instala dependencias del sistema con apt
#   2. crea el usuario de servicio y el entorno virtual de Python
#   3. te pregunta cada valor de configuración y genera /etc/sw-panel/panel.env
#      (hash bcrypt + secreto de sesión incluidos)
#   4. instala el helper privilegiado, la regla de sudoers y el servicio systemd
#   5. (opcional) escribe y habilita el vhost de nginx del panel
#
# Uso:
#   sudo ./install.sh              # instalación completa, interactiva
#   sudo ./install.sh --env-only   # solo (re)genera la configuración .env
#   sudo ./install.sh --yes        # no preguntar en pasos opcionales (asume sí)
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Estilo -----------------------------------------------------------------
if [ -t 1 ]; then
  B="\033[1m"; DIM="\033[2m"; R="\033[0m"
  GREEN="\033[38;5;42m"; CYAN="\033[38;5;44m"; YEL="\033[38;5;220m"; RED="\033[38;5;203m"; VIO="\033[38;5;141m"
else
  B=""; DIM=""; R=""; GREEN=""; CYAN=""; YEL=""; RED=""; VIO=""
fi
say()  { printf "%b\n" "$*"; }
step() { printf "\n${B}${CYAN}▸ %s${R}\n" "$*"; }
ok()   { printf "  ${GREEN}✓${R} %s\n" "$*"; }
warn() { printf "  ${YEL}!${R} %s\n" "$*"; }
err()  { printf "  ${RED}✗ %s${R}\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

ENV_ONLY=0; ASSUME_YES=0
for a in "$@"; do
  case "$a" in
    --env-only) ENV_ONLY=1 ;;
    --yes|-y)   ASSUME_YES=1 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opción desconocida: $a" ;;
  esac
done

# --- Helpers de prompt ------------------------------------------------------
ask() {  # ask <texto> <default> -> stdout
  local p="$1" def="${2:-}" v
  if [ -n "$def" ]; then read -rp "$(printf "  %s ${DIM}[%s]${R}: " "$p" "$def")" v || true
  else read -rp "$(printf "  %s: " "$p")" v || true; fi
  printf '%s' "${v:-$def}"
}
ask_secret() {  # ask_secret <texto> -> stdout (sin eco)
  local p="$1" v
  read -rsp "$(printf "  %s: " "$p")" v || true; printf '\n' >&2
  printf '%s' "$v"
}
confirm() {  # confirm <texto>  (default sí)
  [ "$ASSUME_YES" = 1 ] && return 0
  local v; read -rp "$(printf "  %s ${DIM}[S/n]${R}: " "$1")" v || true
  case "${v:-s}" in [sSyY]*) return 0 ;; *) return 1 ;; esac
}

[ "$(id -u)" -eq 0 ] || die "Ejecuta el instalador como root:  sudo ./install.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say ""
say "${B}${GREEN}  LiteHost Panel${R} ${DIM}· instalador${R}"
say "${DIM}  ---------------------------------------------${R}"

# ===========================================================================
# Paso 1 · Rutas y usuarios
# ===========================================================================
step "Paso 1/8 · Rutas y usuarios"
APP_DIR=$(ask "Directorio de instalación del panel" "/opt/sw-panel")
SERVICE_USER=$(ask "Usuario de servicio (sin privilegios) que correrá el panel" "swpanel")
DEFAULT_SYSUSER="${SUDO_USER:-appuser}"
SYSTEM_USER=$(ask "Usuario del sistema dueño de /home (uploads/backups)" "$DEFAULT_SYSUSER")
DATA_DIR=$(ask "Directorio de datos del panel" "/var/lib/sw-panel")
HOME_DIR="/home/${SYSTEM_USER}"
BACKUPS_DIR="${HOME_DIR}/sw-panel-backups"
ENV_DIR="/etc/sw-panel"
ENV_FILE="${ENV_DIR}/panel.env"

# ===========================================================================
# Paso 2 · Dependencias del sistema (apt)
# ===========================================================================
if [ "$ENV_ONLY" = 0 ]; then
  step "Paso 2/8 · Dependencias del sistema"
  if command -v apt-get >/dev/null 2>&1; then
    if confirm "¿Instalar dependencias con apt (nginx, php-fpm, mariadb, certbot, python3-venv…)?"; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq \
        nginx mariadb-server certbot \
        python3 python3-venv python3-pip \
        unzip curl ca-certificates software-properties-common >/dev/null
      ok "Paquetes base instalados"

      # PHP: para soportar varias versiones por sitio se usa el PPA ondrej/php.
      if confirm "¿Añadir el PPA ondrej/php e instalar PHP 7.4 + 8.1–8.4 (multi-versión)?"; then
        add-apt-repository -y ppa:ondrej/php >/dev/null 2>&1 && apt-get update -qq
        apt-get install -y -qq \
          php7.4-fpm php8.1-fpm php8.2-fpm php8.3-fpm php8.4-fpm \
          php8.3-mysql php8.3-cli >/dev/null 2>&1 || warn "Algún paquete PHP no estaba disponible; revisa manualmente."
        ok "PHP multi-versión instalado (7.4 / 8.1–8.4)"
      else
        apt-get install -y -qq php-fpm php-mysql php-cli >/dev/null
        warn "Instalada solo la versión de PHP por defecto del sistema."
      fi
      if ! command -v wp >/dev/null 2>&1; then
        if confirm "¿Instalar WP-CLI (necesario para sitios WordPress)?"; then
          curl -sSL -o /usr/local/bin/wp \
            https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
          chmod +x /usr/local/bin/wp && ok "WP-CLI instalado"
        fi
      fi
    else
      warn "Saltado. Asegúrate de tener nginx, php-fpm, mysql/mariadb, certbot y python3-venv."
    fi
  else
    warn "Este sistema no usa apt. Instala las dependencias manualmente."
  fi
else
  step "Paso 2/8 · Dependencias del sistema ${DIM}(saltado: --env-only)${R}"
fi

# Detectar versiones de PHP disponibles
PHP_FOUND=$(ls -1 /etc/php 2>/dev/null | grep -E '^[0-9]+\.[0-9]+$' | sort -V | tr '\n' ' ' || true)
DEFAULT_PHP_GUESS=$(echo "$PHP_FOUND" | tr ' ' '\n' | tail -1)
[ -z "$DEFAULT_PHP_GUESS" ] && DEFAULT_PHP_GUESS="8.3"

# ===========================================================================
# Paso 3 · Usuario de servicio + venv
# ===========================================================================
if [ "$ENV_ONLY" = 0 ]; then
  step "Paso 3/8 · Usuario de servicio y entorno Python"
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    ok "Usuario de servicio '$SERVICE_USER' creado"
  else
    ok "Usuario de servicio '$SERVICE_USER' ya existe"
  fi

  # Copiar el código al directorio de instalación (si se ejecuta desde otro lado)
  if [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
    cp -r "$SCRIPT_DIR/app" "$SCRIPT_DIR/requirements.txt" "$APP_DIR"/
    ok "Código copiado a $APP_DIR"
  fi

  python3 -m venv "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install -q --upgrade pip
  "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
  ok "Entorno virtual listo ($APP_DIR/venv)"
  PYBIN="$APP_DIR/venv/bin/python"
else
  # --env-only: usa el venv ya instalado (tiene passlib); si no, python3 del sistema
  if [ -x "$APP_DIR/venv/bin/python" ]; then PYBIN="$APP_DIR/venv/bin/python"; else PYBIN="$(command -v python3)"; fi
  if ! "$PYBIN" -c "import passlib" >/dev/null 2>&1; then
    die "No encuentro 'passlib' (para el hash). Ejecuta el instalador completo primero, o: $PYBIN -m pip install passlib bcrypt"
  fi
fi

# ===========================================================================
# Paso 4 · Asistente de configuración (.env)
# ===========================================================================
step "Paso 4/8 · Configuración del panel"

say "  ${DIM}— Acceso al panel —${R}"
ADMIN_USER=$(ask "Usuario administrador del panel" "admin")
while :; do
  ADMIN_PW=$(ask_secret "Contraseña del administrador")
  [ -z "$ADMIN_PW" ] && { warn "No puede estar vacía."; continue; }
  ADMIN_PW2=$(ask_secret "Repite la contraseña")
  [ "$ADMIN_PW" = "$ADMIN_PW2" ] && break
  warn "No coinciden, intenta de nuevo."
done

say "  ${DIM}— Dominio —${R}"
LAB_DOMAIN=$(ask "Dominio base de los subdominios (wildcard *.dominio)" "lab.example.com")

say "  ${DIM}— MySQL / MariaDB —${R}"
MYSQL_HOST=$(ask "Host de MySQL" "localhost")
MYSQL_ROOT_USER=$(ask "Usuario root de MySQL" "root")
MYSQL_ROOT_PASS=$(ask_secret "Contraseña root de MySQL (vacío si usa auth por socket)")

say "  ${DIM}— PHP —${R}"
[ -n "$PHP_FOUND" ] && say "    ${DIM}versiones detectadas: ${PHP_FOUND}${R}"
DEFAULT_PHP=$(ask "Versión de PHP por defecto para sitios nuevos" "$DEFAULT_PHP_GUESS")

say "  ${DIM}— Coolify (opcional; deja vacío para omitir) —${R}"
COOLIFY_API_URL=$(ask "URL de la API de Coolify" "https://coolify.${LAB_DOMAIN}/api/v1")
COOLIFY_API_TOKEN=$(ask_secret "Token de la API de Coolify (vacío = sin Coolify)")

step "Paso 5/8 · Generando secretos"
PW_HASH=$(ADMIN_PW="$ADMIN_PW" "$PYBIN" - <<'PY'
import os
from passlib.hash import bcrypt
print(bcrypt.hash(os.environ["ADMIN_PW"]))
PY
)
ok "Hash bcrypt de la contraseña generado"
if command -v openssl >/dev/null 2>&1; then
  SESSION_SECRET=$(openssl rand -base64 48 | tr -d '\n')
else
  SESSION_SECRET=$("$PYBIN" -c "import secrets;print(secrets.token_urlsafe(48))")
fi
ok "Secreto de sesión generado"

# ===========================================================================
# Paso 6 · Escribir panel.env y helper.env
# ===========================================================================
step "Paso 6/8 · Escribiendo configuración"
mkdir -p "$ENV_DIR" "$DATA_DIR" "$BACKUPS_DIR" "${HOME_DIR}/uploads"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR" 2>/dev/null || true
id "$SYSTEM_USER" >/dev/null 2>&1 && chown "$SYSTEM_USER" "$BACKUPS_DIR" "${HOME_DIR}/uploads" 2>/dev/null || true

umask 027
cat > "$ENV_FILE" <<EOF
# Generado por install.sh — $(date -u +%Y-%m-%dT%H:%M:%SZ)
# No subas este archivo a git.

PANEL_ADMIN_USER=${ADMIN_USER}
PANEL_ADMIN_PASSWORD_HASH='${PW_HASH}'
PANEL_SESSION_SECRET='${SESSION_SECRET}'

PANEL_LAB_DOMAIN=${LAB_DOMAIN}
PANEL_SYSTEM_USER=${SYSTEM_USER}
PANEL_BASE_DIR=${APP_DIR}
PANEL_DATA_DIR=${DATA_DIR}

MYSQL_HOST=${MYSQL_HOST}
MYSQL_ROOT_USER=${MYSQL_ROOT_USER}
MYSQL_ROOT_PASS='${MYSQL_ROOT_PASS}'

PANEL_DEFAULT_PHP=${DEFAULT_PHP}

COOLIFY_API_URL=${COOLIFY_API_URL}
COOLIFY_API_TOKEN='${COOLIFY_API_TOKEN}'
COOLIFY_PORT_START=8101
COOLIFY_PORT_END=8200
EOF
chown root:"$SERVICE_USER" "$ENV_FILE" 2>/dev/null || true
chmod 0640 "$ENV_FILE"
ok "Configuración escrita en $ENV_FILE"

# helper.env: solo rutas (sin secretos), lo lee sw-panel-helper bajo sudo
cat > "${ENV_DIR}/helper.env" <<EOF
# Rutas para sw-panel-helper (sudo limpia el entorno). Generado por install.sh.
PANEL_WWW_ROOT=/var/www
PANEL_NGINX_AVAILABLE=/etc/nginx/sites-available
PANEL_NGINX_ENABLED=/etc/nginx/sites-enabled
PANEL_BACKUPS_DIR=${BACKUPS_DIR}
EOF
chmod 0644 "${ENV_DIR}/helper.env"
ok "Rutas del helper escritas en ${ENV_DIR}/helper.env"

if [ "$ENV_ONLY" = 1 ]; then
  say "\n${GREEN}${B}Listo (solo .env).${R} Reinicia el servicio si ya estaba activo: ${DIM}systemctl restart sw-panel${R}\n"
  exit 0
fi

# ===========================================================================
# Paso 7 · Helper privilegiado, sudoers y systemd
# ===========================================================================
step "Paso 7/8 · Helper, sudoers y servicio"
install -o root -g root -m 0750 "$SCRIPT_DIR/deploy/sw-panel-helper" /usr/local/bin/sw-panel-helper
ok "Helper instalado en /usr/local/bin/sw-panel-helper"

printf '%s ALL=(root) NOPASSWD: /usr/local/bin/sw-panel-helper\n' "$SERVICE_USER" > /etc/sudoers.d/sw-panel
chmod 0440 /etc/sudoers.d/sw-panel
if visudo -cf /etc/sudoers.d/sw-panel >/dev/null 2>&1; then
  ok "Regla de sudoers instalada y validada"
else
  rm -f /etc/sudoers.d/sw-panel; die "sudoers inválido, abortado por seguridad"
fi

cat > /etc/systemd/system/sw-panel.service <<EOF
[Unit]
Description=LiteHost Panel (FastAPI)
After=network.target mysql.service mariadb.service
Wants=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 9080 --proxy-headers --forwarded-allow-ips '*'
Restart=on-failure
RestartSec=5
NoNewPrivileges=no
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=${DATA_DIR} ${BACKUPS_DIR} ${HOME_DIR}/uploads /tmp

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sw-panel >/dev/null 2>&1 && ok "Servicio sw-panel activo (127.0.0.1:9080)"

# ===========================================================================
# Paso 8 · Vhost de nginx del panel
# ===========================================================================
step "Paso 8/8 · Vhost de nginx"
PANEL_FQDN="panel.${LAB_DOMAIN}"
CERT="/etc/letsencrypt/live/${LAB_DOMAIN}/fullchain.pem"
KEY="/etc/letsencrypt/live/${LAB_DOMAIN}/privkey.pem"
VHOST="/etc/nginx/sites-available/${PANEL_FQDN}"

if confirm "¿Escribir y habilitar el vhost de nginx para ${PANEL_FQDN}?"; then
  if [ -f "$CERT" ]; then
    cat > "$VHOST" <<EOF
server { listen 80; server_name ${PANEL_FQDN}; return 301 https://\$host\$request_uri; }
server {
    listen 443 ssl;
    server_name ${PANEL_FQDN};
    ssl_certificate     ${CERT};
    ssl_certificate_key ${KEY};
    client_max_body_size 512m;
    location / {
        proxy_pass http://127.0.0.1:9080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  else
    warn "No existe el certificado wildcard ($CERT)."
    warn "Escribo un vhost HTTP temporal; genera el cert y reejecuta para HTTPS."
    cat > "$VHOST" <<EOF
server {
    listen 80;
    server_name ${PANEL_FQDN};
    client_max_body_size 512m;
    location / {
        proxy_pass http://127.0.0.1:9080;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  fi
  ln -sf "$VHOST" "/etc/nginx/sites-enabled/${PANEL_FQDN}"
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx && ok "Vhost habilitado y nginx recargado"
  else
    warn "nginx -t falló; revisa la config. El vhost quedó escrito pero no recargado."
  fi
else
  warn "Vhost saltado. Tienes un ejemplo en deploy/nginx-panel.conf.example"
fi

# ===========================================================================
# Resumen
# ===========================================================================
SCHEME="http"; [ -f "$CERT" ] && SCHEME="https"
say ""
say "${GREEN}${B}  ✓ Instalación completada${R}"
say "${DIM}  ---------------------------------------------${R}"
say "  Panel:     ${B}${SCHEME}://${PANEL_FQDN}${R}"
say "  Usuario:   ${ADMIN_USER}"
say "  Config:    ${ENV_FILE}"
say "  Servicio:  ${DIM}systemctl status sw-panel  ·  journalctl -u sw-panel -f${R}"
say ""
say "  ${DIM}Apunta un wildcard DNS  *.{$LAB_DOMAIN} → este servidor y, para HTTPS,${R}"
say "  ${DIM}genera el cert:  certbot certonly --manual --preferred-challenges dns -d '*.${LAB_DOMAIN}'${R}"
say ""
