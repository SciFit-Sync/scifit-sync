"""
신규 DB 환경 초기 테이블 생성 스크립트.

사용법 (server/ 디렉토리에서 실행):
    python create_tables.py
    alembic stamp head   # 생성 후 반드시 실행 — Alembic 상태 동기화
"""
import asyncio

from app.core.database import engine
from app.models import Base  # 모든 모델 포함


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("테이블 생성 완료. 'alembic stamp head'를 실행해 Alembic 상태를 동기화하세요.")


asyncio.run(main())
