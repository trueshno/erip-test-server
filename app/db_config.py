# app/db_config.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv
import os
import oracledb 

load_dotenv()

oracledb.init_oracle_client(lib_dir="/opt/oracle/instantclient_21_13")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "oracle+oracledb://erip_user:password@192.168.100.64:1521/orcl"
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    echo=False,
    connect_args={"encoding": "UTF-8", "nencoding": "UTF-8"}
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

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