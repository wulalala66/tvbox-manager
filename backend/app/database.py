"""数据库初始化"""
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from .config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """WAL + busy_timeout：修复并发写 database is locked（审查项 M7）"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@event.listens_for(engine, "checkin")
def _reset_on_checkin(dbapi_connection, connection_record):
    """归还连接时回滚残留事务，避免连接池长期持有旧 WAL 读快照
    （曾导致：外部直写 DB 后 API 仍返回旧数据 / disk I/O error）"""
    if not connection_record.info.get("invalid", False):
        try:
            dbapi_connection.rollback()
        except Exception:
            pass


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
