"""ProfitLens v3 — SQLAlchemy async database engine and session management."""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# Naming convention for constraints — makes Alembic migrations deterministic
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


def _build_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        echo=settings.db_echo,
    )


engine = _build_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


from contextlib import asynccontextmanager

def create_task_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a fresh engine + session factory for Celery tasks.

    Celery workers fork and create new event loops per task, so they
    cannot share the module-level engine (which is bound to the import-time loop).
    Call this inside each task's async function to get a loop-local session factory.
    """
    task_engine = _build_engine()
    return async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def task_db_session():
    """Async context manager for Celery tasks: creates engine, yields session, disposes engine.

    C-3 fix: Uses a much smaller connection pool than the main app engine.
    Celery workers typically only need 1-2 concurrent connections.

    Usage:
        async with task_db_session() as db:
            ...
    """
    settings = get_settings()
    task_engine = create_async_engine(
        settings.database_url,
        pool_size=2,              # Celery tasks need minimal connections
        max_overflow=3,           # Max 5 total per task
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        echo=False,
    )
    factory = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()
    await task_engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _build_redis_pool():
    """Create a global Redis connection pool (shared across all requests)."""
    import redis.asyncio as aioredis

    settings = get_settings()
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
    )


_redis_pool = _build_redis_pool()


async def get_redis():
    """FastAPI dependency that yields the shared Redis connection pool."""
    yield _redis_pool
