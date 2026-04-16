"""App config and crawl job models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(30), default="once", server_default="once")
    scope: Mapped[str] = mapped_column(String(50), default="new_releases", server_default="new_releases")
    categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running", server_default="running")
    rounds_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
