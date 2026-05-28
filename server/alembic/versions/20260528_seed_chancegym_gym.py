"""더찬스짐 gym 등록 + gym_equipments 매핑

Revision ID: 20260528_seed_chancegym_gym
Revises: 20260528_fix_pulley_ratio
Create Date: 2026-05-28

핸드오프(HANDOFF_chancegym_equipment.md) 우선순위 2 처리.

- gyms 테이블에 '더찬스짐' 1행 등록 (kakao_place_id 기반 결정론적 UUID)
- gym_equipments 테이블에 20260527에서 적재한 찬스짐 기구 33개 매핑 (quantity=1)
- 멱등성: ON CONFLICT DO NOTHING — 재실행 시 skip
"""

import sqlalchemy as sa
from alembic import op

revision = "20260528_seed_chancegym_gym"
down_revision = "20260528_fix_pulley_ratio"
branch_labels = None
depends_on = None

# 더찬스짐 — uuid5(NAMESPACE_DNS, "scifit-gym-kakao-1875030524")
_GYM_ID = "ecdd073b-f894-5c5a-86cc-a9b42a4e6985"
_GYM = {
    "id": _GYM_ID,
    "kakao_place_id": "1875030524",
    "name": "더찬스짐",
    "address": "경기 용인시 처인구 모현읍 외대로26번길 25-1",
    "latitude": 37.3336260282492,
    "longitude": 127.25172831281385,
}

# 20260527_seed_chancegym_equipments 에서 적재한 찬스짐 기구 33개 id
# (1) Preacher Curl GYM80 ~ (33) Smith machine 범용 순
_EQUIPMENT_IDS = [
    "45efe227-5806-5d60-90e3-30dd1850c16a",  # 1  Preacher Curl
    "351ce983-fa20-5676-a05c-37e7cf9b4837",  # 2  Leg Press
    "8e672b7c-89b9-5596-aaa4-f20d888b3386",  # 3  Hack Squat
    "f19ec570-cfe3-5093-8bc2-764ce5e43d26",  # 4  Hack Slide
    "8db23cf2-ff9a-580f-8615-55c1f5b7d2d8",  # 5  Plate Loaded Incline Press
    "fa0d0b81-9759-5f4b-8567-ba9a23a0a4ea",  # 6  Lat Pulldown (Newtech)
    "a97c569a-fda7-5431-b694-14fac355921d",  # 7  Shoulder Press
    "4989dc12-d0be-580d-a9b6-219ebd81add2",  # 8  Chest Press
    "59c360a7-6bab-5bdd-af4f-f642a0b29089",  # 9  Incline Press
    "14eea95a-3c5f-5e5d-a31e-37ac32953b2a",  # 10 Plate Loaded Seated Row
    "48255be6-dd0b-564a-9c80-65969f2f7f81",  # 11 Plate Loaded Shoulder Press
    "b3266141-9f33-5929-a6ee-26e78ee3ac46",  # 12 Hip Thrust Machine
    "be8c8a43-281e-5331-8539-e5ecf1b2cba1",  # 13 M-Torture Front Row
    "568857d6-f3e0-5905-9f60-18ce5180a4e1",  # 14 Plate Loaded Pulldown
    "a8e1e289-f261-5a16-bca8-09b2afb30016",  # 15 Linear Row / Assisted T-Bar Row
    "f9fadf1e-6004-5297-b8d3-7b7a9c1a1bb1",  # 16 Seated Leg Press
    "dc823fdb-8cc0-59db-8d4a-7fd03575723d",  # 17 Low Pulley (Seated Cable Row)
    "c92e39a8-4faf-59d4-9bcb-fad9de96c2df",  # 18 Seated Row
    "325e25e2-4b64-5d2b-8e8e-e6871f9657b3",  # 19 Lat Pulldown (Lexco)
    "2ca108c5-6153-5b7b-9b22-530ef902178c",  # 20 Assisted Dip/Chin
    "9f5ad84b-ff44-5267-83e5-b1eaf7e3bf8d",  # 21 Pectoral Fly / Rear Deltoid (Newtech)
    "d1547e9f-ba27-5993-9b4e-6f5d5f7661e8",  # 22 Pec Fly / Rear Delt (Lexco)
    "9696a691-2dff-5b7f-90d3-7ea38f576381",  # 23 Inner out thigh
    "3194d412-0a32-505b-a2a7-ab0432506d7f",  # 24 Hip adduction/abduction
    "7d60b6f1-912d-5d6b-9585-2ac56d8f4c1a",  # 25 Seated leg curl
    "d12dd92d-9357-59ab-a391-9883b0bc994c",  # 26 Leg curl
    "f13b498f-5922-5387-806b-be9639fee4c3",  # 27 Leg extension (Lexco)
    "ca9ba9fb-5a5a-56c1-9937-73c500b62220",  # 28 Leg extension (Newtech)
    "bf3d0dde-84e3-510c-a43c-d0b017565431",  # 29 Cable (Lexco)
    "e94bec5c-a634-58e9-872f-8f63eee2b625",  # 30 Cable (Newtech)
    "f970fcc9-53e4-5c3c-9faf-24baa5105448",  # 31 Barbell
    "a0b9376d-c6b1-5ea9-bb64-91b11560deae",  # 32 Dumbbell
    "fe005947-b93d-5c51-bdb9-9dad2a8d11bb",  # 33 Smith machine
]


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            INSERT INTO gyms (id, kakao_place_id, name, address, latitude, longitude)
            VALUES (:id, :kakao_place_id, :name, :address, :latitude, :longitude)
            ON CONFLICT DO NOTHING
        """),
        _GYM,
    )

    conn.execute(
        sa.text("""
            INSERT INTO gym_equipments (gym_id, equipment_id, quantity)
            VALUES (:gym_id, :equipment_id, 1)
            ON CONFLICT DO NOTHING
        """),
        [{"gym_id": _GYM_ID, "equipment_id": eid} for eid in _EQUIPMENT_IDS],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM gym_equipments WHERE gym_id = :gym_id"),
        {"gym_id": _GYM_ID},
    )
    conn.execute(
        sa.text("DELETE FROM gyms WHERE id = :gym_id"),
        {"gym_id": _GYM_ID},
    )
