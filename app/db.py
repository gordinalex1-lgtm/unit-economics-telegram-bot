from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, DateTime, String, Text, func
from app.config import settings

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__="users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str|None] = mapped_column(String(255), nullable=True)
class Calculation(Base):
    __tablename__="calculations"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Database:
    def __init__(self,url):
        self.engine=create_async_engine(url,pool_pre_ping=True)
        self.session=async_sessionmaker(self.engine,expire_on_commit=False,class_=AsyncSession)
    async def init(self):
        async with self.engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
db=Database(settings.database_url)
