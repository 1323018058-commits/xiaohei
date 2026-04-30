from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
from queue import Empty, Full, LifoQueue
from threading import BoundedSemaphore, Lock
from time import monotonic, perf_counter
from typing import Iterator

from psycopg import Connection, OperationalError, connect
from psycopg.rows import dict_row

from src.platform.settings.base import settings


POOL_MAX_SIZE = max(1, settings.db_pool_max_size)
POOL_MAX_OVERFLOW = max(0, settings.db_pool_max_overflow)
POOL_TIMEOUT_SECONDS = max(1, settings.db_pool_timeout_seconds)
DB_CONNECT_TIMEOUT_SECONDS = max(1, settings.db_connect_timeout_seconds)
SLOW_DB_CHECKOUT_PROBE_MS = max(1, settings.db_slow_checkout_probe_ms)
POOL_HEALTHCHECK_IDLE_SECONDS = max(1, settings.db_pool_healthcheck_idle_seconds)
_connection_pool: LifoQueue[Connection] | None = None
_connection_slots = BoundedSemaphore(POOL_MAX_SIZE + POOL_MAX_OVERFLOW)
_connection_last_released_at: dict[int, float] = {}
_pool_lock = Lock()
logger = logging.getLogger(__name__)


def _get_pool() -> LifoQueue[Connection]:
    global _connection_pool
    with _pool_lock:
        if _connection_pool is None:
            _connection_pool = LifoQueue(maxsize=POOL_MAX_SIZE)
    return _connection_pool


def _open_connection() -> Connection:
    if not settings.database_url:
        raise RuntimeError("XH_DATABASE_URL 未配置")
    return connect(
        settings.database_url,
        row_factory=dict_row,
        connect_timeout=DB_CONNECT_TIMEOUT_SECONDS,
    )


def _close_connection(connection: Connection) -> None:
    _connection_last_released_at.pop(id(connection), None)
    try:
        connection.close()
    except Exception:
        pass


def _is_connection_healthy(connection: Connection) -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("select 1")
            cursor.fetchone()
        connection.rollback()
        return True
    except OperationalError:
        _close_connection(connection)
        return False
    except Exception:
        _close_connection(connection)
        return False


def _should_healthcheck(connection: Connection) -> bool:
    last_released_at = _connection_last_released_at.get(id(connection))
    if last_released_at is None:
        return True
    return (monotonic() - last_released_at) >= POOL_HEALTHCHECK_IDLE_SECONDS


def _acquire_connection() -> Connection:
    started_at = perf_counter()
    if not _connection_slots.acquire(timeout=POOL_TIMEOUT_SECONDS):
        logger.warning(
            "db_checkout_timeout wait_ms=%.2f pool_size=%s max_overflow=%s",
            (perf_counter() - started_at) * 1000,
            POOL_MAX_SIZE,
            POOL_MAX_OVERFLOW,
        )
        raise TimeoutError("Database connection pool timeout")

    pool = _get_pool()
    try:
        while True:
            try:
                connection = pool.get_nowait()
            except Empty:
                connection = _open_connection()
                elapsed_ms = (perf_counter() - started_at) * 1000
                if elapsed_ms >= SLOW_DB_CHECKOUT_PROBE_MS:
                    logger.warning(
                        "db_checkout_slow source=new elapsed_ms=%.2f",
                        elapsed_ms,
                    )
                return connection

            if connection.closed or connection.broken:
                _close_connection(connection)
                continue
            if _should_healthcheck(connection) and not _is_connection_healthy(connection):
                continue

            elapsed_ms = (perf_counter() - started_at) * 1000
            if elapsed_ms >= SLOW_DB_CHECKOUT_PROBE_MS:
                logger.warning(
                    "db_checkout_slow source=pool elapsed_ms=%.2f",
                    elapsed_ms,
                )
            return connection
    except Exception:
        _connection_slots.release()
        raise


def _release_connection(connection: Connection) -> None:
    try:
        if connection.closed or connection.broken:
            _close_connection(connection)
            return

        try:
            connection.rollback()
        except Exception:
            _close_connection(connection)
            return

        try:
            _connection_last_released_at[id(connection)] = monotonic()
            _get_pool().put_nowait(connection)
        except Full:
            _close_connection(connection)
    finally:
        _connection_slots.release()


def is_database_enabled() -> bool:
    return bool(settings.database_url)


@contextmanager
def get_db_session() -> Iterator[Connection]:
    if not settings.database_url:
        raise RuntimeError("XH_DATABASE_URL 未配置")

    connection = _acquire_connection()
    try:
        yield connection
    except Exception:
        _release_connection(connection)
        raise
    else:
        _release_connection(connection)


def apply_sql_file(path: str | Path) -> None:
    sql_path = Path(path)
    sql_text = sql_path.read_text(encoding="utf-8")
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql_text)
        connection.commit()


def apply_sql_directory(path: str | Path) -> None:
    for sql_path in sorted(Path(path).glob("*.sql")):
        apply_sql_file(sql_path)
