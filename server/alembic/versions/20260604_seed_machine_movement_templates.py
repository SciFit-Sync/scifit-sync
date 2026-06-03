"""PR-2: 머신/케이블 movement_template 시드 + exercise_muscles + movement_label 백필

Revision ID: 20260604_seed_machine_movement_templates
Revises: 20260604_seed_freeweight_exercises
Create Date: 2026-06-04

변경 사항:
  1. exercises (movement_template): 머신/케이블 정규 동작 25개 upsert
     ON CONFLICT(name_en) DO UPDATE — 멱등성 보장.
     core lift 4종(Bench Press/Back Squat/Conventional Deadlift/Overhead Press) name_en 재사용 없음.
  2. exercise_muscles: 각 movement_template의 primary 근육 INSERT ON CONFLICT DO NOTHING.
  3. equipments.movement_label_ko / movement_label_en 백필:
     equipment_type IN ('machine','cable') 전 기구에 정규 동작명 설정.
     movement_label_en 은 반드시 movement_template 의 name_en 과 정확히 일치
     (PR-3 이 movement_label_en → exercises.name_en 으로 해석함).

롤백:
  - 신규 추가한 movement_template exercises 삭제 (name_en IN (...) 로 DELETE)
  - exercise_muscles 는 CASCADE 로 삭제됨
  - movement_label_ko / movement_label_en 을 NULL 로 복원
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_seed_machine_movement_templates"
down_revision = "20260604_seed_freeweight_exercises"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# 정규 동작 정의
# (name_ko, name_en, category, primary_muscle_slug)
#
# category = primary 근육의 body_region (exercises.category 컬럼)
# primary_muscle_slug = muscle_groups.slug (exercise_muscles INSERT 에 사용)
#
# ※ name_en 은 기존 free-weight / core-lift exercises.name_en 과 충돌 방지를 위해
#    머신 특성이 드러나거나("Machine …") 동작 고유명을 사용함.
# ---------------------------------------------------------------------------
_MOVEMENT_TEMPLATES = [
    # ── 가슴 ─────────────────────────────────────────────────────────────────
    ("머신 체스트 프레스", "Machine Chest Press", "chest", "pectoralis_major"),
    ("머신 인클라인 체스트 프레스", "Machine Incline Chest Press", "chest", "pectoralis_major"),
    ("머신 디클라인 체스트 프레스", "Machine Decline Chest Press", "chest", "pectoralis_major"),
    ("펙덱 플라이", "Pec Deck", "chest", "pectoralis_major"),
    # ── 등 ───────────────────────────────────────────────────────────────────
    ("랫 풀다운", "Machine Lat Pulldown", "back", "latissimus_dorsi"),
    ("머신 하이 로우", "Machine High Row", "back", "latissimus_dorsi"),
    ("풀오버 머신", "Pullover Machine", "back", "latissimus_dorsi"),
    ("시티드 케이블 로우", "Seated Cable Row", "back", "rhomboids"),
    ("머신 로우", "Machine Row", "back", "rhomboids"),
    ("백 익스텐션 머신", "Back Extension Machine", "back", "erector_spinae"),
    # ── 어깨 ─────────────────────────────────────────────────────────────────
    ("머신 숄더 프레스", "Machine Shoulder Press", "shoulders", "anterior_deltoid"),
    ("머신 레터럴 레이즈", "Machine Lateral Raise", "shoulders", "lateral_deltoid"),
    ("리버스 펙덱", "Reverse Pec Deck", "shoulders", "posterior_deltoid"),
    # ── 팔 ───────────────────────────────────────────────────────────────────
    ("머신 바이셉 컬", "Machine Biceps Curl", "arms", "biceps_brachii"),
    ("프리처 컬 머신", "Preacher Curl Machine", "arms", "biceps_brachii"),
    ("머신 트라이셉 익스텐션", "Machine Triceps Extension", "arms", "triceps_brachii"),
    ("케이블 트라이셉 푸시다운", "Cable Triceps Pushdown", "arms", "triceps_brachii"),
    # ── 하체 ─────────────────────────────────────────────────────────────────
    ("레그 프레스", "Machine Leg Press", "legs", "quadriceps"),
    ("레그 익스텐션", "Machine Leg Extension", "legs", "quadriceps"),
    ("핵 스쿼트 머신", "Machine Hack Squat", "legs", "quadriceps"),
    ("레그 컬", "Machine Leg Curl", "legs", "hamstrings"),
    ("힙 스러스트 머신", "Hip Thrust Machine", "legs", "gluteus_maximus"),
    ("힙 어덕션/어브덕션 머신", "Hip Adduction Abduction Machine", "legs", "gluteus_medius"),
    # ── 코어 ─────────────────────────────────────────────────────────────────
    ("복부 크런치 머신", "Abdominal Crunch Machine", "core", "rectus_abdominis"),
    ("오블리크 머신", "Oblique Machine", "core", "rectus_abdominis"),
]

# ---------------------------------------------------------------------------
# 기구 ID → 정규 동작 name_en 매핑
# (equipment_id, movement_label_en)
#
# movement_label_en 은 _MOVEMENT_TEMPLATES 의 name_en 과 반드시 일치해야 함.
# ---------------------------------------------------------------------------
_EQUIPMENT_LABEL_MAP = [
    # ── 가슴: Machine Chest Press ────────────────────────────────────────────
    ("5bfab158-11ac-4dac-8ea2-462a7e95b233", "머신 체스트 프레스", "Machine Chest Press"),
    ("33e41f49-5a0a-4a67-bb84-e296e897667b", "머신 체스트 프레스", "Machine Chest Press"),
    ("814ba304-6aa1-4ba7-ba97-04df06fd8848", "머신 체스트 프레스", "Machine Chest Press"),
    ("e4913cd6-efd3-43d5-981a-45b5bc239977", "머신 체스트 프레스", "Machine Chest Press"),
    ("0c6816c6-27e5-4cb2-a998-09ae8ef3a566", "머신 체스트 프레스", "Machine Chest Press"),
    ("5d7c3d55-2f30-4d43-97f5-5cddce04c959", "머신 체스트 프레스", "Machine Chest Press"),
    ("15282ad6-a3fc-4be8-a95a-5e974632adff", "머신 체스트 프레스", "Machine Chest Press"),
    ("4989dc12-d0be-580d-a9b6-219ebd81add2", "머신 체스트 프레스", "Machine Chest Press"),
    # ── 가슴: Machine Incline Chest Press ───────────────────────────────────
    ("a330d5f3-7577-467f-8ea4-25bc6549c4d0", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("de9899fe-ebe1-48d3-8f1d-e97fb3cab291", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("67bda34c-d1b7-4ae7-aa43-11bb74ae40a7", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("13052afb-36e6-4fef-8e5d-e6048c40e9a6", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("910c3910-c313-47a6-8c7f-9161eea7de3d", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("20092f3c-4999-49bd-8ba6-4f51b5d0014e", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("8db23cf2-ff9a-580f-8615-55c1f5b7d2d8", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    ("59c360a7-6bab-5bdd-af4f-f642a0b29089", "머신 인클라인 체스트 프레스", "Machine Incline Chest Press"),
    # ── 가슴: Machine Decline Chest Press ───────────────────────────────────
    ("ca83c9ee-1ef4-4061-9477-db0d4e5dc8b1", "머신 디클라인 체스트 프레스", "Machine Decline Chest Press"),
    ("71cd26ee-394a-4669-9e1a-c4fdc554dc9e", "머신 디클라인 체스트 프레스", "Machine Decline Chest Press"),
    ("209b9675-eca3-4bb8-8246-42ffd3c88bfe", "머신 디클라인 체스트 프레스", "Machine Decline Chest Press"),
    ("ab765661-eb45-424e-ac36-10df2dabd391", "머신 디클라인 체스트 프레스", "Machine Decline Chest Press"),
    # ── 가슴: Pec Deck ──────────────────────────────────────────────────────
    ("344e3a37-a266-477b-8ffd-3f03e00cf2c8", "펙덱 플라이", "Pec Deck"),
    ("2a76d9ef-83a4-422d-ac89-dbfc9ad989dc", "펙덱 플라이", "Pec Deck"),
    # ── 등: Machine Lat Pulldown ─────────────────────────────────────────────
    ("ca6e2e7b-b2ee-4b0a-85fb-2ee516373357", "랫 풀다운", "Machine Lat Pulldown"),
    ("00f1ee81-9b15-43b8-aa1e-f4497ce00ed9", "랫 풀다운", "Machine Lat Pulldown"),
    ("c0e9d8dd-ef31-449c-92a0-5f533132e578", "랫 풀다운", "Machine Lat Pulldown"),
    ("724fbe01-a574-4b36-a28e-dcdcfdfcdae5", "랫 풀다운", "Machine Lat Pulldown"),
    ("b9b0ee51-610e-4546-bbf1-6172c3736808", "랫 풀다운", "Machine Lat Pulldown"),
    ("27632a4b-d5e9-40df-ba5a-6152d4153619", "랫 풀다운", "Machine Lat Pulldown"),
    ("73068157-25fc-4359-817f-e4820f8eaa3f", "랫 풀다운", "Machine Lat Pulldown"),
    ("92e82d08-8376-4b76-a3f6-9701d49d33a1", "랫 풀다운", "Machine Lat Pulldown"),
    ("ec620436-cabb-4f29-8813-1645eb4bd0ee", "랫 풀다운", "Machine Lat Pulldown"),
    ("fa0d0b81-9759-5f4b-8567-ba9a23a0a4ea", "랫 풀다운", "Machine Lat Pulldown"),
    ("568857d6-f3e0-5905-9f60-18ce5180a4e1", "랫 풀다운", "Machine Lat Pulldown"),
    ("325e25e2-4b64-5d2b-8e8e-e6871f9657b3", "랫 풀다운", "Machine Lat Pulldown"),
    ("bf3d0dde-84e3-510c-a43c-d0b017565431", "랫 풀다운", "Machine Lat Pulldown"),
    ("e94bec5c-a634-58e9-872f-8f63eee2b625", "랫 풀다운", "Machine Lat Pulldown"),
    # ── 등: Machine High Row ─────────────────────────────────────────────────
    ("b6bc5c86-ff02-48a0-a35c-9ee42172700f", "머신 하이 로우", "Machine High Row"),
    ("4cfb1e70-3807-469a-8b56-072766c52ab4", "머신 하이 로우", "Machine High Row"),
    ("22cbf7fd-44b5-429f-99dd-c90cf252935a", "머신 하이 로우", "Machine High Row"),
    ("e4b68832-bd2d-4996-a062-f08c96736e23", "머신 하이 로우", "Machine High Row"),
    ("be8c8a43-281e-5331-8539-e5ecf1b2cba1", "머신 하이 로우", "Machine High Row"),
    # ── 등: Pullover Machine ─────────────────────────────────────────────────
    ("91b90e10-cf49-4586-8bf2-f95b474f015b", "풀오버 머신", "Pullover Machine"),
    # ── 등: Seated Cable Row ─────────────────────────────────────────────────
    ("fde366f4-3d4a-434d-b9ea-953ac2450e3d", "시티드 케이블 로우", "Seated Cable Row"),
    ("98aeba22-b028-49c2-adfb-b74ac5384589", "시티드 케이블 로우", "Seated Cable Row"),
    ("d5123039-4a87-4e5c-97fd-bfcff2e65ed8", "시티드 케이블 로우", "Seated Cable Row"),
    ("462123c8-665c-4973-b92f-af706f03ca79", "시티드 케이블 로우", "Seated Cable Row"),
    ("b4b7db6f-fbd9-4a84-b21f-58328c0b0d00", "시티드 케이블 로우", "Seated Cable Row"),
    ("dc823fdb-8cc0-59db-8d4a-7fd03575723d", "시티드 케이블 로우", "Seated Cable Row"),
    ("c92e39a8-4faf-59d4-9bcb-fad9de96c2df", "시티드 케이블 로우", "Seated Cable Row"),
    # ── 등: Machine Row ──────────────────────────────────────────────────────
    ("ae593cd8-56a9-4175-ac62-599358819a80", "머신 로우", "Machine Row"),
    ("1a4c5c46-b772-42eb-8d8f-d3193c870411", "머신 로우", "Machine Row"),
    ("14eea95a-3c5f-5e5d-a31e-37ac32953b2a", "머신 로우", "Machine Row"),
    ("a8e1e289-f261-5a16-bca8-09b2afb30016", "머신 로우", "Machine Row"),
    # ── 등: Back Extension Machine ───────────────────────────────────────────
    ("1f50a13b-9e6a-4735-99e0-ee1c288d7678", "백 익스텐션 머신", "Back Extension Machine"),
    ("656293a3-578d-43e8-b80f-c224c0d93c0e", "백 익스텐션 머신", "Back Extension Machine"),
    # ── 어깨: Machine Shoulder Press ─────────────────────────────────────────
    ("7c8d3d90-04b9-432b-ab25-22d706821801", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("d45d8acd-a416-4170-9a2e-5e65c3a573ae", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("8c53382f-ef12-4f5e-aaca-c82c07ec35b0", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("77138264-6d7e-422d-b23f-033ffab52c10", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("74a84bde-b231-4aa9-9046-e1e1c935bada", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("d9b7ac61-fdd3-4ab7-8be0-27b7d505df0d", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("a97c569a-fda7-5431-b694-14fac355921d", "머신 숄더 프레스", "Machine Shoulder Press"),
    ("48255be6-dd0b-564a-9c80-65969f2f7f81", "머신 숄더 프레스", "Machine Shoulder Press"),
    # ── 어깨: Machine Lateral Raise ───────────────────────────────────────────
    ("69a902e8-51c5-405b-bb7c-76cbf2a05acd", "머신 레터럴 레이즈", "Machine Lateral Raise"),
    ("1c1c2fc5-6230-4763-8a32-193aeba72a5f", "머신 레터럴 레이즈", "Machine Lateral Raise"),
    ("8382e747-afcd-470b-b41f-7a0dd3e2a834", "머신 레터럴 레이즈", "Machine Lateral Raise"),
    ("4cacbc8f-26dd-48ec-a7cd-0f3a0426af3c", "머신 레터럴 레이즈", "Machine Lateral Raise"),
    # ── 어깨: Reverse Pec Deck ───────────────────────────────────────────────
    ("f97ee435-5cd5-44dd-87e3-fa35a7bfce54", "리버스 펙덱", "Reverse Pec Deck"),
    ("f6600405-5fd9-4aa5-864a-0d5788e79546", "리버스 펙덱", "Reverse Pec Deck"),
    ("b4975333-9543-4b69-8926-dd3c9e4e0fb6", "리버스 펙덱", "Reverse Pec Deck"),
    ("a1a42a00-dcd6-4a92-a8bb-2361e297bf55", "리버스 펙덱", "Reverse Pec Deck"),
    ("6fddb51b-6c16-4e9f-b815-415e7601ac03", "리버스 펙덱", "Reverse Pec Deck"),
    ("9f5ad84b-ff44-5267-83e5-b1eaf7e3bf8d", "리버스 펙덱", "Reverse Pec Deck"),
    ("d1547e9f-ba27-5993-9b4e-6f5d5f7661e8", "리버스 펙덱", "Reverse Pec Deck"),
    # ── 팔: Machine Biceps Curl ───────────────────────────────────────────────
    ("c24bd57b-1db7-4d96-a7f7-c75117203b11", "머신 바이셉 컬", "Machine Biceps Curl"),
    ("f9173625-8b40-46a9-b67b-4b2aba396968", "머신 바이셉 컬", "Machine Biceps Curl"),
    ("92127a9c-730e-4013-92ce-85873a4b4028", "머신 바이셉 컬", "Machine Biceps Curl"),
    ("c7ed172e-530b-4053-8970-76a1af1db288", "머신 바이셉 컬", "Machine Biceps Curl"),
    ("432c0565-c5f2-40f3-8882-349a0c9ccdb5", "머신 바이셉 컬", "Machine Biceps Curl"),
    ("52327eb7-9ae7-4732-80b9-e33e18eaa7c5", "머신 바이셉 컬", "Machine Biceps Curl"),
    # ── 팔: Preacher Curl Machine ─────────────────────────────────────────────
    ("67ee5817-ce22-40e8-b40d-96a8c505cba4", "프리처 컬 머신", "Preacher Curl Machine"),
    ("39109cfa-6ee4-4a7d-a931-1fd4a02c3851", "프리처 컬 머신", "Preacher Curl Machine"),
    ("45efe227-5806-5d60-90e3-30dd1850c16a", "프리처 컬 머신", "Preacher Curl Machine"),
    # ── 팔: Machine Triceps Extension ─────────────────────────────────────────
    ("cf32e0d1-1d00-4014-9ad0-acf6b20b90a7", "머신 트라이셉 익스텐션", "Machine Triceps Extension"),
    ("6d981d81-6667-44bc-a240-dfd64f62134b", "머신 트라이셉 익스텐션", "Machine Triceps Extension"),
    ("e6a22037-ad56-4e23-b10f-1d718a443276", "머신 트라이셉 익스텐션", "Machine Triceps Extension"),
    ("0b90c575-35a4-4e8c-af92-56873b895d50", "머신 트라이셉 익스텐션", "Machine Triceps Extension"),
    ("8d17772a-72cd-480a-ac24-9a578d462d88", "머신 트라이셉 익스텐션", "Machine Triceps Extension"),
    # ── 팔: Cable Triceps Pushdown ─────────────────────────────────────────────
    # (케이블 + Assisted Dip/Chin 기구는 Cable Triceps Pushdown 단일 템플릿으로 묶음)
    ("91dd2f21-b791-4ea8-8305-01482d045eaa", "케이블 트라이셉 푸시다운", "Cable Triceps Pushdown"),
    ("b6f855d3-27cf-41cb-9696-fbacc05c8529", "케이블 트라이셉 푸시다운", "Cable Triceps Pushdown"),
    ("8b92bac4-98be-4277-bae3-e45b39629d22", "케이블 트라이셉 푸시다운", "Cable Triceps Pushdown"),
    ("2ca108c5-6153-5b7b-9b22-530ef902178c", "케이블 트라이셉 푸시다운", "Cable Triceps Pushdown"),
    # ── 하체: Machine Leg Press ───────────────────────────────────────────────
    ("1bde4266-92b5-429b-9f9d-ecbadf143715", "레그 프레스", "Machine Leg Press"),
    ("21524b6c-e1e3-45cc-b82e-c258dc963044", "레그 프레스", "Machine Leg Press"),
    ("b2640296-a9cf-4722-a1b3-2eafeab53059", "레그 프레스", "Machine Leg Press"),
    ("22523f1a-dfbf-482f-8247-196e1f894688", "레그 프레스", "Machine Leg Press"),
    ("351ce983-fa20-5676-a05c-37e7cf9b4837", "레그 프레스", "Machine Leg Press"),
    ("f9fadf1e-6004-5297-b8d3-7b7a9c1a1bb1", "레그 프레스", "Machine Leg Press"),
    # ── 하체: Machine Leg Extension ───────────────────────────────────────────
    ("f54d70f0-9362-4330-8e4f-4c61faa36b92", "레그 익스텐션", "Machine Leg Extension"),
    ("0857ee52-c036-40e8-b202-2c666ad65188", "레그 익스텐션", "Machine Leg Extension"),
    ("a10ba94c-8406-4a24-b2ba-4b4a4e3dc580", "레그 익스텐션", "Machine Leg Extension"),
    ("f13b498f-5922-5387-806b-be9639fee4c3", "레그 익스텐션", "Machine Leg Extension"),
    ("ca9ba9fb-5a5a-56c1-9937-73c500b62220", "레그 익스텐션", "Machine Leg Extension"),
    # ── 하체: Machine Hack Squat ──────────────────────────────────────────────
    ("20f53b69-e1d9-4cd1-8f40-09fe644c4141", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("4f0113a1-b2cf-49d1-b9ad-843049a4b94b", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("602a5d88-860c-4e29-b93f-274a45b7278e", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("41428c51-d3da-45dc-8d06-316247033d1d", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("df067c60-2308-4fde-b89c-f23caa796db7", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("b036a564-a3ef-4cf9-b2ba-33a633ec2b94", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("8e672b7c-89b9-5596-aaa4-f20d888b3386", "핵 스쿼트 머신", "Machine Hack Squat"),
    ("f19ec570-cfe3-5093-8bc2-764ce5e43d26", "핵 스쿼트 머신", "Machine Hack Squat"),
    # ── 하체: Machine Leg Curl ────────────────────────────────────────────────
    ("1bbfc63e-e90a-4d6f-91fa-d427746c461c", "레그 컬", "Machine Leg Curl"),
    ("468015e1-14ae-4df5-bf34-dc7e479dbc9f", "레그 컬", "Machine Leg Curl"),
    ("5d130ddc-e1c6-45d9-af22-5378ecdc570a", "레그 컬", "Machine Leg Curl"),
    ("1081a8d8-c2bc-4d38-bd4f-ab22a66fef1e", "레그 컬", "Machine Leg Curl"),
    ("9e7a9577-1a5e-49bf-bf5c-7a990bbdb227", "레그 컬", "Machine Leg Curl"),
    ("7bb7197f-89dc-466a-906d-15e1b8b0906b", "레그 컬", "Machine Leg Curl"),
    ("0375f89d-ad2e-42bc-a2c7-3a4482e0ffbc", "레그 컬", "Machine Leg Curl"),
    ("7331485c-c1c0-4798-b157-b1cac104f378", "레그 컬", "Machine Leg Curl"),
    ("7d60b6f1-912d-5d6b-9585-2ac56d8f4c1a", "레그 컬", "Machine Leg Curl"),
    ("d12dd92d-9357-59ab-a391-9883b0bc994c", "레그 컬", "Machine Leg Curl"),
    # ── 하체: Hip Thrust Machine ──────────────────────────────────────────────
    ("b3266141-9f33-5929-a6ee-26e78ee3ac46", "힙 스러스트 머신", "Hip Thrust Machine"),
    # ── 하체: Hip Adduction Abduction Machine ─────────────────────────────────
    ("9696a691-2dff-5b7f-90d3-7ea38f576381", "힙 어덕션/어브덕션 머신", "Hip Adduction Abduction Machine"),
    ("3194d412-0a32-505b-a2a7-ab0432506d7f", "힙 어덕션/어브덕션 머신", "Hip Adduction Abduction Machine"),
    # ── 코어: Abdominal Crunch Machine ────────────────────────────────────────
    ("312c973a-1aa9-4bc2-aa19-c383ba560fcf", "복부 크런치 머신", "Abdominal Crunch Machine"),
    ("c1415ccb-9224-4781-9c84-8a74d9442f72", "복부 크런치 머신", "Abdominal Crunch Machine"),
    ("b2ccccfe-ac97-4fbc-aa75-dc92f9a9f4fb", "복부 크런치 머신", "Abdominal Crunch Machine"),
    ("03814c50-4988-42fa-9358-b09ded728116", "복부 크런치 머신", "Abdominal Crunch Machine"),
    ("c33f7772-e9ec-485b-8f23-5378f504d995", "복부 크런치 머신", "Abdominal Crunch Machine"),
    # ── 코어: Oblique Machine ────────────────────────────────────────────────
    ("1cf084a3-bc08-4875-9163-4e6aeee6a055", "오블리크 머신", "Oblique Machine"),
]

# name_en 목록 (downgrade 용)
_TEMPLATE_NAME_ENS = [t[1] for t in _MOVEMENT_TEMPLATES]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. movement_template exercises upsert ────────────────────────────────
    # ON CONFLICT(name_en) DO UPDATE: category / name 을 최신 값으로 유지 (멱등성)
    for name_ko, name_en, category, _slug in _MOVEMENT_TEMPLATES:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercises (id, name, name_en, category, created_at, updated_at)
                VALUES (gen_random_uuid(), :name, :name_en, :category, now(), now())
                ON CONFLICT (name_en) DO UPDATE
                    SET name     = EXCLUDED.name,
                        category = EXCLUDED.category,
                        updated_at = now()
                """
            ),
            {"name": name_ko, "name_en": name_en, "category": category},
        )

    # ── 2. exercise_muscles: primary 근육 시드 ────────────────────────────────
    # name_en + slug JOIN → exercise_id / muscle_group_id 해석 → INSERT ON CONFLICT DO NOTHING
    for _name_ko, name_en, _category, slug in _MOVEMENT_TEMPLATES:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT e.id, mg.id, 'primary', NULL
                FROM exercises e
                JOIN muscle_groups mg ON mg.name = :slug
                WHERE e.name_en = :name_en
                ON CONFLICT DO NOTHING
                """
            ),
            {"name_en": name_en, "slug": slug},
        )

    # ── 3. equipments.movement_label_ko / movement_label_en 백필 ────────────
    # equipment_id 로 직접 UPDATE (결정론적, 재실행 안전)
    for equipment_id, label_ko, label_en in _EQUIPMENT_LABEL_MAP:
        conn.execute(
            sa.text(
                """
                UPDATE equipments
                SET movement_label_ko = :label_ko,
                    movement_label_en  = :label_en,
                    updated_at         = now()
                WHERE id = :equipment_id
                """
            ),
            {
                "equipment_id": equipment_id,
                "label_ko": label_ko,
                "label_en": label_en,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()

    # ── 1. movement_label 을 NULL 로 복원 ─────────────────────────────────────
    equipment_ids = [row[0] for row in _EQUIPMENT_LABEL_MAP]
    if equipment_ids:
        conn.execute(
            sa.text(
                """
                UPDATE equipments
                SET movement_label_ko = NULL,
                    movement_label_en  = NULL,
                    updated_at         = now()
                WHERE id = ANY(:ids)
                """
            ),
            {"ids": equipment_ids},
        )

    # ── 2. 신규 movement_template exercises 삭제 ──────────────────────────────
    # exercise_muscles 는 FK CASCADE 로 자동 삭제됨
    conn.execute(
        sa.text("DELETE FROM exercises WHERE name_en = ANY(:names)"),
        {"names": _TEMPLATE_NAME_ENS},
    )
