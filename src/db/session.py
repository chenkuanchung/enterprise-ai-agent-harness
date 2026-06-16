# src/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.core.config.settings import settings

# 建立非同步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",  # 在開發環境印出底層 SQL 語法方便除錯
    future=True,
    pool_size=20,
    max_overflow=10,
)

# 建立非同步 Session 工廠
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db():
    """FastAPI Dependency Injection 使用的資料庫連線產生器"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()