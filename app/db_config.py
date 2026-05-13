#db_config
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

load_dotenv()

# Формат: oracle+oracledb://user:pass@host:port/service
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "oracle+oracledb://erip_user:password@192.168.100.64:1521/orcl"
)

# 1. Асинхронный Engine (oracledb в thin mode по умолчанию)
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    echo=False,
    # ✅ Убрали encoding/nencoding - oracledb использует UTF-8 по умолчанию
    connect_args={}
)

# 2. Фабрика асинхронных сессий
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

# 3. Dependency для FastAPI
async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()