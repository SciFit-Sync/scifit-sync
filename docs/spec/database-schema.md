# 데이터 모델 (29개 테이블)

> Scifit-Sync 프로젝트 기획 및 시스템 설계서 기반 — 개선 ERD
> Stack: PostgreSQL (Supabase) + ChromaDB Persistent 모드 + JSONB 컬럼 활용

---

## 도메인별 테이블 구성

| 도메인 | 개수 | 테이블 |
|---|---|---|
| User | 5 | `users`, `user_profiles`, `user_body_measurements`, `user_exercise_1rm`, `refresh_tokens` |
| Gym | 7 | `gyms`, `user_gyms`, `equipment_brands`, `equipments`, `gym_equipments`, `equipment_reports`, `equipment_muscles` |
| Exercise | 4 | `exercises`, `exercise_equipment_map`, `muscle_groups`, `exercise_muscles` |
| Routine | 4 | `workout_routines`, `routine_days`, `routine_exercises`, `routine_papers` |
| Program | 2 | `programs`, `program_routines` |
| Workout | 2 | `workout_logs`, `workout_log_sets` |
| Chat & RAG | 4 | `chat_sessions`, `chat_messages`, `papers`, `paper_chunks` |
| 기타 | 1 | `notifications` |
| **합계** | **29** | |

---

## 도메인별 설명

### User 도메인 (5개)

| 테이블 | 설명 |
|--------|------|
| `users` | 계정 (로컬 + 카카오 소셜 로그인). `name` 실명 |
| `user_profiles` | 1:1 프로필. 고정값(성별, 생년월일, 키, 경력) + 유저 선호 목표 배열 |
| `user_body_measurements` | 변동 신체 지표 INSERT only 이력 (체중/체지방/골격근량) |
| `user_exercise_1rm` | 운동별 1RM 추정 INSERT only 이력 (Epley 또는 manual) |
| `refresh_tokens` | JWT Refresh Token. `family_id`로 Token Rotation 지원 |

### Gym 도메인 (7개)

| 테이블 | 설명 |
|--------|------|
| `gyms` | 헬스장 (카카오 Local API 연동, `kakao_place_id` UK) |
| `user_gyms` | 사용자↔헬스장 매핑. `is_primary`로 주 이용 헬스장 1개 |
| `equipment_brands` | 기구 제조사 (Life Fitness, Technogym, Hammer Strength, Newtech, Panatta 등). `default_bar_unit` / `default_stack_unit`로 브랜드별 기본 단위 정책 보유 (v2.1) |
| `equipments` | 기구 상세. `category` (근육 부위 대표 1개) + `sub_category` (세부 영역, v2.1) + `equipment_type` (물리 타입) 분리. 중량 계산 엔진의 핵심 참조. 무게 컬럼(`bar_weight`, `min_stack`, `max_stack`, `stack_weight`)은 원본 단위 그대로 저장하며 단위는 `bar_weight_unit` / `stack_unit`에 보존 (v2.1) |
| `gym_equipments` | 헬스장↔기구 매핑 (복합 PK). 헬스장마다 복수 기구 |
| `equipment_reports` | 기구 데이터 사용자 제보 (missing / incorrect_data) + status 워크플로우 |
| `equipment_muscles` | 기구↔근육 N:M. 한 기구가 여러 근육 활성 (예: 체스트 프레스 → chest + triceps) |

### Exercise 도메인 (4개)

| 테이블 | 설명 |
|--------|------|
| `exercises` | 운동 마스터 (한글명 + 영문명 UK). compound/isolation 분류 |
| `exercise_equipment_map` | 운동↔기구 N:M 매핑 (복합 PK) |
| `muscle_groups` | 근육군 마스터 (전신 세부 분류, 31개 시드) |
| `exercise_muscles` | 운동↔근육 N:M. `involvement` (primary/secondary/stabilizer) + `activation_pct` (EMG 수치) |

### Routine 도메인 (4개)

| 테이블 | 설명 |
|--------|------|
| `workout_routines` | 루틴 (AI 생성 또는 사용자 커스텀). `fitness_goals[]` 복수 목표 허용 (D-M6). `gym_id`로 헬스장별 독립 보유 |
| `routine_days` | 분할 일차 (Day 1, Day 2, …). 예: 3분할 → 3 rows |
| `routine_exercises` | 일차별 운동 목록. `reps_min`/`reps_max` 범위 표기, `note` 수행 가이드 |
| `routine_papers` | 루틴/운동별 논문 근거 (다대다) |

### Program 도메인 (2개) — F-7, D-10 해결

| 테이블 | 설명 |
|--------|------|
| `programs` | 프로그램 (여러 루틴 묶음). 예: "4주 벌크업 프로그램" |
| `program_routines` | 프로그램↔루틴 N:M + `order_index`로 순서 |

### Workout 도메인 (2개)

| 테이블 | 설명 |
|--------|------|
| `workout_logs` | 운동 세션 기록. `routine_day_id`로 수행한 Day 기록, `gym_id`로 수행 헬스장 기록, `status` (진행 중/완료) |
| `workout_log_sets` | 세트 단위 수행 기록 (`weight_kg`, `reps`, `rpe`, `is_completed`). **F-10**: `routine_exercise_id`로 루틴 내 운동 슬롯 직접 연결 — 같은 운동이 다른 설정으로 배치된 경우 구분 가능 |

### Chat & RAG 도메인 (4개)

| 테이블 | 설명 |
|--------|------|
| `chat_sessions` | 챗봇 대화 세션 |
| `chat_messages` | 메시지 (user/assistant). `paper_ids` JSONB 배열로 복수 논문 인용 |
| `papers` | PubMed 논문 메타데이터 (`doi`, `pmid` UK). `year`, `abstract`, `summary` (한국어 요약) |
| `paper_chunks` | RAG 청크 (Section-Aware). `chroma_id`로 ChromaDB 벡터 연결 |

### 기타 (1개)

| 테이블 | 설명 |
|--------|------|
| `notifications` | 알림 (`workout_reminder`, `motivation`, `po_suggestion`, `skip_warning`, `system`). `data_json` 확장 데이터 |

---

## ERD

```mermaid
erDiagram
    %% ========================================
    %% User 도메인 (5개 테이블)
    %% ========================================
    users {
        UUID id PK "gen_random_uuid()"
        varchar email UK "NOT NULL"
        varchar username UK "NOT NULL"
        varchar name "NOT NULL (API-1)"
        varchar password_hash "NULL (소셜 로그인 시)"
        varchar provider "local | kakao, NOT NULL DEFAULT local"
        varchar provider_id "소셜 로그인 ID (NULL)"
        boolean is_active "NOT NULL DEFAULT true"
        timestamp created_at "NOT NULL DEFAULT NOW()"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    user_profiles {
        UUID user_id PK "users.id, 1:1"
        enum gender "male | female, NOT NULL"
        date birth_date "NOT NULL (M-2: age→birth_date)"
        decimal height_cm "NOT NULL (M-1: profile 고정값)"
        text_array default_goals "유저 선호 목표 복수 배열 (API-3, 회원가입 goals[] 저장)"
        enum career_level "beginner|novice|intermediate|advanced, NOT NULL"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    user_body_measurements {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        decimal weight_kg "NOT NULL"
        decimal skeletal_muscle_kg "NULL"
        decimal body_fat_pct "NULL"
        date measured_at "NOT NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    user_exercise_1rm {
        UUID id PK "(C-1: UNIQUE 제거, 이력 추적)"
        UUID user_id FK "users.id CASCADE"
        UUID exercise_id FK "exercises.id CASCADE"
        decimal weight_kg "추정 1RM (kg), NOT NULL"
        enum source "manual | epley, NOT NULL DEFAULT manual"
        timestamp estimated_at "측정/추정 시각, NOT NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    refresh_tokens {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        varchar token_hash UK "SHA-256, NOT NULL"
        UUID family_id "Token Rotation 패밀리, NOT NULL"
        UUID replaced_by_id FK "후속 토큰 ID (NULL = 최신)"
        varchar device_info "NULL"
        timestamp expires_at "NOT NULL"
        timestamp revoked_at "NULL = 유효"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    %% ========================================
    %% Gym 도메인 (7개 테이블)
    %% ========================================
    gyms {
        UUID id PK
        varchar kakao_place_id UK "카카오 장소 ID"
        varchar name "NOT NULL"
        varchar address "NOT NULL"
        decimal latitude "NOT NULL"
        decimal longitude "NOT NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    user_gyms {
        UUID user_id FK "users.id CASCADE"
        UUID gym_id FK "gyms.id CASCADE"
        boolean is_primary "NOT NULL DEFAULT false"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    equipment_brands {
        UUID id PK
        varchar name UK "NOT NULL"
        varchar logo_url "NULL"
        enum default_bar_unit "weightunit kg|lb, NOT NULL DEFAULT kg (v2.1)"
        enum default_stack_unit "weightunit kg|lb, NOT NULL DEFAULT kg (v2.1)"
    }

    equipments {
        UUID id PK
        UUID brand_id FK "equipment_brands.id SET NULL, NULL"
        varchar name "NOT NULL"
        varchar name_en "영문명 (NULL, v2.1 ERD 문서 보정)"
        enum category "chest|back|shoulders|arms|core|legs (근육 부위, API-12)"
        varchar sub_category "category 세부 영역 (NULL, v2.1 — upper_back/front_delt 등)"
        enum equipment_type "cable|machine|barbell|dumbbell|bodyweight (물리 타입, API-12)"
        decimal pulley_ratio "NOT NULL DEFAULT 1.0"
        decimal bar_weight "바/레버 무게 (NULL). 값은 bar_weight_unit 단위 그대로. v2.1 RENAME(from bar_weight_kg)"
        enum bar_weight_unit "weightunit kg|lb (NULL only when bar_weight NULL, v2.1) — CHECK 동기성"
        boolean has_weight_assist "어시스트 기구, NOT NULL DEFAULT false"
        decimal min_stack "최소 스택 중량 (NULL). 단위는 stack_unit. v2.1 RENAME(from min_stack_kg)"
        decimal max_stack "최대 스택 중량 (NULL). 단위는 stack_unit. v2.1 RENAME(from max_stack_kg)"
        jsonb stack_weight "스택 한 블록 무게 (NULL, v2.1 RENAME + decimal→jsonb). 단순:{value:5} / 변동:{pattern:[...]}"
        enum stack_unit "weightunit kg|lb (NULL only when all 3 stack fields NULL, v2.1) — CHECK 동기성"
        varchar image_url "기구 이미지 (NULL) (M-6)"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    gym_equipments {
        UUID gym_id FK "gyms.id CASCADE"
        UUID equipment_id FK "equipments.id CASCADE"
        int quantity "NOT NULL DEFAULT 1"
    }

    equipment_reports {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        UUID gym_id FK "gyms.id CASCADE"
        UUID equipment_id FK "equipments.id CASCADE"
        enum report_type "missing | incorrect_data, NOT NULL"
        enum status "pending|reviewed|resolved, NOT NULL DEFAULT pending (M-7)"
        text description "설명 (NULL, API-10)"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    equipment_muscles {
        UUID equipment_id FK "equipments.id CASCADE (API-13)"
        UUID muscle_group_id FK "muscle_groups.id RESTRICT"
        enum involvement "primary | secondary, NOT NULL"
    }

    %% ========================================
    %% Exercise 도메인 (4개 테이블)
    %% ========================================
    exercises {
        UUID id PK
        varchar name "한글명, NOT NULL"
        varchar name_en UK "영문명, NOT NULL (S-4: UNIQUE)"
        varchar category "compound | isolation 등, NOT NULL"
        text description "NULL"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    exercise_equipment_map {
        UUID exercise_id FK "exercises.id CASCADE"
        UUID equipment_id FK "equipments.id CASCADE"
    }

    muscle_groups {
        UUID id PK
        varchar name UK "영문명, NOT NULL"
        varchar name_ko UK "한글명, NOT NULL"
        varchar body_region "chest|back|shoulders|arms|core|legs, NOT NULL"
    }

    exercise_muscles {
        UUID exercise_id FK "exercises.id CASCADE"
        UUID muscle_group_id FK "muscle_groups.id RESTRICT"
        enum involvement "primary|secondary|stabilizer, NOT NULL"
        int activation_pct "EMG 활성도 % (NULL, API-5)"
    }

    %% ========================================
    %% Routine 도메인 (4개 테이블)
    %% ========================================
    workout_routines {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        UUID gym_id FK "gyms.id SET NULL (F-9)"
        varchar name "NOT NULL"
        text_array fitness_goals "복수 목표 배열 (F-5, D-M6 재결정)"
        jsonb target_muscle_group_ids "선택 부위 UUID 배열 (F-5)"
        int session_duration_minutes "세션 시간 (F-5)"
        enum split_type "2split|3split|4split|5split (NULL)"
        enum generated_by "user | ai, NOT NULL DEFAULT user"
        enum status "active|archived, NOT NULL DEFAULT active (M-5)"
        text ai_reasoning "AI 추천 근거 (NULL)"
        timestamp deleted_at "Soft Delete (NULL = 활성)"
        timestamp created_at "NOT NULL DEFAULT NOW()"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    routine_days {
        UUID id PK
        UUID routine_id FK "workout_routines.id CASCADE"
        int day_number "NOT NULL"
        varchar label "가슴/삼두 등, NOT NULL"
    }

    routine_exercises {
        UUID id PK
        UUID routine_day_id FK "routine_days.id CASCADE"
        UUID exercise_id FK "exercises.id RESTRICT"
        UUID equipment_id FK "equipments.id SET NULL, NULL"
        int order_index "NOT NULL"
        int sets "NOT NULL"
        int reps_min "범위 하한 (API-4)"
        int reps_max "범위 상한 (API-4)"
        decimal weight_kg "기구 설정 중량 (NULL = 맨몸)"
        int rest_seconds "NOT NULL DEFAULT 60"
        text note "수행 가이드 메모 (NULL) (S-3)"
    }

    routine_papers {
        UUID id PK
        UUID routine_id FK "workout_routines.id CASCADE"
        UUID routine_exercise_id FK "routine_exercises.id SET NULL, NULL"
        UUID paper_id FK "papers.id CASCADE"
        text relevance_summary "적용 이유 (NULL)"
    }

    %% ========================================
    %% Program 도메인 (2개 테이블) (F-7)
    %% ========================================
    programs {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        varchar name "NOT NULL"
        text description "NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    program_routines {
        UUID program_id FK "programs.id CASCADE"
        UUID routine_id FK "workout_routines.id CASCADE"
        int order_index "프로그램 내 순서, NOT NULL"
    }

    %% ========================================
    %% Workout 도메인 (2개 테이블)
    %% ========================================
    workout_logs {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        UUID routine_day_id FK "routine_days.id SET NULL (C-3)"
        UUID gym_id FK "gyms.id SET NULL (F-9)"
        timestamp started_at "NOT NULL"
        timestamp finished_at "NULL (진행 중 = NULL)"
        enum status "in_progress|completed, DEFAULT in_progress (S-2)"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    workout_log_sets {
        UUID id PK
        UUID workout_log_id FK "workout_logs.id CASCADE"
        UUID exercise_id FK "exercises.id RESTRICT"
        UUID routine_exercise_id FK "routine_exercises.id SET NULL, NULL (F-10)"
        int set_number "NOT NULL"
        decimal weight_kg "기구 설정 중량 (NULL = 맨몸)"
        int reps "NOT NULL"
        decimal rpe "주관적 강도 1-10 (NULL)"
        boolean is_completed "NOT NULL DEFAULT false"
        timestamp performed_at "NOT NULL"
    }

    %% ========================================
    %% Chat & RAG 도메인 (4개 테이블)
    %% ========================================
    chat_sessions {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        varchar title "NOT NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
        timestamp updated_at "NOT NULL DEFAULT NOW()"
    }

    chat_messages {
        UUID id PK
        UUID session_id FK "chat_sessions.id CASCADE"
        enum role "user | assistant, NOT NULL"
        text content "NOT NULL"
        jsonb paper_ids "참조 논문 UUID 배열 (C-2)"
        int token_count "NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    papers {
        UUID id PK
        varchar doi UK "NULL (S-1: UNIQUE)"
        varchar pmid UK "NULL (S-1: UNIQUE)"
        varchar title "NOT NULL"
        text authors "NOT NULL"
        varchar journal "NOT NULL"
        int year "발행 연도 NOT NULL (API-9)"
        text abstract "NOT NULL"
        text summary "한국어 요약 (NULL, API-8)"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    paper_chunks {
        UUID id PK
        UUID paper_id FK "papers.id CASCADE"
        int chunk_index "NOT NULL"
        varchar section_name "Introduction, Methods 등 (NULL)"
        text content "NOT NULL"
        int token_count "NOT NULL"
        varchar chroma_id "ChromaDB 벡터 ID, NOT NULL"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    %% ========================================
    %% 기타 (1개 테이블)
    %% ========================================
    notifications {
        UUID id PK
        UUID user_id FK "users.id CASCADE"
        enum type "workout_reminder|motivation|po_suggestion|skip_warning|system (API-7)"
        varchar title "NOT NULL"
        text body "NOT NULL"
        boolean is_read "NOT NULL DEFAULT false"
        jsonb data_json "PO 제안 등 확장 데이터 (NULL)"
        timestamp created_at "NOT NULL DEFAULT NOW()"
    }

    %% ========================================
    %% 관계 정의
    %% ========================================

    %% User 도메인
    users ||--o| user_profiles : "1:1 프로필"
    users ||--o{ user_body_measurements : "신체 측정 이력"
    users ||--o{ user_exercise_1rm : "1RM 이력 (C-1)"
    users ||--o{ refresh_tokens : "인증 토큰"
    users ||--o{ user_gyms : "이용 헬스장"
    users ||--o{ workout_routines : "보유 루틴"
    users ||--o{ workout_logs : "운동 기록"
    users ||--o{ chat_sessions : "챗봇 세션"
    users ||--o{ notifications : "알림"
    users ||--o{ equipment_reports : "기구 제보"
    users ||--o{ programs : "프로그램 (F-7)"

    %% Gym 도메인
    gyms ||--o{ user_gyms : "회원"
    gyms ||--o{ gym_equipments : "보유 기구"
    gyms ||--o{ equipment_reports : "제보 대상 헬스장"
    gyms ||--o{ workout_routines : "루틴 대상 헬스장 (F-9)"
    gyms ||--o{ workout_logs : "운동 수행 헬스장 (F-9)"
    equipment_brands ||--o{ equipments : "브랜드 기구"
    equipments ||--o{ gym_equipments : "헬스장 배치"
    equipments ||--o{ equipment_reports : "제보 대상 기구"
    equipments ||--o{ equipment_muscles : "활성 근육 (API-13)"
    muscle_groups ||--o{ equipment_muscles : "기구 활성 (API-13)"

    %% Exercise 도메인
    exercises ||--o{ exercise_equipment_map : "사용 가능 기구"
    exercises ||--o{ exercise_muscles : "타겟 근육 (복수)"
    exercises ||--o{ routine_exercises : "루틴 운동"
    exercises ||--o{ workout_log_sets : "기록 운동"
    exercises ||--o{ user_exercise_1rm : "운동별 1RM"
    equipments ||--o{ exercise_equipment_map : "사용 가능 운동"
    muscle_groups ||--o{ exercise_muscles : "근육별 운동"

    %% Routine 도메인
    workout_routines ||--o{ routine_days : "분할 일차"
    workout_routines ||--o{ routine_papers : "참조 논문"
    workout_routines ||--o{ program_routines : "프로그램 소속"
    routine_days ||--o{ routine_exercises : "일차별 운동"
    routine_days ||--o{ workout_logs : "기록 연결 (C-3)"
    routine_exercises ||--o{ routine_papers : "운동별 논문"
    routine_exercises ||--o{ workout_log_sets : "세트 기록 맥락 (F-10)"
    equipments ||--o{ routine_exercises : "루틴 기구"

    %% Program 도메인
    programs ||--o{ program_routines : "루틴 묶음 (F-7)"

    %% Workout 도메인
    workout_logs ||--o{ workout_log_sets : "세트 기록"

    %% Chat & RAG 도메인
    chat_sessions ||--o{ chat_messages : "메시지"
    papers ||--o{ paper_chunks : "RAG 청크"
    papers ||--o{ routine_papers : "루틴 참조"
```

---

## 주요 설계 결정

### 공통
- 모든 PK: UUID v4 (`gen_random_uuid()`)
- 모든 테이블: `created_at` 기록, 변경 가능 테이블은 `updated_at` 자동 갱신
- DB 관리: Alembic 단독 — Supabase 대시보드 직접 수정 절대 금지

### 운동 목표 (D-M6 재결정 — D-14 폐기)
- 단일 enum → **복수 선택 정책으로 전환**
- `user_profiles.default_goals` = `text[]` (회원가입 시 선호 목표 배열)
- `workout_routines.fitness_goals` = `text[]` (루틴별 목표 복수 허용)
- 허용 값: `'hypertrophy' | 'strength' | 'endurance' | 'rehabilitation' | 'weight_loss'`
- ⚠️ 후속 D-issue 등록 예정: 복수 목표 시 PO/권장 중량 계산 기준 정책

### 기구 분류 (API-12: category와 equipment_type 분리)
- `equipments.category` = 근육 부위 대표 1개: `'chest' | 'back' | 'shoulders' | 'arms' | 'core' | 'legs'`
- `equipments.sub_category` = 세부 영역 (v2.1): `'upper_back' | 'lower_back' | 'front_delt' | 'side_delt' | 'rear_delt' | 'upper_chest' | 'mid_chest' | 'lower_chest' | 'biceps' | 'triceps' | 'quads' | 'hamstrings' | 'abs'` 등. enum이 아닌 `varchar` — 향후 어휘 세분화는 스키마 변경 없이 데이터 값 진화로 대응.
- `equipments.equipment_type` = 물리 타입: `'cable' | 'machine' | 'barbell' | 'dumbbell' | 'bodyweight'`
- 중량 계산 엔진은 `equipment_type` + `pulley_ratio` + `bar_weight_kg` + `has_weight_assist` 기준

### 무게 단위 정책 (v2.1)
**DB는 CSV에 표기된 원본 단위 그대로 저장하며, 단위 변환을 storage time에 강제하지 않는다.** 각 값의 단위는 같은 행의 `*_unit` 컬럼에서 즉시 확인할 수 있다. 단위 변환은 비교·합산이 필요한 컴포넌트(예: `load_calc.py`)가 compute time에 책임진다.

두 종류의 무게가 의미적으로 분리된다:

1. **바/레버 그룹** (`bar_weight`, `bar_weight_unit`): 제조사가 하드웨어에 표기한 기구 자체의 무게.
   - 미국 브랜드(Hammer Strength, Life Fitness 등) → `bar_weight_unit='lb'`
   - 한국·유럽 브랜드(Newtech, Panatta 등) → `bar_weight_unit='kg'`
2. **스택/원판 그룹** (`min_stack`, `max_stack`, `stack_weight`, `stack_unit`):
   - selectorized 머신(MTS 시리즈 등): 제조사 내장 스택 → 제조사 표기 단위 그대로 `stack_unit` 기록 (보통 'lb').
   - plate-loaded 머신: 사용자가 끼우는 원판 → 국내 헬스장 표준 kg (`stack_unit='kg'`).

같은 행에서 `bar_weight_unit='lb'`이고 `stack_unit='kg'`인 조합이 정상이며, ETL은 두 그룹을 독립 처리한다. `equipment_brands.default_bar_unit` / `default_stack_unit`은 신규 import 시 명시값이 없을 때의 fallback이다.

**CHECK 제약 (v2.1)** — 값과 단위의 동기성을 DB가 강제:

```sql
ALTER TABLE equipments ADD CONSTRAINT chk_bar_unit_synced CHECK (
  (bar_weight IS NULL AND bar_weight_unit IS NULL)
  OR (bar_weight IS NOT NULL AND bar_weight_unit IS NOT NULL)
);
ALTER TABLE equipments ADD CONSTRAINT chk_stack_unit_synced CHECK (
  (min_stack IS NULL AND max_stack IS NULL AND stack_weight IS NULL AND stack_unit IS NULL)
  OR ((min_stack IS NOT NULL OR max_stack IS NOT NULL OR stack_weight IS NOT NULL) AND stack_unit IS NOT NULL)
);
```

즉, 무게 값이 존재할 때 단위는 반드시 `'kg'` 또는 `'lb'` 중 하나로 결정된다 — "값은 있는데 단위 NULL" 같은 모순 상태 금지.

### `stack_weight` JSONB 스키마 (v2.1)
타입을 `decimal`에서 `jsonb`로 변경. 값의 **단위는 같은 행의 `stack_unit`**이 결정하며 JSONB 내부에는 단위를 넣지 않는다(단일 진실 원칙). 두 가지 형태를 허용:

```jsonc
// 균일 스택
{ "value": 5 }                            // stack_unit='kg' → 5kg
{ "value": 10 }                           // stack_unit='lb' → 10lb

// 변동 스택 (예: Hammer Strength Select 시리즈, 1~5번 블록 10lb, 6~15번 블록 15lb)
{ "pattern": [
    { "from": 1, "to": 5,  "value": 10 },
    { "from": 6, "to": 15, "value": 15 }
]}                                        // 위 예시는 stack_unit='lb'
```

앱 레이어 검증: `value`와 `pattern`은 상호 배타. `pattern[0].from == 1`, 인접 구간 (`prev.to + 1 == curr.from`).

### 중량 기록
- `weight_kg` = 기구 표시값 (사용자 입력)
- 실효 부하 = `weight_kg × pulley_ratio` (cable/machine)

### 1RM 이력 (C-1)
- `user_exercise_1rm`은 INSERT only 이력 — UNIQUE 제거, 시간순 추적

### 삭제 정책
- 루틴: soft delete (`deleted_at` nullable), 복구 불가
- 운동 기록 보존: `workout_logs.routine_day_id`, `workout_log_sets.routine_exercise_id`는 SET NULL (C-3, F-10) — 루틴 삭제 후에도 기록 보존
- 나머지: hard delete

### 임베딩
- ChromaDB Persistent 모드 단독 — pgvector 미사용
- `paper_chunks.chroma_id`로 PostgreSQL ↔ ChromaDB 연결

### JSONB 컬럼 활용
- `chat_messages.paper_ids`: 복수 논문 인용 배열 (C-2)
- `notifications.data_json`: 알림 타입별 확장 데이터
- `workout_routines.target_muscle_group_ids`: 선택 부위 UUID 배열 (F-5)

### Program 도메인 신설 (F-7, D-10 해결)
- D-10 *"Program vs Routine 관계"* 결정: 별도 도메인으로 분리
- 프로그램 = 여러 루틴 묶음 + 순서 (`program_routines.order_index`)
- 사용자 1명 → 프로그램 N개 → 루틴 N개 계층

### Workout 슬롯 추적 (F-10)
- `workout_log_sets.routine_exercise_id`로 루틴 내 운동 슬롯 직접 연결
- 같은 운동(`exercise_id`)이 동일 루틴에 다른 설정으로 두 번 배치된 경우 구분 가능

---

## 변경 이력

| 버전 | 변경 내용 |
|------|----------|
| v2.1 (29테이블, docs-only) | 수집 데이터셋(Hammer Strength / Newtech / Panatta CSV) 정합화. `equipments`에 `name_en` 문서 보정, `sub_category` 신규, `bar_weight_unit` / `stack_unit` 신규. **컬럼 RENAME**: `bar_weight_kg → bar_weight`, `min_stack_kg → min_stack`, `max_stack_kg → max_stack`, `stack_weight_kg → stack_weight`(추가로 `decimal → jsonb`). `equipment_brands`에 `default_bar_unit` / `default_stack_unit` 신규. 신규 enum `weightunit('kg','lb')`. 신규 CHECK 제약 `chk_bar_unit_synced`, `chk_stack_unit_synced` — 값과 단위 동기성 보장. 무게 단위 정책 변경: **단위 변환 없이 원본 그대로 저장**. CSV 템플릿: `docs/templates/equipment_template.csv`. |
| v2 (29테이블) | Program 도메인(`programs`, `program_routines`) 추가, `equipment_muscles` 추가, `user_equipment_selections` / `user_stats` 폐기, 운동 목표 복수 정책 (D-M6), `equipments` category 의미 재정의 + `equipment_type` 분리 (API-12) |
| v1 (28테이블) | 초기 설계 |
