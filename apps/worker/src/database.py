"""Database connection and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def init_db():
    """Initialize database tables and run lightweight migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migration for PublisherAccount new columns (SQLite)
        try:
            from sqlalchemy import text
            # Check existing columns
            result = await conn.execute(text("PRAGMA table_info(publisher_accounts)"))
            cols = {row[1] for row in result.fetchall()}
            for col, ddl in [
                ("credentials", "TEXT"),
                ("folder_id", "VARCHAR(128)"),
                ("folder_name", "VARCHAR(255)"),
                ("extra_config", "TEXT"),
            ]:
                if col not in cols:
                    await conn.execute(text(f"ALTER TABLE publisher_accounts ADD COLUMN {col} {ddl}"))
        except Exception:
            pass  # best-effort, e.g., table not yet created

        # Lightweight migration: series_id on existing tables
        try:
            from sqlalchemy import text

            for table in ("generation_jobs", "runs"):
                result = await conn.execute(text(f"PRAGMA table_info({table})"))
                cols = {row[1] for row in result.fetchall()}
                if cols and "series_id" not in cols:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN series_id VARCHAR(32)"))
        except Exception:
            pass  # best-effort

        # Lightweight migration: progress / cancellation on generation_jobs
        try:
            from sqlalchemy import text

            result = await conn.execute(text("PRAGMA table_info(generation_jobs)"))
            cols = {row[1] for row in result.fetchall()}
            for col, ddl in [
                ("progress", "FLOAT DEFAULT 0"),
                ("current_step", "INTEGER DEFAULT 0"),
                ("message", "TEXT"),
                ("cancel_requested", "BOOLEAN DEFAULT 0"),
            ]:
                if col not in cols:
                    await conn.execute(text(f"ALTER TABLE generation_jobs ADD COLUMN {col} {ddl}"))
        except Exception:
            pass  # best-effort


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
