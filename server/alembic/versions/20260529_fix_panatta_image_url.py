"""fix: Panatta 기구 깨진 이미지 URL 복구 (panattasport.com webp 404 → 대체 URL)

Revision ID: 20260529_fix_panatta_image_url
Revises: 009
Create Date: 2026-05-29

배경: equipments.image_url 에 저장된 Panatta 제품 이미지(panattasport.com /wp-content webp)
URL이 404로 깨져 기구 카탈로그 이미지가 표시되지 않는다. data/panata_image_urls_todo.csv 에서
확정한 31개 기구의 대체 이미지 URL로 보정한다.

정책 준수:
- 이미 적용된 시드 마이그레이션(20260521_seed_equipments)을 수정하지 않고 prod 데이터를 직접
  UPDATE 한다 (20260528_fix_pulley_ratio 선례). 동시에 mlops/data/equipments_seed.csv 도
  갱신해 신규 시드 환경도 처음부터 정상 URL을 갖는다.
- revision id 30자 — alembic_version.version_num VARCHAR(32) 제약 준수.
- 멱등: equipment_id 기준 UPDATE 라 재실행해도 동일 결과.
- downgrade: 원래 URL로 복원 (배포 롤백 `alembic downgrade -1` 대응).

주의: 일부 물리 기구는 category 가 달라 서로 다른 id 의 2개 행으로 등록돼 같은 이미지 URL을
공유한다(예: Multi Press chest/shoulders, Abdominal Crunch/Oblique). 그래서 URL 문자열이 아닌
equipment_id 기준으로 각 행을 개별 UPDATE 한다.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260529_fix_panatta_image_url"
down_revision = "009"  # develop 현재 head(009_add_career_years) 위에 적층 — 단일 선형 유지
branch_labels = None
depends_on = None

# (equipment_id, 깨진 원본 URL, 대체 URL) — data/panata_image_urls_todo.csv 기준 31건
IMAGE_URL_FIXES: list[dict[str, str]] = [
    {
        "id": "92e82d08-8376-4b76-a3f6-9701d49d33a1",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1sc001-2-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTi3t_71Uu8lDLyeBOJciNV_eZbIgcDO9boaw&s",
    },
    {
        "id": "22cbf7fd-44b5-429f-99dd-c90cf252935a",
        "old": "https://www.panattasport.com/wp-content/uploads/2024/07/1FO003-1-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQgzG9mEg_mBPeXnk0UpeHHaddChC2jyLLh4w&s",
    },
    {
        "id": "ec620436-cabb-4f29-8813-1645eb4bd0ee",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1fw101-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTjBABHJ5b71zhGG_dOp1cUJyedfdOWzjCCXQ&s",
    },
    {
        "id": "462123c8-665c-4973-b92f-af706f03ca79",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1sc003-2-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQjV8yo9wP3pSTRLT2Ch6bu7vc1t7GFA_VPdg&s",
    },
    {
        "id": "b4b7db6f-fbd9-4a84-b21f-58328c0b0d00",
        "old": "https://www.panattasport.com/wp-content/uploads/2024/07/1FO002-1-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSkNpTzHzbCb_CmWeAEITHeMPz2CfBkcgpmJQ&s",
    },
    {
        "id": "656293a3-578d-43e8-b80f-c224c0d93c0e",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1fe200-1-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR_gamG7GYYzT4i3BDELumXPTB-7rNJMt1WTw&s",
    },
    {
        "id": "910c3910-c313-47a6-8c7f-9161eea7de3d",
        "old": "https://www.panattasport.com/wp-content/uploads/2024/07/1fO035-1-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcT8IoGZnul2_S_ldz_UPpLBWmnzYFVOSjskdg&s",
    },
    {
        "id": "20092f3c-4999-49bd-8ba6-4f51b5d0014e",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1fe118a-1-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSgWSYQAQboLW2pLTTiUt-bUPc3y3tj4ECwVw&s",
    },
    {
        "id": "15282ad6-a3fc-4be8-a95a-5e974632adff",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1scd030-1-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQi61juK7Pc4LaJ3AG7GUwv5POnRBYBBXxG-g&s",
    },
    {
        "id": "0c6816c6-27e5-4cb2-a998-09ae8ef3a566",
        "old": "https://www.panattasport.com/wp-content/uploads/2022/08/pic_1FW037_02-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTlchoxAiBGnV3B_bBJ18S1pb1GEDtQqLVMSQ&s",
    },
    {
        "id": "2a76d9ef-83a4-422d-ac89-dbfc9ad989dc",
        "old": "https://www.panattasport.com/wp-content/uploads/2020/04/1FT036.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ3mkoElIOzBgEXlUSGJCMfvNxzrZK5vWVe3w&s",
    },
    {
        "id": "5d7c3d55-2f30-4d43-97f5-5cddce04c959",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1fe036-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQzfcayVjCZDHqYWd4c4ghNGyzn6y6m7Cr2Qg&s",
    },
    {
        "id": "ab765661-eb45-424e-ac36-10df2dabd391",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1fw041-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSpxt2n8yks2il2vTVMLC9FE5R4ZDcCOd3SvA&s",
    },
    {
        "id": "d9b7ac61-fdd3-4ab7-8be0-27b7d505df0d",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1scd030-1-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQN34r8T9K6WtOfqYeKc3XdxgL4diKbTKq1yQ&s",
    },
    {
        "id": "4cacbc8f-26dd-48ec-a7cd-0f3a0426af3c",
        "old": "https://www.panattasport.com/wp-content/uploads/2024/07/1FO027-1-1.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSZGcBNS2jTOXful9wigpIxHyPQSbYVaM4V7Q&s",
    },
    {
        "id": "a1a42a00-dcd6-4a92-a8bb-2361e297bf55",
        "old": "https://www.panattasport.com/wp-content/uploads/2024/07/1fO026-1-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRnXztvdoZtiZx03V6TIAd2YcoKTME-pSDDlA&s",
    },
    {
        "id": "6fddb51b-6c16-4e9f-b815-415e7601ac03",
        "old": "https://www.panattasport.com/wp-content/uploads/2026/04/1FT117.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRvOie-DO2wsCsa6QKfCuBlRF4-cYIMkXsE8A&s",
    },
    {
        "id": "52327eb7-9ae7-4732-80b9-e33e18eaa7c5",
        "old": "https://www.panattasport.com/wp-content/uploads/2020/04/1FT051.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQCW9isRNQjx7TAAKqKRxR_KenMB0CzyGNrUg&s",
    },
    {
        "id": "432c0565-c5f2-40f3-8882-349a0c9ccdb5",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/11/1fw451-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS5ygM16G-9e8n2gmn22-Dm6vfNALML3DSfzQ&s",
    },
    {
        "id": "39109cfa-6ee4-4a7d-a931-1fd4a02c3851",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1fw512-1-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQhJJurnxZ0b5StVl1PweY_xKhJxsyS3PJRGg&s",
    },
    {
        "id": "0b90c575-35a4-4e8c-af92-56873b895d50",
        "old": "https://www.panattasport.com/wp-content/uploads/2026/04/1FT053.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTQyTGLq0l2WSjQZsR99cyhKvbdCiwJngLHZg&s",
    },
    {
        "id": "8d17772a-72cd-480a-ac24-9a578d462d88",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/02/1MTH127-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ_8eTmSw6C4zoZ7rU5VqGQzq6RIR61YQlXCg&s",
    },
    {
        "id": "22523f1a-dfbf-482f-8247-196e1f894688",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1mth085-1-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcToXDBpbKpURfZ-uezLtjovbYPFkZMfVUWedA&s",
    },
    {
        "id": "a10ba94c-8406-4a24-b2ba-4b4a4e3dc580",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1mth081-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRXV-XyzevVTaMJScq0ORfHQLZErWqByblM6w&s",
    },
    {
        "id": "df067c60-2308-4fde-b89c-f23caa796db7",
        "old": "https://www.panattasport.com/wp-content/uploads/2026/04/1FO087-1.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQiS1TConvVGJAaQdrDHTKVBaKtC4P3cmuEhQ&s",
    },
    {
        "id": "b036a564-a3ef-4cf9-b2ba-33a633ec2b94",
        "old": "https://www.panattasport.com/wp-content/uploads/2024/07/1fO080-1-jpg.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS9-LzzoXkJB75mDCzqIn6eYUDHPkxKOMdZNg&s",
    },
    {
        "id": "f6fe186b-bff6-40ee-9672-23abbe856b6d",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1sc113a-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS6xrYDCkgJFCB8NSAZiN0syaDa-A4zpA7E9A&s",
    },
    {
        "id": "0375f89d-ad2e-42bc-a2c7-3a4482e0ffbc",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1sc082-2-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRANnj8kQV5UoaPZPr6NHyl2cG4MuXxk1b6ow&s",
    },
    {
        "id": "7331485c-c1c0-4798-b157-b1cac104f378",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1sc083-2-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR0WF1Z0noSvGevv005-_BvyInQ85PP0QuSvA&s",
    },
    {
        "id": "c33f7772-e9ec-485b-8f23-5378f504d995",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1mth067-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRUmcB9XAm1VLhVkzBXhLjBhRD7WiT9ButRvA&s",
    },
    {
        "id": "1cf084a3-bc08-4875-9163-4e6aeee6a055",
        "old": "https://www.panattasport.com/wp-content/uploads/2023/03/1mth067-jpg-webp.webp",
        "new": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRUmcB9XAm1VLhVkzBXhLjBhRD7WiT9ButRvA&s",
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE equipments SET image_url = :new, updated_at = NOW() WHERE id = :id"),
        [{"id": f["id"], "new": f["new"]} for f in IMAGE_URL_FIXES],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE equipments SET image_url = :old, updated_at = NOW() WHERE id = :id"),
        [{"id": f["id"], "old": f["old"]} for f in IMAGE_URL_FIXES],
    )
