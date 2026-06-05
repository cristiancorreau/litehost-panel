from datetime import datetime
from sqlalchemy import create_engine, String, Integer, DateTime, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from contextlib import contextmanager
from . import config


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subdomain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    fqdn: Mapped[str] = mapped_column(String(255), unique=True)
    type: Mapped[str] = mapped_column(String(32))  # wordpress, duplicator, coolify, static
    status: Mapped[str] = mapped_column(String(32), default="creating")  # creating, ready, failed, deleted
    php_version: Mapped[str] = mapped_column(String(8), default="8.1", nullable=True)
    docroot: Mapped[str] = mapped_column(String(512), nullable=True)
    db_name: Mapped[str] = mapped_column(String(64), nullable=True)
    db_user: Mapped[str] = mapped_column(String(64), nullable=True)
    coolify_uuid: Mapped[str] = mapped_column(String(64), nullable=True)
    coolify_port: Mapped[int] = mapped_column(Integer, nullable=True)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Doc(Base):
    __tablename__ = "docs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    is_pinned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(Integer, index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, running, ok, error
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


_engine = None
_SessionLocal = None


def init_db():
    global _engine, _SessionLocal
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{config.DB_PATH}", future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Session:
    if _SessionLocal is None:
        init_db()
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
