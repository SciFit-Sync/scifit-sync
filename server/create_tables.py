import asyncio
from app.core.database import engine
from app.models.base import Base
import app.models

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Done!")

asyncio.run(main())
