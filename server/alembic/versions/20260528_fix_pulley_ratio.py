"""fix: 2:1 도르래 머신 pulley_ratio 2 → 0.5 보정 (AI/Data 팀 확인 답변 B)

배경: load_calc.py는 cable/machine 실효중량을 `stack * pulley_ratio + bar`로 계산한다.
2:1 도르래는 체감 부하를 스택 표기값의 "절반"으로 줄이므로 ratio는 0.5여야 한다.
그러나 찬스짐/ai_gym 시드에 2:1 머신의 pulley_ratio가 `2`로 들어가 있어, 표시 중량과
1RM/PO 권장값이 실제의 4배(2 vs 0.5)로 부풀어 있었다. AI/Data 팀 확인(답변 B) 후 보정.

이미 적용된 시드 마이그레이션을 수정하지 않고, prod 데이터를 직접 UPDATE한다.
멱등: 재실행 시 WHERE 매칭 0건. 신규 환경에서도 시드(2.0) 직후 이 마이그레이션이 0.5로 보정.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "20260528_fix_pulley_ratio"
down_revision = "20260527_chancegym_equipments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE equipments SET pulley_ratio = 0.5, updated_at = NOW() "
            "WHERE pulley_ratio = 2 AND equipment_type IN ('cable', 'machine')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE equipments SET pulley_ratio = 2, updated_at = NOW() "
            "WHERE pulley_ratio = 0.5 AND equipment_type IN ('cable', 'machine')"
        )
    )
