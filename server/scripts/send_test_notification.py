"""
테스트 알림 전송 스크립트.

사용법:
  cd server
  python scripts/send_test_notification.py [이메일] [타입]

예시:
  python scripts/send_test_notification.py 2ziziy@hufs.ac.kr motivation
  python scripts/send_test_notification.py 2ziziy@hufs.ac.kr po_suggestion
  python scripts/send_test_notification.py 2ziziy@hufs.ac.kr workout_reminder

타입 목록:
  workout_reminder  - 운동 알림
  motivation        - 동기부여 메시지 (기본값)
  po_suggestion     - Progressive Overload 제안
  skip_warning      - 운동 건너뜀 경고
  system            - 시스템 알림
"""
import asyncio
import os
import sys
import uuid

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/scifiitsync")
# asyncpg 드라이버 강제 (postgresql:// → postgresql+asyncpg://)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

TEST_NOTIFICATIONS = {
    "motivation": {
        "title": "💪 오늘도 화이팅!",
        "body": "3일 연속 운동 중이에요! 꾸준함이 최고의 루틴입니다. 오늘도 목표를 향해 나아가세요.",
    },
    "po_suggestion": {
        "title": "📈 Progressive Overload 제안",
        "body": "벤치프레스에서 목표 반복 수를 2세션 연속 달성했어요! 다음 세션에서 2.5kg 증량을 시도해보세요.",
    },
    "workout_reminder": {
        "title": "🏋️ 운동할 시간이에요!",
        "body": "오늘 루틴: 상체 A (벤치프레스, 오버헤드프레스, 바벨 로우). 어제보다 강해질 준비 됐나요?",
    },
    "skip_warning": {
        "title": "⚠️ 이틀째 쉬고 있어요",
        "body": "최근 2일간 운동 기록이 없어요. 짧은 운동이라도 연속 기록을 지켜보세요!",
    },
    "system": {
        "title": "🔔 SciFit-Sync 시스템 알림",
        "body": "앱이 정상적으로 업데이트되었습니다. 새로운 AI 코치 기능을 확인해보세요.",
    },
}


async def main():
    email = sys.argv[1] if len(sys.argv) > 1 else "2ziziy@hufs.ac.kr"
    ntype = sys.argv[2] if len(sys.argv) > 2 else "motivation"

    if ntype not in TEST_NOTIFICATIONS:
        print(f"❌ 알 수 없는 타입: {ntype}")
        print(f"사용 가능한 타입: {', '.join(TEST_NOTIFICATIONS.keys())}")
        sys.exit(1)

    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"statement_cache_size": 0},  # PgBouncer transaction mode 호환
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 유저 조회
        row = (await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email}
        )).fetchone()

        if not row:
            print(f"❌ 유저를 찾을 수 없어요: {email}")
            await engine.dispose()
            sys.exit(1)

        user_id = row[0]
        notif = TEST_NOTIFICATIONS[ntype]

        # 알림 삽입
        notif_id = uuid.uuid4()
        await session.execute(
            text("""
                INSERT INTO notifications (id, user_id, type, title, body, is_read, created_at)
                VALUES (:id, :user_id, :type, :title, :body, false, NOW())
            """),
            {
                "id": str(notif_id),
                "user_id": str(user_id),
                "type": ntype,
                "title": notif["title"],
                "body": notif["body"],
            }
        )
        await session.commit()

    await engine.dispose()
    print("✅ 테스트 알림 전송 완료!")
    print(f"   수신자: {email}")
    print(f"   타입:   {ntype}")
    print(f"   제목:   {notif['title']}")


if __name__ == "__main__":
    asyncio.run(main())
