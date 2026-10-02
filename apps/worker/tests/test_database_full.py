"""Full tests for database module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDatabaseModule:
    """Tests for database module."""

    def test_database_imports(self):
        """Test database imports."""
        from src.database import (
            Base,
            async_session_maker,
            engine,
        )

        assert engine is not None
        assert async_session_maker is not None
        assert Base is not None

    def test_base_declarative(self):
        """Test Base is declarative base."""

        from src.database import Base

        assert hasattr(Base, 'metadata')

    def test_engine_creation(self):
        """Test engine is created correctly."""

        from src.database import engine

        assert hasattr(engine, 'sync_engine')

    def test_session_maker(self):
        """Test async_session_maker."""

        from src.database import async_session_maker

        assert async_session_maker is not None

    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test get_session generator."""
        from src.database import get_session

        with patch("src.database.async_session_maker") as mock_maker:
            mock_session = MagicMock()
            mock_session.close = AsyncMock()

            mock_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_maker.return_value.__aexit__ = AsyncMock()

            sessions = []
            for session in await get_session().__anext__():
                sessions.append(session)

    @pytest.mark.asyncio
    async def test_get_db_session_commit(self):
        """Test get_db_session commits on success."""
        from src.database import get_db_session

        with patch("src.database.async_session_maker") as mock_maker:
            mock_session = MagicMock()
            mock_session.commit = AsyncMock()

            mock_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_maker.return_value.__aexit__ = AsyncMock()

            async with get_db_session() as session:
                pass

    @pytest.mark.asyncio
    async def test_get_db_session_rollback(self):
        """Test get_db_session rolls back on error."""
        from src.database import get_db_session

        with patch("src.database.async_session_maker") as mock_maker:
            mock_session = MagicMock()
            mock_session.commit = AsyncMock()
            mock_session.rollback = AsyncMock()

            mock_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_maker.return_value.__aexit__ = AsyncMock()

            try:
                async with get_db_session() as session:
                    raise Exception("Test error")
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_init_db(self):
        """Test init_db function."""
        from src.database import init_db

        with patch("src.database.engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.run_sync = AsyncMock()

            mock_engine.begin = MagicMock()
            mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = AsyncMock()

            await init_db()


class TestDatabaseConfig:
    """Tests for database configuration."""

    def test_database_url_from_settings(self):
        """Test database URL is from settings."""
        from src.config import settings
        from src.database import engine

        assert str(engine.url) == settings.database_url

    def test_engine_echo_setting(self):
        """Test engine echo setting."""
        from src.config import settings
        from src.database import engine

        assert engine.echo == settings.debug
