"""Seedea docs iniciales (arquitectura y la guía de multitenancy en Supabase)
si no existen todavía. Idempotente: nunca pisa contenido editado por el usuario."""
from sqlalchemy import select
from . import db as dbm


_ARCHITECTURE_MD = r"""
# Arquitectura del servidor

Este documento describe cómo viaja una petición desde el navegador hasta el contenedor
que la atiende, y dónde están físicamente las cosas en disco.

## Diagrama

```mermaid
flowchart LR
    User([🌐 Usuario]):::ext --> R53

    subgraph DNS [AWS Route 53 · zona example.com]
      R53["A *.lab.example.com<br/>→ 203.0.113.10"]:::dns
    end

    R53 --> Host

    subgraph HOST [Servidor · 203.0.113.10]
      Host["Linux · puertos 80/443 públicos"]:::host
      Host --> Nginx
      Nginx["nginx · vhosts por subdominio<br/>SSL wildcard *.lab.example.com<br/>(Let's Encrypt)"]:::nginx

      Nginx -->|panel.lab| Panel["sw-panel · FastAPI<br/>127.0.0.1:9080"]:::panel
      Nginx -->|coolify.lab| CoolifyUI["Coolify UI<br/>127.0.0.1:8000"]:::coolify
      Nginx -->|vscode.lab| VSC["code-server"]:::svc
      Nginx -->|*.lab WordPress| PHP["PHP-FPM 7.4 / 8.x<br/>unix sockets"]:::php
      Nginx -->|*.lab static| Disk["/var/www/&lt;fqdn&gt;/"]:::disk
      Nginx -->|*.lab apps Coolify con repo| AppPort["127.0.0.1:8101–8200"]:::coolify
      Nginx -->|supabase.lab| Kong

      subgraph SVC [Service Coolify · sw-supabase]
        Kong["kong:8000 → :8101 host"]:::kong
        Kong -->|/auth/v1| GoTrue[gotrue]:::sb
        Kong -->|/rest/v1| PostgREST[postgrest]:::sb
        Kong -->|/storage/v1| Storage[storage-api]:::sb
        Kong -->|/realtime/v1| Realtime[realtime]:::sb
        Kong -->|/functions/v1| EdgeFn[edge-functions]:::sb
        Kong -->|/pg/| Meta[postgres-meta]:::sb
        Studio["supabase-studio"]:::sb
        Storage --> MinIO[(minio S3)]:::sb
        GoTrue --> DB
        PostgREST --> DB
        Storage --> DB
        Realtime --> DB
        Studio --> Kong
        DB[(supabase-db<br/>postgres 15)]:::sb
      end
    end

    CoolifyUI -.gestiona.-> AppPort
    CoolifyUI -.gestiona.-> SVC

    classDef ext fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a;
    classDef dns fill:#ede9fe,stroke:#8b5cf6,color:#3730a3;
    classDef host fill:#f1f5f9,stroke:#475569,color:#0f172a;
    classDef nginx fill:#d1fae5,stroke:#10b981,color:#064e3b;
    classDef panel fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a;
    classDef coolify fill:#fef3c7,stroke:#eab308,color:#713f12;
    classDef php fill:#e0e7ff,stroke:#6366f1,color:#312e81;
    classDef disk fill:#e7e5e4,stroke:#78716c,color:#1c1917;
    classDef svc fill:#f1f5f9,stroke:#64748b,color:#1e293b;
    classDef kong fill:#ffedd5,stroke:#f97316,color:#7c2d12;
    classDef sb fill:#d1fae5,stroke:#34d399,color:#022c22;
```

## Cómo viaja una petición a `supabase.lab.example.com/auth/v1/health`

1. El cliente DNS resuelve el subdominio en Route 53 → wildcard `*.lab.example.com` → `203.0.113.10`.
2. Conexión TLS al puerto 443 del servidor; nginx termina el TLS con el certificado wildcard de Let's Encrypt.
3. nginx busca el vhost por `server_name`; el de `supabase.lab` hace `proxy_pass http://127.0.0.1:8101`.
4. Coolify expone el container `supabase-kong` (puerto interno 8000) en `127.0.0.1:8101` vía `ports:` declarado en el `docker_compose_raw` del service.
5. kong enruta la URL a la sub-API correspondiente (gotrue para `/auth/v1/*`) usando reglas declarativas.
6. gotrue responde; el flujo regresa por kong → nginx → cliente.

## Las tres capas

| Capa | Rol | Notas |
|---|---|---|
| **DNS · AWS Route 53** | Wildcard `*.lab.example.com` apuntando a la IP pública. | Nuevos subdominios bajo `.lab` resuelven sin tocar DNS. |
| **Reverse proxy · nginx** | Único punto de entrada en 80/443. Termina TLS y rutea por `server_name`. | Templates de vhost generados por sw-panel: `php`, `static`, `proxy`. |
| **Plataforma · Coolify** | Orquestador Docker. Expone apps al host en `127.0.0.1:8101–8200`. | Para services sin repo (Supabase, n8n…) los containers viven en una red Docker propia. |

## Dónde viven los proyectos de Coolify en disco

Coolify monta `/data/coolify` en el host (root) y mapea allí los archivos generados;
los volúmenes nombrados de Docker viven en `/var/lib/docker/volumes/`.

| Path en el host | Qué contiene |
|---|---|
| `/data/coolify/applications/<uuid>/` | Apps con repo Git: clone, build context, scripts. |
| `/data/coolify/services/<uuid>/` | Services compose (Supabase, n8n…). Incluye `docker-compose.yml`, `.env` y `volumes/` (bind mounts: configs, scripts SQL, storage local, snippets). |
| `/data/coolify/databases/<uuid>/` | Databases standalone (resources Postgres/MySQL/Redis creadas directamente en Coolify). |
| `/data/coolify/backups/` | Backups locales de `scheduled_database_backups`. Vacío si no hay backups configurados. |
| `/data/coolify/source/.env` | **Crítico.** Configuración global de Coolify, contiene `APP_KEY` (sin él no se pueden descifrar las variables de los services). |
| `/data/coolify/ssh/` | Llaves SSH para clonar repos privados y conectar a remote servers. |
| `/var/lib/docker/volumes/<volume>/_data` | Volúmenes Docker nombrados: postgres data, deno-cache, etc. Siempre prefijados con el UUID del service. Ej: `a1b2c3d4e5f6g7h8i9j0k1l2_supabase-db-data`. |

## Cómo respaldar un proyecto Coolify

### 1. Backups programados desde Coolify UI (recomendado)

Coolify ejecuta `pg_dump` dentro del container y guarda local y/o en S3 con retención configurable.

1. Coolify → Service `sw-supabase` → tab **Storages** o **Databases**.
2. Seleccionar el postgres interno (`supabase-db`).
3. Tab **Backups** → *Schedule*: cron (ej. `0 3 * * *`), retención local y/o S3.
4. Para S3: *Settings → S3 Storages* y conectar el bucket primero.

Resultado: `.sql` dump en `/data/coolify/backups/` y/o subido a S3.

### 2. Manual · `pg_dumpall` directo al container

Útil para snapshots ad-hoc o si Coolify está caído. No requiere parar nada.

```bash
docker exec supabase-db-a1b2c3d4e5f6g7h8i9j0k1l2 \
  pg_dumpall -U postgres \
  | gzip > supabase-$(date +%F).sql.gz
```

Restore:
```bash
gunzip -c supabase-2026-05-10.sql.gz \
  | docker exec -i supabase-db-a1b2c3d4e5f6g7h8i9j0k1l2 psql -U postgres
```

### 3. Snapshot completo · `tar` de volúmenes + bind mounts

Para Supabase incluye también el storage (minio), snippets, edge functions y configs.

```bash
UUID=a1b2c3d4e5f6g7h8i9j0k1l2
sudo tar czf supabase-$UUID-$(date +%F).tar.gz \
  /data/coolify/services/$UUID \
  /var/lib/docker/volumes/${UUID}_supabase-db-data \
  /var/lib/docker/volumes/${UUID}_supabase-db-config
```

> **⚠ Detener el service primero** (`/services/$UUID/stop` en API) si querés un snapshot consistente del postgres.

### 4. Crítico · Respaldar Coolify mismo

Sin esto no se puede restaurar el estado de Coolify (proyectos, envs encriptadas, llaves).

```bash
sudo tar czf coolify-meta-$(date +%F).tar.gz \
  /data/coolify/source/.env \
  /data/coolify/ssh \
  /data/coolify/ssl
docker exec coolify-db pg_dumpall -U coolify \
  | gzip > coolify-db-$(date +%F).sql.gz
```

`.env` contiene `APP_KEY` sin la cual las variables de los services quedan ilegibles.
"""


_SUPABASE_MULTITENANCY_MD = r"""
# Cómo crear 2 (o N) bases de datos independientes en Supabase

> En Supabase **un "proyecto" = un postgres + un gotrue + un storage + un kong + un studio**.
> No hay un concepto multi-tenant nativo dentro de un proyecto.

Esto te da tres caminos según cuánto aislamiento necesites. **Spoiler**: lo que más se parece
a "dos proyectos en supabase.com" es la **opción C** (un service de Coolify por base).

---

## Opción A · Schemas separados en el mismo proyecto

**Cuándo conviene:** los dos clientes/apps comparten admins, viven en la misma org y aceptan
auth + storage compartidos. El aislamiento queda en manos de RLS y schemas.

```sql
-- conectado al postgres de Supabase con rol postgres:
CREATE SCHEMA tenant_a;
CREATE SCHEMA tenant_b;

-- exponer ambos en PostgREST
ALTER ROLE authenticator SET pgrst.db_schemas TO 'public, tenant_a, tenant_b';
SELECT pg_reload_conf();
```

Para que PostgREST tome los schemas también hay que setear la env `PGRST_DB_SCHEMAS` del
container `supabase-rest` (Coolify → Service → env del service-application). El cliente
elige el schema con header `Accept-Profile: tenant_a`.

**Pros**
- Una sola DB, una sola RAM (≈ 1.5 GB para todo el stack).
- Backups unificados.

**Contras**
- gotrue (auth) es uno solo: la misma tabla `auth.users` para los dos tenants. Si necesitás bases de usuarios separadas, descartá esta opción.
- storage y buckets compartidos a menos que uses prefijos por tenant en cada bucket.
- Si rompés `tenant_a`, podés afectar `tenant_b` (mismo postgres).

---

## Opción B · Dos databases en el mismo postgres ❌ no recomendado

`CREATE DATABASE db2` y reconfigurar PostgREST/gotrue/storage para una segunda DB **es
posible pero frágil**: cada componente de Supabase está cableado a una sola base por
container. Necesitarías duplicar `supabase-rest`, `supabase-auth`, `supabase-storage`,
`supabase-realtime`, etc. Termina siendo más trabajo que la opción C, sin ganar nada.

Saltá esta opción a menos que tengas una razón muy específica.

---

## Opción C · Un service Coolify por base — recomendado ⭐

**Cuándo conviene:** dos productos / clientes / entornos que merecen aislamiento total
(usuarios, roles, storage, dump separado). Es lo más cercano a "dos proyectos en supabase.com".

### Pasos

1. **En Coolify → Projects → Resources → New → Service template → Supabase**.
2. Nombre por ej. `sw-supabase-cliente-a` (Coolify le asigna un UUID propio, ej. `aaaa1111…`).
3. Server: el mismo que ya usás. Network: aislada por UUID, sin colisión.
4. Antes de hacer Deploy, en `docker_compose_raw` agregá el `ports:` del kong para que nginx
   pueda alcanzarlo desde fuera de Docker. **Usá un puerto distinto** del que ya tomó el
   primer Supabase (`8101` está en uso → usá `8102`):
   ```yaml
   supabase-kong:
     image: 'kong/kong:3.9.1'
     ports:
       - '127.0.0.1:8102:8000'
     # ... resto igual
   ```
5. Setear el FQDN del kong en Coolify a `https://supabase-a.lab.example.com` (Service →
   `supabase-kong` → Domains). Coolify regenera las envs públicas.
6. Deploy. Esperar a que los 14 containers queden healthy.
7. **En sw-panel**: `/sites/new` → "Servicio Coolify (sin repo)" →
   - Subdominio: `supabase-a`
   - Service: el nuevo `sw-supabase-cliente-a`
   - Sub-app: `supabase-kong`
   - Puerto host: `8102`
   - Puerto contenedor: `8000`

   El panel escribe el vhost nginx y queda accesible en `https://supabase-a.lab.example.com`.

8. Para el segundo: repetir con `8103`, `supabase-b`, `sw-supabase-cliente-b`.

### Lo que obtenés

| Aspecto | Resultado |
|---|---|
| Postgres | Container y volumen propios. Borrar uno no afecta al otro. |
| Auth (gotrue) | Tablas `auth.users` independientes. Cada tenant inicia fresco. |
| Storage | minio independiente, bucket scope propio, sin colisión de paths. |
| Studio | URL distinta por proyecto, login distinto. |
| API keys (anon/service) | Generadas por Coolify, distintas por proyecto. |
| Backups | Cada uno se respalda por separado (ver doc de arquitectura). |
| RAM | ≈ 1.5 GB por instancia. Confirmar headroom en `/metrics`. |
| Disco | Inicialmente ~80 MB de DB + lo que crezca el storage. |

### Recursos por instancia (referencia)

- Imagen postgres: ~150 MB
- Imagen kong: ~120 MB
- Imágenes auth/rest/storage/realtime/etc.: ~600 MB en total
- Cuando todo está running con tráfico bajo: ~1 GB de RAM, sube con uso.

---

## Decisión rápida

| Pregunta | Sí → opción |
|---|---|
| ¿Los dos tenants comparten usuarios y storage? | **A** (schemas) |
| ¿Cada tenant es un cliente / producto distinto? | **C** (service por tenant) |
| ¿Vas a hacer backups/restore independientes? | **C** |
| ¿Vas a borrar uno sin tocar al otro alguna vez? | **C** |
| ¿El servidor está apretado de RAM (<4 GB libre)? | **A** |

## Limpieza

- Borrar un service Coolify desde la UI no borra automáticamente el vhost de nginx — pasá
  primero por sw-panel `/sites/<id>/delete` para limpiar el vhost; luego borrá el resource
  en Coolify y quedarán los volúmenes huérfanos en `/var/lib/docker/volumes/<UUID>_*`.
- Para liberar disco: `docker volume rm $(docker volume ls -q | grep <UUID>)` después de
  confirmar que no perdés datos.
"""


_INITIAL_DOCS = [
    {
        "slug": "architecture",
        "title": "Arquitectura del servidor",
        "content": _ARCHITECTURE_MD.strip(),
        "is_pinned": 1,
    },
    {
        "slug": "supabase-multitenancy",
        "title": "Cómo crear 2 (o N) bases independientes en Supabase",
        "content": _SUPABASE_MULTITENANCY_MD.strip(),
        "is_pinned": 1,
    },
]


def seed_initial_docs() -> None:
    with dbm.session_scope() as s:
        for spec in _INITIAL_DOCS:
            existing = s.execute(
                select(dbm.Doc).where(dbm.Doc.slug == spec["slug"])
            ).scalar_one_or_none()
            if existing:
                continue
            s.add(dbm.Doc(**spec))
