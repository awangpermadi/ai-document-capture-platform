from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
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
        await connection.run_sync(_add_payment_method_column)


def _add_payment_method_column(connection: Connection) -> None:
    inspector = inspect(connection)
    if "receipts" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("receipts")
    }
    if "payment_method" not in columns:
        connection.execute(
            text("ALTER TABLE receipts ADD COLUMN payment_method VARCHAR(100)")
        )
