import secrets
import string
import pymysql
from .. import config


def _conn():
    return pymysql.connect(
        host=config.MYSQL_HOST,
        user=config.MYSQL_ROOT_USER,
        password=config.MYSQL_ROOT_PASS,
        autocommit=True,
        charset="utf8mb4",
    )


def gen_password(n: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def safe_name(base: str, suffix: str = "") -> str:
    """Convierte un subdominio en un nombre válido para BD/user MySQL (max 32)."""
    base = "".join(c for c in base if c.isalnum() or c == "_")
    name = f"sw_{base}{suffix}"
    return name[:32]


def create_db_and_user(subdomain: str, log: list) -> tuple[str, str, str]:
    """Crea BD y usuario; retorna (db_name, db_user, db_password)."""
    db_name = safe_name(subdomain.replace("-", "_"))
    db_user = db_name
    db_pass = gen_password()
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cur.execute(f"CREATE USER IF NOT EXISTS `{db_user}`@'localhost' IDENTIFIED BY %s", (db_pass,))
            cur.execute(f"ALTER USER `{db_user}`@'localhost' IDENTIFIED BY %s", (db_pass,))
            cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{db_user}`@'localhost'")
            cur.execute("FLUSH PRIVILEGES")
    log.append(f"MySQL: BD={db_name} user={db_user}")
    return db_name, db_user, db_pass


def drop_db_and_user(db_name: str | None, db_user: str | None, log: list):
    if not db_name and not db_user:
        return
    with _conn() as c:
        with c.cursor() as cur:
            if db_name:
                cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                log.append(f"MySQL: dropped DB {db_name}")
            if db_user:
                cur.execute(f"DROP USER IF EXISTS `{db_user}`@'localhost'")
                log.append(f"MySQL: dropped user {db_user}")


def dump_db(db_name: str, dest_path: str, log: list) -> bool:
    """Llama mysqldump vía helper sudo."""
    from .runner import run_sudo
    rc, out, err = run_sudo(["/usr/local/bin/sw-panel-helper", "mysqldump", db_name, dest_path])
    log.append(f"mysqldump {db_name} → {dest_path}: rc={rc} {err}")
    return rc == 0
