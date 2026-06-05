# Contribuir a LiteHost Panel

¡Gracias por tu interés! Este proyecto nació como herramienta interna y se publica para la
comunidad, así que toda ayuda —código, documentación, reportes o ideas— es bienvenida.

- [Formas de contribuir](#formas-de-contribuir)
- [Antes de empezar](#antes-de-empezar)
- [Entorno de desarrollo](#entorno-de-desarrollo)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Estilo de código](#estilo-de-código)
- [El helper privilegiado y la seguridad](#el-helper-privilegiado-y-la-seguridad)
- [Probar tus cambios](#probar-tus-cambios)
- [Commits y Pull Requests](#commits-y-pull-requests)
- [Reportar bugs](#reportar-bugs)
- [Vulnerabilidades de seguridad](#vulnerabilidades-de-seguridad)
- [Licencia](#licencia)

## Formas de contribuir

- 🐛 **Reportar un bug** o pedir una mejora abriendo un [issue](https://github.com/cristiancorreau/litehost-panel/issues).
- 📝 **Mejorar la documentación** (README, landing en `docs/`, comentarios, la mini-wiki sembrada en `app/seed_docs.py`).
- ✨ **Enviar un Pull Request** con una corrección o una feature nueva.
- 🧪 **Probar el instalador** en distintas distros/versiones y reportar lo que falle.
- 🌍 **Traducir** la interfaz o la documentación.

## Antes de empezar

- Para cambios **pequeños** (typos, fixes acotados) abre el PR directamente.
- Para cambios **grandes** (una feature, un refactor, tocar el helper o el modelo de datos),
  **abre primero un issue** describiendo la idea. Así evitamos trabajo duplicado o que un PR
  grande no encaje con la dirección del proyecto.

## Entorno de desarrollo

```bash
git clone https://github.com/cristiancorreau/litehost-panel.git
cd litehost-panel
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Crea un `panel.env` de desarrollo y apunta el panel a él con `PANEL_ENV_FILE`:

```bash
cp .env.example dev.env
# edita dev.env: genera el hash y el secreto (ver comentarios del archivo)
PANEL_ENV_FILE="$PWD/dev.env" PANEL_DATA_DIR="$PWD/.devdata" \
  ./venv/bin/uvicorn app.main:app --reload --port 9080
```

Abre <http://127.0.0.1:9080>.

> [!NOTE]
> Para trabajar en **UI, plantillas o lógica** no necesitas un servidor real: el panel
> arranca igual. Las acciones que tocan el sistema (crear vhosts, BDs, etc.) invocan
> `sudo sw-panel-helper` y devolverán error si no estás en un host configurado — es lo
> esperado en desarrollo. Para probar el flujo completo usa una **VM/contenedor desechable**
> con Ubuntu y corre `sudo ./install.sh`.

## Estructura del proyecto

```
app/
├── main.py            # arranque FastAPI, routers, startup
├── config.py          # configuración (todo vía variables de entorno)
├── auth.py            # autenticación HTTP Basic
├── db.py              # modelos SQLAlchemy (Site, Doc, Operation)
├── seed_docs.py       # docs iniciales de la mini-wiki
├── routes/            # endpoints por área (sites, services, files, docs, metrics, restore)
├── services/          # lógica de negocio (nginx, mysql, wordpress, coolify, backups…)
└── templates/         # vistas Jinja2
deploy/
├── sw-panel-helper    # ejecutor privilegiado (sudo) — el único componente con root
├── sudoers.sw-panel   # regla de sudoers acotada al helper
├── sw-panel.service   # unit de systemd
└── nginx-panel.conf.example
install.sh             # instalador interactivo
docs/                  # GitHub Pages (landing) + banner
```

Regla general: **las rutas (`routes/`) son finas** y delegan en **servicios (`services/`)**,
que a su vez delegan toda acción privilegiada en el helper a través de `services/runner.py`.

## Estilo de código

- **Python**: sigue [PEP 8](https://peps.python.org/pep-0008/), usa *type hints* y mantén el
  estilo del código que rodea tu cambio (nombres, densidad de comentarios, idioma).
- Comentarios y textos de UI están en **español**; mantén la consistencia.
- Evita añadir dependencias nuevas salvo que sean necesarias; si lo son, justifícalo en el PR.
- Mantén los endpoints detrás de `Depends(require_admin)` salvo que haya una razón explícita.
- No introduzcas rutas, dominios, IPs o usuarios **hardcodeados**: usa `config.py`
  (variables de entorno con valores por defecto genéricos).

## El helper privilegiado y la seguridad

`deploy/sw-panel-helper` es el **único** componente que corre como root (vía `sudo`). Si tu
cambio toca este archivo o la forma en que el panel lo invoca, presta especial atención:

- Valida y acota **siempre** las rutas (el gestor de archivos está restringido a `/var/www`).
- No amplíes lo que el helper acepta sin necesidad; cada subcomando es superficie de ataque.
- Si añades un subcomando, documenta su firma y mantén el mismo formato de salida que esperan
  los parsers en `app/services/*.py`.
- La regla de `sudoers` debe seguir apuntando **solo** al binario del helper.

## Probar tus cambios

Antes de abrir el PR, como mínimo:

```bash
# 1) Que todo compile
python -m compileall app

# 2) Que el instalador no tenga errores de sintaxis
bash -n install.sh

# 3) Arranca el panel y revisa las vistas afectadas
PANEL_ENV_FILE="$PWD/dev.env" ./venv/bin/uvicorn app.main:app --reload
```

Si tocas el instalador o el helper, pruébalo en una **VM/contenedor desechable** con Ubuntu
22.04 y describe en el PR qué verificaste.

## Commits y Pull Requests

- Usa mensajes de commit estilo [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`… (es lo que ya usa el historial).
- Un PR = un cambio con foco. PRs pequeños se revisan más rápido.
- En la descripción del PR incluye: **qué** cambia, **por qué**, y **cómo lo probaste**.
- Enlaza el issue relacionado (`Closes #123`).

## Reportar bugs

Abre un [issue](https://github.com/cristiancorreau/litehost-panel/issues) e incluye:

- Qué esperabas que pasara y qué pasó.
- Pasos para reproducirlo.
- Entorno: distro/versión, versión de Python, PHP y base de datos.
- Logs relevantes: `journalctl -u sw-panel -n 50` y/o el log de la operación en el panel.

## Vulnerabilidades de seguridad

Si encuentras una vulnerabilidad (especialmente en el helper, sudoers, autenticación o el
gestor de archivos), **no abras un issue público**. Repórtala de forma privada usando los
[Security Advisories](https://github.com/cristiancorreau/litehost-panel/security/advisories/new)
de GitHub para que pueda corregirse antes de divulgarla.

## Licencia

Al contribuir, aceptas que tu aportación se distribuya bajo la licencia
[MIT](LICENSE) del proyecto.
