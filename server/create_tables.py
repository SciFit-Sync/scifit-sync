import app.models  # noqa: F401  -- side-effect import: registers all models on Base.metadata
from app.core.database import engine


async def main():
    async with engine.begin() as conn:
        await conn
