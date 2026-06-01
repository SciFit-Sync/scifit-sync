"""fix: exercises.gif_url 죽은 /static 상대경로 제거 (NULL화 → WorkoutX 재조회)

Revision ID: 20260602_null_dead_gif_urls
Revises: 20260529_fix_panatta_image_url
Create Date: 2026-06-02

배경: prod exercises 52행 중 48행의 gif_url이 서버에 존재하지 않는 `/static/gifs/XXXX.gif`
상대경로(HTTP 404)였다. #229/#230이 gif 로직을 "DB gif_url 우선, NULL인 경우만 WorkoutX 조회"로
바꾸면서, 이 죽은 경로가 그대로 응답에 실려 프론트(시뮬레이터) gif가 표시되지 않았다.
(이전 로직은 항상 WorkoutX 실 URL을 사용해 죽은 DB 값이 가려져 있었다.)

조치: http 로 시작하지 않는 모든 gif_url 을 NULL 로 정리한다. NULL 이 되면 루틴 상세 조회 시
WorkoutX(정상 full URL 반환)가 호출되고 write-back 으로 정상 URL 이 캐시된다. 런타임 방어는
`routines.py` 의 `_needs_wx_gif` / `_usable_gif_url` 헬퍼가 담당한다(비-http 값은 미캐시로 간주).

정책 준수:
- 이미 적용된 시드 마이그레이션을 수정하지 않고 prod 데이터를 직접 UPDATE (20260529_fix_panatta 선례).
  신규 시드 환경도 seed 가 /static 값을 넣더라도 이 마이그레이션이 뒤에서 NULL 로 정리한다.
- revision id 27자 — alembic_version.version_num VARCHAR(32) 제약 준수.
- 멱등: 비-http 값만 NULL 로 바꾸므로 재실행해도 동일 결과.
- "" sentinel(확정 not-found)도 비-http 라 함께 NULL 되나, 다음 조회 시 다시 sentinel 이 기록되어 무해.
- downgrade: 원본 죽은 경로(404)는 복원 가치가 없어 no-op.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260602_null_dead_gif_urls"
down_revision = "20260529_fix_panatta_image_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE exercises SET gif_url = NULL, updated_at = NOW() "
            "WHERE gif_url IS NOT NULL AND gif_url NOT LIKE 'http%'"
        )
    )


def downgrade() -> None:
    # 죽은 /static 상대경로(404)는 복원 가치가 없어 no-op.
    pass
