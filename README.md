# LiteHost Panel

Panel de control **self-hosted** y ligero, escrito en **FastAPI**, para administrar
múltiples sitios en un único servidor Linux detrás de **nginx**. Aprovisiona sitios
WordPress, sitios estáticos y apps/servicios de **Coolify** como subdominios bajo un
dominio wildcard, gestiona certificados SSL, versiones de PHP-FPM, bases de datos MySQL,
backups/restauración, un gestor de archivos web y una mini-wiki de documentación.

> Este proyecto nació como herramienta interna para un servidor de laboratorio y se
> publica para la comunidad. Los valores específicos del entorno original fueron
> reemplazados por placeholders (`example.com`, `appuser`, IPs de documentación). Revisa
> y adapta la configuración a tu infraestructura antes de usarlo.

---

## Características

- **Sitios WordPress** — descarga el core, crea la BD y el usuario MySQL, escribe
  `wp-config.php`, genera el vhost nginx y corre `wp core install` vía WP-CLI.
- **Sitios estáticos** — docroot + vhost listo, con instrucciones de subida (scp/zip).
- **Restauración Duplicator** — desde un paquete subido o desde un directorio del disco,
  con reescritura de URLs (`wp search-replace`).
- **Servicios/apps Coolify** — registra un subdominio que hace `proxy_pass` a un puerto
  del host (rango configurable 8101–8200) gestionado por Coolify.
- **Gestor de vhosts nginx** — inventario en vivo de `sites-enabled`, plantillas
  `php` / `static` / `proxy`, habilitar/eliminar, cambiar versión de PHP por sitio.
- **PHP-FPM** — ver/editar parámetros del pool (`pm`, `memory_limit`, uploads…) por versión.
- **Backups y restore** — `mysqldump` + `tar` del docroot al borrar un sitio, con
  restauración posterior desde el panel.
- **Gestor de archivos** — navegar/editar/subir/permisos dentro de `/var/www` (acotado).
- **Métricas** — CPU, RAM, disco y uso por sitio.
- **Mini-wiki** — páginas markdown editables (incluye docs de arquitectura y de
  multitenancy con Supabase que vienen sembradas).
- **Landing autogenerada** — index del dominio base con tarjetas de los sitios activos.

## Arquitectura

```
Navegador ─HTTPS─▶ nginx (vhost por subdominio, SSL wildcard)
                     │
                     ├─ panel.<dominio>  ─▶ uvicorn 127.0.0.1:9080  (este panel, FastAPI)
                     ├─ *.<dominio> WP    ─▶ PHP-FPM (unix sockets)
                     ├─ *.<dominio> static─▶ /var/www/<fqdn>/
                     └─ *.<dominio> apps  ─▶ 127.0.0.1:8101-8200 (Coolify)
```

El panel corre como un **usuario sin privilegios**. Toda acción que requiere root
(escribir vhosts, tocar `/var/www`, recargar nginx, php-fpm, systemd, mysqldump…) se
delega en un único helper, **`sw-panel-helper`**, autorizado vía una regla de `sudoers`
acotada exclusivamente a ese binario. Esto mantiene la superficie de privilegios mínima
y auditable.

## Requisitos

- Linux con `nginx`, `php-fpm` (7.4 / 8.x), `mysql`/`mariadb`, `certbot` (SSL wildcard).
- Python 3.11+
- Opcional: [Coolify](https://coolify.io/) si quieres gestionar apps/servicios Docker.
- DNS con un wildcard `*.tu-dominio` apuntando al servidor.

## Instalación

```bash
# 1. Código y entorno
sudo mkdir -p /opt/sw-panel && sudo chown $USER /opt/sw-panel
git clone https://github.com/<tu-usuario>/litehost-panel.git /opt/sw-panel
cd /opt/sw-panel
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. Configuración
sudo mkdir -p /etc/sw-panel
sudo cp .env.example /etc/sw-panel/panel.env
sudo nano /etc/sw-panel/panel.env     # genera el hash y el secreto (ver comentarios)

# 3. Helper privilegiado + sudoers
sudo cp deploy/sw-panel-helper /usr/local/bin/sw-panel-helper
sudo chown root:root /usr/local/bin/sw-panel-helper
sudo chmod 0750 /usr/local/bin/sw-panel-helper
sudo cp deploy/sudoers.sw-panel /etc/sudoers.d/sw-panel
sudo chmod 0440 /etc/sudoers.d/sw-panel
sudo visudo -cf /etc/sudoers.d/sw-panel    # validar

# 4. Servicio systemd
sudo cp deploy/sw-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sw-panel

# 5. Vhost del panel
sudo cp deploy/nginx-panel.conf.example /etc/nginx/sites-available/panel.conf
# edita server_name + rutas SSL, luego:
sudo ln -s /etc/nginx/sites-available/panel.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

El panel queda en `https://panel.<tu-dominio>` protegido con HTTP Basic
(usuario/clave de `panel.env`).

## Configuración

Todas las variables viven en `panel.env` (ver [`.env.example`](.env.example)). Las clave:

| Variable | Para qué |
|---|---|
| `PANEL_ADMIN_USER` / `PANEL_ADMIN_PASSWORD_HASH` | Login del panel (bcrypt). |
| `PANEL_SESSION_SECRET` | Secreto de sesión. |
| `PANEL_LAB_DOMAIN` | Dominio base de los subdominios. |
| `PANEL_SYSTEM_USER` | Usuario dueño de `/home/<user>` (uploads/backups). |
| `MYSQL_ROOT_*` | Credenciales para crear BDs de WordPress. |
| `COOLIFY_API_*` | Integración opcional con Coolify. |

## El helper `sw-panel-helper`

`deploy/sw-panel-helper` es una **implementación de referencia** reconstruida a partir
de los puntos de llamada del código. Implementa subcomandos para nginx, gestión de
docroots, el gestor de archivos (acotado a `/var/www`), backups, php-fpm, servicios y
WP-CLI. **Audítalo y ajústalo a tu entorno antes de producción** — es el componente con
privilegios.

## Seguridad

- Cambia `PANEL_SESSION_SECRET` y usa una contraseña fuerte.
- Sirve el panel **siempre tras HTTPS**.
- La regla de sudoers debe apuntar **solo** a `sw-panel-helper`.
- El gestor de archivos está acotado a `/var/www`; revisa los guardas si amplías rutas.

## Licencia

[MIT](LICENSE).
