from sqlalchemy.ext.asyncio import AsyncEngine

from app.database.session import engine
from app.models import Base


async def initialize_database(
    database_engine: AsyncEngine | None = None,
) -> None:
    target_engine = database_engine or engine
    # TODO: use Alembic migrations instead of create_all before production.
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
