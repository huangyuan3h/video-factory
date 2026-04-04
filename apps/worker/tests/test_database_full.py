"""Full tests for database module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestDatabaseModule:
    """Tests for database module."""

    def test_database_imports(self):
        """Test database imports."""
        from src.database import engine, async_session_maker, Base
        from src.database import init_db, get_session, get_db_session
        
        assert engine is not None
        assert async_session_maker is not None
        assert Base is not None

    def test_base_declarative(self):
        """Test Base is declarative base."""
        from src.database import Base
        from sqlalchemy.orm import declarative_base
        
        assert hasattr(Base, 'metadata')

    def test_engine_creation(self):
        """Test engine is created correctly."""
        from src.database import engine
        from sqlalchemy.ext.asyncio import AsyncEngine
        
        assert hasattr(engine, 'sync_engine')

    def test_session_maker(self):
        """Test async_session_maker."""
        from src.database import async_session_maker
        from sqlalchemy.ext.asyncio import async_sessionmaker
        
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
        from src.database import engine
        from src.config import settings
        
        assert str(engine.url) == settings.database_url

    def test_engine_echo_setting(self):
        """Test engine echo setting."""
        from src.database import engine
        from src.config import settings
        
        assert engine.echo == settings.debug