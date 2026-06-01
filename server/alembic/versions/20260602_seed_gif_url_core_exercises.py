"""핵심 운동 5개 gif_url 하드코딩 (WorkoutX 검증값)

백 스쿼트 / 벤치 프레스 / 바벨 로우 / 오버헤드 프레스 / AB 롤아웃

Revision ID: 20260602_seed_gif_url_core_exercises
Revises: 20260529_fix_panatta_image_url
Create Date: 2026-06-02
"""

from alembic import op

revision = "20260602_seed_core_gif_url"
down_revision = "20260529_fix_panatta_image_url"
branch_labels = None
depends_on = None

_GIF_URLS = [
    ("백 스쿼트", "https://api.workoutxapp.com/v1/gifs/0102.gif"),
    ("벤치 프레스", "https://api.workoutxapp.com/v1/gifs/0025.gif"),
    ("바벨 로우", "https://api.workoutxapp.com/v1/gifs/0027.gif"),
    ("오버헤드 프레스", "https://api.workoutxapp.com/v1/gifs/0091.gif"),
    ("AB 롤아웃", "https://api.workoutxapp.com/v1/gifs/0103.gif"),
]


def upgrade() -> None:
    for name, gif_url in _GIF_URLS:
        op.execute(
            f"UPDATE exercises SET gif_url = '{gif_url}', updated_at = NOW() "
            f"WHERE name = '{name}' AND (gif_url IS NULL OR gif_url = '')"
        )


def downgrade() -> None:
    for name, _ in _GIF_URLS:
        op.execute(
            f"UPDATE exercises SET gif_url = NULL, updated_at = NOW() "
            f"WHERE name = '{name}'"
        )
